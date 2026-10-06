// Live (beta): detect a swing from the camera, send keypoints, show/speak the grade.
// Phone-side MediaPipe does the pose work, so live grading needs no GPU or Modal.
import {drawSkeleton, bodyFrame} from "./draw.js";
import {getLandmarker, startCamera, stopCamera, runLoop} from "./pose.js";
import {speak} from "./align.js";
import {drawGeometry, LiveGeometry, mirrorPts, loadTargets} from "./geometry.js";
import {guessView} from "./pose.js";

const STILL = 0.45;        // torso lengths / s
const MOVE = 1.6;
const SWING_PEAK = 3.0;    // a real swing gets well above this
const PRE_ROLL = 1.2, POST_ROLL = 0.35, MAX_SWING = 5.0;

let stopLoop = null, state = "waiting", buf = [], prev = null, speed = 0, stillSince = null;
const geo = new LiveGeometry();
let swingStart = 0, peak = 0, onResultCb = null, settingsRef = null, fpsSeen = 0, busy = false;

const el = (id) => document.getElementById(id);

function setState(s, msg) {
  state = s;
  el("live-state").textContent = msg;
  el("live-state").className = "chip " + s;
}

async function submit(frames, video) {
  busy = true;
  setState("grading", "Grading…");
  try {
    const body = {frames, width: video.videoWidth, height: video.videoHeight,
      view: settingsRef.view, handed: settingsRef.handed, pro_id: settingsRef.proId || "",
      height_cm: settingsRef.heightCm || null};
    const r = await fetch("/api/analyze_keypoints", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "Could not grade that swing");
    const g = j.tour, cue = j.cues?.[0];
    el("live-card").innerHTML = `<div class="grade ${g.letter}">${g.letter}</div>
      <div><b>${g.score.toFixed(0)}/100</b> vs tour${j.pro ? ` · ${j.pro.grade.letter} vs ${j.pro.player}` : ""}<br>
      ${cue ? cue.text : "Nice swing. Nothing major to fix."}<br>
      <small>Tempo ${j.metrics.tempo_ratio?.value.toFixed(1) ?? "?"}:1 · ${j.fps_effective} fps</small></div>`;
    el("live-card").classList.add("show");
    if (settingsRef.speak) speak(`${g.letter}. ${Math.round(g.score)}. ${cue ? cue.text.split(".")[0] : "Nice swing"}.`);
    if (onResultCb) onResultCb(j);
  } catch (e) {
    el("live-card").innerHTML = `<div class="grade F">?</div><div>${e.message}</div>`;
    el("live-card").classList.add("show");
  } finally {
    busy = false;
    stillSince = null;
    setState("ready", "Set up again to re-arm");
  }
}

function onFrame(f, video) {
  const canvas = el("live-canvas");
  canvas.width = video.videoWidth; canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  fpsSeen = f.fps;
  el("live-fps").textContent = `${f.fps.toFixed(0)} fps`;
  buf.push({t: f.t, lm: f.lm});
  while (buf.length && f.t - buf[0].t > 9) buf.shift();
  if (busy) return;

  const mirror = settingsRef.facing === "user" || settingsRef.mirror;
  const p = mirror ? mirrorPts(f.coco, canvas.width) : f.coco;
  const vis = p ? p.filter((k) => k[2] > 0.5).length : 0;
  if (!p || vis < 11) {
    prev = null; speed = 0;
    if (state !== "swinging") setState("waiting", "Step into frame");
    return;
  }
  const sm = geo.smooth(p);
  if (state === "swinging") geo.addHands(p);
  drawSkeleton(ctx, p, {color: state === "swinging" ? "#e74c3c" : "#2ecc71", alpha: settingsRef.geometry === false ? 1 : 0.55});
  if (settingsRef.geometry !== false) {
    const atAddress = (state === "armed" || state === "ready" || state === "waiting") && geo.trail.length === 0;
    drawGeometry(ctx, {pts: sm, ref: geo.ref, trail: geo.trail,
      view: settingsRef.view === "auto" ? guessView(geo.ref || sm) : settingsRef.view,
      handed: settingsRef.handed, heightCm: +settingsRef.heightCm || null,
      mode: atAddress || !geo.ref ? "setup" : "swing"});
  }
  const b = bodyFrame(p);
  const hands = [(p[9][0] + p[10][0]) / 2, (p[9][1] + p[10][1]) / 2];
  if (prev) {
    const dt = Math.max(1e-3, f.t - prev.t);
    const v = Math.hypot(hands[0] - prev.h[0], hands[1] - prev.h[1]) / dt / Math.max(b.torso, 1);
    speed = 0.5 * speed + 0.5 * v;
  }
  prev = {t: f.t, h: hands};

  if (state === "waiting" || state === "ready") {
    if (speed < STILL) {
      stillSince ??= f.t;
      if (f.t - stillSince > 0.5) { setState("armed", "Armed: swing when ready"); geo.setReference(sm); }
      else setState("ready", "Hold your address…");
    } else { stillSince = null; setState("ready", "Hold still at address to arm"); }
  } else if (state === "armed" || state === "grading") {
    if (state === "armed" && speed < STILL) geo.setReference(sm);  // keep address current while waggling settles
    if (speed > MOVE) { state = "swinging"; swingStart = f.t; peak = speed; setState("swinging", "Swing detected…"); el("live-card").classList.remove("show"); }
  } else if (state === "swinging") {
    peak = Math.max(peak, speed);
    if (speed < STILL) { stillSince ??= f.t; } else { stillSince = null; }
    const settled = stillSince !== null && f.t - stillSince > 0.4;
    if (settled || f.t - swingStart > MAX_SWING) {
      if (peak >= SWING_PEAK) {
        const frames = buf.filter((x) => x.t >= swingStart - PRE_ROLL && x.t <= f.t + POST_ROLL && x.lm);
        submit(frames, video);
      } else {
        stillSince = f.t;
        setState("armed", "Waggle ignored. Armed.");
      }
    }
  }
}

export async function start(settings, onResult) {
  settingsRef = settings; onResultCb = onResult;
  const video = el("live-video");
  el("live-state").textContent = "Loading pose model…";
  const cam = await startCamera(video, settings.facing);
  const lmk = await getLandmarker(settings.model);
  el("live-cam").textContent = `camera ${cam.width}×${cam.height}${cam.fps ? " @ " + Math.round(cam.fps) + " fps" : ""}`;
  const mirror = settings.facing === "user" || settings.mirror;
  video.classList.toggle("mirror", mirror);
  buf = []; prev = null; stillSince = null; busy = false; geo.reset();
  loadTargets();
  setState("waiting", "Step into frame");
  stopLoop = runLoop(video, lmk, (f) => onFrame(f, video));
}

export function stop() {
  if (stopLoop) stopLoop();
  stopLoop = null;
  stopCamera(el("live-video"));
}
