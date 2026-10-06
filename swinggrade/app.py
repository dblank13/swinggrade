"""SwingGrade FastAPI server.

Run:  uvicorn swinggrade.app:app --host 0.0.0.0 --port 8000
Phone camera access needs HTTPS: put a Cloudflare/Tailscale tunnel in front (see README).
"""
from __future__ import annotations

import logging
import mimetypes
import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, pros
from .analysis import pipeline
from .analysis.events import SwingNotFound
from .analysis.keypoints import Swing, normalized_pose
from .pose import backends

for ext, typ in ((".mjs", "text/javascript"), (".js", "text/javascript"), (".wasm", "application/wasm"),
                 (".webmanifest", "application/manifest+json"), (".task", "application/octet-stream")):
    mimetypes.add_type(typ, ext)  # older distros' mime tables break ES-module / WASM loading

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("swinggrade")

app = FastAPI(title="SwingGrade", version="0.1.0")
reqlog = logging.getLogger("swinggrade.http")


@app.middleware("http")
async def log_problems(request: Request, call_next):
    """Make failures stand out in the container logs (uvicorn logs every request at INFO)."""
    t0 = time.time()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("UNHANDLED %s %s", request.method, request.url.path)
        raise
    if response.status_code >= 400 and request.url.path not in ("/robots.txt", "/favicon.ico"):
        lvl = logging.ERROR if response.status_code >= 500 else logging.WARNING
        reqlog.log(lvl, "HTTP %s %s %s (%.0f ms) ua=%s", response.status_code, request.method, request.url.path,
                   (time.time() - t0) * 1000, request.headers.get("user-agent", "")[:80])
    return response
UPLOADS = config.WORK_DIR / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)
JOBS: dict[str, dict] = {}
_pool = ThreadPoolExecutor(max_workers=1)  # one pose job at a time keeps a home CPU responsive
_jobs_lock = threading.Lock()


def _cleanup():
    cutoff = time.time() - config.UPLOAD_TTL_MIN * 60
    for d in UPLOADS.iterdir():
        if d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            JOBS.pop(d.name, None)


# ------------------------------------------------------------------ info ----
@app.get("/api/status")
def status():
    return {"pose_backend_setting": config.POSE_BACKEND, "next_backend": backends.choose_backend(),
            "modal_configured": backends.modal_configured(), "modal_gpu": config.MODAL_GPU,
            "modal_rate_per_s": round(backends.rate_per_s(), 6), "modal_usage": backends.usage(),
            "local_pose_mode": config.LOCAL_POSE_MODE, "jobs_running": sum(j["state"] == "running" for j in JOBS.values())}


@app.get("/api/pros")
def list_pros(view: str | None = None):
    return {"pros": pros.list_pros(view)}


@app.get("/api/benchmarks")
def benchmarks():
    """Targets/tolerances the phone uses to colour the live geometry overlay."""
    from .analysis.scoring import BENCH
    return {k: {"target": m["target"], "tol": m["tol"], "label": m["label"]} for k, m in BENCH["metrics"].items()}


@lru_cache(maxsize=256)
def _ghost(pro_id: str, view: str):
    ref = pros.get(pro_id) if pro_id else None
    if ref and ref["view"] == view:
        kp = pros.keypoint_swing(ref)
        if kp:
            p, ev, _ = pipeline._pro_from_keypoints(kp)
            return {"pose": normalized_pose(p, ev["address"]), "kind": "pro", "player": ref["player"]}
    return {"pose": pros.templates()[view], "kind": "template", "player": None}


@app.get("/api/ghost")
def ghost(view: str = "dtl", pro_id: str = ""):
    if view not in ("fo", "dtl"):
        raise HTTPException(400, "view must be fo or dtl")
    return _ghost(pro_id, view)


# ---------------------------------------------------------------- upload ----
def _num(v):
    try:
        return float(v) if v not in (None, "", "auto") else None
    except ValueError:
        return None


def _run_job(job_id: str, path: str, opts: dict):
    job = JOBS[job_id]
    job["state"] = "running"
    log.info("job %s started (%s, %.1f MB, opts=%s)", job_id, Path(path).suffix, Path(path).stat().st_size / 1e6, opts)

    def progress(msg):
        job["progress"] = msg

    try:
        t0 = time.time()
        r = backends.run(path, progress)
        progress("Analysing swing")
        sw = Swing.from_pose_result(r, source="upload")
        result = pipeline.analyze(sw, view=opts["view"], handed=opts["handed"], pro_id=opts["pro_id"],
                                  height_cm=opts["height_cm"], capture_fps=opts["capture_fps"])
        result["processing"] = {"backend": r.get("backend"), "pose_seconds": r.get("seconds"),
                                "total_seconds": round(time.time() - t0, 2),
                                "est_cost_usd": r.get("est_cost_usd"), "video": r.get("meta")}
        result["video_url"] = f"/api/jobs/{job_id}/video"
        job.update(state="done", result=result, progress="Done")
        log.info("job %s done in %.1fs via %s: %s %s, %d frames @%s fps, grade %s", job_id, time.time() - t0,
                 r.get("backend"), result["view"], result["handed"], len(r.get("t", [])), result["fps_effective"],
                 result["tour"]["letter"])
    except SwingNotFound as exc:
        log.warning("job %s: no swing found (%s)", job_id, exc)
        job.update(state="error", error=f"{exc} Make sure the clip contains one full swing with the whole body in view.")
    except Exception as exc:
        log.error("job %s failed: %s\n%s", job_id, exc, traceback.format_exc())
        job.update(state="error", error=str(exc))


@app.post("/api/analyze")
async def analyze_upload(file: UploadFile = File(...), view: str = Form("auto"), handed: str = Form("auto"),
                         pro_id: str = Form(""), height_cm: str = Form(""), capture_fps: str = Form("")):
    _cleanup()
    job_id = uuid.uuid4().hex[:12]
    d = UPLOADS / job_id
    d.mkdir(parents=True)
    suffix = "." + (file.filename or "clip.mov").rsplit(".", 1)[-1].lower()[:5]
    path = d / f"clip{suffix}"
    size, limit = 0, config.MAX_UPLOAD_MB * 1024 * 1024
    with open(path, "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                shutil.rmtree(d, ignore_errors=True)
                raise HTTPException(413, f"Clip larger than {config.MAX_UPLOAD_MB} MB; trim it to the swing.")
            f.write(chunk)
    opts = {"view": view, "handed": handed, "pro_id": pro_id or None,
            "height_cm": _num(height_cm), "capture_fps": _num(capture_fps)}
    with _jobs_lock:
        JOBS[job_id] = {"state": "queued", "progress": "Queued", "path": str(path), "created": time.time()}
    _pool.submit(_run_job, job_id, str(path), opts)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown or expired job")
    return {k: v for k, v in job.items() if k != "path"}


@app.get("/api/jobs/{job_id}/video")
def job_video(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown or expired job")
    return FileResponse(job["path"])


class ClientLog(BaseModel):
    where: str = ""
    message: str = ""
    stack: str = ""
    page: str = ""
    ua: str = ""
    source: str | None = None
    line: int | None = None


@app.post("/api/client-log", status_code=204)
def client_log(entry: ClientLog):
    """Browser errors (phone camera, pose model, uploads) forwarded to the server log."""
    log.error("client-error [%s] %s | page=%s src=%s:%s ua=%s%s", entry.where[:40], entry.message[:500],
              entry.page[:80], entry.source, entry.line, entry.ua[:120],
              ("\n" + entry.stack[:1500]) if entry.stack else "")


# ------------------------------------------------------------------ live ----
class LiveFrame(BaseModel):
    t: float
    lm: list[list[float]]


class LiveSwing(BaseModel):
    frames: list[LiveFrame]
    width: int
    height: int
    view: str = "auto"
    handed: str = "auto"
    pro_id: str = ""
    height_cm: float | None = None


@app.post("/api/analyze_keypoints")
def analyze_live(body: LiveSwing):
    """Live (beta): the phone already ran MediaPipe; grade the keypoint sequence directly."""
    if len(body.frames) < 10:
        raise HTTPException(400, "Too few frames")
    try:
        sw = Swing.from_mediapipe([f.model_dump() for f in body.frames], body.width, body.height)
        r = pipeline.analyze(sw, view=body.view, handed=body.handed, pro_id=body.pro_id or None,
                             height_cm=body.height_cm)
        r["processing"] = {"backend": "phone (MediaPipe in browser)", "est_cost_usd": 0.0}
        return r
    except (SwingNotFound, ValueError) as exc:
        log.warning("live swing rejected: %s (%d frames)", exc, len(body.frames))
        raise HTTPException(422, str(exc))


app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
