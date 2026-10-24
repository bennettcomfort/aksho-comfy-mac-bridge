## Learned User Preferences

- Keep Atelier pointed at `127.0.0.1:8188`. ComfyUI itself listens on `127.0.0.1:18188`. `browser_bridge.py` owns 8188 and accepts both plain HTTP and the HTTPS Safari upgrades that address to.
- Treat a working Atelier connection as a browser check in Safari, Orion, Firefox, and Chrome. A terminal request to the server is not enough.
- Explain this project in plain language: Aksho built the Windows installer and glue, and this repo rebuilds that setup for Mac.

## Learned Workspace Facts

- This repo is the Apple Silicon port of https://github.com/aksho-technologies/aksho-comfy, published at https://github.com/bennettcomfort/aksho-comfy-mac-bridge. It is the installer, launchers, and small extensions around stock ComfyUI so AkshoAI Atelier can generate images locally.
- The installed app lives at `~/AkshoComfy` and runs ComfyUI v0.38.0 with Metal PyTorch. Skip the Windows portable zip and CUDA wheels; they cannot run on Apple Silicon.
- Assets are pinned in the live manifest at https://dl.akshoai.com and checked with sha256. That manifest is newer than the upstream GitHub copy. Core includes Dreamhex v5 (`Vete_Dreamhex_v5.safetensors`), IP-Adapter, Impact Pack, ADetailer, and the AnimeSharp upscaler.
- Aksho-authored code to preserve is `extensions/ComfyUI-Aksho-ModelInfo` (`/aksho/checkpoint-clip`), `extensions/gligen-xl`, and `agent/aksho-agent.py`. Users do not run `publish/`.
- Leave Z-Image and Krea2 disabled: their FP8 text encoders crash on Metal with ComfyUI v0.38.0. RES4LYF still calls CUDA, so multi-character support is a known Mac limit.
- Atelier at `https://akshoai.com` calls `http://127.0.0.1:8188`, and its live channel is `ws://`. The page CSP `upgrade-insecure-requests` makes Safari and Orion send TLS to that port; Chrome and Firefox do not. The server must echo origin `https://akshoai.com` and send `Access-Control-Allow-Private-Network`, including on the WebSocket 101. Do not pair `Access-Control-Allow-Origin: *` with credentials. Reapply the ComfyUI patch on every launch because an update replaces `server.py`.
