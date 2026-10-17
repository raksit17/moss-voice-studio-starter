from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import logging
import threading
import time
import wave
import json

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import settings
from .db import execute, initialize, now_iso, query_all, query_one
from .engine import engine
from .model_manager import ImportModel, import_model, list_models, resolve_model, register_original, activate, default_model
from .streaming import StreamBody, stream_pcm, status as stream_status
from .voice_models.registry import BuildVoicePackage, build_package, delete_package, list_packages, resolve_package
from .voice_models.runtimes.f5_thai_runtime import synthesize_f5

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('moss-studio')
initialize()
register_original()
app = FastAPI(title='MOSS Voice Studio API', version='0.1.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.allowed_origins.split(',') if x.strip()],
    allow_credentials=False,
    allow_methods=['GET', 'POST', 'DELETE'],
    allow_headers=['Content-Type', 'X-API-Key'],
    expose_headers=['X-Audio-Encoding', 'X-Sample-Rate', 'X-Channels'],
)
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='moss-inference')
slots = threading.BoundedSemaphore(8)


def authorize(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key or x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail='Invalid API key')


class GenerateBody(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    language: str = 'Thai'
    voice_id: str | None = None
    model_id: str | None = None
    voice_model_id: str | None = None
    temperature: float = Field(default=1.7, ge=0.1, le=2.0)
    top_p: float = Field(default=0.8, ge=0.05, le=1.0)
    top_k: int = Field(default=25, ge=1, le=100)


def public_job(row: dict) -> dict:
    return {
        'id': row['id'], 'voice_id': row['voice_id'], 'model_id': row.get('model_id'), 'voice_model_id': row.get('voice_model_id'), 'text': row['text'],
        'language': row['language'], 'status': row['status'], 'error': row['error'],
        'created_at': row['created_at'], 'updated_at': row['updated_at'],
        'started_at': row.get('started_at'), 'finished_at': row.get('finished_at'),
        'duration_seconds': row.get('duration_seconds'),
        'audio_url': f"/v1/jobs/{row['id']}/audio" if row['status'] == 'completed' else None,
        'settings': json.loads(row.get('settings_json') or '{}'),
    }


@app.get('/v1/health', dependencies=[Depends(authorize)])
def health():
    return {
        'ok': True,
        'engine': engine.state,
        'device': engine.device_name,
        'model': (default_model() or {}).get('name'),
        'loaded_model_id': engine.loaded_model_id,
        'error': engine.last_error,
        'sample_rate': 48000,
        'streaming': bool(settings.sglang_base_url),
        'stream_backend': 'sglang-omni' if settings.sglang_base_url else None,
    }


@app.get('/v1/voices', dependencies=[Depends(authorize)])
def list_voices():
    rows = query_all('SELECT id, name, language, transcript, character, created_at FROM voices ORDER BY created_at DESC')
    return {'items': rows}


@app.post('/v1/voices', status_code=201, dependencies=[Depends(authorize)])
async def upload_voice(
    name: str = Form(..., min_length=1, max_length=80),
    language: str = Form('Thai'),
    consent: bool = Form(False),
    transcript: str = Form('', max_length=1000),
    character: str = Form('', max_length=80),
    audio: UploadFile = File(...),
):
    if language not in ('Thai', 'English'):
        raise HTTPException(422, detail='Supported languages: Thai / English')
    if not consent:
        raise HTTPException(400, detail='Confirm permission to use this voice')
    # WAV-only MVP avoids FFmpeg dependency and transcoding mismatch on Windows.
    if Path(audio.filename or '').suffix.lower() != '.wav':
        raise HTTPException(415, detail='Only PCM WAV files are supported in this version')
    contents = await audio.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(contents) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, detail='Audio exceeds upload limit')
    if not contents.startswith(b'RIFF') or contents[8:12] != b'WAVE':
        raise HTTPException(415, detail='Invalid WAV file')
    voice_id = str(uuid4())
    path = settings.data_dir / 'voices' / f'{voice_id}.wav'
    path.write_bytes(contents)
    try:
        with wave.open(str(path), 'rb') as wav:
            if wav.getcomptype() != 'NONE' or wav.getnframes() == 0:
                raise ValueError('Only uncompressed PCM WAV is accepted')
            duration = wav.getnframes() / wav.getframerate()
            if duration > 60 or duration < 1:
                raise ValueError('Use 1–60 seconds of reference audio (3–20s recommended)')
    except (wave.Error, ValueError, ZeroDivisionError) as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, detail=str(exc)) from exc
    timestamp = now_iso()
    execute('INSERT INTO voices(id,name,language,file_path,created_at,transcript,character) VALUES (?,?,?,?,?,?,?)',
            (voice_id, name.strip(), language, str(path.resolve()), timestamp, transcript.strip(), character.strip()))
    return {'id': voice_id, 'name': name.strip(), 'language': language, 'transcript': transcript.strip(),
            'character': character.strip(), 'created_at': timestamp}


@app.get('/v1/voices/{voice_id}/audio', dependencies=[Depends(authorize)])
def voice_audio(voice_id: str):
    voice = query_one('SELECT * FROM voices WHERE id=?', (voice_id,))
    if not voice:
        raise HTTPException(404, detail='Voice not found')
    return FileResponse(voice['file_path'], media_type='audio/wav')


@app.delete('/v1/voices/{voice_id}', dependencies=[Depends(authorize)])
def delete_voice(voice_id: str):
    voice = query_one('SELECT * FROM voices WHERE id=?', (voice_id,))
    if not voice:
        raise HTTPException(404, detail='Voice not found')
    # Keep generation history; voice id remains in past jobs (SQLite FK checks default off).
    execute('DELETE FROM voices WHERE id=?', (voice_id,))
    Path(voice['file_path']).unlink(missing_ok=True)
    return {'deleted': True}


def _process_job(job_id: str, text: str, language: str, reference: Path | None, generation: dict, selected_model: dict | None, voice_package: dict | None = None) -> None:
    output = settings.data_dir / 'generations' / f'{job_id}.wav'
    started_clock = None
    try:
        started_at = now_iso()
        started_clock = time.perf_counter()
        execute('UPDATE jobs SET status=?, started_at=?, updated_at=? WHERE id=?',
                ('running', started_at, started_at, job_id))
        if voice_package is not None:
            # One executor queues MOSS and F5 jobs; release MOSS GPU memory first.
            engine.unload()
            synthesize_f5(text, voice_package, output)
        else:
            engine.synthesize(text, language, reference, output, generation, selected_model)
        finished_at = now_iso()
        duration = round(time.perf_counter() - started_clock, 2)
        execute('UPDATE jobs SET status=?, output_path=?, updated_at=?, finished_at=?, duration_seconds=? WHERE id=?',
                ('completed', str(output.resolve()), finished_at, finished_at, duration, job_id))
    except Exception as exc:
        logger.exception('Generation failed for %s', job_id)
        finished_at = now_iso()
        duration = round(time.perf_counter() - started_clock, 2) if started_clock is not None else None
        execute('UPDATE jobs SET status=?, error=?, updated_at=?, finished_at=?, duration_seconds=? WHERE id=?',
                ('failed', str(exc)[:500], finished_at, finished_at, duration, job_id))
        output.unlink(missing_ok=True)
    finally:
        slots.release()


@app.post('/v1/jobs', status_code=202, dependencies=[Depends(authorize)])
def create_job(body: GenerateBody):
    if body.language not in ('Thai', 'English'):
        raise HTTPException(422, detail='Supported languages: Thai / English')
    if not body.text.strip():
        raise HTTPException(422, detail='Text cannot be blank')
    if body.voice_model_id and (body.voice_id or body.model_id):
        raise HTTPException(422, detail='voice_model_id cannot be combined with MOSS voice_id or model_id')
    voice_package = resolve_package(body.voice_model_id) if body.voice_model_id else None
    if voice_package and body.language != voice_package['language']:
        raise HTTPException(422, detail='Voice package language must match requested language')
    voice = query_one('SELECT * FROM voices WHERE id=?', (body.voice_id,)) if body.voice_id else None
    if body.voice_id and not voice:
        raise HTTPException(404, detail='Selected voice not found')
    model = None if voice_package else resolve_model(body.model_id)
    if not slots.acquire(blocking=False):
        raise HTTPException(429, detail='Generation queue full (8 jobs)')
    job_id = str(uuid4())
    timestamp = now_iso()
    generation = {'temperature': body.temperature, 'top_p': body.top_p, 'top_k': body.top_k}
    try:
        execute('INSERT INTO jobs(id,voice_id,text,language,status,created_at,updated_at,settings_json,model_id,voice_model_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (job_id, body.voice_id, body.text.strip(), body.language, 'queued', timestamp, timestamp,
                 json.dumps(generation), model['id'] if model else None, voice_package['id'] if voice_package else None))
        executor.submit(_process_job, job_id, body.text.strip(), body.language,
                        Path(voice['file_path']) if voice else None, generation, model, voice_package)
    except Exception:
        slots.release()
        raise
    return {'id': job_id, 'status': 'queued', 'status_url': f'/v1/jobs/{job_id}'}


@app.get('/v1/jobs', dependencies=[Depends(authorize)])
def list_jobs():
    return {'items': [public_job(r) for r in query_all('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100')]}


@app.get('/v1/jobs/{job_id}', dependencies=[Depends(authorize)])
def get_job(job_id: str):
    row = query_one('SELECT * FROM jobs WHERE id=?', (job_id,))
    if not row:
        raise HTTPException(404, detail='Job not found')
    return public_job(row)


@app.get('/v1/jobs/{job_id}/audio', dependencies=[Depends(authorize)])
def job_audio(job_id: str):
    row = query_one('SELECT * FROM jobs WHERE id=?', (job_id,))
    if not row or row['status'] != 'completed' or not row['output_path']:
        raise HTTPException(404, detail='Audio not found')
    return FileResponse(row['output_path'], media_type='audio/wav', filename=f'{job_id}.wav')

@app.get('/v1/stream/status', dependencies=[Depends(authorize)])
async def streaming_status():
    return await stream_status()


@app.post('/v1/stream', dependencies=[Depends(authorize)])
async def stream_speech(body: StreamBody):
    """Return progressive raw PCM directly from the running SGLang model server."""
    return await stream_pcm(body)

@app.get('/v1/models', dependencies=[Depends(authorize)])
def models_list():
    return {'items': list_models()}


@app.post('/v1/models/import', status_code=201, dependencies=[Depends(authorize)])
def models_import(body: ImportModel):
    return import_model(body)


@app.post('/v1/models/{model_id}/activate', dependencies=[Depends(authorize)])
def models_activate(model_id: str):
    return activate(model_id)


@app.get('/v1/models/runtime', dependencies=[Depends(authorize)])
def models_runtime():
    return {'state': engine.state, 'loaded_model_id': engine.loaded_model_id,
            'device': engine.device_name, 'error': engine.last_error}


@app.post('/v1/models/{model_id}/load', dependencies=[Depends(authorize)])
def models_load(model_id: str):
    model = resolve_model(model_id)
    executor.submit(engine.load_model, model).result()
    return models_runtime()


@app.post('/v1/models/{model_id}/unload', dependencies=[Depends(authorize)])
def models_unload(model_id: str):
    if engine.loaded_model_id != model_id:
        raise HTTPException(409, 'This model is not loaded')
    executor.submit(engine.unload).result()
    return models_runtime()


@app.post('/v1/models/{model_id}/validate', dependencies=[Depends(authorize)])
def models_validate(model_id: str):
    model = query_one('SELECT * FROM models WHERE id=?', (model_id,))
    if not model:
        raise HTTPException(404, 'Model not found')
    if model['precision'] == 'int8':
        raise HTTPException(501, 'INT8 custom checkpoint loader/exporter is not verified; refusing unsafe validation')
    path = Path(model['model_path'])
    if not path.exists():
        raise HTTPException(422, 'Validation of a remote model requires explicit trusted runtime configuration')
    from uuid import uuid4 as _uuid
    test_path = settings.data_dir / 'generations' / f'validation-{_uuid()}.wav'
    def check():
        try:
            engine.unload()
            engine.synthesize('สวัสดีค่ะ', 'Thai', None, test_path, {}, model)
            with wave.open(str(test_path), 'rb') as w:
                if w.getnframes() == 0:
                    raise ValueError('Empty WAV')
            engine.unload()
            engine.load_model(model)
        finally:
            test_path.unlink(missing_ok=True)
    try:
        executor.submit(check).result()
    except Exception as exc:
        execute("UPDATE models SET status='failed' WHERE id=?", (model_id,))
        raise HTTPException(422, 'Validation failed: ' + str(exc)[:300]) from exc
    execute("UPDATE models SET status='ready' WHERE id=?", (model_id,))
    return query_one('SELECT * FROM models WHERE id=?', (model_id,))


@app.post('/v1/models/export', dependencies=[Depends(authorize)])
def models_export():
    raise HTTPException(501, 'One-time INT8 export needs an architecture-specific verified serialization and reload implementation')


# Reusable F5 reference packages are distinct from MOSS checkpoints.
@app.get('/v1/voice-models', dependencies=[Depends(authorize)])
def voice_models_list():
    return {'items': list_packages()}


@app.post('/v1/voice-models', status_code=201, dependencies=[Depends(authorize)])
def voice_models_build(body: BuildVoicePackage):
    return build_package(body)


@app.get('/v1/voice-models/{package_id}', dependencies=[Depends(authorize)])
def voice_models_get(package_id: str):
    return resolve_package(package_id)


@app.get('/v1/voice-models/{package_id}/reference', dependencies=[Depends(authorize)])
def voice_models_reference(package_id: str):
    package = resolve_package(package_id)
    return FileResponse(Path(package['package_dir']) / 'reference.wav', media_type='audio/wav')


@app.delete('/v1/voice-models/{package_id}', dependencies=[Depends(authorize)])
def voice_models_delete(package_id: str):
    delete_package(package_id)
    return {'deleted': True}
