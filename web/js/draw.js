// Skeleton drawing helpers (COCO-17 layout).
export const SKELETON = [[5,6],[5,7],[7,9],[6,8],[8,10],[5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16],[0,5],[0,6]];
export const MP_TO_COCO = [0,2,5,7,8,11,12,13,14,15,16,23,24,25,26,27,28];

export function drawSkeleton(ctx, pts, {color = "#2ecc71", width = 3, alpha = 1, dots = true} = {}) {
  if (!pts) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = width; ctx.lineCap = "round";
  for (const [a, b] of SKELETON) {
    if (!pts[a] || !pts[b]) continue;
    ctx.beginPath(); ctx.moveTo(pts[a][0], pts[a][1]); ctx.lineTo(pts[b][0], pts[b][1]); ctx.stroke();
  }
  if (dots) for (const p of pts) { if (!p) continue; ctx.beginPath(); ctx.arc(p[0], p[1], width * 1.2, 0, 7); ctx.fill(); }
  // head
  if (pts[0]) { ctx.beginPath(); ctx.arc(pts[0][0], pts[0][1], width * 4, 0, 7); ctx.stroke(); }
  ctx.restore();
}

// Torso-unit pose (origin mid-hip, y down) -> canvas pixels.
export function placePose(pose, cx, cy, scale, mirror = false) {
  return pose.map(([x, y]) => [cx + (mirror ? -x : x) * scale, cy + y * scale]);
}

// Draw two normalised poses side by side (or overlaid) on a canvas.
export function drawCompare(canvas, userPose, proPose, {overlay = false, labels = ["You", "Pro"]} = {}) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const scale = H / 4.2, cy = H * 0.52;
  if (overlay) {
    if (proPose) drawSkeleton(ctx, placePose(proPose, W / 2, cy, scale), {color: "#f39c12", alpha: 0.85});
    if (userPose) drawSkeleton(ctx, placePose(userPose, W / 2, cy, scale), {color: "#2ecc71"});
  } else {
    if (userPose) drawSkeleton(ctx, placePose(userPose, W * 0.27, cy, scale), {color: "#2ecc71"});
    if (proPose) drawSkeleton(ctx, placePose(proPose, W * 0.73, cy, scale), {color: "#f39c12"});
    ctx.fillStyle = "#aaa"; ctx.font = "14px system-ui";
    ctx.fillText(labels[0], W * 0.27 - 14, 18);
    if (proPose) ctx.fillText(labels[1], W * 0.73 - 14, 18);
  }
}

// Mid-hip and torso length of a COCO pose in pixels.
export function bodyFrame(p) {
  const mh = [(p[11][0] + p[12][0]) / 2, (p[11][1] + p[12][1]) / 2];
  const ms = [(p[5][0] + p[6][0]) / 2, (p[5][1] + p[6][1]) / 2];
  return {midHip: mh, midSho: ms, torso: Math.hypot(ms[0] - mh[0], ms[1] - mh[1])};
}
