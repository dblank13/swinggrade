#!/usr/bin/env python3
"""Generate a synthetic COCO-17 keypoint swing with known parameters.

Used by the test-suite (and handy for checking the pipeline without a camera).
It is a simple kinematic stick figure, not a biomechanical model.
"""
from __future__ import annotations

import math

import numpy as np

FO_ADDR = np.array(
    [[-0.06, -1.33], [0.0, -1.38], [-0.12, -1.38], [0.06, -1.35], [-0.18, -1.35],
     [0.34, -1.02], [-0.44, -0.93], [0.20, -0.58], [-0.24, -0.56], [0.06, -0.22], [0.01, -0.20],
     [0.19, 0.0], [-0.19, 0.0], [0.27, 0.85], [-0.27, 0.85], [0.33, 1.72], [-0.33, 1.72]])


def _ease(u):
    u = min(max(u, 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * u)


def swing_phase(t, t_addr, back, down, follow):
    """phi: 0 address -> 1 top -> 0 impact -> -1 finish."""
    if t < t_addr:
        return 0.0
    t -= t_addr
    if t < back:
        return _ease(t / back)
    t -= back
    if t < down:
        u = t / down
        return 1.0 - u ** 1.6  # accelerating downswing
    t -= down
    return -_ease(t / follow)


def make(view="fo", fps=240.0, tempo=3.0, downswing=0.28, early_ext=0.0, head_rise=0.0,
         hip_sway_top=0.03, noise=0.006, seed=0, torso_px=180.0, width=1280, height=720,
         lefty=False):
    rng = np.random.default_rng(seed)
    t_addr, back, follow, hold = 0.6, tempo * downswing, 0.5, 0.6
    total = t_addr + back + downswing + follow + hold
    ts = np.arange(0, total, 1.0 / fps)
    origin = np.array([width / 2, height * 0.42])
    frames = []
    for t in ts:
        phi = swing_phase(t, t_addr, back, downswing, follow)
        in_down = t_addr + back <= t <= t_addr + back + downswing
        after = t > t_addr + back + downswing
        down_u = (t - t_addr - back) / downswing if in_down else (1.0 if after else 0.0)
        k = np.zeros((17, 2))
        if view == "fo":
            k[:] = FO_ADDR
            hip_c = np.array([(-hip_sway_top * max(phi, 0)) + 0.04 * down_u, 0.0])
            ht = math.radians(45 * phi) if phi > 0 else math.radians(-60 * -phi)
            st = math.radians(88 * phi) if phi > 0 else math.radians(-95 * -phi)
            tilt = math.radians(40 * max(phi, 0) - 24 * down_u * (1 - abs(min(phi, 0))))
            hw = 0.19 * math.cos(ht)
            k[11] = hip_c + [hw, 0]
            k[12] = hip_c + [-hw, 0]
            sc = hip_c + [-0.05, -0.97]
            sw = 0.39 * max(math.cos(st), 0.08)
            k[5] = sc + [sw * math.cos(tilt), sw * math.sin(tilt)]
            k[6] = sc + [-sw * math.cos(tilt), -sw * math.sin(tilt)]
            th = math.radians(-150 * phi)
            hands = np.array([0.0, -0.95]) + 0.75 * np.array([math.sin(th), math.cos(th)])
            k[9] = hands + [0.03, -0.01]
            k[10] = hands + [-0.03, 0.01]
            k[7] = (k[5] + k[9]) / 2 + [0.04, 0.02]
            k[8] = (k[6] + k[10]) / 2 + [-0.04, 0.05]
            k[0:5] = FO_ADDR[0:5] + [hip_c[0] * 0.5, 0]
        else:  # down-the-line, golfer faces +x
            bend0 = math.radians(41.5)
            ee = early_ext * (math.sin(math.pi * min(down_u, 1.0) / 2) if (in_down or after) else 0.0)
            hip_c = np.array([ee, 0.0])
            sho_c = np.array([math.sin(bend0), -math.cos(bend0)])  # shoulders stay put
            k[11] = hip_c + [0.02, -0.01]
            k[12] = hip_c + [-0.02, 0.01]
            k[5] = sho_c + [0.02, -0.02]
            k[6] = sho_c + [-0.03, 0.02]
            a0, a1 = np.array([0.86, -0.08]), np.array([0.40, -1.55])
            ctrl = np.array([1.15, -1.05]) if phi >= 0 else np.array([0.2, -0.7])
            u = abs(phi)
            end = a1 if phi >= 0 else np.array([0.15, -1.5])
            hands = (1 - u) ** 2 * a0 + 2 * (1 - u) * u * ctrl + u ** 2 * end
            k[9] = hands + [0.02, -0.01]
            k[10] = hands + [-0.02, 0.01]
            k[7] = (k[5] + k[9]) / 2 + [0.05, 0.02]
            k[8] = (k[6] + k[10]) / 2 + [0.0, 0.05]
            head = sho_c + np.array([0.36, -0.23])
            k[0] = head
            k[1], k[2] = head + [-0.03, -0.04], head + [-0.04, -0.03]
            k[3], k[4] = head + [-0.14, -0.02], head + [-0.16, -0.01]
            k[13], k[14] = [0.30, 0.83], [0.26, 0.85]
            k[15], k[16] = [0.16, 1.68], [0.12, 1.70]
        if head_rise and (in_down or after):
            k[0:5, 1] -= head_rise * min(down_u, 1.0)
        k += rng.normal(0, noise, k.shape)
        frames.append(origin + k * torso_px)
    xy = np.asarray(frames)
    if lefty:  # a left-hander is the mirror image of a right-hander
        xy[..., 0] = width - xy[..., 0]
        xy = xy[:, [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15], :]
    conf = np.full(xy.shape[:2], 0.9)
    truth = {"address": t_addr, "top": t_addr + back, "impact": t_addr + back + downswing}
    return {"xy": xy.tolist(), "conf": conf.tolist(), "t": ts.tolist(), "width": width,
            "height": height, "truth": truth}


def to_mediapipe(r: dict) -> list:
    """Convert a synthetic result to the live endpoint's MediaPipe-33 frame format."""
    coco_to_mp = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
    W, H = r["width"], r["height"]
    frames = []
    for t, k in zip(r["t"], r["xy"]):
        lm = [[0.5, 0.5, 0.0] for _ in range(33)]
        for c, m in enumerate(coco_to_mp):
            lm[m] = [k[c][0] / W, k[c][1] / H, 0.95]
        frames.append({"t": t, "lm": lm})
    return frames
