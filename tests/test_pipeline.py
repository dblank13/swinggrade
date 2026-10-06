"""Pipeline tests on synthetic swings with known parameters (no camera/model needed)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import synthetic_swing as S  # noqa: E402

from swinggrade import posecore, pros  # noqa: E402
from swinggrade.analysis import pipeline  # noqa: E402
from swinggrade.analysis.keypoints import Swing  # noqa: E402

GOLFDB_CLIP = Path("/tmp/golfdb/test_video.mp4")


def run(**kw):
    r = S.make(**kw)
    return r, pipeline.analyze(Swing.from_pose_result(r), **{k: v for k, v in kw.items() if k in ()})


@pytest.mark.parametrize("view", ["fo", "dtl"])
def test_events_view_and_tempo(view):
    r, out = run(view=view)
    assert out["view"] == view and out["handed"] == "right"
    for name in ("address", "top", "impact"):
        assert abs(out["events"][name]["t"] - r["truth"][name]) < 0.1, name
    t = [out["events"][e]["frame"] for e in pipeline.events.EVENTS]
    assert t == sorted(t) and len(set(t)) == 8
    assert abs(out["metrics"]["tempo_ratio"]["value"] - 3.0) < 0.35
    assert abs(out["metrics"]["downswing_s"]["value"] - 0.28) < 0.05


def test_early_extension_is_detected_and_cued():
    _, clean = run(view="dtl")
    _, bad = run(view="dtl", early_ext=0.15)
    assert abs(clean["metrics"]["early_extension"]["value"]) < 0.03
    assert 0.12 < bad["metrics"]["early_extension"]["value"] < 0.18
    assert bad["tour"]["categories"]["posture"] < clean["tour"]["categories"]["posture"]
    assert bad["cues"][0]["metric"] in ("early_extension", "posture_change_impact")


@pytest.mark.parametrize("view", ["fo", "dtl"])
def test_left_handed_mirror_gives_same_metrics(view):
    _, right = run(view=view)
    _, left = run(view=view, lefty=True)
    assert left["handed"] == "left"
    for k, v in right["metrics"].items():
        assert left["metrics"][k]["value"] == pytest.approx(v["value"], abs=0.02), k


def test_slow_motion_exported_at_30fps_is_rescaled():
    r = S.make(view="fo", fps=240)
    r["t"] = (np.asarray(r["t"]) * 8).tolist()  # 240 fps capture played back at 30 fps
    out = pipeline.analyze(Swing.from_pose_result(r))
    assert out["time_scale"] == 8
    assert abs(out["metrics"]["downswing_s"]["value"] - 0.28) < 0.05
    out2 = pipeline.analyze(Swing.from_pose_result(r), capture_fps=240)
    assert out2["time_scale"] == pytest.approx(8, rel=0.02)


def test_live_mediapipe_path_and_low_fps_warning():
    r = S.make(view="dtl", fps=30)
    sw = Swing.from_mediapipe(S.to_mediapipe(r), r["width"], r["height"])
    out = pipeline.analyze(sw)
    assert out["source"] == "live" and out["view"] == "dtl"
    assert any("fps" in w for w in out["warnings"])
    assert all(row["reliability"] != "good" for row in out["tour"]["rows"])


def test_pro_tempo_comparison_uses_real_golfdb_numbers():
    ref = pros.get("rory-mcilroy__dtl")
    assert ref and 2.0 < ref["tempo_mean"] < 4.0
    _, out = run(view="dtl")
    out = pipeline.analyze(Swing.from_pose_result(S.make(view="dtl")), pro_id="rory-mcilroy__dtl")
    tr = [x for x in out["pro"]["grade"]["rows"] if x["metric"] == "tempo_ratio"][0]
    assert tr["target"] == ref["tempo_mean"]


def test_pro_keypoint_reference_similarity(tmp_path, monkeypatch):
    # fake an extracted pro swing (synthetic) with GolfDB-style labelled events
    r = S.make(view="fo", seed=3, tempo=3.2)
    t = np.asarray(r["t"])
    ev_t = [r["truth"]["address"], 0.85, 1.05, r["truth"]["top"], 1.65, r["truth"]["impact"], 1.9, 2.3]
    kp = {"golfdb_id": 99999, "view": "fo", "events": [int(np.argmin(abs(t - x))) for x in ev_t],
          **{k: r[k] for k in ("xy", "conf", "t", "width", "height")}}
    monkeypatch.setattr(pros, "keypoint_swing", lambda ref: kp)
    out = pipeline.analyze(Swing.from_pose_result(S.make(view="fo")), pro_id="tiger-woods__fo")
    assert out["pro"]["keypoints"] is True
    assert out["pro"]["similarity"]["overall"] > 80
    assert "similarity" in out["pro"]["grade"]["categories"]


@pytest.mark.skipif(not GOLFDB_CLIP.exists(), reason="GolfDB sample clip not present")
def test_video_probe_and_decode_on_real_golfdb_clip():
    meta = posecore.probe(str(GOLFDB_CLIP))
    ts = posecore.frame_times(str(GOLFDB_CLIP))
    frames = list(posecore.iter_frames(str(GOLFDB_CLIP), max_height=360, meta=meta))
    assert len(frames) == len(ts) == meta["nb_frames"]
    assert frames[0].shape[0] == 360
    assert 29 < 1 / np.median(np.diff(ts)) < 31


def test_benchmarks_are_consistent():
    b = json.loads((ROOT / "swinggrade/benchmarks.json").read_text())
    for k, m in b["metrics"].items():
        assert m["category"] in b["categories"], k
        assert m["reliability"] in ("good", "moderate", "weak"), k
        assert m["tol"] > 0, k
