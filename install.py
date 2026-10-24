#!/usr/bin/env python3
"""Aksho Comfy installer for Apple Silicon.

Same job as the Windows install.ps1: read manifest.json from dl.akshoai.com,
download the feature packs the user picked, and start ComfyUI on port 8188
so Atelier's Local provider can connect.

The Windows portable runtime (comfyui-portable.zip) is skipped. bootstrap_comfy
checks out the manifest's ComfyUI tag and installs Metal PyTorch instead.

Modes:
  install.py                 install or update, then launch
  install.py --no-launch     install or update, do not start ComfyUI
  install.py --update-check  quick check used by the Run script
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import bootstrap_comfy

PORTABLE_ID = "comfyui-portable"
DEFAULT_BASE_URL = "https://dl.akshoai.com"
COMFY_PORT = 8188
ATELIER_URL = "https://akshoai.com/atelier"
# Kept in sync with the Run .command scripts.
COMFY_ARGS = [
    "--port",
    str(COMFY_PORT),
    "--enable-cors-header",
    "--enable-assets",
    "--enable-asset-hashing",
    "--disable-auto-launch",
    "--preview-method",
    "auto",
]
LAUNCHER_NAMES = (
    "install.py",
    "bootstrap_comfy.py",
    "mac-env.sh",
)
# fp8 text encoders crash on MPS with ComfyUI v0.38.0 (no float8 kernels).
OFF_BY_DEFAULT = {"z-image", "krea2"}
PACK_NOTES = {
    "multi": "RES4LYF in this pack calls CUDA directly. Some multi-character workflows will fail on Mac until that is patched.",
    "z-image": "FP8 text encoder. ComfyUI v0.38.0 cannot run float8 math on Metal. Leave this off.",
    "krea2": "FP8 text encoder. Same Metal limit as Z-Image. Leave this off.",
}

LOG_PATH: Path | None = None


def info(message: str) -> None:
    line = f"[AKSHO COMFY] {message}"
    print(line, flush=True)
    if LOG_PATH is not None:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def die(message: str) -> None:
    info(f"ERROR: {message}")
    raise SystemExit(1)


def format_size(num_bytes: int) -> str:
    if num_bytes >= 1_000_000_000:
        return f"{num_bytes / 1_000_000_000:.2f} GB"
    if num_bytes >= 1_000_000:
        return f"{num_bytes / 1_000_000:.0f} MB"
    return f"{num_bytes} B"


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def default_root() -> Path:
    # A copy living in <root>/installer belongs to that install, same as Windows.
    here = script_dir()
    if here.name == "installer" and (here.parent / "installed.json").is_file():
        return here.parent
    return Path.home() / "AkshoComfy"


def empty_state() -> dict:
    return {"bundleVersion": "", "packs": [], "components": {}, "runtime": {}}


def load_state(root: Path) -> dict:
    path = root / "installed.json"
    if not path.is_file():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_state()
    data.setdefault("bundleVersion", "")
    data.setdefault("components", {})
    data.setdefault("runtime", {})
    packs = data.get("packs") or []
    if isinstance(packs, str):
        packs = [packs]
    data["packs"] = [pack for pack in packs if isinstance(pack, str) and pack]
    return data


def save_state(root: Path, state: dict) -> None:
    path = root / "installed.json"
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def fetch_manifest(base_url: str, timeout: int) -> dict | None:
    url = base_url.rstrip("/") + "/manifest.json"
    destination = Path(tempfile.gettempdir()) / "aksho-comfy-manifest.json"
    result = subprocess.run(
        ["curl", "-fsS", "-m", str(timeout), "-o", str(destination), url],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(destination.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def component_index(manifest: dict) -> dict[str, dict]:
    return {component["id"]: component for component in manifest["components"]}


def pack_download_bytes(pack: dict, components: dict[str, dict]) -> int:
    total = 0
    for component_id in pack["components"]:
        if component_id == PORTABLE_ID:
            continue
        component = components.get(component_id)
        if component:
            total += int(component["sizeBytes"])
    return total


def default_pack_ids(manifest: dict) -> list[str]:
    chosen = []
    for pack in manifest["packs"]:
        if pack.get("required") or pack["id"] not in OFF_BY_DEFAULT:
            chosen.append(pack["id"])
    return chosen


def console_picker(manifest: dict, components: dict[str, dict], root: Path, selected: list[str], allow_folder: bool) -> tuple[Path, list[str]]:
    info("Choose what to install (Enter keeps the shown answer).")
    chosen: list[str] = []
    for pack in manifest["packs"]:
        size = format_size(pack_download_bytes(pack, components))
        if pack.get("required"):
            print(f"  [x] {pack['label']} ({size}) - required", flush=True)
            if pack.get("description"):
                print(f"      {pack['description']}", flush=True)
            chosen.append(pack["id"])
            continue
        if pack.get("description"):
            print(f"      {pack['description']}", flush=True)
        note = PACK_NOTES.get(pack["id"])
        if note:
            print(f"      Note: {note}", flush=True)
        default = "Y" if pack["id"] in selected else "N"
        answer = input(f"  {pack['label']} ({size})? [{default}] ").strip()
        if not answer:
            answer = default
        if answer.lower().startswith("y"):
            chosen.append(pack["id"])
    print(flush=True)
    print("ComfyUI itself and PyTorch come from GitHub and PyPI (a few GB), not from the Windows portable zip.", flush=True)
    if allow_folder:
        answer = input(f"Install folder [{root}] ").strip()
        if answer:
            root = Path(answer).expanduser()
    return root, chosen


def resolve_selection(manifest: dict, components: dict[str, dict], args: argparse.Namespace, root: Path, state: dict, fresh: bool) -> tuple[Path, list[str]]:
    required = [pack["id"] for pack in manifest["packs"] if pack.get("required")]
    if args.packs:
        requested = [part.strip() for part in args.packs.split(",") if part.strip()]
        known = {pack["id"] for pack in manifest["packs"]}
        unknown = [pack_id for pack_id in requested if pack_id not in known]
        if unknown:
            die(f"Unknown pack id: {', '.join(unknown)}")
        selected = list(dict.fromkeys([*required, *requested]))
        return root, selected

    saved = list(state["packs"])
    if fresh or not saved:
        saved = default_pack_ids(manifest)
    if args.yes or not sys.stdin.isatty():
        if not args.yes:
            info("No interactive terminal. Using the default pack selection. Pass --packs to override.")
        return root, saved
    allow_folder = fresh and not args.install_path
    return console_picker(manifest, components, root, saved, allow_folder)


def selected_components(manifest: dict, pack_ids: list[str]) -> list[dict]:
    wanted: set[str] = set()
    chosen = set(pack_ids)
    for pack in manifest["packs"]:
        if pack.get("required") or pack["id"] in chosen:
            wanted.update(pack["components"])
    return [component for component in manifest["components"] if component["id"] in wanted]


def rename_migrations(root: Path, components: list[dict]) -> None:
    for component in components:
        old_rel = component.get("renameFrom")
        if not old_rel:
            continue
        target = root / component["targetPath"]
        old = root / old_rel
        if target.exists() or not old.exists():
            continue
        info(f"Renaming {old_rel} -> {component['targetPath']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        old.rename(target)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_component(state: dict, component: dict) -> None:
    state["components"][component["id"]] = {
        "sha256": component["sha256"],
        "sizeBytes": int(component["sizeBytes"]),
        "installedAt": datetime.now(timezone.utc).isoformat(),
    }


def needs_install(root: Path, component: dict, state: dict) -> bool:
    recorded = state["components"].get(component["id"])
    target = root / component["targetPath"]
    if recorded is None and component["kind"] == "file" and target.is_file() and target.stat().st_size == int(component["sizeBytes"]):
        info(f"Checking {component['id']} already on disk...")
        if file_sha256(target).lower() == component["sha256"].lower():
            record_component(state, component)
            return False
    if recorded is None or str(recorded.get("sha256", "")).lower() != component["sha256"].lower():
        return True
    if component["kind"] == "file":
        if not target.is_file() or target.stat().st_size != int(component["sizeBytes"]):
            return True
        return False
    if component["kind"] == "archive-extract":
        return not target.exists()
    die(f"Unknown component kind '{component.get('kind')}' for {component['id']}")
    return True


def ensure_disk_space(root: Path, needed: list[dict], runtime_missing: bool) -> None:
    total = sum(int(component["sizeBytes"]) for component in needed)
    total = int(total * 1.2)
    if runtime_missing:
        total += 6_000_000_000
    probe = root
    while not probe.exists():
        probe = probe.parent
    free = shutil.disk_usage(probe).free
    if free < total:
        die(f"Not enough disk space. Need about {format_size(total)}, {format_size(free)} free.")


def download(url: str, dest: Path, expected_sha256: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = Path(str(dest) + ".part")
    for attempt in range(1, 4):
        result = subprocess.run(
            ["curl", "-fL", "-C", "-", "--retry", "3", "--retry-delay", "5", "--progress-bar", "-o", str(part), url]
        )
        if result.returncode != 0:
            if attempt == 3:
                die(f"Download failed: {url}")
            info(f"Download interrupted (attempt {attempt}), resuming...")
            continue
        info(f"Verifying {dest.name}...")
        actual = file_sha256(part)
        if actual.lower() == expected_sha256.lower():
            os.replace(part, dest)
            return
        info(f"Hash mismatch (attempt {attempt}), redownloading...")
        part.unlink(missing_ok=True)
    die(f"Hash verification failed after retries: {url}")


def install_component(root: Path, component: dict) -> None:
    downloads = root / "_downloads"
    kind = component["kind"]
    if kind == "file":
        staged = downloads / component["id"]
        download(component["url"], staged, component["sha256"])
        target = root / component["targetPath"]
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, target)
        return
    if kind == "archive-extract":
        staged = downloads / f"{component['id']}.zip"
        download(component["url"], staged, component["sha256"])
        target = root / component["targetPath"]
        target.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["tar", "-xf", str(staged), "-C", str(target)])
        if result.returncode != 0:
            die(f"Extraction failed: {component['id']}")
        staged.unlink(missing_ok=True)
        return
    die(f"Unknown component kind '{kind}' for {component['id']}")


def portable_component(components: list[dict]) -> dict:
    for component in components:
        if component["id"] == PORTABLE_ID:
            return component
    die("Manifest has no comfyui-portable component, so there is no ComfyUI version to install.")
    return {}


def runtime_ready(root: Path, state: dict, portable: dict) -> bool:
    runtime = state.get("runtime") or {}
    python = bootstrap_comfy.venv_python(root)
    comfy_dir = root / "ComfyUI"
    return (
        python.is_file()
        and (comfy_dir / "main.py").is_file()
        and bootstrap_comfy.installed_comfy_version(comfy_dir) == portable.get("sourceVersion")
        and runtime.get("sha256") == portable.get("sha256")
        and runtime.get("sourceVersion") == portable.get("sourceVersion")
    )


def post_install(root: Path, components: list[dict]) -> None:
    python = bootstrap_comfy.venv_python(root)
    if not python.is_file():
        die(f"Python environment is missing at {python}")
    for component in components:
        post = component.get("postInstall") or {}
        if not post:
            continue
        ext_dir = root / component["targetPath"]
        requirements = post.get("pipRequirements")
        if requirements:
            req_path = ext_dir / requirements
            if req_path.is_file():
                info(f"Installing Python packages for {component['id']}...")
                bootstrap_comfy.pip_install(python, ["-r", str(req_path)])
        script = post.get("runScript")
        if script:
            script_path = ext_dir / script
            if script_path.is_file():
                info(f"Running setup script for {component['id']}...")
                result = subprocess.run([str(python), str(script_path)], cwd=ext_dir)
                if result.returncode != 0:
                    die(f"Setup script failed for {component['id']}")


def install_base_packages(root: Path, manifest: dict) -> None:
    packages = list(manifest.get("basePipPackages") or [])
    if not packages:
        return
    python = bootstrap_comfy.venv_python(root)
    if not python.is_file():
        return
    info("Ensuring base Python packages...")
    bootstrap_comfy.pip_install(python, packages)


def copy_installer(root: Path) -> None:
    destination = root / "installer"
    destination.mkdir(parents=True, exist_ok=True)
    for name in LAUNCHER_NAMES:
        source = script_dir() / name
        target = destination / name
        if not source.is_file():
            continue
        if source.resolve() == target.resolve():
            continue
        shutil.copy2(source, target)


def command_header() -> str:
    return """#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$ROOT/installer/mac-env.sh"
cd "$ROOT"
"""


def write_launchers(root: Path) -> None:
    run_script = command_header() + f"""python3 -u "$ROOT/installer/install.py" --update-check --install-path "$ROOT" || true
if /usr/sbin/lsof -nP -iTCP:8188 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[AKSHO COMFY] ERROR: Port 8188 is already in use. Quit the other ComfyUI, then run this again."
  exit 1
fi
echo "[AKSHO COMFY] Starting ComfyUI on port 8188..."
exec "$ROOT/.venv/bin/python" -s "$ROOT/ComfyUI/main.py" {' '.join(COMFY_ARGS)}
"""
    update_script = command_header() + """python3 -u "$ROOT/installer/install.py" --no-launch --install-path "$ROOT"
echo
read -r -p "Press return to close." _
"""
    agent_script = command_header() + """if [[ ! -f "$ROOT/agent/aksho-agent.py" ]]; then
  echo "[AKSHO COMFY] Relay agent is not installed. Install the Core pack first."
  exit 1
fi
echo "[AKSHO COMFY] Starting the Aksho agent. Leave this window open while you generate."
exec "$ROOT/.venv/bin/python" -u "$ROOT/agent/aksho-agent.py"
"""
    files = {
        "Run Aksho ComfyUI.command": run_script,
        "Update Aksho ComfyUI.command": update_script,
        "Run Aksho Agent.command": agent_script,
    }
    for name, body in files.items():
        path = root / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)


def wait_for_comfy(timeout_sec: int = 180) -> bool:
    url = f"http://127.0.0.1:{COMFY_PORT}/system_stats"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(2)
    return False


def launch(root: Path) -> None:
    command = root / "Run Aksho ComfyUI.command"
    info("Starting ComfyUI for a first health check...")
    subprocess.Popen(["open", str(command)])
    if wait_for_comfy():
        info(f"ComfyUI is ready on http://127.0.0.1:{COMFY_PORT}")
        info("Opening Atelier. Pick the Local provider and connect to 127.0.0.1:8188.")
        subprocess.run(["open", ATELIER_URL], check=False)
        return
    die("ComfyUI did not respond within 3 minutes. Check the ComfyUI terminal window.")


def start_log(root: Path) -> None:
    global LOG_PATH
    log_dir = root / "installer"
    log_dir.mkdir(parents=True, exist_ok=True)
    LOG_PATH = log_dir / "last-run.log"
    LOG_PATH.write_text("", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install or update Aksho Comfy on Apple Silicon.")
    parser.add_argument("--install-path", default="", help="Install folder. Default: ~/AkshoComfy")
    parser.add_argument("--update-check", action="store_true", help="Fast launch-time update check.")
    parser.add_argument("--no-launch", action="store_true", help="Install or update without starting ComfyUI.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--yes", action="store_true", help="Accept the default pack selection without prompting.")
    parser.add_argument("--packs", default="", help="Comma-separated pack ids to install. Required packs are always included.")
    return parser.parse_args()


def confirm_update(state: dict, manifest: dict, assume_yes: bool) -> bool:
    current = state.get("bundleVersion") or "none"
    new_version = manifest["bundleVersion"]
    if not assume_yes and sys.stdin.isatty():
        answer = input(f"Update available ({current} -> {new_version}). Update now? [Y/n] ").strip().lower()
        if answer == "n":
            return False
        return True
    info(f"Update available ({current} -> {new_version}). Applying it.")
    return True


def main() -> None:
    bootstrap_comfy.require_apple_silicon()
    args = parse_args()
    root = Path(args.install_path).expanduser() if args.install_path else default_root()
    fresh = not (root / "installed.json").is_file()
    state = load_state(root)

    if root.exists():
        start_log(root)

    if args.update_check:
        manifest = fetch_manifest(args.base_url, 3)
        if manifest is None:
            info("Offline - skipping update check.")
            raise SystemExit(0)
        portable = portable_component(manifest["components"])
        versions_match = manifest.get("bundleVersion") == state.get("bundleVersion")
        if versions_match and runtime_ready(root, state, portable):
            raise SystemExit(0)
        if versions_match:
            info("ComfyUI runtime is missing or out of date. Repairing...")
        elif not confirm_update(state, manifest, args.yes):
            raise SystemExit(0)
    else:
        manifest = fetch_manifest(args.base_url, 30)
        if manifest is None:
            die("Could not fetch the update manifest. Check your connection and try again.")

    if not args.update_check:
        components_by_id = component_index(manifest)
        root, pack_ids = resolve_selection(manifest, components_by_id, args, root, state, fresh)
    else:
        pack_ids = list(state["packs"]) or default_pack_ids(manifest)

    root.mkdir(parents=True, exist_ok=True)
    if LOG_PATH is None:
        start_log(root)

    components = selected_components(manifest, pack_ids)
    portable = portable_component(components)
    downloads = [component for component in components if component["id"] != PORTABLE_ID]
    source_version = portable.get("sourceVersion") or "v0.38.0"

    rename_migrations(root, downloads)
    needed = [component for component in downloads if needs_install(root, component, state)]
    # needs_install may adopt on-disk files into state.
    save_state(root, state)

    runtime_missing = not runtime_ready(root, state, portable)
    if needed or runtime_missing:
        ensure_disk_space(root, needed, runtime_missing)

    if runtime_missing:
        info(f"Setting up ComfyUI {source_version} with Metal PyTorch...")
        bootstrap_comfy.bootstrap(root, source_version)
        state["runtime"] = {
            "sourceVersion": source_version,
            "sha256": portable.get("sha256"),
            "installedAt": datetime.now(timezone.utc).isoformat(),
        }
        save_state(root, state)

    if not needed:
        info(f"Everything is up to date (bundle {manifest['bundleVersion']}).")
    else:
        total = sum(int(component["sizeBytes"]) for component in needed)
        info(f"{len(needed)} component(s) to download (about {format_size(total)}).")
        for component in needed:
            info(f"Downloading {component['id']} ({format_size(int(component['sizeBytes']))})...")
            install_component(root, component)
            record_component(state, component)
            save_state(root, state)

    post_targets = components if runtime_missing else needed
    post_install(root, [component for component in post_targets if component.get("postInstall")])
    install_base_packages(root, manifest)

    state["bundleVersion"] = manifest["bundleVersion"]
    state["packs"] = pack_ids
    save_state(root, state)
    copy_installer(root)
    write_launchers(root)
    downloads_dir = root / "_downloads"
    if downloads_dir.exists():
        shutil.rmtree(downloads_dir, ignore_errors=True)

    info(f"Done (bundle {manifest['bundleVersion']}).")
    info(f"Install folder: {root}")
    if args.update_check or args.no_launch:
        raise SystemExit(0)
    launch(root)


if __name__ == "__main__":
    main()
