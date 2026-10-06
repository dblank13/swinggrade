// In-browser pose (MediaPipe Pose Landmarker, Apache-2.0) + camera helpers.
// setup.sh downloads the library and model into web/vendor so the phone does not
// depend on third-party CDNs; if they are missing we fall back to the CDN.
import {MP_TO_COCO} from "./draw.js";

const LOCAL = {
  lib: "./vendor/tasks-vision/vision_bundle.mjs",
  wasm: "./vendor/tasks-vision/wasm",
  model: (v) => `./vendor/models/pose_landmarker_${v}.task`,
};
const CDN = {
  lib: "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/vision_bundle.mjs",
  wasm: "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.0.1/wasm",
  model: (v) => `https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_${v}/float16/latest/pose_landmarker_${v}.task`,
};

let landmarker = null, loadedVariant = null;

async function exists(url) {
  try { return (await fetch(url, {method: "HEAD"})).ok; } catch { return false; }
}

export async function getLandmarker(variant = "full") {
  if (landmarker && loadedVariant === variant) return landmarker;
  const src = (await exists(LOCAL.lib)) && (await exists(LOCAL.model(variant))) ? LOCAL : CDN;
  const vision = await import(src.lib);
  const files = await vision.FilesetResolver.forVisionTasks(src.wasm);
  const opts = (delegate) => ({
    baseOptions: {modelAssetPath: src.model(variant), delegate},
    runningMode: "VIDEO", numPoses: 1,
    minPoseDetectionConfidence: 0.5, minPosePresenceConfidence: 0.5, minTrackingConfidence: 0.5,
  });
  try { landmarker = await vision.PoseLandmarker.createFromOptions(files, opts("GPU")); }
  catch { landmarker = await vision.PoseLandmarker.createFromOptions(files, opts("CPU")); }
  loadedVariant = variant;
  return landmarker;
}

export async function startCamera(video, facing = "environment") {
  if (video.srcObject) video.srcObject.getTracks().forEach((t) => t.stop());
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera needs HTTPS (or localhost).");
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {facingMode: facing, width: {ideal: 1280}, height: {ideal: 720}, frameRate: {ideal: 60}},
  });
  video.srcObject = stream;
  video.setAttribute("playsinline", "");
  video.muted = true;
  await video.play();
  const s = stream.getVideoTracks()[0].getSettings();
  return {width: video.videoWidth, height: video.videoHeight, fps: s.frameRate};
}

export function stopCamera(video) {
  if (video.srcObject) video.srcObject.getTracks().forEach((t) => t.stop());
  video.srcObject = null;
}

// Run the landmarker on every new video frame; cb({t, lm, coco, fps}).
export function runLoop(video, lmk, cb) {
  let running = true, last = -1, n = 0, t0 = performance.now(), fps = 0;
  const step = () => {
    if (!running) return;
    if (video.readyState >= 2 && video.currentTime !== last) {
      last = video.currentTime;
      const now = performance.now();
      const res = lmk.detectForVideo(video, now);
      n++;
      if (now - t0 > 1000) { fps = (n * 1000) / (now - t0); n = 0; t0 = now; }
      const lm = res.landmarks?.[0];
      const W = video.videoWidth, H = video.videoHeight;
      cb({
        t: now / 1000, fps,
        lm: lm ? lm.map((p) => [+p.x.toFixed(5), +p.y.toFixed(5), +(p.visibility ?? 1).toFixed(3)]) : null,
        coco: lm ? MP_TO_COCO.map((i) => [lm[i].x * W, lm[i].y * H, lm[i].visibility ?? 1]) : null,
      });
    }
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(step);
    else requestAnimationFrame(step);
  };
  step();
  return () => { running = false; };
}

// Camera-side view guess: wide shoulders vs torso = face-on, narrow = down-the-line.
export function guessView(coco) {
  const sw = Math.abs(coco[5][0] - coco[6][0]);
  const mh = [(coco[11][0] + coco[12][0]) / 2, (coco[11][1] + coco[12][1]) / 2];
  const ms = [(coco[5][0] + coco[6][0]) / 2, (coco[5][1] + coco[6][1]) / 2];
  const torso = Math.hypot(ms[0] - mh[0], ms[1] - mh[1]) || 1;
  return sw / torso > 0.45 ? "fo" : "dtl";
}
