#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/mac-env.sh"
ROOT="${AKSHO_COMFY_ROOT:-$HOME/AkshoComfy}"
if [[ ! -f "$ROOT/agent/aksho-agent.py" ]]; then
  echo "[AKSHO COMFY] Relay agent is not installed. Install the Core pack first."
  exit 1
fi
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "[AKSHO COMFY] ComfyUI's Python is missing. Run \"Install Aksho Comfy.command\" first."
  exit 1
fi
echo "[AKSHO COMFY] Starting the Aksho agent. Leave this window open while you generate."
cd "$ROOT"
exec "$ROOT/.venv/bin/python" -u "$ROOT/agent/aksho-agent.py"
