# MOSS Voice Studio roadmap and delivery status

## Phase 1 — implemented and covered by smoke tests
- Thai/English WAV generation via native Transformers MOSS adapter
- Zero-shot voice profiles with consent + PCM WAV validation
- SQLite metadata/history, single in-process GPU queue, private audio routes
- API-key-protected REST API and Vue 3 playground
- On-demand loading (requires separately downloaded MOSS model/tokenizer)

## Phase 2 — implemented and covered by mocked upstream tests
- True progressive PCM streaming via **official SGLang-Omni** MOSS Local v1.5 API
- Voice ID -> reference WAV data URI -> SGLang, optional source transcript
- Configurable `SGLANG_BASE_URL` and health check endpoint
- One active stream per API process, error preflight, client disconnect cleanup
- Web Audio signed 16-bit mono/48k playback, buffering, stop via AbortController
- Streaming status and live controls integrated in the existing Vue playground

## Phase 3 — integrated foundations delivered
- Server-side NestJS progressive streaming client and relay controller examples
- Ordered `speech`/`action` playback utility with sequence indexes
- Audio analyser RMS -> Live2D mouth-open parameter (ParamA) with smoothing
- Abort support / speech motion sync / safe handling of action-only segments
- Character voice IDs and reference-transcript persistence
- Character preset labels and per-generation temperature/top-p/top-k controls for WAV and streaming
- GitHub Actions checks for backend tests and frontend Vue/TypeScript build
- Integration/security guide for backend-only production API keys

## Not delivered yet (requires additional infrastructure or hardware)
- Validation of the multi-GB MOSS model on user's NVIDIA GPU
- Running SGLang-Omni in a Linux/CUDA deployment / end-to-end streaming latency benchmark
- Multi-tenant auth, per-user quotas, RBAC, billing, encrypted object storage
- Persistent Redis/Celery queue, job retries/cancellation across workers
- Multiple reference clips per profile, provenance workflows, pronunciation dictionary
- Waveform A/B compare, automated MOS/speaker-similarity quality evaluation
- Full integration into a *separate* anime-ai-companion GitHub repository

Do not advertise production readiness merely because mock tests and builds pass.
