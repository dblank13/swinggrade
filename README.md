# SwingGrade (prototype)

Grade a golf swing from a phone video. Get the swing geometry, the top fixes, and a
comparison with a tour pro, using body keypoints only (no club or face data).

- **Upload (primary):** record a Slo-mo clip, upload it, and get a grade, cues, geometry and a skeleton overlay.
- **Live (beta):** the phone watches through the camera, detects a swing by itself, and speaks the grade.
- **Align:** a ghost of the pro's (or a generic) address pose, plus green/red framing checks to line up the camera.
- **Pick a pro to mimic:** 280 player/view references built from real GolfDB pro swing labels.

Hardware-agnostic: the phone only needs a browser. The server runs on any Linux box, and the
heavy pose step can go to a Modal GPU on the free tier.

```
Phone (Safari/Chrome, installable as a home-screen app)
 ├─ Align: camera → MediaPipe in browser → ghost + checks
 ├─ Live:  camera → MediaPipe in browser → swing detector → POST keypoints ─┐
 └─ Upload: Slo-mo clip ────────────────────────────── POST video ─┐        │
                                                                    ▼        ▼
Linux box (FastAPI)                                         same analysis pipeline
 ├─ pose: Modal GPU (RTMPose, budget-capped)  ──or──  local CPU (RTMPose/ONNX)
 └─ events → metrics → grades (tour + pro) → cues → JSON
```

## Quick start (Ubuntu or any Linux)

```bash
./setup.sh            # ffmpeg, venv, Python deps, browser + server pose models, runs tests
./run.sh --tunnel     # starts the server + a free Cloudflare HTTPS tunnel, prints the phone URL
```

Open the printed `https://….trycloudflare.com` URL on your iPhone. Safari only allows camera
access over HTTPS. Then tap **Share → Add to Home Screen** to get an app-like icon; no App Store needed.

Without `--tunnel` the app is on `http://<box-ip>:8000`. Upload works over plain HTTP, but Align
and Live (camera) do not. Tailscale Funnel or your own reverse proxy also work instead of Cloudflare.
The quick-tunnel URL changes each run; a named Cloudflare tunnel gives a fixed one.

Alternatively: `docker build -t swinggrade . && docker run -p 8000:8000 swinggrade`.

## Modal GPU on the free tier (optional)

```bash
./modal_setup.sh      # modal token new (free account) + deploy modal_worker/pose_worker.py
```

| Setting (.env) | Default | Why |
|---|---|---|
| `POSE_BACKEND` | `auto` | Modal while under budget, else this CPU; also falls back if Modal errors |
| `MODAL_GPU` | `L4` | ~$0.000222/s GPU + CPU/RAM ≈ $0.00026/s total; `T4` is ~25% cheaper |
| `MODAL_MONTHLY_BUDGET_USD` | `25` | app-side cap, leaving headroom under the $30/month Starter credit |
| `MODAL_SCALEDOWN_S` | `15` | idle GPU time is billed, so keep it short |

How the budget guard works:
- Each Modal run is charged in `work/modal_usage.json` as (call time + idle window) × rate. This is deliberately pessimistic.
- When the month's estimate hits the cap, analysis switches to the local CPU until the 1st.
- The footer shows spend so far.
- `max_containers=1` stops bursts from fanning out across many GPUs.
- Also set a **workspace spending limit** in the Modal dashboard as a hard backstop.

Expected cost is roughly $0.005–0.01 per uploaded swing (estimate; dominated by cold start + idle
window), so $25 covers on the order of 2,500+ swings a month. Live mode costs nothing because the
phone does the pose work. Rates are from modal.com/pricing (Oct 2026); check them before relying on them.

## Using it

1. **Settings:**
   - **View:** Down-the-line = camera behind the hands on the target line; Face-on = camera square to the chest.
   - **Handedness**
   - **Pro:** filtered by view; ★ means full-body keypoints are available.
   - **Height:** optional; turns distances into cm.
2. **Align:** tap *Start camera*, match the orange ghost, and get all checks green. *Enable level*
   uses the phone's motion sensor. To see the screen from the tee, AirPlay or Chromecast-mirror the phone to a TV or tablet.
3. **Upload:** record with the Camera app in **Slo-mo** (120/240 fps) on a tripod at hand height,
   trim to one swing, then upload. Slo-mo files re-exported at 30 fps are detected and re-timed
   automatically, or you can set *Capture frame rate* yourself.
4. **Live (beta):** hold still at address (it arms), swing, and the grade is spoken. Expect ~30 fps
   from Safari's live camera, so tempo and impact timing are rough and every metric is marked as lower reliability.

## Geometry overlay

Swing geometry is drawn on the image itself in three places:
- **Align:** a setup checker on the live camera.
- **Live:** during and after each swing.
- **Results:** on the uploaded video, or on the skeleton replay for live swings.

It is drawn by `web/js/geometry.js` on the phone, using the same keypoints and targets as the grader (`/api/benchmarks`). Colors: green means within tolerance, yellow is borderline, red needs work.

| Layer | Down-the-line | Face-on |
|---|---|---|
| Spine | spine line + angle from vertical; at address vs the 41.5° target, mid-swing as change vs address (dashed line = address spine) | side-bend line + angle away from / toward target |
| Hips | **butt line** behind the address pelvis; turns red when the hips move toward the ball (early extension) | **sway lines** at the address hip positions; trail line turns red on sway, lead line on excessive slide |
| Head | box around the address head position; dot = head now | same |
| Plane / tilt | shoulder plane line (address hands → trail shoulder) | shoulder and hip tilt lines with angle (lead/trail down) |
| Angles | lead and trail knee flex at address | lead arm angle |
| Hand path | orange backswing, cyan downswing | same |

Live mode captures the address reference when it arms (you're still at address). It draws the hand path during the swing and keeps it on screen until it re-arms.

To turn the overlay off: Settings → *Draw swing geometry*, or the *swing geometry* checkbox in Results.

## What's measured

Swing events follow GolfDB's 8: address, toe-up, mid-backswing, top, mid-downswing, impact,
mid-follow-through, finish. They are found from hand trajectory and stillness.

| Metric | View | Tour target (source) | Reliability |
|---|---|---|---|
| Tempo (backswing:downswing) | both | 3.4:1, GolfDB median of 1,400 pro swings | good |
| Downswing time | both | 0.28 s (GolfDB pros; Chu 2010: 0.30 ± 0.06 s) | good |
| Head rise at impact | both | 0 | good |
| Forward bend at address | DTL | 41.5° (elite golfers, JSSM 2018) | good |
| Knee flex at address | DTL | 21.5° lead / 24.4° trail (JSSM 2018) | moderate |
| Posture change, top / impact | DTL | 0° (Chu 2010) | good |
| Early extension | DTL | 0 (TPI) | good |
| Hands vs shoulder-plane line at top | DTL | vs pro only | moderate |
| Head sway at top / shift at impact | FO | ~0 | good |
| Pelvis sway at top / slide at impact | FO | ~2 cm each (Chu 2010) | good |
| Shoulder tilt, top / impact | FO | 48° / 25° (Meister 2011) | moderate |
| Side bend at impact | FO | 14.4° (Chu 2010) | good |
| Lead arm angle at top | FO | ~168° | moderate |
| Shoulder turn, hip turn, X-factor | FO | 88° / 45° / 45° (2D-projected) | **weak** |

Each metric scores `100·exp(−z²/2)` with `z = (you − target)/tol`.
- Category weights: posture 25, sway/head 20, tempo 15, rotation 15, arms 15, similarity-to-pro 10.
- Reliability scales a metric's weight within its category.
- Cues come from the largest weighted shortfalls, skipping weak metrics.
- Targets and cue text live in `swinggrade/benchmarks.json`. Edit them freely.

You get two grades:
- **vs tour norms**
- **vs your pro:** the pro's real GolfDB tempo and downswing time. When their keypoints have been extracted, it also uses their per-metric values and a phase-aligned DTW motion similarity.

## The pro library (real data)

- `data/golfdb_index.json` is extracted from GolfDB's `golfDB.mat` (McNally et al., CVPR-W 2019): 1,400 labelled swings, 246 players, 580 YouTube videos.
- `tools/build_pro_index.py` builds `data/pros/index.json`: one reference per player and view (2+ swings), with their tempo and downswing time computed from the human-labelled event frames.
  - Sanity check: the median is 3.4:1; Inbee Park's famously slow tempo comes out 5–6:1; Rory McIlroy's is 2.8:1.
- Full-body references (ghost, per-metric targets, DTW) need keypoints from the actual swing video:

```bash
pip install yt-dlp     # or put <youtube_id>.mp4 files in data/golfdb_videos/ yourself
python tools/build_pro_keypoints.py --player "Rory McIlroy" --list
python tools/build_pro_keypoints.py --player "Rory McIlroy" --view dtl --club driver --limit 2 --download [--backend modal]
```

This trims each clip to GolfDB's labelled bounds, crops to the golfer, runs pose, and stores only
keypoints in `data/pros/kp/`. Restart the server afterwards.

**Licensing:**
- GolfDB annotations and code are CC BY-NC 4.0.
- The footage belongs to the broadcasters/tours. Download it only for personal, non-commercial use, and don't redistribute it.
- For anything public or commercial, record or license your own reference swings.

## Project layout

```
swinggrade/app.py            FastAPI: upload jobs, live keypoint endpoint, pros, ghost, status
swinggrade/posecore.py       ffprobe/ffmpeg decode (rotation, real timestamps) + RTMPose; shared with Modal
swinggrade/pose/backends.py  Modal-vs-local choice, budget accounting, fallback
swinggrade/analysis/         keypoints (cleaning, lefty mirroring, smoothing) · events · metrics · scoring · compare (DTW) · pipeline
modal_worker/pose_worker.py  Modal GPU class (CUDA 12 + onnxruntime-gpu + rtmlib, models baked into the image)
web/                         phone UI: upload, align (ghost), live beta, results; PWA manifest
tools/                       GolfDB extraction, pro index/keypoint builders, synthetic swing generator
tests/                       pipeline + API tests (synthetic swings with known answers)
```

Open source used:
- MediaPipe Pose Landmarker (Apache-2.0)
- RTMPose via rtmlib (Apache-2.0)
- GolfDB labels (CC BY-NC 4.0)
- FastAPI, NumPy/SciPy, OpenCV, ffmpeg

## Limitations and next steps

- **2D only.** Rotation metrics are projections and can't exceed 90°. Treat them as trends against yourself and your pro.
- **Event detection is heuristic.** It uses no club data, so impact is "hands back at address height". SwingNet (GolfDB) is more accurate but is non-commercial and needs trimmed clips.
- **Generic pose models drift on fast hands and self-occlusion.** Good light and 240 fps help most. GolfPose's golf-tuned models are the accuracy upgrade.
- **Live mode on iPhone is capped by Safari's ~30 fps camera.** Android Chrome is usually better.
- **Possible next steps:**
  - a 3D lifting step for real turn angles
  - a fixed tunnel URL
  - history of your swings over time
