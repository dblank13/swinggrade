"""Pose backends: Modal GPU (free-tier budget guarded) with local CPU fallback."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .. import config, posecore

log = logging.getLogger("swinggrade.pose")
_USAGE = config.WORK_DIR / "modal_usage.json"
_lock = threading.RLock()
_local_est = None


# ---------------------------------------------------------------- budget ----
def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usage() -> dict:
    with _lock:
        u = json.loads(_USAGE.read_text()) if _USAGE.exists() else {}
    if u.get("month") != _month():
        u = {"month": _month(), "est_usd": 0.0, "calls": 0, "billed_s": 0.0}
    u["budget_usd"] = config.MODAL_MONTHLY_BUDGET_USD
    u["remaining_usd"] = round(max(0.0, config.MODAL_MONTHLY_BUDGET_USD - u["est_usd"]), 4)
    return u


def rate_per_s(gpu: str | None = None) -> float:
    g = config.MODAL_GPU_RATES.get((gpu or config.MODAL_GPU).upper(), config.MODAL_GPU_RATES["L4"])
    return g + config.MODAL_CPU_CORES * config.MODAL_CPU_CORE_RATE + config.MODAL_MEM_GIB * config.MODAL_MEM_GIB_RATE


def _record(seconds: float) -> float:
    """Conservative estimate: call time + idle window before scale-down, all billed."""
    billed = seconds + config.MODAL_SCALEDOWN_S
    cost = billed * rate_per_s()
    with _lock:
        u = usage()
        u["est_usd"] = round(u["est_usd"] + cost, 5)
        u["calls"] += 1
        u["billed_s"] = round(u["billed_s"] + billed, 1)
        _USAGE.parent.mkdir(parents=True, exist_ok=True)
        _USAGE.write_text(json.dumps({k: u[k] for k in ("month", "est_usd", "calls", "billed_s")}))
    return cost


# ---------------------------------------------------------------- modal -----
def modal_configured() -> bool:
    try:
        import modal  # noqa: F401
    except ImportError:
        return False
    import os
    return bool(os.getenv("MODAL_TOKEN_ID")) or (Path.home() / ".modal.toml").exists()


def _modal_pose(path: str) -> dict:
    import modal
    cls = modal.Cls.from_name(config.MODAL_APP, "Pose")
    data = Path(path).read_bytes()
    t0 = time.time()
    try:
        r = cls().infer.remote(data, config.MAX_HEIGHT, config.MAX_CLIP_SECONDS)
    finally:
        cost = _record(time.time() - t0)
    r["backend"] = f"modal:{r.get('provider', config.MODAL_GPU)}"
    r["est_cost_usd"] = round(cost, 5)
    return r


# ---------------------------------------------------------------- local -----
def _local_pose(path: str) -> dict:
    global _local_est
    with _lock:
        if _local_est is None:
            try:
                _local_est = posecore.make_estimator(device="cpu", mode=config.LOCAL_POSE_MODE)
            except OSError as exc:  # URLError subclasses OSError
                raise RuntimeError("Local pose model isn't downloaded and couldn't be fetched "
                                   f"({exc}). Run ./setup.sh while online, or set up Modal.") from exc
    r = posecore.run_pose(path, estimator=_local_est, max_height=config.MAX_HEIGHT,
                          max_seconds=config.MAX_CLIP_SECONDS)
    r["backend"] = f"local-cpu:{config.LOCAL_POSE_MODE}"
    r["est_cost_usd"] = 0.0
    return r


def choose_backend() -> str:
    b = config.POSE_BACKEND
    if b in ("local", "modal"):
        return b
    if modal_configured() and usage()["remaining_usd"] > 0.02:
        return "modal"
    return "local"


def run(path: str, progress=lambda msg: None) -> dict:
    backend = choose_backend()
    if backend == "modal":
        if usage()["remaining_usd"] <= 0.02 and config.POSE_BACKEND == "modal":
            raise RuntimeError("Monthly Modal budget reached; set POSE_BACKEND=auto to fall back to CPU.")
        progress("Running pose estimation on Modal GPU")
        try:
            return _modal_pose(path)
        except Exception as exc:
            log.warning("Modal pose failed (%s); falling back to local CPU", exc)
            if config.POSE_BACKEND == "modal":
                raise
            progress("Modal unavailable, using local CPU")
    else:
        progress("Running pose estimation on this computer's CPU")
    return _local_pose(path)
