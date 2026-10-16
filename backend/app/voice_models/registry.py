"""Reusable F5 Thai voice packages: WAV/transcript/manifest, not trained checkpoints."""
import hashlib
import json
import shutil
import wave
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from ..config import settings
from ..db import execute, now_iso, query_all, query_one


class BuildVoicePackage(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    source_voice_id: str | None = None
    source_job_id: str | None = None

    @model_validator(mode='after')
    def check_source(self):
        if bool(self.source_voice_id) == bool(self.source_job_id):
            raise ValueError('Provide exactly one source_voice_id or source_job_id')
        if not self.name.strip():
            raise ValueError('Package name cannot be blank')
        return self


def list_packages() -> list[dict]:
    return query_all('SELECT * FROM voice_models ORDER BY created_at DESC')


def resolve_package(package_id: str) -> dict:
    row = query_one('SELECT * FROM voice_models WHERE id=?', (package_id,))
    if not row:
        raise HTTPException(404, detail='Saved voice package not found')
    folder = Path(row['package_dir'])
    if not all((folder / n).is_file() for n in ('manifest.json', 'reference.wav', 'reference.txt')):
        raise HTTPException(409, detail='Saved voice package files are missing')
    return row


def _source(body: BuildVoicePackage) -> tuple[str, str, str, Path, str]:
    if body.source_voice_id:
        row = query_one('SELECT * FROM voices WHERE id=?', (body.source_voice_id,))
        if not row:
            raise HTTPException(404, detail='Voice Profile not found')
        source_type, source_id = 'voice', row['id']
        transcript = row['transcript'].strip()
        source_path = Path(row['file_path'])
    else:
        row = query_one('SELECT * FROM jobs WHERE id=?', (body.source_job_id,))
        if not row or row['status'] != 'completed' or not row['output_path']:
            raise HTTPException(422, detail='Source job must have completed WAV audio')
        source_type, source_id = 'generation', row['id']
        transcript = row['text'].strip()
        source_path = Path(row['output_path'])
    if row['language'] != 'Thai':
        raise HTTPException(422, detail='This F5-TTS-THAI builder currently requires Thai reference audio')
    if not transcript:
        raise HTTPException(422, detail='The reference audio needs an exact transcript')
    if not source_path.is_file():
        raise HTTPException(409, detail='Reference WAV is no longer available')
    return source_type, source_id, transcript, source_path, row['language']


def build_package(body: BuildVoicePackage) -> dict:
    source_type, source_id, transcript, source_path, language = _source(body)
    try:
        with wave.open(str(source_path), 'rb') as wav:
            if wav.getcomptype() != 'NONE' or not wav.getnframes():
                raise ValueError('Reference must be non-empty uncompressed PCM WAV')
            duration = wav.getnframes() / wav.getframerate()
            if not 1 <= duration <= 60:
                raise ValueError('Reference WAV must be 1-60 seconds')
    except (ValueError, wave.Error, ZeroDivisionError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    package_id = str(uuid4())
    folder = (settings.models_dir / 'voice-packages').resolve() / package_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
        reference_path = folder / 'reference.wav'
        shutil.copyfile(source_path, reference_path)
        (folder / 'reference.txt').write_text(transcript, encoding='utf-8')
        timestamp = now_iso()
        manifest = {
            'schema_version': 1, 'id': package_id, 'name': body.name.strip(),
            'kind': 'reference_voice_package', 'trained_checkpoint': False,
            'runtime': 'f5-tts-th', 'runtime_model': 'v1', 'method': 'zero_shot',
            'source_type': source_type, 'source_id': source_id,
            'language': language, 'created_at': timestamp,
            'duration_seconds': round(duration, 2),
            'recommended_reference_seconds': '2-8',
            'sha256': hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        }
        (folder / 'manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        execute('''INSERT INTO voice_models
            (id,name,runtime,method,source_type,source_id,language,transcript,package_dir,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (package_id, body.name.strip(), 'f5-tts-th', 'zero_shot',
             source_type, source_id, language, transcript, str(folder), timestamp))
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return resolve_package(package_id)


def delete_package(package_id: str) -> None:
    row = resolve_package(package_id)
    folder = Path(row['package_dir']).resolve()
    root = (settings.models_dir / 'voice-packages').resolve()
    if not folder.is_relative_to(root) or folder == root:
        raise HTTPException(409, detail='Unsafe package location')
    execute('DELETE FROM voice_models WHERE id=?', (package_id,))
    shutil.rmtree(folder)
