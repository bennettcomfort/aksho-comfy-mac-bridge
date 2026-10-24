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
if /usr/sbin/lsof -nP -iTCP:18188 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[AKSHO COMFY] ERROR: Aksho ComfyUI is already running."
  exit 1
fi
python3 -c 'import pathlib, sys; sys.path.insert(0, "'"$HERE"'"); import bootstrap_comfy; bootstrap_comfy.patch_browser_cors(pathlib.Path("'"$ROOT"'") / "ComfyUI")'
python3 "$HERE/browser_bridge.py" --root "$ROOT"
cleanup() {
  python3 "$HERE/browser_bridge.py" --root "$ROOT" --stop || true
}
trap cleanup EXIT HUP
echo "[AKSHO COMFY] Starting ComfyUI on port 8188..."
cd "$ROOT"
"$ROOT/.venv/bin/python" -s "$ROOT/ComfyUI/main.py" --port 18188 --listen 127.0.0.1 --enable-cors-header --enable-assets --enable-asset-hashing --disable-auto-launch --preview-method auto
