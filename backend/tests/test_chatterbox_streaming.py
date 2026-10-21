"""Tests for progressive Chatterbox sentence streaming without real model weights."""
import io
import tempfile
import wave

from fastapi.testclient import TestClient

from app.main import app
from app import streaming
from test_routes import HEADERS, fake_wav

client = TestClient(app)


def pcm24_wav():
    file = io.BytesIO()
    with wave.open(file, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b'\x01\x00' * 2400)
    return file.getvalue()


def test_chatterbox_streaming_without_sglang(monkeypatch):
    monkeypatch.setattr(streaming.settings, 'sglang_base_url', '')
    monkeypatch.setattr(streaming.chatterbox, 'status', lambda: {
        'ready': True, 'python_found': True, 'error': None,
    })
    status = client.get('/v1/stream/status', headers=HEADERS).json()
    assert status['ready'] is False
    assert status['engines']['chatterbox-turbo']['ready'] is True
    assert status['engines']['chatterbox-turbo']['sample_rate'] == 24000
    assert status['engines']['chatterbox-turbo']['mode'] == 'sentence-chunks'
    calls = []

    def fake_synthesize(text, reference, output, generation=None):
        calls.append((text, reference, generation))
        output.write_bytes(pcm24_wav())

    monkeypatch.setattr(streaming.chatterbox, 'synthesize', fake_synthesize)
    response = client.post('/v1/stream', headers=HEADERS, json={
        'text': 'Hello there! How are you? [chuckle]',
        'language': 'English',
        'engine': 'chatterbox-turbo',
    })
    assert response.status_code == 200, response.text
    assert response.headers['x-audio-encoding'] == 'pcm_s16le'
    assert response.headers['x-sample-rate'] == '24000'
    assert response.headers['x-stream-mode'] == 'sentence-chunks'
    assert response.content == b'\x01\x00' * 2400 * len(calls)
    assert len(calls) == 2
    assert calls[0][0] == 'Hello there!'
    assert calls[1][0] == 'How are you? [chuckle]'
    assert calls[0][2]['temperature'] == .8
    assert calls[0][2]['top_k'] == 1000


def test_chatterbox_stream_voice_validation_and_releases_slot(monkeypatch):
    monkeypatch.setattr(streaming.chatterbox, 'synthesize',
                        lambda *args, **kwargs: args[2].write_bytes(pcm24_wav()))
    assert client.post('/v1/stream', headers=HEADERS, json={
        'text': 'hello', 'engine': 'chatterbox-turbo', 'language': 'Thai',
    }).status_code == 422
    assert client.post('/v1/stream', headers=HEADERS, json={
        'text': 'hello', 'engine': 'chatterbox-turbo', 'language': 'English',
        'voice_id': 'missing',
    }).status_code == 404
    voice = client.post('/v1/voices', headers=HEADERS, data={
        'name': 'Yuna', 'language': 'English', 'consent': 'true'
    }, files={'audio': ('ref.wav', fake_wav(), 'audio/wav')})
    assert voice.status_code == 201, voice.text
    result = client.post('/v1/stream', headers=HEADERS, json={
        'text': 'Hello.', 'engine': 'chatterbox-turbo', 'language': 'English',
        'voice_id': voice.json()['id'],
        'temperature': .6, 'top_p': .9, 'top_k': 200,
    })
    assert result.status_code == 200, result.text
    assert len(result.content) == 4800
    assert client.post('/v1/stream', headers=HEADERS, json={
        'text': 'Hi.', 'engine': 'chatterbox-turbo', 'language': 'English',
    }).status_code == 200
    assert client.delete('/v1/voices/' + voice.json()['id'], headers=HEADERS).status_code == 200
