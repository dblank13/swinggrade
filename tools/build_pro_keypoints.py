#!/usr/bin/env python3
"""Extract body keypoints for GolfDB pro swings so they can be used as full-body
references (alignment ghost, per-metric "vs pro" targets, DTW similarity).

Only the derived keypoints are stored (data/pros/kp/<golfdb_id>.json, a few
hundred KB each). The source videos are YouTube/broadcaster copyright: download
them only for personal, non-commercial research, keep them local, and do not
redistribute them. GolfDB annotations are CC BY-NC 4.0.

Examples
  # list a player's swings
  python tools/build_pro_keypoints.py --player "Rory McIlroy" --list
  # download with yt-dlp (if installed) and extract 2 face-on driver swings on this CPU
  python tools/build_pro_keypoints.py --player "Rory McIlroy" --view fo --club driver --limit 2 --download
  # use videos you already have in data/golfdb_videos/<youtube_id>.mp4, run on Modal
  python tools/build_pro_keypoints.py --player "Lydia Ko" --view dtl --limit 3 --backend modal
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from swinggrade import posecore  # noqa: E402

VIEW = {"fo": "face-on", "dtl": "down-the-line"}


def find_video(vdir: Path, yid: str):
    for ext in (".mp4", ".mkv", ".webm", ".mov"):
        p = vdir / f"{yid}{ext}"
        if p.exists():
            return p
    return None


def download(vdir: Path, yid: str):
    if not shutil.which("yt-dlp"):
        print("  yt-dlp not installed (pip install yt-dlp); place the file manually.")
        return None
    vdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["yt-dlp", "-f", "mp4[height<=720]/best[height<=720]", "-o",
                    str(vdir / f"{yid}.%(ext)s"), f"https://www.youtube.com/watch?v={yid}"], check=False)
    return find_video(vdir, yid)


def cut_clip(src: Path, events: list, bbox: list, out: Path) -> int:
    """Trim to GolfDB clip bounds and crop to the labelled golfer box."""
    cap = cv2.VideoCapture(str(src))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    x, y, w, h = int(bbox[0] * W), int(bbox[1] * H), int(bbox[2] * W), int(bbox[3] * H)
    x, y = max(0, x), max(0, y)
    w, h = min(w, W - x) // 2 * 2, min(h, H - y) // 2 * 2
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (w, h))
    cap.set(cv2.CAP_PROP_POS_FRAMES, events[0])
    n = 0
    for _ in range(events[-1] - events[0] + 1):
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(frame[y:y + h, x:x + w])
        n += 1
    writer.release()
    cap.release()
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--player", required=True)
    ap.add_argument("--view", choices=["fo", "dtl"])
    ap.add_argument("--club", help="driver|iron|fairway|hybrid|wedge")
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--video-dir", default=str(ROOT / "data/golfdb_videos"))
    ap.add_argument("--download", action="store_true", help="fetch missing videos with yt-dlp")
    ap.add_argument("--backend", choices=["local", "modal"], default="local")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    rows = json.loads((ROOT / "data/golfdb_index.json").read_text())
    sel = [r for r in rows if r["player"].lower() == args.player.lower()
           and (not args.view or r["view"] == VIEW[args.view])
           and (not args.club or r["club"] == args.club)]
    sel.sort(key=lambda r: (r["slow"], r["club"] != "driver"))
    if not sel:
        sys.exit("No matching GolfDB swings.")
    if args.list:
        for r in sel:
            print(r["id"], r["view"], r["club"], "slow" if r["slow"] else "real-time", r["youtube_id"])
        return

    vdir = Path(args.video_dir)
    kp_dir = ROOT / "data/pros/kp"
    kp_dir.mkdir(parents=True, exist_ok=True)
    est = posecore.make_estimator("cpu") if args.backend == "local" else None
    done = 0
    for r in sel:
        if done >= args.limit:
            break
        print(f"GolfDB #{r['id']} {r['player']} {r['view']} {r['club']} ({r['youtube_id']})")
        src = find_video(vdir, r["youtube_id"]) or (download(vdir, r["youtube_id"]) if args.download else None)
        if not src:
            print(f"  missing {vdir}/{r['youtube_id']}.mp4; skipping")
            continue
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td) / "clip.mp4"
            n = cut_clip(src, r["events"], r["bbox"], clip)
            if n < r["events"][-1] - r["events"][0]:
                print("  video shorter than labels (different upload?); skipping")
                continue
            if args.backend == "modal":
                import modal
                res = modal.Cls.from_name("swinggrade-pose", "Pose")().infer.remote(clip.read_bytes(), 720, 60.0)
            else:
                res = posecore.run_pose(str(clip), estimator=est, max_seconds=60.0)
        ev = [e - r["events"][0] for e in r["events"][1:9]]
        out = {"golfdb_id": r["id"], "player": r["player"].title(), "youtube_id": r["youtube_id"],
               "view": {"face-on": "fo", "down-the-line": "dtl"}[r["view"]], "club": r["club"],
               "slow": r["slow"], "events": ev, **{k: res[k] for k in ("xy", "conf", "t", "width", "height")}}
        (kp_dir / f"{r['id']}.json").write_text(json.dumps(out))
        print(f"  saved {len(res['xy'])} frames -> data/pros/kp/{r['id']}.json")
        done += 1
    print(f"{done} reference(s) built. Restart the server to pick them up.")


if __name__ == "__main__":
    main()
