"""End-to-end analysis: keypoints -> events -> metrics -> grades -> cues."""
from __future__ import annotations

import numpy as np

from .. import pros
from . import compare, events, metrics, scoring
from .keypoints import (LEAD_SHO, LR_SWAP, TRAIL_SHO, Prepared, Swing,
                        normalized_pose, prepare)


def detect_handedness(p: Prepared, ev: dict, view: str) -> str:
    A, TP = ev["address"], ev["top"]
    if view == "fo":
        a = p.xy[A, LEAD_SHO, 0] - p.xy[A, TRAIL_SHO, 0]  # anatomical L minus R
        h = p.hands[TP, 0] - p.hands[A, 0]
        return "right" if np.sign(a) != np.sign(h) else "left"
    # down-the-line: right-handers face right of frame from the standard DTL position
    return "right" if p.hands[A, 0] >= p.mid_hip[A, 0] else "left"


def _prep_and_detect(sw: Swing, handed: str):
    p = prepare(sw, handed)
    return p, events.detect(p)


def _overlay(p: Prepared, max_frames: int = 900) -> dict:
    """Pixel skeleton per frame in ORIGINAL orientation, for drawing over the video."""
    xy = p.xy.copy()
    if p.handed == "left":
        xy = xy[:, LR_SWAP, :]
        xy[..., 0] = p.width - xy[..., 0]
    stride = max(1, int(np.ceil(len(xy) / max_frames)))
    return {"t_file": p.t_file[::stride].round(4).tolist(),
            "xy": xy[::stride].round(1).tolist(), "width": p.width, "height": p.height}


def _event_times(p: Prepared, ev: dict) -> dict:
    return {k: {"frame": int(v), "t": round(float(p.t[v]), 4), "t_file": round(float(p.t_file[v]), 4)}
            for k, v in ev.items()}


def _pro_from_keypoints(kp: dict):
    """Prepare a stored GolfDB pro swing using its human-labelled events."""
    sw = Swing(np.asarray(kp["xy"], float), np.asarray(kp["conf"], float),
               np.asarray(kp["t"], float), kp["width"], kp["height"], source="pro")
    p0 = prepare(sw, "right")
    view = kp.get("view") or metrics.classify_view(p0, 0)[0]

    def map_events(p):
        ev = {}
        for name, idx in zip(events.EVENTS, kp["events"]):
            t_orig = kp["t"][min(idx, len(kp["t"]) - 1)]
            ev[name] = int(np.argmin(np.abs(p.t_file - t_orig)))
        return ev

    ev = map_events(p0)
    if detect_handedness(p0, ev, view) == "left":
        p0 = prepare(sw, "left")
        ev = map_events(p0)
    return p0, ev, view


def analyze(sw: Swing, view: str = "auto", handed: str = "auto", pro_id: str | None = None,
            height_cm: float | None = None, capture_fps: float | None = None) -> dict:
    warnings = []
    if capture_fps and sw.source == "upload":
        file_fps = 1.0 / float(np.median(np.diff(sw.t))) if len(sw.t) > 1 else capture_fps
        if capture_fps > file_fps * 1.5:
            sw.time_scale = capture_fps / file_fps

    hand0 = "right" if handed == "auto" else handed
    try:
        p, ev = _prep_and_detect(sw, hand0)
    except events.SwingNotFound:
        # a slow-mo exported at 30 fps can be too slow to look like a swing at all
        if sw.source != "upload" or capture_fps:
            raise
        for k in (4.0, 8.0):
            sw.time_scale = k
            try:
                p, ev = _prep_and_detect(sw, hand0)
                break
            except events.SwingNotFound:
                continue
        else:
            sw.time_scale = 1.0
            raise
        sw.time_scale = 1.0
        p = prepare(sw, hand0)  # re-derive below from file time

    if sw.source == "upload" and not capture_fps:
        k = events.infer_time_scale(p, ev)
        if k != 1.0:
            sw.time_scale = k
            warnings.append(f"Clip looks like slow-motion played back {k:g}x slower; timing was corrected. "
                            "Set 'capture fps' if this is wrong.")
            p, ev = _prep_and_detect(sw, p.handed)

    view_ratio = None
    if view not in ("fo", "dtl"):
        view, view_ratio = metrics.classify_view(p, ev["address"])
    if handed == "auto":
        h = detect_handedness(p, ev, view)
        if h != p.handed:
            p, ev = _prep_and_detect(sw, h)

    real_fps = 1.0 / p.dt
    if real_fps < 100:
        warnings.append(f"Effective frame rate is ~{real_fps:.0f} fps. Tempo and impact timing are coarse; "
                        "record in Slo-mo (120-240 fps) for best results.")
    if float(np.mean(p.conf)) < 0.55:
        warnings.append("Low pose confidence. Use better light, a plain background and keep the whole body in frame.")

    m = metrics.compute(p, ev, view, height_cm)
    tour = scoring.grade(m, view, sw.source)

    result = {
        "source": sw.source, "view": view, "view_ratio": view_ratio, "handed": p.handed,
        "fps_effective": round(real_fps, 1), "time_scale": sw.time_scale,
        "torso_px": round(p.torso, 1), "height_cm": height_cm,
        "events": _event_times(p, ev), "metrics": m,
        "tour": tour, "cues": scoring.cues(tour),
        "poses": {k: normalized_pose(p, v) for k, v in ev.items()},
        "overlay": _overlay(p), "warnings": warnings, "pro": None,
    }

    ref = pros.get(pro_id) if pro_id else None
    if ref:
        targets = {"tempo_ratio": ref["tempo_mean"]}
        if ref.get("downswing_s_mean"):
            targets["downswing_s"] = ref["downswing_s_mean"]
        pro_block = {"id": ref["id"], "player": ref["player"], "view": ref["view"],
                     "n_swings": ref["n_swings"], "tempo": ref["tempo_mean"],
                     "downswing_s": ref.get("downswing_s_mean"), "keypoints": False}
        sim = None
        kp = pros.keypoint_swing(ref) if ref["view"] == view else None
        if ref["view"] != view:
            warnings.append(f"{ref['player']} reference is {ref['view'].upper()} but your clip is {view.upper()}; "
                            "only tempo is compared.")
        if kp:
            try:
                pp, pev, pview = _pro_from_keypoints(kp)
                pm = metrics.compute(pp, pev, pview)
                for key, rec in pm.items():
                    if key in ("backswing_s", "downswing_s", "tempo_ratio"):
                        continue  # use GolfDB multi-swing averages for timing
                    targets[key] = rec["value"]
                sim = compare.similarity(metrics.feature_series(p, view), ev,
                                         metrics.feature_series(pp, pview), pev)
                pro_block.update(keypoints=True, golfdb_id=kp.get("golfdb_id"),
                                 poses={k: normalized_pose(pp, v) for k, v in pev.items()},
                                 metrics=pm, similarity=sim)
            except Exception as exc:  # a bad reference must not break the user's result
                warnings.append(f"Pro keypoint comparison skipped: {exc}")
        vs = scoring.grade(m, view, sw.source, targets=targets,
                           similarity=sim["overall"] if sim else None)
        pro_block["grade"] = vs
        pro_block["cues"] = scoring.cues(vs, n=2)
        result["pro"] = pro_block
    return result
