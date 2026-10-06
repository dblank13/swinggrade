"""Grade a swing against tour norms and against a chosen pro; pick coaching cues."""
from __future__ import annotations

import json
import math
from pathlib import Path

BENCH = json.loads((Path(__file__).resolve().parent.parent / "benchmarks.json").read_text())
REL_W = {"good": 1.0, "moderate": 0.7, "weak": 0.4}
DOWNGRADE = {"good": "moderate", "moderate": "weak", "weak": "weak"}


def letter(score: float) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"


def _score(value, target, tol) -> float:
    z = (value - target) / tol
    return 100.0 * math.exp(-0.5 * z * z)


def grade(metrics: dict, view: str, source: str, targets: dict | None = None,
          similarity: float | None = None) -> dict:
    """targets: optional {metric: value} overriding benchmark targets (pro comparison)."""
    cats = BENCH["categories"]
    rows, by_cat = [], {}
    for key, m in metrics.items():
        b = BENCH["metrics"].get(key)
        if not b or (b["view"] not in ("both", view)):
            continue
        target = (targets or {}).get(key, None if targets is not None else b["target"])
        if target is None:
            continue
        tol = b["tol"]
        rel = b["reliability"]
        if source == "live":
            rel = DOWNGRADE[rel]
            if b["category"] == "tempo":
                tol *= 1.75  # ~30 fps live capture: a single frame is ~10% of the downswing
        s = _score(m["value"], target, tol)
        diff = m["value"] - target
        rows.append({"metric": key, "label": b["label"], "value": m["value"], "unit": m["unit"],
                     "cm": m.get("cm"), "target": round(float(target), 3), "tol": tol,
                     "score": round(s, 1), "reliability": rel, "category": b["category"],
                     "direction": "high" if diff > 0 else "low", "source": b["source"],
                     "at": m.get("at")})
        by_cat.setdefault(b["category"], []).append((s, REL_W[rel]))
    if similarity is not None:
        by_cat["similarity"] = [(similarity, 1.0)]
    cat_scores = {c: sum(s * w for s, w in v) / sum(w for _, w in v) for c, v in by_cat.items()}
    total_w = sum(cats[c] for c in cat_scores)
    overall = sum(cat_scores[c] * cats[c] for c in cat_scores) / total_w if total_w else 0.0
    return {"score": round(overall, 1), "letter": letter(overall),
            "categories": {c: round(v, 1) for c, v in cat_scores.items()},
            "rows": sorted(rows, key=lambda r: r["score"])}


def cues(graded: dict, n: int = 3) -> list:
    cats = BENCH["categories"]
    picks = []
    for r in graded["rows"]:
        if r["reliability"] == "weak" or r["score"] >= 75:
            continue
        b = BENCH["metrics"][r["metric"]]
        text = b.get("cue_" + r["direction"]) or ""
        if not text:
            continue
        priority = (100 - r["score"]) * cats[r["category"]] * REL_W[r["reliability"]]
        picks.append({"metric": r["metric"], "label": r["label"], "score": r["score"],
                      "text": text, "priority": round(priority, 1)})
    picks.sort(key=lambda c: -c["priority"])
    return picks[:n]
