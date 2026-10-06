// Send browser-side errors to the server so they show up in the container logs
// (Railway → Deploy logs, search "client-error"). Best effort, rate limited.
let sent = 0;
const seen = new Set();

export function reportError(where, err, extra = {}) {
  const msg = err && err.message ? err.message : String(err);
  const key = where + "|" + msg;
  if (seen.has(key) || sent >= 30) return;
  seen.add(key);
  sent++;
  const body = JSON.stringify({
    where, message: msg.slice(0, 1000), stack: (err && err.stack ? String(err.stack) : "").slice(0, 2000),
    page: location.pathname + location.hash, ua: navigator.userAgent, ...extra,
  });
  try {
    if (navigator.sendBeacon) navigator.sendBeacon("/api/client-log", new Blob([body], {type: "application/json"}));
    else fetch("/api/client-log", {method: "POST", headers: {"Content-Type": "application/json"}, body, keepalive: true});
  } catch { /* never let reporting break the app */ }
}

window.addEventListener("error", (e) => {
  // resource load failures (img/script/link) have no message, only a target
  if (e.target && e.target !== window && (e.target.src || e.target.href)) {
    reportError("resource", new Error(`failed to load ${e.target.src || e.target.href}`));
  } else {
    reportError("window.onerror", e.error || e.message, {source: e.filename, line: e.lineno});
  }
}, true);
window.addEventListener("unhandledrejection", (e) => reportError("unhandledrejection", e.reason));
