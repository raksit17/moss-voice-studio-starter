# Run MOSS Voice Studio with Docker Compose (Windows + Companion)

## Prerequisites

- Docker Desktop with WSL2 and NVIDIA GPU container support (`docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi`). GPU is required for practical MOSS inference; the 5B checkpoint may still exceed an 8GB card.
- Stop any native Windows MOSS API already listening on host port 8001, or set `MOSS_BACKEND_PORT` to a different published port. Docker service-to-service traffic always uses port 8001.
- Run from the `moss-voice-studio-starter` repository root, not `integration/companion-mcp`.

## Start standalone MOSS

1. Copy `backend/.env.example` to `backend/.env` (only if `.env` doesn't already exist), then set a **new random** `API_KEY`. Never put it in `frontend/.env`, a `VITE_` value, or Git.
2. Make sure `backend/data` and `backend/models` contain the intended Studio assets or are empty new directories. Old SQLite rows containing *Windows absolute paths* for voices/models will not automatically work inside a Linux container: back up and migrate/re-register those assets rather than assuming path compatibility.
3. From the MOSS repo root run:

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs -f moss-backend
```

Open `http://127.0.0.1:5176` (Docker Studio UI). The MOSS API is bound only to `127.0.0.1:8001` on the Windows host. To change published ports, set `MOSS_WEB_PORT` or `MOSS_BACKEND_PORT` in the shell or a root `.env` file; these variables are for Compose interpolation only.

Backend dependencies include CUDA PyTorch 2.9.1 and MOSS dependencies. The English Chatterbox-Turbo worker is installed in a **separate Python venv**, to preserve its pinned Torch/Transformers versions; it is loaded lazily. First build and model download can consume several GB of disk/network. For a smaller MOSS-only build, set `MOSS_INSTALL_CHATTERBOX=false` before building; English Chatterbox then will **not** be available. F5-Thai and SGLang are not automatically installed.

Studio's Nginx reverse proxy authenticates same-origin `/v1/` calls with `backend/.env` `API_KEY`; it is not bundled into browser JavaScript. Both published ports are loopback-only. Do not publish Studio publicly without additional authentication/HTTPS hardening.

Check health (the result `not_loaded` still means weights have not been loaded):

```powershell
$key = (Get-Content backend/.env | Where-Object { $_ -match '^API_KEY=' } | Select-Object -Last 1) -replace '^API_KEY=', ''
Invoke-RestMethod http://127.0.0.1:8001/v1/health -Headers @{'X-API-Key'=$key}
```

## Connect with anime-ai-companion through Docker network

Keep the repositories next to each other, as in `D:\GitPoom\moss-voice-studio-starter` and `D:\GitPoom\anime-ai-companion`. Start MOSS Compose **first**; this creates network `moss-voice-shared`. Use Companion's optional third override file `docker-compose.moss.yml` after `docker-compose.yml` and `docker-compose.mcp.yml`. It attaches only the Companion `voice-gateway` to the MOSS network, and overrides its upstream to `http://moss-backend:8001` (the container DNS name, not Windows `127.0.0.1`).

```powershell
cd ..\anime-ai-companion
docker compose --env-file ../moss-voice-studio-starter/integration/companion-mcp/.env -f docker-compose.yml -f docker-compose.mcp.yml -f docker-compose.moss.yml up -d --build postgres redis voice-gateway api web
```

Set `MOSS_API_KEY` in `integration/companion-mcp/.env` to exactly the same value as `backend/.env` `API_KEY`. Set a **different** `GATEWAY_API_KEY` there. Do not put either key into the browser. In Companion `apps/api/.env`, keep `VOICE_TTS_PROVIDER=moss`, `VOICE_STUDIO_EN_ENGINE=chatterbox-turbo` and `VOICE_STUDIO_TH_ENGINE=moss`. If `docker-compose.mcp.yml` still overrides `VOICE_STUDIO_EN_ENGINE=moss`, remove that override or use the updated companion Compose version. The Gateway REST proxy forwards the `engine` field unchanged; its MCP `synthesize_speech` tool separately defaults to MOSS.

To check from the Companion Gateway:

```powershell
docker exec anime-ai-companion-voice-gateway-1 python -c "import os,httpx; r=httpx.get(os.environ['MOSS_URL']+'/v1/health',headers={'X-API-Key':os.environ['MOSS_API_KEY']}); print(r.status_code,r.text[:250])"
```

The Compose network and HTTP health check prove connectivity, **not** that CUDA, weights, English voice cloning, or a real speech-generation request succeeds. Verify an actual Thai MOSS and English Chatterbox WAV job separately. If the new Docker backend starts with empty data, old voice IDs from Windows will not exist until profiles are migrated or registered again.

## Stop without destroying voice data

```powershell
docker compose down
```

Do **not** use `down -v`: it removes the Hugging Face cache volume. Voice library and SQLite are bind-mounted under `backend/data`, and models under `backend/models`; back them up.
