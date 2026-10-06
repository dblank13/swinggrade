"""Pro reference library (GolfDB-derived)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .config import DATA_DIR

INDEX = DATA_DIR / "pros" / "index.json"
KP_DIR = DATA_DIR / "pros" / "kp"
TEMPLATES = DATA_DIR / "templates.json"


@lru_cache(maxsize=1)
def _index() -> dict:
    if not INDEX.exists():
        return {"pros": []}
    data = json.loads(INDEX.read_text())
    for p in data["pros"]:  # refresh keypoint availability
        for s in p["swings"]:
            s["has_keypoints"] = (KP_DIR / f"{s['golfdb_id']}.json").exists()
        p["has_keypoints"] = any(s["has_keypoints"] for s in p["swings"])
    return data


def reload():
    _index.cache_clear()


def list_pros(view: str | None = None) -> list:
    out = []
    for p in _index()["pros"]:
        if view in (None, "", "auto") or p["view"] == view:
            out.append({k: p[k] for k in ("id", "player", "view", "clubs", "n_swings", "tempo_mean",
                                          "tempo_sd", "downswing_s_mean", "has_keypoints")})
    return out


def get(pro_id: str) -> dict | None:
    return next((p for p in _index()["pros"] if p["id"] == pro_id), None)


def keypoint_swing(pro: dict) -> dict | None:
    """First swing of this pro that has extracted keypoints (prefer driver, real-time)."""
    cands = [s for s in pro["swings"] if s["has_keypoints"]]
    cands.sort(key=lambda s: (s["club"] != "driver", s["slow"]))
    for s in cands:
        return json.loads((KP_DIR / f"{s['golfdb_id']}.json").read_text())
    return None


def templates() -> dict:
    return json.loads(TEMPLATES.read_text())
