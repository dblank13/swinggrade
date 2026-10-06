#!/usr/bin/env bash
# Start SwingGrade. Usage: ./run.sh [--tunnel]
#   --tunnel  also start a free Cloudflare quick tunnel and print the https:// URL
#             for your phone (camera access in Safari requires HTTPS).
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
. .venv/bin/activate
HOST="${HOST:-0.0.0.0}"; PORT="${PORT:-8000}"

if [[ "${1:-}" == "--tunnel" ]]; then
  if ! command -v cloudflared >/dev/null; then
    arch=$(uname -m); case "$arch" in x86_64) a=amd64;; aarch64|arm64) a=arm64;; armv7l) a=arm;; *) a=amd64;; esac
    echo "Downloading cloudflared ($a) to ./bin ..."
    mkdir -p bin
    curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$a" -o bin/cloudflared
    chmod +x bin/cloudflared
    export PATH="$PWD/bin:$PATH"
  fi
  cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT" 2>&1 | \
    grep --line-buffered -o 'https://[a-z0-9-]*\.trycloudflare\.com' | \
    while read -r url; do printf '\n\033[1;32mOpen on your phone: %s\033[0m\n\n' "$url"; done &
  trap 'kill 0' EXIT
fi

echo "SwingGrade on http://$HOST:$PORT  (pose backend: ${POSE_BACKEND:-auto})"
exec uvicorn swinggrade.app:app --host "$HOST" --port "$PORT" --proxy-headers --forwarded-allow-ips='*'
