"""2D swing geometry from body keypoints.

Image coordinates: x right, y DOWN. Distances are reported in torso lengths
(mid-shoulder to mid-hip at address); converted to cm when the golfer's height
is supplied (torso ~= 0.29 x standing height).

View conventions
- down-the-line (dtl): camera behind the hands looking down the target line.
  "toward ball" direction = sign(hands_x - hips_x) at address.
- face-on (fo): camera square to the chest. "toward target" direction =
  sign(lead_shoulder_x - trail_shoulder_x) at address.
"""
from __future__ import annotations

import math

import numpy as np

from .keypoints import (LEAD_ANK, LEAD_ELB, LEAD_HIP, LEAD_KNEE, LEAD_SHO,
                        LEAD_WRI, NOSE, TRAIL_ANK, TRAIL_HIP, TRAIL_KNEE,
                        TRAIL_SHO, Prepared)

TORSO_FRACTION_OF_HEIGHT = 0.29


def _angle3(a, b, c) -> float:
    u, w = a - b, c - b
    cosv = float(np.dot(u, w) / (np.linalg.norm(u) * np.linalg.norm(w) + 1e-9))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosv))))


def classify_view(p: Prepared, address: int) -> tuple[str, float]:
    """Shoulder width relative to torso length is wide face-on, narrow down-the-line."""
    w = abs(p.xy[address, LEAD_SHO, 0] - p.xy[address, TRAIL_SHO, 0])
    ratio = w / p.torso
    return ("fo" if ratio > 0.45 else "dtl"), round(float(ratio), 3)


def compute(p: Prepared, ev: dict, view: str, height_cm: float | None = None) -> dict:
    A, TP, I, F = ev["address"], ev["top"], ev["impact"], ev["finish"]
    L = p.torso
    X = p.xy
    hands, mhip, msho = p.hands, p.mid_hip, p.mid_sho
    cm = (TORSO_FRACTION_OF_HEIGHT * height_cm) if height_cm else None
    out: dict = {}

    def put(key, value, unit, at=None):
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return
        rec = {"value": round(float(value), 3), "unit": unit}
        if at:
            rec["at"] = at
        if unit == "torso" and cm:
            rec["cm"] = round(float(value) * cm, 1)
        out[key] = rec

    # ---- timing (both views) ----
    back = p.t[TP] - p.t[A]
    down = p.t[I] - p.t[TP]
    put("backswing_s", back, "s")
    put("downswing_s", down, "s")
    if down > 0:
        put("tempo_ratio", back / down, "ratio")

    # head rise (+) / drop (-) at impact, both views
    put("head_rise_impact", (X[A, NOSE, 1] - X[I, NOSE, 1]) / L, "torso", "impact")

    if view == "dtl":
        s = 1.0 if hands[A, 0] >= mhip[A, 0] else -1.0  # toward-ball direction

        def bend(i):
            v = msho[i] - mhip[i]
            return math.degrees(math.atan2(s * v[0], -v[1]))

        put("address_forward_bend", bend(A), "deg", "address")
        put("posture_change_top", bend(TP) - bend(A), "deg", "top")
        put("posture_change_impact", bend(I) - bend(A), "deg", "impact")
        put("lead_knee_flex_address", 180 - _angle3(X[A, LEAD_HIP], X[A, LEAD_KNEE], X[A, LEAD_ANK]), "deg", "address")
        put("trail_knee_flex_address", 180 - _angle3(X[A, TRAIL_HIP], X[A, TRAIL_KNEE], X[A, TRAIL_ANK]), "deg", "address")
        put("early_extension", s * (mhip[I, 0] - mhip[A, 0]) / L, "torso", "impact")
        put("head_toward_ball_impact", s * (X[I, NOSE, 0] - X[A, NOSE, 0]) / L, "torso", "impact")
        # hands at top relative to a line from address hands through the trail shoulder
        a, b = hands[A], X[A, TRAIL_SHO]
        d = b - a
        n = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-9)
        if n[1] > 0:
            n = -n  # normal points "up"
        put("hands_above_plane_top", float(np.dot(hands[TP] - a, n)) / L, "torso", "top")

    else:  # face-on
        g = 1.0 if X[A, LEAD_SHO, 0] >= X[A, TRAIL_SHO, 0] else -1.0  # toward-target direction
        put("head_sway_top", -g * (X[TP, NOSE, 0] - X[A, NOSE, 0]) / L, "torso", "top")
        put("head_shift_impact", g * (X[I, NOSE, 0] - X[A, NOSE, 0]) / L, "torso", "impact")
        put("pelvis_sway_top", -g * (mhip[TP, 0] - mhip[A, 0]) / L, "torso", "top")
        put("pelvis_slide_impact", g * (mhip[I, 0] - mhip[A, 0]) / L, "torso", "impact")

        def sho_tilt(i, lead_down=True):
            dy = X[i, LEAD_SHO, 1] - X[i, TRAIL_SHO, 1]
            dx = abs(X[i, LEAD_SHO, 0] - X[i, TRAIL_SHO, 0])
            ang = math.degrees(math.atan2(dy, dx))
            return ang if lead_down else -ang

        put("shoulder_tilt_top", sho_tilt(TP, True), "deg", "top")
        put("shoulder_tilt_impact", sho_tilt(I, False), "deg", "impact")
        v = msho[I] - mhip[I]
        put("side_bend_impact", math.degrees(math.atan2(-g * v[0], -v[1])), "deg", "impact")
        put("lead_arm_straightness_top", _angle3(X[TP, LEAD_SHO], X[TP, LEAD_ELB], X[TP, LEAD_WRI]), "deg", "top")

        def turn(i, a, b):
            w0 = abs(X[A, a, 0] - X[A, b, 0])
            w = abs(X[i, a, 0] - X[i, b, 0])
            return math.degrees(math.acos(max(0.0, min(1.0, w / (w0 + 1e-9)))))

        st, ht = turn(TP, LEAD_SHO, TRAIL_SHO), turn(TP, LEAD_HIP, TRAIL_HIP)
        put("shoulder_turn_top", st, "deg", "top")
        put("hip_turn_top", ht, "deg", "top")
        put("x_factor_top", st - ht, "deg", "top")

    return out


def feature_series(p: Prepared, view: str) -> np.ndarray:
    """Per-frame size-invariant features used for DTW swing similarity."""
    L = p.torso
    o = p.mid_hip[0]
    v = p.mid_sho - p.mid_hip
    bend = np.degrees(np.arctan2(v[:, 0], -v[:, 1])) / 30.0
    sho = p.j(LEAD_SHO) - p.j(TRAIL_SHO)
    tilt = np.degrees(np.arctan2(sho[:, 1], np.abs(sho[:, 0]) + 1e-6)) / 30.0
    width = np.abs(sho[:, 0]) / L
    hands = (p.hands - o) / L
    hip = (p.mid_hip - o) / L
    head = (p.j(NOSE) - p.j(NOSE)[0]) / L
    return np.column_stack([bend, tilt, width, hands, hip * 2, head * 2])
