# Aksho Comfy for Mac

Double-click installer that puts a local ComfyUI on an Apple Silicon Mac so [AkshoAI Atelier](https://akshoai.com/atelier) can generate images on this computer.

This is the Mac version of [aksho-comfy](https://github.com/aksho-technologies/aksho-comfy). That project is a Windows installer: it downloads ComfyUI's NVIDIA portable build, the Dreamhex checkpoint, and Atelier's add-ons, then starts a server on `127.0.0.1:8188`. The models and add-ons are the same here. The Windows Python and CUDA PyTorch are not. This installer checks out the same ComfyUI version and installs Apple's Metal build of PyTorch instead.

## Requirements

- Apple Silicon Mac (M1 or later). Intel Macs are not supported.
- macOS 13 or later
- About 20 GB free for the core install, and up to about 50 GB if every pack is selected
- [uv](https://docs.astral.sh/uv/getting-started/installation/) and git

16 GB of memory is a practical minimum for Dreamhex (SDXL) plus image reference. More is better.

## Install

1. Clone this repo.
2. Double-click `Install Aksho Comfy.command`.
3. Leave Core ticked. Leave Z-Image and Krea2 off (see below). Pick any other packs you want.
4. Wait for the downloads. The default folder is `~/AkshoComfy`.
5. ComfyUI starts on port 8188 and Atelier opens. Choose the **Local** provider and connect to `127.0.0.1:8188`.

A core-only install from the terminal, without opening ComfyUI at the end:

```bash
python3 install.py --yes --packs core --no-launch
```

Start the server later with `Run Aksho ComfyUI.command` in this repo or in `~/AkshoComfy`. Atelier expects port 8188. If another ComfyUI is already using that port, quit it first. Add packs later with `Update Aksho ComfyUI.command`. `Run Aksho Agent.command` starts the optional remote agent, which dials out to Aksho so Atelier can reach this ComfyUI when you are not on the same machine.

## Pack notes

| Pack | On a Mac |
|---|---|
| Core | The path Atelier uses to generate. Dreamhex, image reference, the model-info route, and the relay agent. |
| ADetailer, Upscaling, 3D Poser, Inpaint, Anima | Weights are the same files as Windows. Face detection may run on CPU. That is fine. |
| Multi-Character | The GLIGEN loader is fine. RES4LYF hardcodes CUDA in several nodes, so some regional workflows will error until those calls are patched. |
| Z-Image, Krea2 | Off by default. Their text encoders are FP8, and ComfyUI v0.38.0 has no Metal path for float8 math. They crash with `Float8_e4m3fn` until ComfyUI grows that support or a small workaround is added. |

Drop extra checkpoints, LoRAs, or upscalers into the matching `~/AkshoComfy/ComfyUI/models/` folders. Atelier picks them up through the model-info route.

## What talks to what

Atelier in the browser sends normal ComfyUI prompts to `http://127.0.0.1:8188`. The server is started with CORS enabled so the website is allowed to do that. A small add-on, ComfyUI-Aksho-ModelInfo, answers `GET /aksho/checkpoint-clip` so Atelier can tell checkpoints apart without reading the files itself.

The launch flags match the Windows bundle:

```text
python -s ComfyUI/main.py --port 8188 --enable-cors-header --enable-assets --enable-asset-hashing --disable-auto-launch --preview-method auto
```

## Uninstall

Quit ComfyUI and delete `~/AkshoComfy`. The installer does not write anywhere else, apart from the files in this repo.
