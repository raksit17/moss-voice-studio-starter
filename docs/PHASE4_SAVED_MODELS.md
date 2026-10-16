# Phase 4: Saved Models (initial implementation)

The original Hugging Face model is automatically registered as `moss-original` on first startup. Existing databases are upgraded to add `models` and `jobs.model_id`.

## Workflow

1. Set `MODELS_DIR` in `backend/.env` (default `./models`, relative to the backend process working directory).
2. Put a trusted local MOSS checkpoint under that directory, including its `config.json` and safetensors shards.
3. In **Model Manager**, import the server-side absolute folder path. Imported models start as `pending_validation`.
4. Click **Validate WAV**. The server will run a real sample synthesis, check the WAV is nonempty, unload and reload the selected model. Only success changes the model to `ready`.
5. **Load Model** loads the model on demand. **Set Default** changes the persistent selection in SQLite. The Voice Playground can select a ready model independently per job.
6. A restart retains the default selection but not GPU resident weights.

The single-worker inference executor serializes model operations and queued speech jobs. Only one model remains resident at a time. The API requires `X-API-Key`.

## API

- `GET /v1/models`
- `POST /v1/models/import` with `{name,model_path,precision}`
- `POST /v1/models/{id}/validate`
- `POST /v1/models/{id}/activate`
- `POST /v1/models/{id}/load`
- `POST /v1/models/{id}/unload`
- `GET /v1/models/runtime`
- `POST /v1/jobs` accepts optional `model_id`, which is persisted with the job.

## INT8 and limitations

**INT8 export is NOT implemented.** `POST /v1/models/export` returns HTTP 501. Imported INT8 models cannot pass validation or load until the custom MOSS transformer supports tested checkpoint quantization, serialization and restoration. The interface must not claim that such a file is usable. Likewise, models imported from paths outside `MODELS_DIR` are rejected, and arbitrary browsers cannot upload model code. Only import models from trusted sources because the MOSS processor/model loader uses `trust_remote_code=True`.

External SGLang streaming uses its own model server; `model_id` selection currently applies to queued `/v1/jobs` WAV generation, not `/v1/stream`. GPU validation must be run on a machine with the MOSS dependencies and adequate memory; unit tests use stubs and cannot certify model audio fidelity.
