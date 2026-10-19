# Chatterbox-Turbo voice cloning (English)

Studio now supports Resemble AI's **Chatterbox-Turbo 350M** as a separate English-only TTS provider. It preserves MOSS and F5-TTS-THAI. Reference profiles continue to use the existing voice library and `voice_id`; no new voice training is needed.

## Install on Windows (recommended RTX 4060 / 8 GB)

From `moss-voice-studio-starter/backend` in PowerShell:

```powershell
py -3.11 -m venv .venv-chatterbox
.\.venv-chatterbox\Scripts\python.exe -m pip install --upgrade pip
.\.venv-chatterbox\Scripts\python.exe -m pip install -r requirements-chatterbox.txt
```

Install Python 3.11 first if `py -3.11` is unavailable. Chatterbox upstream tests Python 3.11. If torch CUDA is unavailable after installation, check the matching CUDA-enabled PyTorch/torchaudio package guidance for your driver and OS. **No weights are committed**; the first model load will download them from Hugging Face.

In `backend/.env` (use existing configuration):

```dotenv
CHATTERBOX_PYTHON=
CHATTERBOX_DEVICE=auto
CHATTERBOX_TIMEOUT_SECONDS=300
```

The default python path is `backend/.venv-chatterbox/Scripts/python.exe` on Windows, `backend/.venv-chatterbox/bin/python` on Linux. A custom `CHATTERBOX_PYTHON` path may be absolute or relative to `backend`. Keep this venv **separate from the MOSS venv**.

Start Studio as before:

```powershell
# From backend, using the MOSS/API venv (NOT .venv-chatterbox):
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

The worker launches automatically on the first English job, stays alive for subsequent jobs, and can be warmed/unloaded under **Model Manager**. The single inference queue serializes MOSS, F5, and Chatterbox work. Switching to MOSS/F5 releases Chatterbox GPU memory; switching to Chatterbox unloads the MOSS checkpoint. If Ollama is also on the same GPU, unload Ollama first if memory is tight.

## Frontend workflow

1. Open **Voice Library** and upload a clean **authorized** PCM WAV sample (ideally English, ~10 seconds), with name and optional transcript. Never upload voice audio without permission.
2. In **Voice Playground**, select **Chatterbox-Turbo (English / 350M)** as Speech Runtime. English will be selected automatically.
3. Pick your saved Voice Profile, type an **English** sentence and optionally include supported tags such as `[chuckle]`, `[laugh]`.
4. Click **Generate Speech**. Jobs use the same queued WAV API; once completed, listen/download in Output and Generation History.

This runtime does **not translate** Thai input. A Thai voice sample may clone less faithfully than a clean English sample. Chatterbox default voice works without a reference.

## API

```http
GET /v1/chatterbox/status
POST /v1/chatterbox/load
POST /v1/chatterbox/unload
```

All endpoints require the existing `X-API-Key` header. For a job:

```json
{
  "text": "Welcome back! [chuckle] I missed you.",
  "language": "English",
  "engine": "chatterbox-turbo",
  "voice_id": null
}
```

POST to `/v1/jobs`, poll `/v1/jobs/{id}`, then fetch `/v1/jobs/{id}/audio`. Pass a saved profile UUID in `voice_id` to clone. The public job includes its `engine`.

## Troubleshooting

- `python_found: false`: install the separate venv or set `CHATTERBOX_PYTHON`.
- `state: error`: inspect `backend/data/logs/chatterbox.log`, or the `log_path` field in status.
- CUDA OOM: stop/unload other GPU models (Ollama included), try `CHATTERBOX_DEVICE=cpu`, or reduce workload.
- Worker timeout or crash: the studio terminates it and starts fresh for the next request.
- **WAV jobs are not real-time audio streaming.** First job includes model download/load; later jobs reuse the resident model. The existing SGLang streaming feature remains MOSS-only.
- For the first run, ensure the Hugging Face model can download. Use `POST /v1/chatterbox/load` to warm before a conversation.

See the upstream reference implementation: https://github.com/resemble-ai/chatterbox.
