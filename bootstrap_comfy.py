#!/usr/bin/env python3
"""Install the Mac ComfyUI runtime into an Aksho Comfy folder.

The Windows bundle downloads comfyui-portable.zip (embedded CPython plus a
CUDA build of PyTorch). That zip does not run on Apple Silicon. This module
checks out the same ComfyUI tag and installs the normal macOS PyTorch wheel,
which uses Metal (MPS).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

COMFY_REPO = "https://github.com/Comfy-Org/ComfyUI.git"
PYTHON_VERSION = "3.13"


def info(message: str) -> None:
    print(f"[AKSHO COMFY] {message}", flush=True)


def die(message: str) -> None:
    print(f"[AKSHO COMFY] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def require_apple_silicon() -> None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        die("This installer is for Apple Silicon Macs (M1 or later).")


def require_tool(name: str, hint: str) -> str:
    found = shutil.which(name)
    if not found:
        die(f"Could not find `{name}` on PATH. {hint}")
    return found


def run(command: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        die(f"Command failed ({result.returncode}): {' '.join(command)}")


def venv_python(root: Path) -> Path:
    return root / ".venv" / "bin" / "python"


def ensure_venv(root: Path) -> Path:
    python = venv_python(root)
    if python.exists():
        return python
    uv = require_tool("uv", "Install it from https://docs.astral.sh/uv/getting-started/installation/")
    info(f"Creating a Python {PYTHON_VERSION} environment...")
    run([uv, "venv", "--python", PYTHON_VERSION, str(root / ".venv")])
    if not python.exists():
        die(f"uv did not create {python}")
    return python


def installed_comfy_version(comfy_dir: Path) -> str:
    stamp = comfy_dir / ".aksho-version"
    if not stamp.is_file():
        return ""
    return stamp.read_text(encoding="utf-8").strip()


def ensure_comfy(root: Path, source_version: str) -> None:
    """Check out ComfyUI without touching models or custom nodes.

    Those directories are untracked (ComfyUI gitignores them), so a later
    tag checkout keeps weights the installer already downloaded.
    """
    dest = root / "ComfyUI"
    if dest.is_dir() and (dest / "main.py").is_file() and installed_comfy_version(dest) == source_version:
        info(f"ComfyUI {source_version} is already present.")
        return
    if dest.exists() and not (dest / ".git").is_dir():
        die(f"{dest} exists but is not a ComfyUI git checkout. Move that folder aside and run the installer again.")

    git = require_tool("git", "Install the Xcode command line tools, or Homebrew git.")
    if not dest.exists():
        info(f"Cloning ComfyUI {source_version}...")
        run([git, "clone", "--depth", "1", "--branch", source_version, COMFY_REPO, str(dest)])
    else:
        info(f"Updating ComfyUI to {source_version}...")
        run([git, "fetch", "--depth", "1", "origin", "tag", source_version], cwd=dest)
        run([git, "checkout", "--detach", source_version], cwd=dest)
    (dest / ".aksho-version").write_text(source_version + "\n", encoding="utf-8")


def pip_install(python: Path, packages: list[str]) -> None:
    if not packages:
        return
    uv = require_tool("uv", "Install it from https://docs.astral.sh/uv/getting-started/installation/")
    run([uv, "pip", "install", "--python", str(python), *packages])


def install_runtime_packages(python: Path, comfy_dir: Path) -> None:
    # PyPI's macOS torch wheel is the Metal build. Do not pass a CUDA index.
    info("Installing PyTorch for Apple Silicon...")
    pip_install(python, ["torch", "torchvision"])
    info("Installing ComfyUI's Python packages. The first run takes a while...")
    pip_install(python, ["-r", str(comfy_dir / "requirements.txt")])


def assert_mps(python: Path) -> None:
    info("Checking Metal acceleration...")
    script = (
        "import torch\n"
        "ok = torch.backends.mps.is_available()\n"
        "print(f'[AKSHO COMFY] torch {torch.__version__}  MPS {ok}')\n"
        "raise SystemExit(0 if ok else 1)\n"
    )
    result = subprocess.run([str(python), "-c", script])
    if result.returncode != 0:
        die("PyTorch installed, but Metal (MPS) is not available. ComfyUI would run on CPU only.")


def bootstrap(root: Path, source_version: str) -> Path:
    """Create .venv, check out ComfyUI, and install MPS PyTorch. Returns the venv python."""
    require_apple_silicon()
    root.mkdir(parents=True, exist_ok=True)
    python = ensure_venv(root)
    ensure_comfy(root, source_version)
    install_runtime_packages(python, root / "ComfyUI")
    assert_mps(python)
    return python
