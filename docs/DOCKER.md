# Docker Compose: Chatterbox-Turbo GPU + Voice Studio Web

Runs the **FastAPI server on http://127.0.0.1:8001** and a production-built
Vue web frontend on **http://127.0.0.1:5175**, both in Linux containers.

This Docker image deliberately supports **Chatterbox-Turbo (English) only**.
MOSS 5B and F5-TTS are still available in the project's existing non-Docker
setup, but their runtimes are **not installed** in this container image.
The UI may display their options; jobs using them will fail until separate
compatible runtimes are added.

## Prerequisites

- Windows 11 + Docker Desktop using its **WSL2 Linux engine** (Linux containers),
  or another Linux host with NVIDIA GPU container support.
- NVIDIA driver and Docker GPU integration working. Check:

  ```powershell
  docker info --format '{{.OSType}}'
  docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
  ```

  The first command should print `linux`; the second should show the GPU.
- Sufficient disk space for the CUDA/PyTorch dependencies and first model
  download. The first build is large and requires internet access.

## Start (from repository root)

```powershell
cd D:\GitPoom\moss-voice-studio-starter
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f api
```

Open **http://127.0.0.1:5175** (or **http://localhost:5175**).
The API is exposed only on **http://127.0.0.1:8001**.

The frontend is an Nginx-served Vite production build, **not** a Vite HMR
development server. Rebuild after changing frontend source:

```powershell
docker compose up -d --build web
```

## Confirm CUDA in the Chatterbox worker

```powershell
docker compose exec api /opt/venvs/chatterbox/bin/python -c "import torch; print(torch.__version__); print('CUDA:', torch.cuda.is_available())"
```

Expected: `CUDA: True`. If false, fix Docker/NVIDIA GPU access before
attempting to load the TTS model. The API container has a lightweight
Python environment; PyTorch is installed in **/opt/venvs/chatterbox**.

Warm the model (downloads its weights on first use):

```powershell
$headers = @{ "X-API-Key" = "local-dev-key" }
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/v1/chatterbox/load" -Headers $headers
Invoke-RestMethod -Uri "http://127.0.0.1:8001/v1/chatterbox/status" -Headers $headers
```

If the worker fails, check its log:

```powershell
docker compose exec api sh -c 'tail -n 120 /app/data/logs/chatterbox.log'
```

## Notes

- This uses **Linux PyTorch 2.6.0 + CUDA 12.4** wheels in a separate Python 3.11
  worker. It does not load Windows `torch.dll`, avoiding the Windows Code
  Integrity DLL block previously seen with native Python. It still requires
  functioning GPU passthrough.
- The API remains bound to **localhost**; its frontend key is embedded in
  client-side JavaScript and is **not secret**. Do not make these ports public
  without adding real server-side auth/proxying and origin restrictions.
- Default `STUDIO_API_KEY` is `local-dev-key`. To override it, add
  `STUDIO_API_KEY=your-dev-key` to a **repo-root** `.env` (not committed),
  then **rebuild web** so Vite gets the same key. The key is still visible
  to anyone able to use the frontend.
- Data and model cache are stored in Docker named volumes `studio-data`
  and `hf-cache` and persist across `docker compose down`. Existing
  `backend/data` on Windows is **not automatically migrated**: its SQLite
  voice paths may be Windows absolute paths unsuitable for Linux. Re-upload
  authorized voice samples through Voice Library instead of copying the
  database unchanged.
- After edits to source or Dockerfiles, use `docker compose up -d --build`.
- To stop: `docker compose down`. **Do not use `down -v`** unless you want
  to permanently delete the Docker-stored voices, history, and model cache.
- Web `5175` and API `8001` are host ports; the Nginx container listens
  on port `80`, and the FastAPI container listens on port `8001`.
- Docker images have not been built or GPU-benchmarked by CI; validate the
  first build, import, model load, and test synthesis on your machine.
