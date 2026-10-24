#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/mac-env.sh"
ROOT="${AKSHO_COMFY_ROOT:-$HOME/AkshoComfy}"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "[AKSHO COMFY] Not installed yet. Double-click \"Install Aksho Comfy.command\" first."
  exit 1
fi
python3 -u "$HERE/install.py" --update-check --install-path "$ROOT" || true
if /usr/sbin/lsof -nP -iTCP:8188 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[AKSHO COMFY] ERROR: Port 8188 is already in use. Quit the other ComfyUI, then run this again."
  exit 1
fi
echo "[AKSHO COMFY] Starting ComfyUI on port 8188..."
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -s "$ROOT/ComfyUI/main.py" --port 8188 --enable-cors-header --enable-assets --enable-asset-hashing --disable-auto-launch --preview-method auto
