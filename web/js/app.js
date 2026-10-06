import {reportError} from "./report.js";
import * as align from "./align.js";
import * as live from "./live.js";
import {drawSkeleton, drawCompare} from "./draw.js";
import {drawGeometry, loadTargets} from "./geometry.js";

const el = (id) => document.getElementById(id);
const EVENTS = ["address", "toe_up", "mid_backswing", "top", "mid_downswing", "impact", "mid_follow_through", "finish"];
const LABEL = {address: "Address", toe_up: "Toe-up", mid_backswing: "Mid-back", top: "Top",
  mid_downswing: "Mid-down", impact: "Impact", mid_follow_through: "Follow", finish: "Finish"};

// ------------------------------------------------------------- settings ----
const settings = JSON.parse(localStorageGet("sg-settings") || "null") || {
  view: "dtl", handed: "right", proId: "", heightCm: "", facing: "environment",
  mirror: false, model: "full", speak: true, geometry: true,
};
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function save() { try { localStorage.setItem("sg-settings", JSON.stringify(settings)); } catch {} }

function bindSettings() {
  const map = {"s-view": "view", "s-handed": "handed", "s-height": "heightCm", "s-facing": "facing", "s-model": "model"};
  for (const [id, key] of Object.entries(map)) {
    el(id).value = settings[key];
    el(id).onchange = () => { settings[key] = el(id).value; save(); if (key === "view") loadPros(); };
  }
  for (const [id, key] of [["s-mirror", "mirror"], ["s-speak", "speak"], ["s-geo", "geometry"]]) {
    el(id).checked = settings[key] !== false;
    el(id).onchange = () => { settings[key] = el(id).checked; save(); };
  }
  el("s-pro").onchange = () => { settings.proId = el("s-pro").value; save(); showProInfo(); };
}

let pros = [];
async function loadPros() {
  const view = settings.view === "auto" ? "" : settings.view;
  pros = (await (await fetch(`/api/pros?view=${view}`)).json()).pros;
  const sel = el("s-pro");
  sel.innerHTML = `<option value="">None (tour norms only)</option>` + pros.map((p) =>
    `<option value="${p.id}">${p.player} · ${p.view.toUpperCase()} · ${p.n_swings} swings${p.has_keypoints ? " ★" : ""}</option>`).join("");
  if (pros.some((p) => p.id === settings.proId)) sel.value = settings.proId;
  else { settings.proId = ""; sel.value = ""; }
  showProInfo();
}
function showProInfo() {
  const p = pros.find((x) => x.id === settings.proId);
  el("pro-info").textContent = p
    ? `${p.player}: tempo ${p.tempo_mean}:1${p.tempo_sd ? ` (±${p.tempo_sd})` : ""}` +
      (p.downswing_s_mean ? `, downswing ${p.downswing_s_mean.toFixed(2)} s` : "") +
      ` from ${p.n_swings} GolfDB swings. ` + (p.has_keypoints ? "★ Full body comparison available." : "Tempo comparison (run tools/build_pro_keypoints.py for full body comparison).")
    : "";
}

// ----------------------------------------------------------------- tabs ----
function showTab(name) {
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll("section.tab").forEach((s) => s.hidden = s.id !== "tab-" + name);
  if (name !== "align") align.stop();
  if (name !== "live") live.stop();
}

// --------------------------------------------------------------- upload ----
async function upload(file) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("view", settings.view); fd.append("handed", settings.handed);
  fd.append("pro_id", settings.proId || ""); fd.append("height_cm", settings.heightCm || "");
  fd.append("capture_fps", el("u-fps").value);
  const status = el("u-status");
  status.textContent = `Uploading ${(file.size / 1e6).toFixed(1)} MB…`;
  el("u-go").disabled = true;
  try {
    const r = await fetch("/api/analyze", {method: "POST", body: fd});
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || "Upload failed");
    const localUrl = URL.createObjectURL(file);
    for (;;) {
      await new Promise((res) => setTimeout(res, 1500));
      const s = await (await fetch(`/api/jobs/${j.job_id}`)).json();
      status.textContent = s.progress || s.state;
      if (s.state === "done") { renderResult(s.result, localUrl); showTab("results"); status.textContent = ""; break; }
      if (s.state === "error") throw new Error(s.error);
    }
  } catch (e) { status.textContent = "⚠ " + e.message; reportError("upload", e); }
  finally { el("u-go").disabled = false; refreshStatus(); }
}

// -------------------------------------------------------------- results ----
let current = null, player = null;

function fmt(r, heightCm) {
  const v = r.value;
  if (r.unit === "torso" && r.cm == null && heightCm) r = {...r, cm: +(v * 0.29 * heightCm).toFixed(1)};
  const unit = {deg: "°", s: " s", ratio: ":1", torso: " torso"}[r.unit] ?? "";
  const main = r.unit === "torso" && r.cm != null ? `${r.cm} cm` : `${(+v).toFixed(r.unit === "deg" ? 1 : 2)}${unit}`;
  return main;
}

function scoreClass(s) { return s >= 85 ? "good" : s >= 65 ? "fair" : "poor"; }

function renderResult(res, videoUrl) {
  current = res;
  const pro = res.pro;
  const g = res.tour;
  let html = `<div class="grades">
    <div class="gcard"><div class="grade ${g.letter}">${g.letter}</div><div>${g.score.toFixed(0)}/100<br><small>vs tour norms</small></div></div>`;
  if (pro) html += `<div class="gcard"><div class="grade ${pro.grade.letter}">${pro.grade.letter}</div><div>${pro.grade.score.toFixed(0)}/100<br><small>vs ${pro.player}${pro.keypoints ? "" : " (tempo)"}</small></div></div>`;
  html += `</div>`;
  html += `<p class="meta">${res.source === "live" ? "LIVE (beta, lower precision)" : "Upload"} · view ${res.view.toUpperCase()} · ${res.handed}-handed · ${res.fps_effective} fps` +
    (res.time_scale !== 1 ? ` · slow-mo ×${res.time_scale}` : "") +
    (res.processing ? ` · ${res.processing.backend}${res.processing.total_seconds ? `, ${res.processing.total_seconds}s` : ""}${res.processing.est_cost_usd ? `, ~$${res.processing.est_cost_usd.toFixed(4)}` : ""}` : "") + `</p>`;
  for (const w of res.warnings) html += `<p class="warn">⚠ ${w}</p>`;
  html += `<h3>Fix first</h3>` + (res.cues.length ? `<ol class="cues">${res.cues.map((c) => `<li><b>${c.label}</b> (${c.score.toFixed(0)}): ${c.text}</li>`).join("")}</ol>` : `<p>Nothing major vs tour norms.</p>`);
  if (pro?.cues?.length) html += `<h3>Biggest differences vs ${pro.player}</h3><ol class="cues">${pro.cues.map((c) => `<li><b>${c.label}</b>: ${c.text}</li>`).join("")}</ol>`;
  if (pro?.similarity) html += `<p>Motion similarity to ${pro.player}: <b>${pro.similarity.overall}</b>/100 ` +
    `(back ${pro.similarity["address->top"]}, down ${pro.similarity["top->impact"]}, through ${pro.similarity["impact->finish"]})</p>`;
  el("r-summary").innerHTML = html;

  // categories
  el("r-cats").innerHTML = Object.entries(g.categories).map(([c, s]) =>
    `<div class="bar"><span>${c.replace("_", " / ")}</span><div><i class="${scoreClass(s)}" style="width:${s}%"></i></div><b>${s.toFixed(0)}</b></div>`).join("");

  // metric table
  const proRows = pro ? Object.fromEntries(pro.grade.rows.map((r) => [r.metric, r])) : {};
  el("r-table").innerHTML = `<tr><th>Metric</th><th>You</th><th>Tour</th>${pro ? `<th>${pro.player.split(" ").pop()}</th>` : ""}<th>Score</th></tr>` +
    g.rows.sort((a, b) => a.metric.localeCompare(b.metric)).map((r) => {
      const pr = proRows[r.metric];
      return `<tr title="${r.source}"><td>${r.label}<small class="rel ${r.reliability}">${r.reliability}</small></td><td>${fmt(r)}</td>` +
        `<td>${fmt({...r, value: r.target, cm: null}, res.height_cm)}</td>${pro ? `<td>${pr ? fmt({...pr, value: pr.target, cm: null}, res.height_cm) : "–"}</td>` : ""}` +
        `<td class="${scoreClass(r.score)}">${r.score.toFixed(0)}</td></tr>`;
    }).join("");

  // event buttons
  el("r-events").innerHTML = EVENTS.map((e) => `<button data-ev="${e}">${LABEL[e]}</button>`).join("");
  el("r-events").querySelectorAll("button").forEach((b) => b.onclick = () => selectEvent(b.dataset.ev));

  // video + overlay (upload) or skeleton replay (live)
  const vid = el("r-video");
  if (player) player.stop();
  if (videoUrl && res.source === "upload") {
    vid.hidden = false; vid.src = videoUrl;
    player = startOverlay(vid, el("r-overlay"), res);
  } else {
    vid.hidden = true; vid.removeAttribute("src");
    player = startReplay(el("r-overlay"), res);
  }
  selectEvent("top");
}

function nearest(ts, t) {
  let lo = 0, hi = ts.length - 1;
  while (lo < hi) { const m = (lo + hi) >> 1; if (ts[m] < t) lo = m + 1; else hi = m; }
  return lo > 0 && Math.abs(ts[lo - 1] - t) < Math.abs(ts[lo] - t) ? lo - 1 : lo;
}

// Draw skeleton + swing geometry for analysed frame i, mapped by (s, ox, oy).
function drawFrame(ctx, res, i, s, ox, oy) {
  const ov = res.overlay;
  const map = (q) => [ox + q[0] * s, oy + q[1] * s];
  const pts = ov.xy[i].map(map);
  const geoOn = el("r-geo").checked;
  if (el("r-skel").checked) drawSkeleton(ctx, pts, {width: 2, alpha: geoOn ? 0.55 : 1});
  if (!geoOn) return;
  const a = nearest(ov.t_file, res.events.address.t_file);
  const fin = nearest(ov.t_file, res.events.finish.t_file);
  const trail = [];
  for (let k = a; k <= Math.min(i, fin); k++) trail.push(map([(ov.xy[k][9][0] + ov.xy[k][10][0]) / 2, (ov.xy[k][9][1] + ov.xy[k][10][1]) / 2]));
  drawGeometry(ctx, {pts, ref: ov.xy[a].map(map), trail, view: res.view, handed: res.handed,
    heightCm: res.height_cm, mode: i <= a ? "setup" : "swing"});
}

function startOverlay(video, canvas, res) {
  let run = true;
  const ov = res.overlay;
  const draw = () => {
    if (!run) return;
    canvas.width = video.clientWidth; canvas.height = video.clientHeight;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (ov.xy.length && canvas.width) {
      // fit the analysed frame into the displayed video box (object-fit: contain)
      const s = Math.min(canvas.width / ov.width, canvas.height / ov.height);
      const ox = (canvas.width - ov.width * s) / 2, oy = (canvas.height - ov.height * s) / 2;
      drawFrame(ctx, res, nearest(ov.t_file, video.currentTime), s, ox, oy);
    }
    requestAnimationFrame(draw);
  };
  draw();
  return {stop: () => { run = false; }, seek: (t) => { video.pause(); video.currentTime = t; }};
}

// Live results have no video: replay the skeleton. Tap to play/pause; event buttons seek.
function startReplay(canvas, res) {
  const ov = res.overlay;
  let run = true, i = 0, playing = true;
  const W = Math.min(720, canvas.parentElement.clientWidth * (window.devicePixelRatio || 1) || 720);
  canvas.width = W; canvas.height = Math.round(W * ov.height / ov.width);
  const ctx = canvas.getContext("2d");
  const s = canvas.width / ov.width;
  const dt = ov.t_file.length > 1 ? (ov.t_file.at(-1) - ov.t_file[0]) / (ov.t_file.length - 1) : 0.033;
  const paint = () => {
    ctx.fillStyle = "#111"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    drawFrame(ctx, res, i, s, 0, 0);
  };
  const tick = () => {
    if (!run) return;
    paint();
    if (playing) i = (i + 1) % ov.xy.length;
    setTimeout(() => requestAnimationFrame(tick), Math.max(16, dt * 1000 * 2));  // half speed
  };
  canvas.onclick = () => { playing = !playing; };
  tick();
  return {stop: () => { run = false; canvas.onclick = null; },
    seek: (t) => { playing = false; i = nearest(ov.t_file, t); paint(); }};
}

function selectEvent(ev) {
  if (!current) return;
  el("r-events").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.ev === ev));
  if (player) player.seek(current.events[ev].t_file);
  const pro = current.pro;
  drawCompare(el("r-compare"), current.poses[ev], pro?.poses?.[ev] || null,
    {overlay: el("r-overlaycmp").checked, labels: ["You", pro?.player || "Pro"]});
  el("r-evtime").textContent = `${LABEL[ev]} at ${current.events[ev].t.toFixed(2)} s`;
}

// --------------------------------------------------------------- status ----
async function refreshStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    const u = s.modal_usage;
    el("status").textContent = `Pose: ${s.next_backend}${s.modal_configured ? ` · Modal ${s.modal_gpu} $${u.est_usd.toFixed(2)}/${u.budget_usd} this month (${u.calls} runs)` : " · Modal not configured"}`;
  } catch { el("status").textContent = "Server offline?"; }
}

// ----------------------------------------------------------------- init ----
window.addEventListener("DOMContentLoaded", async () => {
  bindSettings();
  document.querySelectorAll("nav button").forEach((b) => b.onclick = () => showTab(b.dataset.tab));
  el("u-file").onchange = el("u-cam").onchange = (e) => { el("u-name").textContent = e.target.files[0]?.name || ""; el("u-go").dataset.src = e.target.id; };
  el("u-go").onclick = () => { const f = el(el("u-go").dataset.src || "u-file").files[0]; if (f) upload(f); else el("u-status").textContent = "Pick or record a clip first."; };
  el("a-start").onclick = () => align.start(settings).catch((e) => { el("align-status").textContent = "⚠ " + e.message; reportError("align.start", e); });
  el("a-stop").onclick = () => align.stop();
  el("a-level").onclick = () => align.enableLevel().catch((e) => alert(e.message));
  el("l-start").onclick = () => live.start(settings, (r) => renderResult(r, null)).catch((e) => { el("live-state").textContent = "⚠ " + e.message; reportError("live.start", e); });
  el("l-stop").onclick = () => live.stop();
  el("l-details").onclick = () => current && showTab("results");
  el("r-overlaycmp").onchange = () => { const on = el("r-events").querySelector("button.on"); if (on) selectEvent(on.dataset.ev); };
  if (!window.isSecureContext) el("secure-warn").hidden = false;
  window.SG = {renderResult, showTab, settings};  // handy from the browser console
  showTab("upload");
  loadTargets();
  el("r-geo").checked = settings.geometry !== false;
  await loadPros();
  refreshStatus();
});
