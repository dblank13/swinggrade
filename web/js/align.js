// Live camera alignment: ghost of the chosen pro's (or a generic) address pose,
// plus framing / level / view checks that turn green when the shot is lined up.
import {drawSkeleton, placePose, bodyFrame} from "./draw.js";
import {getLandmarker, startCamera, stopCamera, runLoop, guessView} from "./pose.js";
import {drawGeometry, mirrorPts, loadTargets, TARGETS} from "./geometry.js";

let stopLoop = null, ghost = null, tilt = null, spoke = false;

function el(id) { return document.getElementById(id); }

async function loadGhost(settings) {
  const view = settings.view === "auto" ? "dtl" : settings.view;
  const r = await fetch(`/api/ghost?view=${view}&pro_id=${encodeURIComponent(settings.proId || "")}`);
  ghost = await r.json();
  ghost.view = view;
  el("align-ghost-src").textContent = ghost.kind === "pro"
    ? `Ghost: ${ghost.player}'s address (${view.toUpperCase()})`
    : `Ghost: generic ${view.toUpperCase()} address (pick a pro with keypoints for their exact setup)`;
}

function setCheck(id, ok, text) {
  const li = el(id);
  li.className = ok === null ? "pending" : ok ? "ok" : "bad";
  li.querySelector("span").textContent = text;
}

function onFrame(f, settings) {
  const canvas = el("align-canvas"), video = el("align-video");
  canvas.width = video.videoWidth; canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const W = canvas.width, H = canvas.height;
  const lefty = settings.handed === "left";
  const mirror = settings.facing === "user" || settings.mirror;
  el("align-fps").textContent = `${f.fps.toFixed(0)} fps`;

  // ghost: anchored on the user's hips/torso when visible, otherwise a default spot
  let cx = W / 2, cy = H * 0.55, scale = H * 0.2;
  // mirroring is done on the points (not with CSS) so overlay text stays readable
  const p = mirror ? mirrorPts(f.coco, W) : f.coco;
  const vis = p ? p.filter((k) => k[2] > 0.5).length : 0;
  if (p && vis >= 12) { const b = bodyFrame(p); cx = b.midHip[0]; cy = b.midHip[1]; scale = b.torso; }
  const ghostPx = ghost ? placePose(ghost.pose, cx, cy, scale, lefty !== mirror) : null;
  if (ghostPx) drawSkeleton(ctx, ghostPx, {color: "#f39c12", alpha: 0.55, width: 6, dots: false});
  if (p) drawSkeleton(ctx, p, {color: "#2ecc71", width: 3, alpha: settings.geometry === false ? 1 : 0.6});
  let geo = null;
  if (p && vis >= 12 && settings.geometry !== false) {
    geo = drawGeometry(ctx, {pts: p, view: settings.view === "auto" ? guessView(p) : settings.view,
      handed: settings.handed, mode: "setup", heightCm: +settings.heightCm || null});
  }

  // ---- checks ----
  if (!p || vis < 12) {
    setCheck("chk-body", false, "Step into frame (whole body, head to feet)");
    ["chk-size", "chk-head", "chk-view", "chk-match"].forEach((c) => setCheck(c, null, "…"));
  } else {
    const ys = p.map((k) => k[1]), xs = p.map((k) => k[0]);
    const top = Math.min(...ys) - 0.12 * scale * 2.5, bottom = Math.max(...ys);
    const feet = Math.max(p[15][1], p[16][1]);
    setCheck("chk-body", p[15][2] > 0.5 && p[16][2] > 0.5 && feet < H * 0.98, "Feet and head visible");
    const frac = (bottom - Math.min(...ys)) / H;
    setCheck("chk-size", frac > 0.45 && frac < 0.75,
      frac <= 0.45 ? `Move closer (body ${Math.round(frac * 100)}% of height, aim 50-70%)` :
      frac >= 0.75 ? `Move back (body ${Math.round(frac * 100)}%, leave room for the club)` : `Size good (${Math.round(frac * 100)}%)`);
    setCheck("chk-head", top > H * 0.04 && Math.min(...xs) > W * 0.05 && Math.max(...xs) < W * 0.95,
      "Room above the head and to the sides for the club");
    const v = guessView(p);
    const want = settings.view === "auto" ? v : settings.view;
    setCheck("chk-view", v === want, v === want ? `View: ${v.toUpperCase()}` :
      want === "fo" ? "Face-on: camera square to your chest, at hand height" : "Down-the-line: camera behind your hands, on the target line");
    if (ghostPx) {
      const idx = [5, 6, 11, 12, 13, 14, 15, 16, 9, 10];
      const d = idx.reduce((s, i) => s + Math.hypot(p[i][0] - ghostPx[i][0], p[i][1] - ghostPx[i][1]), 0) / idx.length / scale;
      setCheck("chk-match", d < 0.22, d < 0.22 ? "Setup matches the ghost" : `Match the ghost setup (off by ${(d * 100).toFixed(0)}% torso)`);
    }
    if (geo && geo.view === "dtl" && geo.spine != null) {
      const t = TARGETS.address_forward_bend;
      const ok = Math.abs(geo.spine - t.target) <= t.tol;
      setCheck("chk-posture", ok, `Spine bend ${geo.spine.toFixed(0)}° (aim ${Math.round(t.target - t.tol)}–${Math.round(t.target + t.tol)}°)` +
        (geo.lead_knee != null ? `, knees ${geo.lead_knee.toFixed(0)}°/${geo.trail_knee.toFixed(0)}°` : ""));
    } else {
      setCheck("chk-posture", true, geo?.view === "fo" ? "Posture: checked from down-the-line" : "Posture");
    }
  }
  if (tilt !== null) setCheck("chk-level", Math.abs(tilt) < 3, `Phone tilt ${tilt.toFixed(1)}°${Math.abs(tilt) < 3 ? "" : ": level it"}`);

  const allOk = [...document.querySelectorAll("#align-checks li")].every((li) => li.className === "ok" || li.id === "chk-level" && tilt === null);
  el("align-banner").classList.toggle("show", allOk);
  if (allOk && !spoke && settings.speak) { speak("Aligned. Ready."); spoke = true; }
  if (!allOk) spoke = false;
}

export function speak(text) {
  if (!("speechSynthesis" in window)) return;
  const u = new SpeechSynthesisUtterance(text); u.rate = 1.05;
  speechSynthesis.cancel(); speechSynthesis.speak(u);
}

export async function enableLevel() {
  if (typeof DeviceOrientationEvent !== "undefined" && DeviceOrientationEvent.requestPermission) {
    const r = await DeviceOrientationEvent.requestPermission();
    if (r !== "granted") throw new Error("Motion permission denied");
  }
  window.addEventListener("deviceorientation", (e) => {
    const landscape = Math.abs(window.orientation || screen.orientation?.angle || 0) === 90;
    tilt = landscape ? (e.beta ?? 0) : (e.gamma ?? 0);  // roll of the phone
  });
}

export async function start(settings) {
  el("align-status").textContent = "Loading pose model…";
  await Promise.all([loadGhost(settings), loadTargets()]);
  const video = el("align-video");
  await startCamera(video, settings.facing);
  const lmk = await getLandmarker(settings.model);
  el("align-status").textContent = "";
  const mirror = settings.facing === "user" || settings.mirror;
  video.classList.toggle("mirror", mirror);
  stopLoop = runLoop(video, lmk, (f) => onFrame(f, settings));
}

export function stop() {
  if (stopLoop) stopLoop();
  stopLoop = null;
  stopCamera(el("align-video"));
}
