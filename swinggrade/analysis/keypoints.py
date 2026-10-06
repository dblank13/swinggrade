"""Keypoint containers, cleaning, handedness normalisation and smoothing.

Canonical layout is COCO-17. After `prepare()`, the golfer is always treated as
right-handed: anatomical LEFT = LEAD side, RIGHT = TRAIL side.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import savgol_filter

NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 1, 2, 3, 4
L_SHO, R_SHO, L_ELB, R_ELB, L_WRI, R_WRI = 5, 6, 7, 8, 9, 10
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK = 11, 12, 13, 14, 15, 16

# lead/trail aliases (valid after prepare(); lead = anatomical left)
LEAD_SHO, TRAIL_SHO, LEAD_ELB, TRAIL_ELB = L_SHO, R_SHO, L_ELB, R_ELB
LEAD_WRI, TRAIL_WRI, LEAD_HIP, TRAIL_HIP = L_WRI, R_WRI, L_HIP, R_HIP
LEAD_KNEE, TRAIL_KNEE, LEAD_ANK, TRAIL_ANK = L_KNEE, R_KNEE, L_ANK, R_ANK

LR_SWAP = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]
# MediaPipe Pose (33 landmarks) -> COCO-17
MP33_TO_COCO = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]

SKELETON = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
            (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]


@dataclass
class Swing:
    xy: np.ndarray          # (T,17,2) pixels
    conf: np.ndarray        # (T,17)
    t: np.ndarray           # (T,) seconds, file/stream time
    width: int
    height: int
    source: str = "upload"  # "upload" | "live"
    time_scale: float = 1.0  # real_seconds = file_seconds / time_scale (slow-mo playback)
    meta: dict = field(default_factory=dict)

    @classmethod
    def from_pose_result(cls, r: dict, source="upload"):
        return cls(np.asarray(r["xy"], float), np.asarray(r["conf"], float),
                   np.asarray(r["t"], float), int(r["width"]), int(r["height"]),
                   source=source, meta=r.get("meta", {}))

    @classmethod
    def from_mediapipe(cls, frames: list, width: int, height: int, source="live"):
        """frames: [{"t": seconds, "lm": [[x,y,visibility]*33]}] with x,y normalised 0..1."""
        frames = [f for f in frames if f.get("lm") and len(f["lm"]) >= 29]
        lm = np.asarray([f["lm"] for f in frames], float)[:, MP33_TO_COCO, :]
        xy = lm[..., :2] * np.array([width, height])
        conf = lm[..., 2] if lm.shape[-1] > 2 else np.ones(lm.shape[:2])
        t = np.asarray([f["t"] for f in frames], float)
        return cls(xy, conf, t - t[0], width, height, source=source)


@dataclass
class Prepared:
    xy: np.ndarray       # (T,17,2) smoothed, uniform time grid, lead = left
    conf: np.ndarray     # (T,17) mean confidence carried through
    t: np.ndarray        # (T,) REAL seconds (slow-mo corrected)
    t_file: np.ndarray   # (T,) seconds in the video file (for overlay sync)
    dt: float
    torso: float         # torso length in px at address region
    width: int
    height: int
    handed: str
    source: str

    def j(self, idx):
        return self.xy[:, idx, :]

    def mid(self, a, b):
        return (self.xy[:, a, :] + self.xy[:, b, :]) / 2

    @property
    def hands(self):
        return self.mid(LEAD_WRI, TRAIL_WRI)

    @property
    def mid_sho(self):
        return self.mid(LEAD_SHO, TRAIL_SHO)

    @property
    def mid_hip(self):
        return self.mid(LEAD_HIP, TRAIL_HIP)


def _interp_nans(a: np.ndarray, t: np.ndarray) -> np.ndarray:
    ok = ~np.isnan(a)
    if ok.sum() == 0:
        return np.zeros_like(a)
    if ok.all():
        return a
    return np.interp(t, t[ok], a[ok])


def prepare(sw: Swing, handed: str = "right", conf_thr: float = 0.3) -> Prepared:
    if len(sw.t) < 8:
        raise ValueError("Too few frames with a detected person.")
    xy = sw.xy.astype(float).copy()
    conf = sw.conf.astype(float).copy()
    if handed == "left":  # mirror so every golfer is analysed as right-handed
        xy[..., 0] = sw.width - xy[..., 0]
        xy = xy[:, LR_SWAP, :]
        conf = conf[:, LR_SWAP]

    t = sw.t.astype(float)
    order = np.argsort(t)
    t, xy, conf = t[order], xy[order], conf[order]
    keep = np.concatenate([[True], np.diff(t) > 1e-6])
    t, xy, conf = t[keep], xy[keep], conf[keep]

    present = (conf > conf_thr).sum(1) >= 8
    if present.sum() < 8:
        raise ValueError("No golfer detected in enough frames. Is the whole body in view?")
    # trim leading/trailing frames with nobody in view
    first, last = np.argmax(present), len(present) - np.argmax(present[::-1])
    t, xy, conf = t[first:last], xy[first:last], conf[first:last]

    # low-confidence joints -> NaN -> time interpolation
    for j in range(17):
        bad = conf[:, j] < conf_thr
        for d in range(2):
            col = xy[:, j, d].copy()
            col[bad] = np.nan
            xy[:, j, d] = _interp_nans(col, t)

    # resample to a uniform grid (handles variable frame rate)
    dt = float(np.median(np.diff(t)))
    grid = np.arange(t[0], t[-1] + dt * 0.5, dt)
    xy_u = np.empty((len(grid), 17, 2))
    conf_u = np.empty((len(grid), 17))
    for j in range(17):
        conf_u[:, j] = np.interp(grid, t, conf[:, j])
        for d in range(2):
            xy_u[:, j, d] = np.interp(grid, t, xy[:, j, d])

    # light smoothing: ~40 ms window, never fewer than 5 samples
    real_dt = dt / max(sw.time_scale, 1e-6)
    win = max(5, int(round(0.04 / real_dt)) | 1)
    if win < len(grid):
        xy_u = savgol_filter(xy_u, win, 2, axis=0)

    mid_sho = (xy_u[:, LEAD_SHO] + xy_u[:, TRAIL_SHO]) / 2
    mid_hip = (xy_u[:, LEAD_HIP] + xy_u[:, TRAIL_HIP]) / 2
    torso_series = np.linalg.norm(mid_sho - mid_hip, axis=1)
    n0 = max(3, len(grid) // 4)
    torso = float(np.median(torso_series[:n0]))
    if torso < 5:
        raise ValueError("Golfer is too small in frame.")

    return Prepared(xy=xy_u, conf=conf_u, t=(grid - grid[0]) / sw.time_scale,
                    t_file=grid, dt=real_dt, torso=torso, width=sw.width,
                    height=sw.height, handed=handed, source=sw.source)


def normalized_pose(p: Prepared, i: int, origin=None) -> list:
    """Pose at frame i in torso units, origin = mid-hip at address (or given)."""
    o = p.mid_hip[0] if origin is None else origin
    return ((p.xy[i] - o) / p.torso).round(4).tolist()
