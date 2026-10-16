# Phase 3 — Anime AI Companion integration

Voice Studio owns MOSS weights, reference WAVs, and API keys. Companion calls it
from **NestJS server-side** (never put production credentials in Vue/Live2D JS).

## Speech/action protocol

Treat the LLM's `segments` as an ordered list. Speak only `type: "speech"`
segments; execute Live2D motions for `type: "action"` and never synthesize
their narrative descriptions. For speech, select a saved voice ID (e.g. Yuna),
and language Thai or English.

```json
{
  "segments": [
    {"type":"speech","text":"กลับมาแล้วเหรอคะ","emotion":"happy"},
    {"type":"action","expression":"smile","motion":"wave"},
    {"type":"speech","text":"ดีใจจังเลย","emotion":"shy"}
  ]
}
```

## Two supported synthesis modes

- **Reliable WAV:** `POST /v1/jobs` -> poll `/v1/jobs/{id}` -> download WAV;
  useful when running the built-in Transformers adapter without SGLang.
- **Progressive speech:** `POST /v1/stream` on the Voice Studio API proxies
  genuine PCM bytes from a separately running **SGLang-Omni** MOSS Local v1.5
  server. This route returns raw **signed 16-bit little-endian mono 48 kHz PCM**,
  NOT WAV. It starts yielding audio before generation ends.

NestJS can proxy the upstream stream using `Readable.fromWeb(response.body)`
with `Content-Type: application/octet-stream` and
`X-Audio-Encoding: pcm_s16le`, `X-Sample-Rate: 48000`,
`X-Channels: 1`; do not buffer `response.arrayBuffer()`.
Use Node 20+ fetch and send `X-API-Key` only from the NestJS backend.
See `docs/anime-ai-companion-integration.ts` for a working service example.

## Live2D lip sync

Use Web Audio (decode PCM into mono Float32 buffers; see
`frontend/src/pcm-player.ts`). Drive `ParamA` or your character's lip sync
parameter with **RMS of the audio actually being played**, not LLM text
length. Clamp to 0..1 and smooth to reduce flicker. Speech segment completion
must await playback completion before the next action/segment to preserve order.
Provide cancellation via AbortController on interruptions.

## Voice consent and privacy

Only use reference samples you are permitted to synthesize. Current app is
localhost/single-user. For public deployments: use server-side authentication
and access control, do not put API keys in public Vite builds, enforce quotas
and voice ownership, add per-user storage deletion and retention policies.

## Local streaming setup

```bash
# On a machine with appropriate GPU, install sglang-omni per official guide:
sgl-omni serve --model-path OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5 --port 8000
```

Set `SGLANG_BASE_URL=http://127.0.0.1:8000` in `backend/.env`
and restart FastAPI. The Studio plays progressive audio via `/v1/stream`
and `GET /v1/stream/status`. This model server is a **separate process**:
starting FastAPI alone never starts streaming inference.

Upstream reference:
https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Local-Transformer-v1.5
