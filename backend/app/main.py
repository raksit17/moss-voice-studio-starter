from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import logging
import threading
import wave

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import settings
from .db import execute, initialize, now_iso, query_all, query_one
from .engine import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('moss-studio')
initialize()
app = FastAPI(title='MOSS Voice Studio API', version='0.1.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.allowed_origins.split(',') if x.strip()],
    allow_credentials=False,
    allow_methods=['GET', 'POST', 'DELETE'],
    allow_headers=['Content-Type', 'X-API-Key'],
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


def public_job(row: dict) -> dict:
    return {
        'id': row['id'], 'voice_id': row['voice_id'], 'text': row['text'],
        'language': row['language'], 'status': row['status'], 'error': row['error'],
        'created_at': row['created_at'], 'updated_at': row['updated_at'],
        'audio_url': f"/v1/jobs/{row['id']}/audio" if row['status'] == 'completed' else None,
    }


@app.get('/v1/health', dependencies=[Depends(authorize)])
def health():
    return {
        'ok': True,
        'engine': engine.state,
        'device': engine.device_name,
        'model': settings.moss_model_id,
        'error': engine.last_error,
        'sample_rate': 48000,
        'streaming': False,
    }


@app.get('/v1/voices', dependencies=[Depends(authorize)])
def list_voices():
    rows = query_all('SELECT id, name, language, created_at FROM voices ORDER BY created_at DESC')
    return {'items': rows}


@app.post('/v1/voices', status_code=201, dependencies=[Depends(authorize)])
async def upload_voice(
    name: str = Form(..., min_length=1, max_length=80),
    language: str = Form('Thai'),
    consent: bool = Form(False),
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
    execute('INSERT INTO voices(id,name,language,file_path,created_at) VALUES (?,?,?,?,?)',
            (voice_id, name.strip(), language, str(path.resolve()), timestamp))
    return {'id': voice_id, 'name': name.strip(), 'language': language, 'created_at': timestamp}


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


def _process_job(job_id: str, text: str, language: str, reference: Path | None) -> None:
    output = settings.data_dir / 'generations' / f'{job_id}.wav'
    try:
        execute('UPDATE jobs SET status=?, updated_at=? WHERE id=?', ('running', now_iso(), job_id))
        engine.synthesize(text, language, reference, output)
        execute('UPDATE jobs SET status=?, output_path=?, updated_at=? WHERE id=?',
                ('completed', str(output.resolve()), now_iso(), job_id))
    except Exception as exc:
        logger.exception('Generation failed for %s', job_id)
        execute('UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?',
                ('failed', str(exc)[:500], now_iso(), job_id))
        output.unlink(missing_ok=True)
    finally:
        slots.release()


@app.post('/v1/jobs', status_code=202, dependencies=[Depends(authorize)])
def create_job(body: GenerateBody):
    if body.language not in ('Thai', 'English'):
        raise HTTPException(422, detail='Supported languages: Thai / English')
    if not body.text.strip():
        raise HTTPException(422, detail='Text cannot be blank')
    voice = query_one('SELECT * FROM voices WHERE id=?', (body.voice_id,)) if body.voice_id else None
    if body.voice_id and not voice:
        raise HTTPException(404, detail='Selected voice not found')
    if not slots.acquire(blocking=False):
        raise HTTPException(429, detail='Generation queue full (8 jobs)')
    job_id = str(uuid4())
    timestamp = now_iso()
    try:
        execute('INSERT INTO jobs(id,voice_id,text,language,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                (job_id, body.voice_id, body.text.strip(), body.language, 'queued', timestamp, timestamp))
        executor.submit(_process_job, job_id, body.text.strip(), body.language,
                        Path(voice['file_path']) if voice else None)
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
