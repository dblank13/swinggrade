"""Phase-aligned DTW similarity between a user swing and a pro reference."""
from __future__ import annotations

import numpy as np

PHASES = [("address", "top", 40), ("top", "impact", 15), ("impact", "finish", 25)]


def _resample(seg: np.ndarray, n: int) -> np.ndarray:
    if len(seg) == 1:
        return np.repeat(seg, n, axis=0)
    src = np.linspace(0, 1, len(seg))
    dst = np.linspace(0, 1, n)
    return np.column_stack([np.interp(dst, src, seg[:, k]) for k in range(seg.shape[1])])


def dtw(a: np.ndarray, b: np.ndarray, band: float = 0.2) -> float:
    """Mean per-step Euclidean cost along the DTW path (Sakoe-Chiba band)."""
    n, m = len(a), len(b)
    w = max(int(band * max(n, m)), abs(n - m))
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0
    L = np.zeros((n + 1, m + 1))
    for i in range(1, n + 1):
        for j in range(max(1, i - w), min(m, i + w) + 1):
            c = float(np.linalg.norm(a[i - 1] - b[j - 1]))
            opts = (D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
            k = int(np.argmin(opts))
            D[i, j] = c + opts[k]
            L[i, j] = 1 + (L[i - 1, j], L[i, j - 1], L[i - 1, j - 1])[k]
    return float(D[n, m] / max(L[n, m], 1))


def similarity(user_feat, user_ev, pro_feat, pro_ev, scale: float = 0.6) -> dict:
    """Return overall and per-phase similarity (0-100)."""
    out = {}
    for a, b, n in PHASES:
        u = _resample(np.asarray(user_feat)[user_ev[a]:user_ev[b] + 1], n)
        p = _resample(np.asarray(pro_feat)[pro_ev[a]:pro_ev[b] + 1], n)
        out[f"{a}->{b}"] = round(100 * float(np.exp(-dtw(u, p) / scale)), 1)
    out["overall"] = round(float(np.mean(list(out.values()))), 1)
    return out
