# Product phases

## Phase 1 — packaged in this scaffold
- Thai/English text-to-speech playground (non-streaming full WAV)
- Zero-shot cloned voice reference profiles via PCM WAV, consent checkbox
- SQLite history, job queue, access-controlled audio files
- FastAPI REST integration, responsive Vue 3 frontend
- Lazy-loading Hugging Face MOSS Local Transformer v1.5

## Phase 2 — next implementation targets
- Upstream realtime streaming adapter (MOSS streaming runtime or SGLang-Omni)
- WebSocket/PCM playback on frontend; progress and cancellation
- Voice profile management: reference transcripts, multiple reference clips per voice, quality validation/normalization
- Pronunciation assistance: Thai number/date normalization and exceptions dictionary
- Per-generation settings (temperature, top-p, top-k, seed, pause markup)
- Waveform and A/B voice comparisons; clone similarity evaluation
- Persistent Redis queue + workers, retries and cancellation

## Phase 3 — companion integration
- Explicit `speech` and `action` segmentation from LLM
- Short response chunking, optional streaming speech packets, sequence number for synchronization
- Browser Web Audio playback with RMS-driven Live2D ParamA lip sync
- Preset profiles per character with permissions and voice provenance
- User auth, quotas, object storage and privacy controls for multi-user use
