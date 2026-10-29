"""Local single-user REST compatibility gateway and MCP tool server."""
import asyncio
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from redis.asyncio import Redis
from starlette.responses import Response, StreamingResponse

KEY = os.environ['GATEWAY_API_KEY']
if len(KEY) < 32:
    raise RuntimeError('GATEWAY_API_KEY must contain at least 32 characters')
MOSS_KEY = os.environ['MOSS_API_KEY']
BASE = os.environ.get('MOSS_URL', 'http://moss:8001').rstrip('/')
CHANNEL = 'companion.voice.events.v1'
log = logging.getLogger('gateway')
http = httpx.AsyncClient(base_url=BASE, headers={'X-API-Key': MOSS_KEY}, timeout=30)
redis = Redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'), decode_responses=True, socket_connect_timeout=2, socket_timeout=3)
mcp = FastMCP('Companion Voice', stateless_http=True, json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=['localhost:*', '127.0.0.1:*', 'voice-gateway:*'],
        allowed_origins=['http://localhost:*', 'http://127.0.0.1:*']))

def job_id(value: str) -> str:
    return str(UUID(value))

async def call(method: str, path: str, body=None):
    try:
        r = await http.request(method, path, json=body)
    except httpx.HTTPError as exc:
        raise HTTPException(503, 'MOSS unavailable') from exc
    if r.is_error:
        raise HTTPException(r.status_code, r.text[:1000])
    return r.json()

async def publish(job):
    # Text, voice samples and credentials never enter the event channel.
    event = {'schema_version': 1, 'event_id': str(uuid4()), 'timestamp': time.time(),
             'job_id': job['id'], 'status': job['status'], 'source': 'moss'}
    try:
        await redis.publish(CHANNEL, json.dumps(event))
    except Exception:
        log.warning('Redis event delivery unavailable; use job status REST/MCP')

async def reconcile():
    # Snapshot reconciliation after restart; MOSS remains the source of truth.
    previous = {}
    while True:
        try:
            data = await call('GET', '/v1/jobs')
            jobs = data.get('items', []) if isinstance(data, dict) else data
            current = {}
            for job in jobs:
                current[job['id']] = job['status']
                if previous.get(job['id']) != job['status']:
                    await publish(job)
            previous = current
        except Exception:
            log.warning('MOSS status reconciliation unavailable')
        await asyncio.sleep(1)

@mcp.tool()
async def voice_health() -> dict:
    """Read MOSS connection and model readiness; not an inference test."""
    return await call('GET', '/v1/health')

@mcp.tool()
async def list_voices() -> dict:
    """List existing consented voice profiles."""
    return await call('GET', '/v1/voices')

@mcp.tool()
async def synthesize_speech(text: str, language: str = 'Thai', voice_id: str | None = None) -> dict:
    """Create one MOSS WAV job. Poll get_speech_job; audio is a separate binary route."""
    if not text.strip() or len(text) > 600:
        raise ValueError('text must contain 1–600 characters')
    if language not in ('Thai', 'English'):
        raise ValueError('language must be Thai or English')
    return await call('POST', '/v1/jobs', {'text': text, 'language': language, 'voice_id': voice_id, 'engine': 'moss'})

@mcp.tool()
async def get_speech_job(id: str) -> dict:
    """Read authoritative job state, including after event loss."""
    return await call('GET', '/v1/jobs/' + job_id(id))

@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        task = asyncio.create_task(reconcile())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await http.aclose()
            await redis.aclose()

app = FastAPI(lifespan=lifespan)

@app.middleware('http')
async def authenticate(request: Request, next_handler):
    supplied = request.headers.get('X-API-Key', '')
    bearer = request.headers.get('Authorization', '')
    if bearer.startswith('Bearer '):
        supplied = bearer[7:]
    if not hmac.compare_digest(supplied.encode(), KEY.encode()):
        return Response(status_code=401)
    return await next_handler(request)

@app.get('/events')
async def events(request: Request):
    async def stream():
        try:
            async with redis.pubsub() as sub:
                await sub.subscribe(CHANNEL)
                yield ': connected; recover state with GET /v1/jobs\n\n'
                while not await request.is_disconnected():
                    msg = await sub.get_message(ignore_subscribe_messages=True, timeout=1)
                    if msg:
                        yield 'data: ' + msg['data'] + '\n\n'
                    else:
                        yield ': heartbeat\n\n'
        except Exception:
            yield 'event: unavailable\ndata: {"recover":"GET /v1/jobs"}\n\n'
    return StreamingResponse(stream(), media_type='text/event-stream')

@app.api_route('/v1/{path:path}', methods=['GET', 'POST'])
async def proxy(path: str, request: Request):
    # Explicit allowlist; no arbitrary upstream URLs or filesystem paths.
    import re
    allowed = path in ('health', 'voices', 'jobs', 'stream', 'stream/status') or bool(
        re.fullmatch(r'jobs/[0-9a-fA-F-]{36}(?:/audio)?', path))
    if not allowed or (request.method == 'POST' and path not in ('jobs', 'stream')):
        raise HTTPException(404)
    raw = await request.body()
    if len(raw) > 32768:
        raise HTTPException(413)
    try:
        upstream = await http.send(http.build_request(request.method, '/v1/' + path,
            content=raw, headers={'Content-Type': request.headers.get('Content-Type', 'application/json')}), stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(503, 'MOSS unavailable') from exc
    async def chunks():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
    headers = {k: v for k, v in upstream.headers.items() if k.lower() in
        ('content-type', 'x-audio-encoding', 'x-sample-rate', 'x-channels', 'x-stream-mode')}
    return StreamingResponse(chunks(), status_code=upstream.status_code, headers=headers)

app.mount('/', mcp.streamable_http_app())
