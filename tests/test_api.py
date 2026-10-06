"""API smoke tests. Pose estimation is stubbed with a synthetic swing so the
tests run without downloading models; video handling uses a real GolfDB clip."""
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import synthetic_swing as S  # noqa: E402

from swinggrade import app as appmod  # noqa: E402
from swinggrade.pose import backends  # noqa: E402

client = TestClient(appmod.app)


def test_index_status_and_pros():
    assert "SwingGrade" in client.get("/").text
    s = client.get("/api/status").json()
    assert s["next_backend"] in ("modal", "local")
    p = client.get("/api/pros?view=fo").json()["pros"]
    assert len(p) > 50 and all(x["view"] == "fo" for x in p)
    g = client.get("/api/ghost?view=dtl&pro_id=" + p[0]["id"]).json()
    assert len(g["pose"]) == 17 and g["kind"] == "template"


def test_upload_job_flow(monkeypatch, tmp_path):
    def fake_run(path, progress=lambda m: None):
        r = S.make(view="dtl", early_ext=0.12)
        r.update(backend="stub", seconds=0.1, est_cost_usd=0.0, meta={})
        return r
    monkeypatch.setattr(backends, "run", fake_run)
    clip = tmp_path / "swing.mov"
    clip.write_bytes(b"\x00" * 2048)
    r = client.post("/api/analyze", files={"file": ("swing.mov", clip.read_bytes(), "video/quicktime")},
                    data={"view": "auto", "handed": "auto", "pro_id": "lydia-ko__dtl", "height_cm": "180"})
    job = r.json()["job_id"]
    for _ in range(50):
        s = client.get(f"/api/jobs/{job}").json()
        if s["state"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert s["state"] == "done", s
    res = s["result"]
    assert res["view"] == "dtl" and res["pro"]["player"] == "Lydia Ko"
    assert res["metrics"]["early_extension"]["cm"] == pytest.approx(0.12 * 0.29 * 180, abs=2)
    assert client.get(f"/api/jobs/{job}/video").status_code == 200


def test_live_keypoints_endpoint():
    r = S.make(view="fo", fps=30)
    body = {"frames": S.to_mediapipe(r), "width": r["width"], "height": r["height"],
            "view": "auto", "handed": "auto", "pro_id": "michelle-wie__fo"}
    out = client.post("/api/analyze_keypoints", json=body).json()
    assert out["source"] == "live" and out["tour"]["letter"] in "ABCDF"
    assert out["pro"]["player"] == "Michelle Wie"


def test_live_rejects_non_swing():
    r = S.make(view="fo", fps=30)
    frames = S.to_mediapipe(r)[:15]  # address only, no swing
    res = client.post("/api/analyze_keypoints", json={"frames": frames, "width": 1280, "height": 720})
    assert res.status_code == 422


def test_budget_accounting(tmp_path, monkeypatch):
    monkeypatch.setattr(backends, "_USAGE", tmp_path / "u.json")
    before = backends.usage()["est_usd"]
    cost = backends._record(20.0)
    assert cost == pytest.approx((20 + backends.config.MODAL_SCALEDOWN_S) * backends.rate_per_s())
    assert backends.usage()["est_usd"] == pytest.approx(before + cost, abs=1e-5)


def test_benchmarks_endpoint_feeds_overlay():
    b = client.get("/api/benchmarks").json()
    assert b["address_forward_bend"]["target"] == 41.5
    assert b["early_extension"]["tol"] > 0
