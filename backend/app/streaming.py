"""Gateway to the official SGLang-Omni MOSS streaming API.

Returns progressive signed 16-bit little-endian mono PCM at 48 kHz.
This service performs authorization and reference lookup; SGLang owns inference.
"""
import base64
import logging
import threading
from pathlib import Path
from typing import Literal

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import settings
from .db import query_one

logger = logging.getLogger(__name__)
stream_slots = threading.BoundedSemaphore(1)


class StreamBody(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    language: Literal['Thai', 'English'] = 'Thai'
    voice_id: str | None = None
    instructions: str | None = Field(default=None, max_length=240)
    temperature: float = Field(default=1.7, ge=0.1, le=2.0)
    top_p: float = Field(default=0.8, ge=0.05, le=1.0)
    top_k: int = Field(default=25, ge=1, le=100)


def make_payload(body: StreamBody) -> dict:
    if not body.text.strip() or body.language not in ('Thai', 'English'):
        raise HTTPException(422, detail='Nonblank text and Thai or English are required')
    payload = {
        'input': body.text.strip(),
        'language': body.language,
        'stream': True,
        'response_format': 'pcm',
        'stream_format': 'audio',
        'audio_temperature': body.temperature,
        'audio_top_p': body.top_p,
        'audio_top_k': body.top_k,
    }
    if body.instructions:
        payload['instructions'] = body.instructions.strip()
    if body.voice_id:
        voice = query_one('SELECT * FROM voices WHERE id=?', (body.voice_id,))
        if not voice:
            raise HTTPException(404, detail='Selected voice not found')
        audio = Path(voice['file_path'])
        if not audio.is_file():
            raise HTTPException(404, detail='Reference WAV file missing')
        reference = {
            'audio_path': 'data:audio/wav;base64,' +
                base64.b64encode(audio.read_bytes()).decode('ascii'),
        }
        if voice.get('transcript'):
            reference['text'] = voice['transcript']
        payload['references'] = [reference]
    return payload


def create_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10))


async def stream_pcm(body: StreamBody) -> StreamingResponse:
    if not settings.sglang_base_url:
        raise HTTPException(503, detail='Streaming disabled: configure SGLANG_BASE_URL')
    payload = make_payload(body)
    if not stream_slots.acquire(blocking=False):
        raise HTTPException(429, detail='Streaming engine busy')
    client = None
    upstream = None
    try:
        client = create_client()
        request = client.build_request('POST',
            settings.sglang_base_url.rstrip('/') + '/v1/audio/speech', json=payload)
        upstream = await client.send(request, stream=True)
        if upstream.status_code >= 400:
            detail = (await upstream.aread())[:400].decode('utf-8', errors='replace')
            raise HTTPException(502, detail=f'SGLang HTTP {upstream.status_code}: {detail}')
        sample_rate = upstream.headers.get('x-moss-sample-rate', upstream.headers.get('x-sample-rate', '48000'))
        channels = upstream.headers.get('x-moss-channels', upstream.headers.get('x-channels', '1'))
        if sample_rate != '48000' or channels != '1':
            raise HTTPException(502, detail='Unexpected PCM format returned by SGLang')
    except HTTPException:
        if upstream is not None:
            await upstream.aclose()
        if client is not None:
            await client.aclose()
        stream_slots.release()
        raise
    except (httpx.HTTPError, OSError) as exc:
        if upstream is not None:
            await upstream.aclose()
        if client is not None:
            await client.aclose()
        stream_slots.release()
        logger.warning('SGLang connection failed: %s', exc)
        raise HTTPException(503, detail='Cannot connect to SGLang-Omni') from exc

    async def chunks():
        try:
            async for chunk in upstream.aiter_bytes():
                if chunk:
                    yield chunk
        except httpx.HTTPError:
            logger.exception('PCM stream interrupted')
        finally:
            await upstream.aclose()
            await client.aclose()
            stream_slots.release()

    return StreamingResponse(chunks(), media_type='application/octet-stream',
        headers={'X-Audio-Encoding': 'pcm_s16le', 'X-Sample-Rate': '48000',
                 'X-Channels': '1', 'Cache-Control': 'no-store'})


async def status() -> dict:
    if not settings.sglang_base_url:
        return {'configured': False, 'ready': False, 'reason': 'SGLANG_BASE_URL is not set'}
    try:
        async with create_client() as client:
            response = await client.get(settings.sglang_base_url.rstrip('/') + '/health')
            return {'configured': True, 'ready': response.status_code == 200,
                    'reason': None if response.status_code == 200 else f'HTTP {response.status_code}'}
    except httpx.HTTPError:
        return {'configured': True, 'ready': False, 'reason': 'SGLang unreachable'}
