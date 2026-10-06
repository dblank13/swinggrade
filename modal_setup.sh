#!/usr/bin/env bash
# Connect the Modal GPU worker (optional). Free Starter plan: $30/month credit.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
. .venv/bin/activate

if [ ! -f "$HOME/.modal.toml" ] && [ -z "${MODAL_TOKEN_ID:-}" ]; then
  echo "Opening Modal sign-in (creates a free account if you don't have one)..."
  modal token new
fi

echo "Building and deploying the pose worker (first build takes a few minutes)..."
MODAL_GPU="${MODAL_GPU:-L4}" MODAL_SCALEDOWN_S="${MODAL_SCALEDOWN_S:-15}" modal deploy modal_worker/pose_worker.py

cat <<EOF

Modal worker deployed on ${MODAL_GPU:-L4}. POSE_BACKEND=auto will now use it until the
app's estimate reaches MODAL_MONTHLY_BUDGET_USD=${MODAL_MONTHLY_BUDGET_USD:-25}, then fall back to CPU.

Recommended hard backstop: modal.com -> Settings -> Usage & Billing -> set a workspace
spending limit (e.g. \$30) so Modal itself stops before you are charged.
EOF
