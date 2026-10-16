"""Smoke tests run without downloading model weights."""
import io
import os
import tempfile
import wave
from fastapi.testclient import TestClient

os.environ['API_KEY'] = 'local-dev-key'
os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='moss-test-')
from app.main import app  # noqa: E402

client = TestClient(app)
HEADERS = {'X-API-Key': 'local-dev-key'}


def fake_wav():
    bio = io.BytesIO()
    with wave.open(bio, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b'\0\0' * 16000 * 3)
    return bio.getvalue()


def test_auth_and_health():
    assert client.get('/v1/health').status_code == 401
    r = client.get('/v1/health', headers=HEADERS)
    assert r.status_code == 200
    assert r.json()['streaming'] is False


def test_upload_and_list_voice():
    r = client.post('/v1/voices', headers=HEADERS,
                    data={'name': 'Yuna', 'language': 'Thai', 'consent': 'true',
                          'transcript': 'สวัสดีค่ะ', 'character': 'Yuna'},
                    files={'audio': ('yuna.wav', fake_wav(), 'audio/wav')})
    assert r.status_code == 201, r.text
    voice_id = r.json()['id']
    voice = next(v for v in client.get('/v1/voices', headers=HEADERS).json()['items'] if v['id'] == voice_id)
    assert voice['transcript'] == 'สวัสดีค่ะ'
    assert voice['character'] == 'Yuna'
    assert client.get(f'/v1/voices/{voice_id}/audio', headers=HEADERS).status_code == 200
    assert client.delete(f'/v1/voices/{voice_id}', headers=HEADERS).status_code == 200


def test_invalid_generation():
    assert client.post('/v1/jobs', headers=HEADERS, json={'text': 'x', 'language': 'Klingon'}).status_code == 422
    assert client.post('/v1/jobs', headers=HEADERS,
                       json={'text': 'hello', 'language': 'Thai', 'voice_id': 'unknown'}).status_code == 404
    assert client.post('/v1/jobs', headers=HEADERS,
                       json={'text': 'hello', 'temperature': 9}).status_code == 422


def test_generation_lifecycle(monkeypatch):
    """Test queue / status / audio endpoint with a test stub, NOT real inference."""
    import time
    from app.engine import engine

    def stub_synthesis(_text, _language, _reference, output, _generation=None, _model=None):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(fake_wav())

    monkeypatch.setattr(engine, 'synthesize', stub_synthesis)
    created = client.post('/v1/jobs', headers=HEADERS,
                          json={'text': 'สวัสดีค่ะ', 'language': 'Thai'})
    assert created.status_code == 202
    job_id = created.json()['id']
    for _ in range(50):
        job = client.get(f'/v1/jobs/{job_id}', headers=HEADERS).json()
        if job['status'] in ('completed', 'failed'):
            break
        time.sleep(0.02)
    assert job['status'] == 'completed', job
    wav_response = client.get(f'/v1/jobs/{job_id}/audio', headers=HEADERS)
    assert wav_response.status_code == 200
    assert wav_response.content.startswith(b'RIFF')
    assert job['settings'] == {'temperature': 1.7, 'top_p': 0.8, 'top_k': 25}

def test_model_registry_and_activation():
    res = client.get('/v1/models', headers=HEADERS)
    assert res.status_code == 200
    assert any(m['id'] == 'moss-original' and m['is_default'] for m in res.json()['items'])
    assert client.get('/v1/models/runtime', headers=HEADERS).status_code == 200
    assert client.post('/v1/models/missing/activate', headers=HEADERS).status_code == 404
    assert client.post('/v1/models/export', headers=HEADERS).status_code == 501


def test_model_import_rejects_untrusted_path():
    res = client.post('/v1/models/import', headers=HEADERS, json={
        'name': 'Outside root', 'model_path': '/does/not/exist', 'precision': 'bf16'
    })
    assert res.status_code in (403, 422)
    res = client.post('/v1/jobs', headers=HEADERS,
                      json={'text': 'hello', 'model_id': 'no-such-model'})
    assert res.status_code == 404
