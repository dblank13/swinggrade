#!/usr/bin/env bash
# One-time setup on any Linux box (Ubuntu/Debian, Fedora/RHEL, Arch, openSUSE).
# Creates .venv, installs Python deps, downloads browser + server pose models.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

# ---- system packages: python3 + venv, ffmpeg -------------------------------
need=()
command -v ffmpeg >/dev/null || need+=(ffmpeg)
command -v python3 >/dev/null || need+=(python3)
python3 -c "import venv, ensurepip" 2>/dev/null || need+=(venv)
if ((${#need[@]})); then
  say "Installing system packages: ${need[*]}"
  SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  if command -v apt-get >/dev/null; then
    $SUDO apt-get update -y && $SUDO apt-get install -y ffmpeg python3 python3-venv python3-pip curl
  elif command -v dnf >/dev/null; then
    $SUDO dnf install -y python3 python3-pip curl && ($SUDO dnf install -y ffmpeg || \
      echo "ffmpeg needs RPM Fusion on Fedora/RHEL: https://rpmfusion.org/Configuration")
  elif command -v pacman >/dev/null; then
    $SUDO pacman -Sy --noconfirm ffmpeg python python-pip curl
  elif command -v zypper >/dev/null; then
    $SUDO zypper install -y ffmpeg python3 python3-pip curl
  else
    echo "Please install: python3 (3.10+), python3-venv, ffmpeg, curl"; exit 1
  fi
fi
python3 - <<'EOF'
import sys
if sys.version_info < (3, 10):
    sys.exit("Python 3.10+ required")
EOF

# ---- python venv ------------------------------------------------------------
say "Creating .venv and installing Python packages"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

# ---- pose models: MediaPipe for the browser, RTMPose for the CPU fallback ----
say "Downloading pose models"
sh tools/fetch_models.sh

[ -f .env ] || cp .env.example .env
mkdir -p work

say "Running tests"
python -m pytest -q || echo "(tests failed; see above)"

cat <<'EOF'

Setup complete.
  Start the server:      ./run.sh
  Add the Modal GPU:     ./modal_setup.sh      (optional, free tier)
  Phone needs HTTPS:     ./run.sh --tunnel     (free Cloudflare quick tunnel)
EOF
