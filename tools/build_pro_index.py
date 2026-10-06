#!/usr/bin/env python3
"""Build data/pros/index.json from the real GolfDB annotations.

GolfDB (McNally et al., CVPR-W 2019, https://github.com/wmcnally/golfdb) labels
1,400 pro swings from YouTube with player, club, view and 8 swing events.
From the event frames alone we get each pro's real tempo (backswing:downswing).
Event frames for real-time clips were labelled at 30 fps, giving downswing time.

Usage: python tools/build_pro_index.py [--min-swings 2]
Input:  data/golfdb_index.json (extracted from golfDB.mat by tools/extract_golfdb.py)
"""
import argparse
import json
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEW = {"face-on": "fo", "down-the-line": "dtl"}
FPS = 30.0  # GolfDB real-time clips


def nice_name(s):
    n = s.title()
    n = re.sub(r"\b(Mc|Mac|De|O')([a-z])", lambda m: m.group(1) + m.group(2).upper(), n)
    return n


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-swings", type=int, default=2)
    args = ap.parse_args()
    rows = json.loads((ROOT / "data/golfdb_index.json").read_text())
    groups = defaultdict(list)
    for r in rows:
        v = VIEW.get(r["view"])
        if v:
            groups[(r["player"], v)].append(r)

    kp_dir = ROOT / "data/pros/kp"
    pros = []
    for (player, view), swings in groups.items():
        if len(swings) < args.min_swings:
            continue
        tempos, downs, items = [], [], []
        for r in swings:
            e = r["events"]  # [clip_start, address, toe_up, mid_back, top, mid_down, impact, mid_follow, finish, clip_end]
            back, down = e[4] - e[1], e[6] - e[4]
            if down > 0 and back > 0:
                tempos.append(back / down)
                if not r["slow"]:
                    downs.append(down / FPS)
            items.append({"golfdb_id": r["id"], "youtube_id": r["youtube_id"], "club": r["club"],
                          "slow": r["slow"], "events": [x - e[0] for x in e[1:9]],
                          "has_keypoints": (kp_dir / f"{r['id']}.json").exists()})
        if not tempos:
            continue
        pid = f"{slug(player)}__{view}"
        clubs = sorted({r["club"] for r in swings})
        pros.append({
            "id": pid, "player": nice_name(player), "sex": swings[0]["sex"], "view": view,
            "clubs": clubs, "n_swings": len(swings),
            "tempo_mean": round(st.mean(tempos), 2),
            "tempo_sd": round(st.pstdev(tempos), 2) if len(tempos) > 1 else None,
            "downswing_s_mean": round(st.mean(downs), 3) if downs else None,
            "n_realtime": len(downs),
            "has_keypoints": any(i["has_keypoints"] for i in items),
            "swings": items,
        })
    pros.sort(key=lambda p: (-p["n_swings"], p["player"]))
    out = ROOT / "data/pros/index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "GolfDB (CC BY-NC 4.0 annotations; footage is YouTube/broadcaster copyright)",
                               "pros": pros}, indent=1))
    all_t = [p["tempo_mean"] for p in pros]
    print(f"{len(pros)} pro/view references -> {out}")
    print(f"tempo across references: median {st.median(all_t):.2f}, range {min(all_t)}-{max(all_t)}")


if __name__ == "__main__":
    main()
