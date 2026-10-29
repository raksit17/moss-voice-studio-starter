# MOSS Voice Studio — Phase 3: Local Thai/English TTS + Progressive Streaming

## Standalone MOSS Docker Compose (optional GPU inference)

เริ่ม MOSS Backend + Vue Studio ผ่าน Docker ได้จาก root repo โดยอ่าน [คู่มือ Docker Compose](docs/DOCKER-COMPOSE.md) ก่อนใช้งาน ต้องตั้ง `backend/.env` และเตรียม NVIDIA GPU/WSL2; Chatterbox แยก Python venv ภายใน Docker ส่วนเว็บ Nginx proxy จะไม่ฝัง API key ลง bundle. ใช้ร่วมกับ `anime-ai-companion` ผ่าน shared Docker network `moss-voice-shared` และ `docker-compose.moss.yml` ของ Companion ได้ (เริ่ม MOSS ก่อน). การย้าย SQLite/voice library เดิมจาก Windows ต้องตรวจ absolute paths ก่อน.

```powershell
# Run from moss-voice-studio-starter repository root
docker compose up -d --build
```

## MCP + Redis + Docker integration

คู่มือติดตั้งและเชื่อมสอง repo: [MCP / Redis / Docker (ภาษาไทย)](docs/MCP-REDIS-DOCKER.md). Companion ใช้ REST gateway เดิม พร้อม MCP tools และ Redis/SSE event interfaces เพิ่มเติม; โดยค่าเริ่มต้น MOSS inference รันบน Windows host หรือเลือกใช้ Docker standalone ที่เพิ่มใหม่ได้ตามคู่มือด้านล่าง.

A standalone **Voice Library + TTS Playground + REST API** using **MOSS-TTS-Local-Transformer-v1.5**. Built for experimenting with cloned voices and integrating with apps such as anime-ai-companion. The model weights are **not bundled**.

## Features

- Vue 3 + Vite + TypeScript modern dark frontend, Thai UI
- FastAPI Python backend, SQLite history, voice reference file library
- **Real** official MOSS Transformers inference adapter (no fabricated audio/demo synthesizer)
- **Real progressive PCM streaming** via optional separately running SGLang-Omni
- Web Audio live player with stop/cancel, reference transcripts, and streaming status
- Phase 3 NestJS client, PCM relay controller and Live2D RMS speech/action bridge
- Upload authorized **PCM WAV** reference voice, save its exact transcript and per-character label, and reuse by `voice_id`
- Synthesize Thai/English, with or without a reference clip
- Adjust temperature, top-p, and top-k for each WAV or progressive stream request
- Queue up to 8 jobs, run one at a time on the GPU, poll jobs, play/download resulting WAV
- API-key authentication for local use; documented client integration
- Model is lazily loaded on the first generation (downloaded on first use unless local path configured)

## Requirements / caveats

**Recommended:** NVIDIA GPU with sufficient VRAM for the ~5B checkpoint **and** 48 kHz stereo tokenizer, Python **3.12**, Node **20+**. CPU-only is technically possible but impractical for interactive speech. This scaffold has not been tested with the multi-GB model weights in this environment.

The official code uses `trust_remote_code=True`; pin a trusted model revision and review upstream code before deploying. The model license is **Apache-2.0**; obtain consent for each voice, respect copyrighted samples, and review dependencies and deployment obligations.

### Backend (Windows PowerShell)

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
pip install -r requirements.txt
```

**Recommended (tested upstream dependency stack):** install official MOSS dependencies from the upstream repository. This is a large download and requires a GPU driver compatible with CUDA 12.8; verify your driver first.

```powershell
git clone https://github.com/OpenMOSS/MOSS-TTS.git third_party/MOSS-TTS
pip install --extra-index-url https://download.pytorch.org/whl/cu128 -e "third_party/MOSS-TTS[torch-runtime]"
pip install -r requirements-moss.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

If your GPU/driver needs a different CUDA runtime, use the appropriate PyTorch install command instead of the upstream `torch-runtime` extra; keep torch/torchaudio/torchcodec version compatibility. See https://github.com/OpenMOSS/MOSS-TTS .

**Downloading weights once (optional, recommended for offline use):**

```powershell
pip install -U huggingface_hub
hf download OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5 --local-dir models/moss-tts-local-v1.5
hf download OpenMOSS-Team/MOSS-Audio-Tokenizer-v2 --local-dir models/moss-audio-tokenizer-v2
```

**IMPORTANT:** The processor config from the main model points to the online tokenizer ID `OpenMOSS-Team/MOSS-Audio-Tokenizer-v2`, so `models/moss-audio-tokenizer-v2` is *not automatically loaded* in the basic adapter. With network access it downloads/caches the tokenizer on first use. For fully offline use: mirror both into the HF cache under their repo IDs, or adapt the trusted processor config in a local copy to point to the local tokenizer directory. Do not assume downloading the model folder alone makes inference offline.

For a model downloaded under `backend/models/...`, update `.env`:

```dotenv
MOSS_MODEL_ID=./models/moss-tts-local-v1.5
```

`GET /v1/health` will say `not_loaded` until a synthesis starts; this is **expected**. First generation may take a while to load. Runtime CUDA capability, dependencies and model weights are required for real synthesis.

### Frontend

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open http://127.0.0.1:5173.

The UI can render when the API is offline, but buttons that require inference or storage will report errors rather than playing fake generated audio.

### Backend API

All endpoints expect `X-API-Key: local-dev-key` in the default local configuration. Adjust `.env` for your environment.

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/health` | Connection, engine, model status |
| GET | `/v1/voices` | List voice profiles |
| POST | `/v1/voices` | Multipart: `name`, `language`, `consent=true`, `audio` (PCM WAV) |
| GET | `/v1/voices/{id}/audio` | Listen to reference |
| DELETE | `/v1/voices/{id}` | Remove reference profile |
| POST | `/v1/jobs` | Generate WAV in background |
| GET | `/v1/jobs` | Recent jobs |
| GET | `/v1/jobs/{id}` | Poll a job |
| GET | `/v1/jobs/{id}/audio` | Download generated WAV |
| GET | `/v1/stream/status` | Check SGLang-Omni health and availability |
| POST | `/v1/stream` | Return genuine 48 kHz PCM chunks while synthesis is ongoing |

Example call:

```powershell
$headers = @{"X-API-Key"="local-dev-key"}
$body = @{ text="สวัสดีค่ะ วันนี้เป็นอย่างไรบ้างคะ"; language="Thai"; voice_id=$null } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8001/v1/jobs' -Method Post -Headers $headers -ContentType 'application/json' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

The POST returns job ID / status URL, not the audio itself. Poll the status endpoint until completed, then GET the `.wav` audio endpoint. Clone mode uses the saved `voice_id` reference clip. This is **zero-shot voice cloning**, not training new weights.

### Integrating with anime-ai-companion

Keep the model in **this service only**, not the companion project. A server-side NestJS example is included at `docs/anime-ai-companion-integration.ts`. Your companion backend sends LLM `speech` segments to `POST /v1/jobs` with the chosen voice ID, polls `GET /v1/jobs/{id}`, then downloads the authenticated WAV. Feed it to your web audio player and existing Live2D RMS lip-sync. Do not send LLM `action`/stage directions to TTS. API keys stay on the companion backend.

The repository now includes **true progressive streaming** through SGLang-Omni, plus a separate queued WAV route. See the streaming setup below and `docs/COMPANION_PHASE3.md`.

### Real-time progressive streaming (Phase 2 + 3)

Run **SGLang-Omni** as a separate inference server; the built-in Transformers
engine handles WAV jobs only. You must download the model and have a CUDA GPU
with enough VRAM. Follow the official SGLang-Omni installation instructions
(prefer Linux / WSL2 + CUDA for this engine):

```bash
sgl-omni serve --model-path OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5 --port 8000
```

Set in `backend/.env`:

```dotenv
SGLANG_BASE_URL=http://127.0.0.1:8000
```

Restart FastAPI, open **Voice Playground**, type a Thai sentence, select a
consented voice profile and choose **Stream Speech (Live)**. To control cloning,
set the **Reference transcript** to the words *actually spoken* in your sample
when uploading the voice. The live API is:

```http
POST /v1/stream
X-API-Key: local-dev-key
Content-Type: application/json

{"text":"สวัสดีค่ะ วันนี้เป็นยังไงบ้างคะ","voice_id":null,"language":"Thai"}
```

Response: raw `pcm_s16le` mono, 48000 samples/second; `X-Audio-Encoding`,
`X-Sample-Rate` and `X-Channels` headers describe it. **It is not WAV.**
The backend verifies voice ID, forwards the reference by data URI and streams
bytes without waiting for the complete utterance. Stop button aborts browser
playback. Use the `/v1/stream/status` endpoint to diagnose configuration.

The companion integration is supplied as reusable NestJS/TypeScript examples:
`docs/anime-ai-companion-integration.ts`,
`docs/anime-ai-companion-stream.controller.ts`, and
`frontend/src/companion-bridge.ts`. The bridge uses an AnalyserNode to map
real playback RMS to Live2D lip sync and preserves speech/action ordering.

**Installation/benchmarks disclaimer:** Real CUDA model inference has not
been executed in CI; tests mock SGLang. Streaming requires a separate
operational model server. No large model weights are committed to GitHub.

### Security / future production hardening

Designed for localhost, single user. The Vite `VITE_API_KEY` is visible to browser clients: **do not expose this frontend publicly with production credentials**. Use a reverse proxy/BFF, user auth, quotas, rate limits, per-user ownership and object storage if deploying online. Voice files are private authenticated routes. The system currently uses one local SQLite DB and one in-process queue. On restart, abandoned queued/running jobs are marked failed; use a durable broker for production. The optional PCM streaming gateway is limited to one request at a time per worker. See `docs/ROADMAP.md` for remaining multi-tenant security and infrastructure work.

### Quality notes

- 48 kHz stereo is the codec format; it is **not** a guarantee of pronunciation accuracy.
- Voice cloning depends on input quality. Use clean, authorized 3–20 second WAV samples.
- Thai/English language tags are passed explicitly.
- Test Thai tones, numbers, code-switching and speaker similarity before any commercial release.

## Project layout

```text
moss-voice-studio/
├─ backend/
│  ├─ app/
│  │  ├─ config.py        environment configuration
│  │  ├─ db.py            SQLite metadata/history
│  │  ├─ engine.py        official HF MOSS inference adapter
│  │  └─ main.py          voice upload / jobs / audio REST endpoints
│  ├─ tests/
│  ├─ requirements.txt
│  ├─ requirements-moss.txt
│  └─ .env.example
├─ frontend/
│  ├─ src/
│  │  ├─ api.ts           typed HTTP client
│  │  ├─ App.vue          UI & interactions
│  │  ├─ style.css        responsive dark theme
│  │  └─ main.ts
│  └─ package.json
└─ README.md
```


## Saved Small Voice Packages (Phase 5)

MOSS generates the first Thai clip; then **Model Manager -> Create Small Voice Package** saves that completed WAV + transcript as a reusable F5-TTS-THAI voice package. **Voice Playground** can subsequently select that package, automatically unload MOSS and run F5 in a separate subprocess. This avoids reloading MOSS 5B but still needs the F5 base model, which uses its own memory. This is zero-shot voice cloning, **not** trained-model distillation or LoRA.

Install `backend/requirements-f5-thai.txt` in a separate Python virtual environment, set `F5_PYTHON` in `backend/.env`, and follow [Phase 5 instructions](docs/PHASE5_VOICE_PACKAGES.md). GPU behavior and voice fidelity must be tested on the local machine.

## English voice cloning with Chatterbox-Turbo (350M)

Use the **Chatterbox-Turbo** option in **Voice Playground** for English-only zero-shot cloning and tags such as `[chuckle]`. It reuses Voice Library WAV profiles and saves generation history in the existing job API. Turbo runs in a **separate Python 3.11 environment** with a persistent worker, so subsequent jobs reuse the loaded model without loading MOSS 5B. Switching runtimes unloads the other resident speech model to free VRAM. This does not automatically unload Ollama and does not add progressive streaming for Turbo.

**Setup / Windows PowerShell (from `backend`) — Python 3.14.2:**

```powershell
powershell -ExecutionPolicy Bypass -File .\\install-chatterbox.ps1
```

The installer creates an isolated Python 3.14 Chatterbox venv, installs PyTorch CUDA 12.8 wheels and applies a **local metadata-only workaround** for upstream `spacy-pkuseg` (Chinese segmentation; not needed by English Turbo). For Python 3.11, use `py -3.11 -m venv .venv-chatterbox` and install `requirements-chatterbox.txt` normally. MOSS/F5 environments remain unchanged.

Start the existing API and frontend as before. In Voice Playground choose **Chatterbox-Turbo · English**, upload a consented ~10-second English WAV in Voice Library, select its profile and generate. For a warm first response, use **Model Manager → Load / Warm Turbo**. CPU fallback can be configured with `CHATTERBOX_DEVICE=cpu`; the default `auto` prefers CUDA. For troubleshooting see [Chatterbox-Turbo setup & API](docs/CHATTERBOX_TURBO.md).
