"""Mock SGLang HTTP tests: no weights or GPU needed."""
import io
import os
import tempfile
import wave

import httpx
from fastapi.testclient import TestClient

os.environ['API_KEY'] = 'local-dev-key'
os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='moss-stream-test-')

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app import streaming  # noqa: E402

client = TestClient(app)
headers = {'X-API-Key': 'local-dev-key'}


def make_wav():
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b'\0\0' * 16000 * 3)
    return output.getvalue()


def test_stream_auth_disabled(monkeypatch):
    monkeypatch.setattr(settings, 'sglang_base_url', '')
    assert client.post('/v1/stream', json={'text': 'hello'}).status_code == 401
    response = client.post('/v1/stream', headers=headers, json={'text': 'hello'})
    assert response.status_code == 503
    assert client.get('/v1/stream/status', headers=headers).json()['configured'] is False


def test_upstream_failure_releases_slot(monkeypatch):
    monkeypatch.setattr(settings, 'sglang_base_url', 'http://127.0.0.1:8000')

    def fake_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(500, text='GPU unavailable')))
    monkeypatch.setattr(streaming, 'create_client', fake_client)
    for _ in range(2):
        response = client.post('/v1/stream', headers=headers, json={'text': 'hello'})
        assert response.status_code == 502
        assert 'SGLang HTTP 500' in response.json()['detail']


def test_streaming_and_voice_reference(monkeypatch):
    monkeypatch.setattr(settings, 'sglang_base_url', 'http://127.0.0.1:8000')
    voice = client.post('/v1/voices', headers=headers,
        data={'name': 'Yuna', 'language': 'Thai', 'consent': 'true',
              'transcript': 'นี่คือเสียงต้นแบบ'},
        files={'audio': ('yuna.wav', make_wav(), 'audio/wav')})
    assert voice.status_code == 201, voice.text
    requests = []

    def fake_upstream(request):
        import json
        if request.url.path == '/health':
            return httpx.Response(200)
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=b'\0\0\x01\x00' * 400,
            headers={'x-moss-sample-rate': '48000', 'x-moss-channels': '1'})

    monkeypatch.setattr(streaming, 'create_client',
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake_upstream)))
    assert client.get('/v1/stream/status', headers=headers).json()['ready']
    result = client.post('/v1/stream', headers=headers, json={
        'text': 'สวัสดีค่ะ', 'language': 'Thai', 'voice_id': voice.json()['id']})
    assert result.status_code == 200, result.text
    assert len(result.content) == 1600
    assert result.headers['x-audio-encoding'] == 'pcm_s16le'
    assert requests[0]['stream'] is True
    assert requests[0]['references'][0]['text'] == 'นี่คือเสียงต้นแบบ'
    assert requests[0]['references'][0]['audio_path'].startswith('data:audio/wav;base64,')
    assert client.post('/v1/stream', headers=headers,
        json={'text': 'x', 'voice_id': '../etc/passwd'}).status_code == 404


def test_invalid_stream_settings():
    assert client.post('/v1/stream', headers=headers,
        json={'text': 'hello', 'language': 'Invalid'}).status_code == 422
