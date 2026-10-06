"""Video decoding + 2D pose estimation, shared by the local CPU backend and the
Modal GPU worker. Keep this file dependency-light (numpy, opencv, ffmpeg on PATH,
rtmlib) because it is copied as-is into the Modal container image.

Output keypoints are COCO-17 in pixel coordinates of the *rotated, scaled* frame.
"""
from __future__ import annotations

import json
import subprocess
import time

import numpy as np


def probe(path: str) -> dict:
    """Read stream metadata with ffprobe (dimensions, rotation, frame rate)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
         "-show_format", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    s = info["streams"][0]
    rot = 0
    for sd in s.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(round(float(sd["rotation"])))
    if not rot and "rotate" in (s.get("tags") or {}):
        rot = int(s["tags"]["rotate"])
    w, h = int(s["width"]), int(s["height"])
    if abs(rot) % 180 == 90:
        w, h = h, w

    def _rate(r):
        try:
            n, d = r.split("/")
            return float(n) / float(d) if float(d) else 0.0
        except Exception:
            return 0.0

    return {
        "width": w, "height": h, "rotation": rot,
        "codec": s.get("codec_name"),
        "avg_fps": _rate(s.get("avg_frame_rate", "0/0")),
        "r_fps": _rate(s.get("r_frame_rate", "0/0")),
        "duration": float(info.get("format", {}).get("duration") or s.get("duration") or 0),
        "nb_frames": int(s.get("nb_frames") or 0),
    }


def frame_times(path: str) -> np.ndarray:
    """Presentation timestamps (s) of every video frame, from packet PTS (no decode)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout
    ts = sorted(float(x.split(",")[0]) for x in out.split() if x and x.split(",")[0] not in ("N/A", ""))
    t = np.asarray(ts, dtype=np.float64)
    return t - t[0] if len(t) else t


def iter_frames(path: str, max_height: int = 720, meta: dict | None = None):
    """Yield BGR frames (autorotated, downscaled to max_height), one per source frame."""
    meta = meta or probe(path)
    w, h = meta["width"], meta["height"]
    oh = min(max_height, h) // 2 * 2
    ow = int(round(w * oh / h / 2)) * 2
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-an", "-fps_mode", "passthrough",
           "-vf", f"scale={ow}:{oh}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = ow * oh * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(oh, ow, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def pick_person(kps: np.ndarray, scores: np.ndarray, prev_center):
    """Choose the golfer: the biggest confident skeleton, preferring continuity."""
    if kps is None or len(kps) == 0:
        return None, None
    best, best_val = 0, -1e18
    for i in range(len(kps)):
        k, s = kps[i], scores[i]
        good = s > 0.3
        if good.sum() < 5:
            continue
        span = k[good].max(0) - k[good].min(0)
        val = float(span[0] * span[1]) * float(s.mean())
        if prev_center is not None:
            c = k[good].mean(0)
            val /= 1.0 + float(np.linalg.norm(c - prev_center)) / max(1.0, float(span[1]))
        if val > best_val:
            best, best_val = i, val
    return kps[best], scores[best]


def make_estimator(device: str = "cpu", mode: str = "balanced", det_frequency: int = 4):
    from rtmlib import Body, PoseTracker  # Apache-2.0, RTMPose via ONNX Runtime
    return PoseTracker(Body, det_frequency=det_frequency, tracking=False,
                       mode=mode, backend="onnxruntime", device=device)


def run_pose(path: str, estimator=None, device: str = "cpu", mode: str = "balanced",
             max_height: int = 720, max_seconds: float = 12.0) -> dict:
    """Decode a clip and return the golfer's COCO-17 keypoints for every frame."""
    t0 = time.time()
    meta = probe(path)
    ts = frame_times(path)
    est = estimator or make_estimator(device=device, mode=mode)
    xy, conf = [], []
    prev = None
    size = None
    for frame in iter_frames(path, max_height=max_height, meta=meta):
        size = frame.shape[1], frame.shape[0]
        k, s = est(frame)
        k, s = pick_person(np.asarray(k) if len(k) else None, np.asarray(s) if len(s) else None, prev)
        if k is None:
            xy.append(np.zeros((17, 2)))
            conf.append(np.zeros(17))
        else:
            xy.append(k[:17])
            conf.append(s[:17])
            prev = k[:17][s[:17] > 0.3].mean(0) if (s[:17] > 0.3).any() else prev
        if len(ts) > len(xy) and ts[len(xy)] > max_seconds:
            break
    n = len(xy)
    if len(ts) < n:  # timestamps unavailable/mismatched: assume constant rate
        fps = meta["avg_fps"] or meta["r_fps"] or 30.0
        ts = np.arange(n) / fps
    return {
        "xy": np.asarray(xy, np.float32).round(2).tolist(),
        "conf": np.asarray(conf, np.float32).round(3).tolist(),
        "t": np.asarray(ts[:n]).round(5).tolist(),
        "width": size[0] if size else meta["width"],
        "height": size[1] if size else meta["height"],
        "meta": meta,
        "seconds": round(time.time() - t0, 2),
    }
