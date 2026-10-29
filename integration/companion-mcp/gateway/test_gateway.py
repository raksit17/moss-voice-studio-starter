"""Run: python -m unittest discover -s gateway -v (no models required)."""
import os
import unittest
from unittest.mock import AsyncMock
import httpx
os.environ['GATEWAY_API_KEY'] = 'a' * 32
os.environ['MOSS_API_KEY'] = 'test-moss'
import server

class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old = server.http
        self.requests = []
        def handler(request):
            self.requests.append(request)
            if request.url.path.endswith('/audio'):
                return httpx.Response(200, content=b'RIFFtest', headers={'Content-Type':'audio/wav'})
            return httpx.Response(200, json={'ok':True, 'id':'test', 'status':'queued'})
        server.http = httpx.AsyncClient(base_url='http://moss', headers={'X-API-Key':'test-moss'}, transport=httpx.MockTransport(handler))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://localhost:8088', headers={'X-API-Key':'a'*32})

    async def asyncTearDown(self):
        await self.client.aclose()
        await server.http.aclose()
        server.http = self.old

    async def test_auth(self):
        response = await self.client.get('/v1/health', headers={'X-API-Key':'wrong'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.requests, [])

    async def test_mcp_tools_list(self):
        async with server.app.router.lifespan_context(server.app):
            response = await self.client.post('/mcp', headers={
                'Accept':'application/json, text/event-stream'}, json={
                'jsonrpc':'2.0', 'id':1, 'method':'tools/list', 'params':{}})
            self.assertEqual(response.status_code, 200, response.text)
            names = {tool['name'] for tool in response.json()['result']['tools']}
            self.assertEqual(names, {'voice_health', 'list_voices', 'synthesize_speech', 'get_speech_job'})

    async def test_proxy_and_key_separation(self):
        response = await self.client.get('/v1/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.requests[0].headers['X-API-Key'], 'test-moss')

    async def test_binary_audio(self):
        response = await self.client.get('/v1/jobs/12345678-1234-1234-1234-123456789abc/audio')
        self.assertEqual(response.content, b'RIFFtest')
        self.assertEqual(response.headers['content-type'], 'audio/wav')

    async def test_allowlist(self):
        self.assertEqual((await self.client.get('/v1/models/import')).status_code, 404)
        self.assertEqual((await self.client.post('/v1/voices')).status_code, 404)

    async def test_tool_validation(self):
        with self.assertRaises(ValueError):
            await server.synthesize_speech('x'*601)
        self.assertEqual(self.requests, [])

    async def test_redis_failure_does_not_break_job_status(self):
        old = server.redis
        server.redis = AsyncMock()
        server.redis.publish.side_effect = ConnectionError('offline')
        try:
            await server.publish({'id':'example', 'status':'completed'})
            self.assertTrue((await server.get_speech_job('12345678-1234-1234-1234-123456789abc')))
        finally:
            server.redis = old

if __name__ == '__main__':
    unittest.main()
