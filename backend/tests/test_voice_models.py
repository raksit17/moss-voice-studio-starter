"""API contract checks using an F5 worker stub: no GPU or model download."""
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app, engine
from test_routes import HEADERS, fake_wav

client = TestClient(app)


def test_reference_package_and_f5_job(monkeypatch):
    voice = client.post('/v1/voices', headers=HEADERS, data={
        'name': 'test1', 'language': 'Thai', 'consent': 'true',
        'transcript': 'สวัสดีค่ะ',
    }, files={'audio': ('test1.wav', fake_wav(), 'audio/wav')})
    assert voice.status_code == 201, voice.text
    voice_id = voice.json()['id']
    saved = client.post('/v1/voice-models', headers=HEADERS,
                        json={'name': 'test1-small', 'source_voice_id': voice_id})
    assert saved.status_code == 201, saved.text
    package = saved.json()
    folder = Path(package['package_dir'])
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['trained_checkpoint'] is False
    assert (folder / 'reference.wav').read_bytes().startswith(b'RIFF')
    assert (folder / 'reference.txt').read_text(encoding='utf-8') == 'สวัสดีค่ะ'

    bad = client.post('/v1/jobs', headers=HEADERS, json={
        'text': 'ทดสอบ', 'language': 'Thai',
        'voice_model_id': package['id'], 'model_id': 'moss-original'})
    assert bad.status_code == 422

    calls = []
    def fake_unload(): calls.append('unload')
    def fake_f5(_text, _package, output):
        calls.append('f5')
        output.write_bytes(fake_wav())
    monkeypatch.setattr(engine, 'unload', fake_unload)
    monkeypatch.setattr('app.main.synthesize_f5', fake_f5)
    created = client.post('/v1/jobs', headers=HEADERS,
                          json={'text': 'ทดสอบ', 'language': 'Thai',
                                'voice_model_id': package['id']})
    assert created.status_code == 202, created.text
    for _ in range(100):
        job = client.get('/v1/jobs/' + created.json()['id'], headers=HEADERS).json()
        if job['status'] in ('failed', 'completed'):
            break
        time.sleep(.02)
    assert job['status'] == 'completed', job
    assert job['model_id'] is None and job['voice_model_id'] == package['id']
    assert calls == ['unload', 'f5']
    assert client.delete('/v1/voices/' + voice_id, headers=HEADERS).status_code == 200
    assert client.get('/v1/voice-models/' + package['id'] + '/reference', headers=HEADERS).status_code == 200
    assert client.delete('/v1/voice-models/' + package['id'], headers=HEADERS).status_code == 200
    assert not folder.exists()


def test_completed_generation_as_source():
    from app.db import execute, now_iso
    from app.config import settings
    from uuid import uuid4
    job_id = str(uuid4())
    path = settings.data_dir / 'generations' / (job_id + '.wav')
    path.write_bytes(fake_wav())
    ts = now_iso()
    execute('INSERT INTO jobs(id,text,language,status,output_path,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
            (job_id, 'สวัสดีค่ะ', 'Thai', 'completed', str(path), ts, ts))
    saved = client.post('/v1/voice-models', headers=HEADERS,
                        json={'name': 'test1-small', 'source_job_id': job_id})
    assert saved.status_code == 201, saved.text
    assert saved.json()['source_type'] == 'generation'
    assert client.delete('/v1/voice-models/' + saved.json()['id'], headers=HEADERS).status_code == 200


def test_builder_rejects_invalid_source():
    assert client.get('/v1/voice-models', headers={}).status_code == 401
    assert client.post('/v1/voice-models', headers=HEADERS,
                       json={'name': 'invalid'}).status_code == 422
    assert client.post('/v1/voice-models', headers=HEADERS,
                       json={'name': 'invalid', 'source_voice_id': 'missing'}).status_code == 404
