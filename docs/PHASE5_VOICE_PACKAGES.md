# Phase 5: F5 Thai Saved Voice Packages

Voice packages are **reusable references**, NOT trained checkpoints, LoRA, distilled models or compressed MOSS models. They consist of a copied reference WAV, exact transcript and manifest.json in MODELS_DIR/voice-packages/<uuid>. The base F5-TTS-THAI model must still be installed and loaded to generate new text; it does not require MOSS 5B.

## Setup (Windows)
From backend/ use a dedicated Python environment for F5 to avoid changing MOSS dependencies:

    py -3.12 -m venv .venv-f5
    .venv-f5\Scripts\python.exe -m pip install -r requirements-f5-thai.txt

Install a CUDA-compatible PyTorch based on your local driver and the F5 package. In backend/.env configure F5_PYTHON to the absolute path of this virtual environment's python.exe. Launch FastAPI from backend/ so the spawned module app.voice_models.f5_worker can be imported.

## Workflow
1. Generate a short Thai clip with MOSS, wait for completion, OR upload a Thai Voice Profile whose transcript matches its audio.
2. In Model Manager -> Create Small Voice Package, choose a completed generation or Voice Profile, and name it test1-small.
3. Save the package. MOSS does not train or distill anything during this operation.
4. Use in Playground and generate Thai text. The worker queue unloads MOSS, then spawns F5 independently.
5. The child exits after each WAV (lower GPU residency, but reloads F5 each time). Reopening the app preserves package registration and references. Best reference length: 2-8 seconds.

API: GET/POST /v1/voice-models; GET/DELETE /v1/voice-models/{id}; GET /v1/voice-models/{id}/reference.
POST body: {"name":"test1-small","source_job_id":"COMPLETED_ID"} or {"name":"test1-small","source_voice_id":"VOICE_ID"}.
Generate with POST /v1/jobs: {"text":"สวัสดีค่ะ","language":"Thai","voice_model_id":"PACKAGE_ID"}; do not combine with MOSS model_id or voice_id.

Manifest flags: trained_checkpoint=false, method=zero_shot. A small package FILE does not equal a tiny base-model VRAM footprint. Test real VRAM and speaker similarity locally. F5 may not perfectly reproduce MOSS timbre and emotion. Fine-tuning, student checkpoints, a dedicated dataset/training pipeline, and INT8 exports remain NOT IMPLEMENTED. Only use voices for which you have permission. Model weights are not committed to Git.
