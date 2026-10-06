"""Swing event detection from body keypoints only (no club tracking).

Uses the same 8 events as GolfDB (McNally et al., 2019):
address, toe_up, mid_backswing, top, mid_downswing, impact, mid_follow_through, finish.
Heuristics follow the hand-trajectory approach used by several open-source
MediaPipe swing analysers: stillness -> hands rise -> highest point -> return
to address height at high speed -> stillness.
"""
from __future__ import annotations

import numpy as np

from .keypoints import LEAD_SHO, LEAD_WRI, Prepared

EVENTS = ["address", "toe_up", "mid_backswing", "top", "mid_downswing",
          "impact", "mid_follow_through", "finish"]


class SwingNotFound(ValueError):
    pass


def hand_speed(p: Prepared) -> np.ndarray:
    """Hand speed in torso-lengths per (real) second."""
    v = np.gradient(p.hands, p.dt, axis=0)
    return np.linalg.norm(v, axis=1) / p.torso


def _horizontal_arm(p: Prepared, a: int, b: int) -> int:
    """Frame in [a, b] where the lead arm (shoulder->wrist) is closest to horizontal."""
    if b <= a:
        return a
    v = p.j(LEAD_WRI)[a:b + 1] - p.j(LEAD_SHO)[a:b + 1]
    s = np.abs(v[:, 1]) / (np.linalg.norm(v, axis=1) + 1e-6)
    return a + int(np.argmin(s))


def _at_height(y: np.ndarray, target: np.ndarray, a: int, b: int) -> int:
    if b <= a:
        return a
    return a + int(np.argmin(np.abs(y[a:b + 1] - target[a:b + 1])))


def detect(p: Prepared) -> dict:
    T = len(p.t)
    sp = hand_speed(p)
    hy = p.hands[:, 1]
    hip_y = p.mid_hip[:, 1]
    edge = max(2, int(0.02 / p.dt))

    peak = edge + int(np.argmax(sp[edge:T - edge])) if T > 2 * edge + 1 else int(np.argmax(sp))
    if sp[peak] < 2.5:
        raise SwingNotFound("No swing-speed hand motion found in this clip.")
    still = max(0.5, 0.08 * sp[peak])

    # top of backswing = hands highest (min y) in the ~2.5 s before peak speed
    a0 = max(0, peak - int(2.5 / p.dt))
    top = a0 + int(np.argmin(hy[a0:peak + 1]))
    if top >= peak:
        raise SwingNotFound("Could not find the top of the backswing.")

    # address = last still frame before the takeaway. Hands also pause at the top,
    # so first walk back until they are well below the top position.
    m = top
    while m > 0 and hy[m] < hy[top] + 0.5 * p.torso:
        m -= 1
    address = 0
    for i in range(m, -1, -1):
        if sp[i] < still:
            address = i
            break

    # impact = first frame after top where hands return to address height
    lim = min(T - 1, peak + int(0.25 / p.dt))
    target_y = hy[address] - 0.12 * p.torso
    impact = None
    for i in range(top + 1, lim + 1):
        if hy[i] >= target_y:
            impact = i
            break
    if impact is None:
        impact = peak

    # finish = hands still again (or clip end)
    finish = T - 1
    need = max(2, int(0.12 / p.dt))
    run = 0
    for i in range(impact + 1, min(T, impact + int(3.0 / p.dt))):
        run = run + 1 if sp[i] < still else 0
        if run >= need:
            finish = i - need + 1
            break

    ev = {"address": address, "top": top, "impact": impact, "finish": finish}
    ev["mid_backswing"] = _horizontal_arm(p, address + 1, top - 1)
    ev["toe_up"] = _at_height(hy, hip_y, address + 1, ev["mid_backswing"])
    ev["mid_downswing"] = _horizontal_arm(p, top + 1, impact - 1)
    half = impact + max(1, (finish - impact) // 2)
    ev["mid_follow_through"] = _at_height(hy, hip_y - 0.3 * p.torso, impact + 1, half)

    # enforce ordering
    prev = -1
    for name in EVENTS:
        ev[name] = int(min(max(ev[name], prev + 1 if name != "address" else 0), T - 1))
        prev = ev[name]
    return ev


def infer_time_scale(p: Prepared, ev: dict) -> float:
    """Slow-motion clips exported at 30 fps play back 4x/8x slower than reality.
    A real downswing takes ~0.2-0.45 s (Chu et al. 2010: 0.30 +/- 0.06 s), so a
    much longer measured downswing reveals the playback factor."""
    ds = p.t[ev["impact"]] - p.t[ev["top"]]
    if ds <= 0.9:
        return 1.0
    # common phone slow-mo factors (120/30, 240/30, 240/24 ...); pick the one that
    # puts the downswing closest to a typical 0.28 s
    return float(min((2, 4, 5, 8, 10, 16), key=lambda k: abs(np.log(ds / k / 0.28))))
