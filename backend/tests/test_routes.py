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
                    data={'name': 'Yuna', 'language': 'Thai', 'consent': 'true'},
                    files={'audio': ('yuna.wav', fake_wav(), 'audio/wav')})
    assert r.status_code == 201, r.text
    voice_id = r.json()['id']
    assert any(v['id'] == voice_id for v in client.get('/v1/voices', headers=HEADERS).json()['items'])
    assert client.get(f'/v1/voices/{voice_id}/audio', headers=HEADERS).status_code == 200
    assert client.delete(f'/v1/voices/{voice_id}', headers=HEADERS).status_code == 200


def test_invalid_generation():
    assert client.post('/v1/jobs', headers=HEADERS, json={'text': 'x', 'language': 'Klingon'}).status_code == 422
    assert client.post('/v1/jobs', headers=HEADERS,
                       json={'text': 'hello', 'language': 'Thai', 'voice_id': 'unknown'}).status_code == 404


def test_generation_lifecycle(monkeypatch):
    """Test queue / status / audio endpoint with a test stub, NOT real inference."""
    import time
    from app.engine import engine

    def stub_synthesis(_text, _language, _reference, output):
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
