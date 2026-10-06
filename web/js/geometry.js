// Swing geometry drawn on top of the image: spine angle, head box, butt line /
// sway lines, shoulder plane, shoulder & hip tilt, joint angles and hand path.
// Input is COCO-17 pixel points in the coordinates being drawn (already scaled /
// mirrored), so every angle shown is measured from what is on screen.
const NOSE = 0;
const L = {sho: 5, elb: 7, wri: 9, hip: 11, knee: 13, ank: 15};
const R = {sho: 6, elb: 8, wri: 10, hip: 12, knee: 14, ank: 16};

export const TARGETS = {
  address_forward_bend: {target: 41.5, tol: 6},
  lead_knee_flex_address: {target: 21.5, tol: 9},
  trail_knee_flex_address: {target: 24.4, tol: 8},
  posture_change_impact: {target: 0, tol: 6},
  early_extension: {target: 0, tol: 0.07},
  lead_arm_straightness_top: {target: 168, tol: 12},
  head_move: {target: 0, tol: 0.1},
};

export async function loadTargets() {
  try {
    const j = await (await fetch("/api/benchmarks")).json();
    for (const [k, v] of Object.entries(j)) if (TARGETS[k] && v.target != null) Object.assign(TARGETS[k], v);
  } catch { /* defaults are fine */ }
}

const COL = {ok: "#2ecc71", warn: "#f1c40f", bad: "#e74c3c", neutral: "#ffffff",
  ref: "rgba(255,255,255,0.6)", plane: "#3fa9f5", back: "#f39c12", down: "#00e5ff", tilt: "#c39bd3"};

const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const len = (v) => Math.hypot(v[0], v[1]);
const deg = (r) => r * 180 / Math.PI;
const ext = (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k];
function ang3(a, b, c) {
  const u = sub(a, b), w = sub(c, b);
  const d = (u[0] * w[0] + u[1] * w[1]) / (len(u) * len(w) + 1e-9);
  return deg(Math.acos(Math.max(-1, Math.min(1, d))));
}
function grade(value, target, tol) {
  const z = Math.abs(value - target) / tol;
  return z <= 1 ? COL.ok : z <= 2 ? COL.warn : COL.bad;
}

export function sides(handed) { return handed === "left" ? {lead: R, trail: L} : {lead: L, trail: R}; }

export function bodyInfo(p, handed = "right") {
  const s = sides(handed);
  const hip = mid(p[s.lead.hip], p[s.trail.hip]), sho = mid(p[s.lead.sho], p[s.trail.sho]);
  return {s, hip, sho, torso: len(sub(sho, hip)) || 1, hands: mid(p[9], p[10]), nose: p[NOSE]};
}

export function guessView(p) {
  const b = bodyInfo(p);
  return Math.abs(p[5][0] - p[6][0]) / b.torso > 0.45 ? "fo" : "dtl";
}

// ------------------------------------------------------------- drawing ----
function line(ctx, a, b, color, w, dash = []) {
  ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = w; ctx.setLineDash(dash); ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); ctx.restore();
}
function circle(ctx, c, r, color, w, dash = [], fill = null) {
  ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = w; ctx.setLineDash(dash);
  ctx.beginPath(); ctx.arc(c[0], c[1], r, 0, Math.PI * 2);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  ctx.stroke(); ctx.restore();
}
function label(ctx, text, at, color, fs, dx = 0, dy = 0) {
  ctx.save();
  ctx.font = `600 ${fs}px system-ui, -apple-system, sans-serif`;
  const w = ctx.measureText(text).width + fs * 0.8, h = fs * 1.45;
  const x = Math.min(Math.max(at[0] + dx, 2), ctx.canvas.width - w - 2);
  let y = Math.min(Math.max(at[1] + dy - h / 2, 2), ctx.canvas.height - h - 2);
  // nudge down (then up) until it no longer overlaps an earlier label
  const boxes = ctx.__sgLabels || (ctx.__sgLabels = []);
  const hit = (yy) => boxes.some((b) => x < b[0] + b[2] && x + w > b[0] && yy < b[1] + b[3] && yy + h > b[1]);
  const y0 = y;
  for (let k = 1; hit(y) && k <= 8; k++) {
    y = Math.min(Math.max(y0 + (k % 2 ? 1 : -1) * Math.ceil(k / 2) * (h + 2), 2), ctx.canvas.height - h - 2);
  }
  boxes.push([x, y, w, h]);
  ctx.fillStyle = "rgba(0,0,0,0.68)";
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, h / 2); else ctx.rect(x, y, w, h);
  ctx.fill();
  ctx.fillStyle = color; ctx.textBaseline = "middle";
  ctx.fillText(text, x + fs * 0.4, y + h / 2);
  ctx.restore();
}
function arc(ctx, center, a, b, color, r, w) {
  // small arc showing the angle a-center-b
  const t1 = Math.atan2(a[1] - center[1], a[0] - center[0]);
  const t2 = Math.atan2(b[1] - center[1], b[0] - center[0]);
  let d = t2 - t1; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI;
  ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = w;
  ctx.beginPath(); ctx.arc(center[0], center[1], r, t1, t1 + d, d < 0); ctx.stroke(); ctx.restore();
}

/**
 * o = {pts, ref?, trail?, view, handed, heightCm?, mode: "setup"|"swing", layers?}
 *  pts   current pose (COCO-17 pixels)          ref   address pose (same space) or null
 *  trail [[x,y],...] hand positions since address (backswing orange, downswing cyan)
 *  layers {spine, head, hips, plane, tilt, angles, trail} — any set false is hidden
 * Returns the measured values so callers can show them elsewhere.
 */
export function drawGeometry(ctx, o) {
  const p = o.pts;
  if (!p) return null;
  const handed = o.handed === "left" ? "left" : "right";
  const ref = o.ref || null;
  const view = o.view === "fo" || o.view === "dtl" ? o.view : guessView(ref || p);
  const c = bodyInfo(p, handed), r = ref ? bodyInfo(ref, handed) : null, base = r || c;
  const T = base.torso;
  const H = ctx.canvas.height;
  const fs = Math.round(Math.max(12, Math.min(22, H / 40)));
  const lw = Math.max(2, H / 360);
  const setup = o.mode === "setup" || !ref;
  const show = (k) => !o.layers || o.layers[k] !== false;
  const dist = (v) => o.heightCm ? `${Math.round(Math.abs(v) * 0.29 * o.heightCm)} cm` : `${Math.round(Math.abs(v) * 100)}% torso`;
  const out = {view};
  ctx.__sgLabels = [];

  // ---- hand path ----
  if (show("trail") && o.trail && o.trail.length > 1) {
    let top = 0;
    o.trail.forEach((q, i) => { if (q[1] < o.trail[top][1]) top = i; });
    ctx.save(); ctx.lineWidth = lw * 1.4; ctx.lineJoin = "round"; ctx.lineCap = "round";
    for (const [from, to, col] of [[0, top, COL.back], [top, o.trail.length - 1, COL.down]]) {
      if (to <= from) continue;
      ctx.strokeStyle = col; ctx.beginPath(); ctx.moveTo(o.trail[from][0], o.trail[from][1]);
      for (let i = from + 1; i <= to; i++) ctx.lineTo(o.trail[i][0], o.trail[i][1]);
      ctx.stroke();
    }
    ctx.restore();
  }

  if (view === "dtl") {
    const d = Math.sign(base.hands[0] - base.hip[0]) || 1;  // +1: ball is to the right
    const bend = (b) => deg(Math.atan2(d * (b.sho[0] - b.hip[0]), b.hip[1] - b.sho[1]));

    if (show("plane") && r) {  // address hands through trail shoulder
      const a = r.hands, b = ref[r.s.trail.sho];
      line(ctx, ext(a, b, -0.8), ext(a, b, 1.7), COL.plane, lw, [lw * 4, lw * 3]);
      label(ctx, "Shoulder plane", ext(a, b, 1.7), COL.plane, fs * 0.85, d > 0 ? -fs * 6 : fs * 0.5, 0);
    }

    if (show("hips") && r) {  // butt line: behind the pelvis at address
      const x = r.hip[0] - d * 0.22 * T;
      const ee = d * (c.hip[0] - r.hip[0]) / T;  // + = hips moved toward the ball
      const tol = TARGETS.early_extension.tol;
      const col = ee > tol ? COL.bad : ee > tol / 2 ? COL.warn : COL.ok;
      line(ctx, [x, r.hip[1] - 0.55 * T], [x, Math.max(ref[15][1], ref[16][1]) + 0.05 * T], col, lw, [lw * 3, lw * 2]);
      circle(ctx, [c.hip[0] - d * 0.22 * T, c.hip[1]], lw * 2.5, col, lw, [], col);
      label(ctx, ee > tol / 2 ? `Hips → ball ${dist(ee)}` : "Butt line", [x, r.hip[1] - 0.55 * T], col, fs * 0.85,
        d > 0 ? -fs * 7 : fs * 0.3, -fs);
      out.early_extension = ee;
    }

    if (show("spine")) {
      const b = bend(c);
      let col = COL.neutral, txt = `Spine ${b.toFixed(0)}°`;
      if (setup) {
        const t = TARGETS.address_forward_bend;
        col = grade(b, t.target, t.tol);
        txt += ` (aim ${Math.round(t.target - t.tol)}–${Math.round(t.target + t.tol)})`;
      } else {
        const dlt = b - bend(r);
        col = grade(dlt, 0, TARGETS.posture_change_impact.tol);
        txt += ` (${dlt >= 0 ? "+" : ""}${dlt.toFixed(0)}°)`;
        line(ctx, ext(r.hip, r.sho, -0.1), ext(r.hip, r.sho, 1.4), COL.ref, lw, [lw * 2, lw * 2]);
      }
      line(ctx, ext(c.hip, c.sho, -0.15), ext(c.hip, c.sho, 1.4), col, lw * 1.5);
      line(ctx, c.hip, [c.hip[0], c.hip[1] - 0.6 * T], "rgba(255,255,255,0.35)", lw * 0.8, [lw, lw * 2]);
      arc(ctx, c.hip, [c.hip[0], c.hip[1] - 1], c.sho, col, 0.35 * T, lw);
      label(ctx, txt, ext(c.hip, c.sho, 1.4), col, fs, d > 0 ? -fs * 9 : fs * 0.5, 0);
      out.spine = b;
    }

    if (show("angles") && setup) {  // knee flex is an address check; hidden mid-swing to reduce clutter
      for (const [side, key, place] of [["lead", "lead_knee_flex_address", 1], ["trail", "trail_knee_flex_address", -1]]) {
        const j = c.s[side];
        if (!p[j.knee] || !p[j.ank]) continue;
        const flex = 180 - ang3(p[j.hip], p[j.knee], p[j.ank]);
        const t = TARGETS[key];
        const col = setup ? grade(flex, t.target, t.tol) : COL.neutral;
        arc(ctx, p[j.knee], p[j.hip], p[j.ank], col, 0.18 * T, lw);
        label(ctx, `${side === "lead" ? "Lead" : "Trail"} knee ${flex.toFixed(0)}°`, p[j.knee], col, fs * 0.8,
          place * d > 0 ? fs * 0.8 : -fs * 8.5, place > 0 ? -fs * 0.9 : fs * 0.9);
        out[side + "_knee"] = flex;
      }
    }
  } else {
    // ---------------- face-on ----------------
    const src = ref || p;
    const g = Math.sign(src[c.s.lead.sho][0] - src[c.s.trail.sho][0]) || 1;  // +1: target is to the right

    if (show("hips") && r) {  // sway lines at the address hip positions
      const yTop = r.hip[1] - 0.45 * T, yBot = Math.max(ref[15][1], ref[16][1]) + 0.05 * T;
      const trailX = ref[r.s.trail.hip][0], leadX = ref[r.s.lead.hip][0];
      const sway = -g * (p[c.s.trail.hip][0] - trailX) / T;   // + = trail hip moved away from target
      const slide = g * (p[c.s.lead.hip][0] - leadX) / T;     // + = lead hip moved toward target
      const cT = sway > 0.12 ? COL.bad : sway > 0.06 ? COL.warn : COL.ok;
      const cL = slide > 0.2 ? COL.bad : slide > 0.12 ? COL.warn : COL.ok;
      line(ctx, [trailX, yTop], [trailX, yBot], cT, lw, [lw * 3, lw * 2]);
      line(ctx, [leadX, yTop], [leadX, yBot], cL, lw, [lw * 3, lw * 2]);
      const shift = g * (c.hip[0] - r.hip[0]) / T;
      if (Math.abs(shift) > 0.03) {
        label(ctx, `Hips ${shift > 0 ? "→ target" : "→ trail"} ${dist(shift)}`, [r.hip[0], yBot], Math.abs(shift) > 0.15 ? COL.warn : COL.neutral,
          fs * 0.85, -fs * 4.5, fs * 0.2);
      }
      out.hip_shift = shift;
    }

    if (show("tilt")) {
      for (const [a, b, name, k] of [[c.s.lead.sho, c.s.trail.sho, "Shoulders", 0.4], [c.s.lead.hip, c.s.trail.hip, "Hips", 0.3]]) {
        const pa = p[a], pb = p[b];
        const dx = Math.abs(pa[0] - pb[0]);
        line(ctx, ext(pa, pb, -k), ext(pa, pb, 1 + k), COL.tilt, lw);
        if (dx < 0.15 * T) continue;  // rotated nearly edge-on: angle would be meaningless
        const tilt = deg(Math.atan2(pa[1] - pb[1], dx));  // + = lead side lower
        const at = ext(pa, pb, -k);
        label(ctx, `${name} ${Math.abs(tilt).toFixed(0)}° ${tilt >= 0 ? "lead" : "trail"} down`, at, COL.tilt, fs * 0.8,
          g > 0 ? fs * 0.4 : -fs * 9, name === "Hips" ? fs * 0.9 : -fs * 0.9);
        out[name.toLowerCase() + "_tilt"] = tilt;
      }
    }

    if (show("spine")) {
      const v = sub(c.sho, c.hip);
      const side = deg(Math.atan2(-g * v[0], -v[1]));  // + = leaning away from target
      line(ctx, ext(c.hip, c.sho, -0.15), ext(c.hip, c.sho, 1.45), COL.neutral, lw * 1.5);
      line(ctx, c.hip, [c.hip[0], c.hip[1] - 0.6 * T], "rgba(255,255,255,0.35)", lw * 0.8, [lw, lw * 2]);
      arc(ctx, c.hip, [c.hip[0], c.hip[1] - 1], c.sho, COL.neutral, 0.35 * T, lw);
      if (r && !setup) line(ctx, ext(r.hip, r.sho, -0.1), ext(r.hip, r.sho, 1.4), COL.ref, lw, [lw * 2, lw * 2]);
      label(ctx, `Spine tilt ${Math.abs(side).toFixed(0)}° ${side >= 0 ? "away" : "toward"}`, ext(c.hip, c.sho, 1.45), COL.neutral, fs,
        -fs * 5, -fs * 0.6);
      out.side_bend = side;
    }

    if (show("angles")) {
      const j = c.s.lead;
      const a = ang3(p[j.sho], p[j.elb], p[j.wri]);
      const t = TARGETS.lead_arm_straightness_top;
      const col = setup ? COL.neutral : grade(a, t.target, t.tol);
      arc(ctx, p[j.elb], p[j.sho], p[j.wri], col, 0.15 * T, lw);
      label(ctx, `Lead arm ${a.toFixed(0)}°`, p[j.elb], col, fs * 0.8, fs * 0.6, 0);
      out.lead_arm = a;
    }
  }

  if (show("head") && r) {  // head box: where the head was at address
    const moved = len(sub(c.nose, r.nose)) / T;
    const tol = TARGETS.head_move.tol;
    const col = moved <= tol ? COL.ok : moved <= tol * 1.8 ? COL.warn : COL.bad;
    const rad = 0.17 * T;
    ctx.save(); ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.setLineDash([lw * 3, lw * 2]);
    ctx.strokeRect(r.nose[0] - rad, r.nose[1] - rad * 1.2, rad * 2, rad * 2.2); ctx.restore();
    circle(ctx, c.nose, lw * 2.2, col, lw, [], col);
    if (moved > tol / 2) label(ctx, `Head ${dist(moved)}`, [r.nose[0] + rad, r.nose[1] - rad * 1.2], col, fs * 0.8, fs * 0.3, 0);
    out.head_move = moved;
  }
  return out;
}

// Smoothing + reference/trail bookkeeping for the live camera.
export class LiveGeometry {
  constructor() { this.reset(); }
  reset() { this.sm = null; this.ref = null; this.trail = []; }
  smooth(p) {
    if (!this.sm || this.sm.length !== p.length) { this.sm = p.map((q) => [q[0], q[1]]); return this.sm; }
    // arms move fast in a swing: follow them closely; steady the trunk and legs
    this.sm = this.sm.map((q, i) => {
      const a = i >= 7 && i <= 10 ? 0.85 : 0.45;
      return [q[0] + a * (p[i][0] - q[0]), q[1] + a * (p[i][1] - q[1])];
    });
    return this.sm;
  }
  setReference(p) { this.ref = p.map((q) => [q[0], q[1]]); this.trail = []; }
  addHands(p) { this.trail.push(mid(p[9], p[10])); if (this.trail.length > 900) this.trail.shift(); }
}

// Mirror COCO points horizontally (front camera / mirrored preview).
export function mirrorPts(p, width) { return p ? p.map((q) => [width - q[0], q[1], q[2]]) : p; }
