#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/mac-env.sh"
ROOT="${AKSHO_COMFY_ROOT:-$HOME/AkshoComfy}"
python3 -u "$HERE/install.py" --no-launch --install-path "$ROOT"
echo
read -r -p "Press return to close." _
