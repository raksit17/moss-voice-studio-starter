"""Chatterbox Turbo routes use stubs: no CUDA/model download required in CI."""
import time

from fastapi.testclient import TestClient

from app.main import app, engine, chatterbox
from test_routes import HEADERS, fake_wav

client = TestClient(app)


def wait_for_job(job_id):
    for _ in range(100):
        result = client.get('/v1/jobs/' + job_id, headers=HEADERS)
        assert result.status_code == 200
        data = result.json()
        if data['status'] in ('completed', 'failed'):
            return data
        time.sleep(.02)
    raise AssertionError('Job did not complete in test time')


def test_turbo_status_requires_key():
    assert client.get('/v1/chatterbox/status').status_code == 401
    status = client.get('/v1/chatterbox/status', headers=HEADERS)
    assert status.status_code == 200
    assert status.json()['engine'] == 'chatterbox-turbo'
    assert isinstance(status.json()['python_found'], bool)
    assert 'ready' in status.json()


def test_turbo_rejects_thai_and_moss_model_selection():
    for body in (
        {'text': 'hello', 'language': 'Thai', 'engine': 'chatterbox-turbo'},
        {'text': 'hello', 'language': 'English', 'engine': 'chatterbox-turbo',
         'model_id': 'moss-original'},
        {'text': 'hello', 'language': 'English', 'engine': 'chatterbox-turbo',
         'voice_model_id': 'any'},
        {'text': 'hello', 'language': 'English', 'engine': 'unknown'},
    ):
        response = client.post('/v1/jobs', headers=HEADERS, json=body)
        assert response.status_code == 422, response.text
    assert client.post('/v1/jobs', headers=HEADERS, json={
        'text': 'hello', 'language': 'English', 'engine': 'chatterbox-turbo',
        'voice_id': 'missing',
    }).status_code == 404


def test_turbo_english_voice_clone_and_audio(monkeypatch):
    voice = client.post('/v1/voices', headers=HEADERS, data={
        'name': 'Turbo voice', 'language': 'English', 'consent': 'true',
        'transcript': 'Hello there!',
    }, files={'audio': ('english.wav', fake_wav(), 'audio/wav')})
    assert voice.status_code == 201, voice.text
    voice_id = voice.json()['id']
    called = []

    def fake_unload():
        called.append('unload-moss')

    def fake_turbo(text, reference, output):
        called.append(('turbo', text, reference.name if reference else None))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(fake_wav())

    monkeypatch.setattr(engine, 'unload', fake_unload)
    monkeypatch.setattr(chatterbox, 'synthesize', fake_turbo)
    submitted = client.post('/v1/jobs', headers=HEADERS, json={
        'text': 'Welcome back! [chuckle]',
        'engine': 'chatterbox-turbo', 'language': 'English', 'voice_id': voice_id,
    })
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()['id']
    job = wait_for_job(job_id)
    assert job['status'] == 'completed', job
    assert job['engine'] == 'chatterbox-turbo'
    assert job['voice_id'] == voice_id
    assert job['model_id'] is None and job['voice_model_id'] is None
    assert called == ['unload-moss', ('turbo', 'Welcome back! [chuckle]', voice_id + '.wav')]
    assert client.get('/v1/jobs/' + job_id + '/audio', headers=HEADERS).content.startswith(b'RIFF')
    listing = client.get('/v1/jobs', headers=HEADERS).json()['items']
    assert next(item for item in listing if item['id'] == job_id)['engine'] == 'chatterbox-turbo'
    assert client.delete('/v1/voices/' + voice_id, headers=HEADERS).status_code == 200


def test_turbo_default_voice(monkeypatch):
    monkeypatch.setattr(engine, 'unload', lambda: None)
    def fake_turbo(text, reference, output):
        assert text == 'Hello'
        assert reference is None
        output.write_bytes(fake_wav())
    monkeypatch.setattr(chatterbox, 'synthesize', fake_turbo)
    response = client.post('/v1/jobs', headers=HEADERS, json={
        'text': 'Hello', 'language': 'English', 'engine': 'chatterbox-turbo',
    })
    assert response.status_code == 202, response.text
    assert wait_for_job(response.json()['id'])['status'] == 'completed'


def test_turbo_failed_inference_surfaces_job_error(monkeypatch):
    monkeypatch.setattr(engine, 'unload', lambda: None)
    def fail(*args):
        raise RuntimeError('CUDA out of memory')
    monkeypatch.setattr(chatterbox, 'synthesize', fail)
    response = client.post('/v1/jobs', headers=HEADERS, json={
        'text': 'Hello', 'language': 'English', 'engine': 'chatterbox-turbo',
    })
    assert response.status_code == 202
    job = wait_for_job(response.json()['id'])
    assert job['status'] == 'failed'
    assert 'CUDA out of memory' in job['error']
    assert job['audio_url'] is None
