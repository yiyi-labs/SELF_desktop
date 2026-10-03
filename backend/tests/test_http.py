"""In-process HTTP contract tests. Mock planner results are never model evidence."""
import base64
import os
import unittest
from unittest.mock import AsyncMock, patch
import httpx
import app as server
from test_contracts import snapshot
from deepseek_client import ModelFailure

class HttpBoundary(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        server.recent.clear(); server.completed.clear(); server.inflight.clear()
        self.environment=patch.dict(os.environ,{'SELF_DEV_LOOPBACK':'1','SELF_BACKEND_TOKEN':''})
        self.environment.start()
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app,client=('127.0.0.1',123)),base_url='http://self')
        self.body={'snapshot':snapshot().model_dump(),'images':[base64.b64encode(b'fixture').decode()]}
    async def asyncTearDown(self):
        await self.client.aclose(); self.environment.stop()
    async def test_auth_rejects_before_planner(self):
        with patch.dict(os.environ,{'SELF_BACKEND_TOKEN':'test-only'}),patch.object(server,'propose',new_callable=AsyncMock) as call:
            r=await self.client.post('/v1/edit-plans',json=self.body)
            self.assertEqual(r.status_code,401);call.assert_not_called()
    async def test_denied_upload_extra_fields_no_upstream(self):
        for field in ('denied','extra'):
            body={'snapshot':snapshot().model_dump(),'images':self.body['images']}
            if field=='denied':body['snapshot']['uploadAuthorized']=False
            else:body['secret']='must-not-echo'
            with patch.object(server,'propose',new_callable=AsyncMock) as call:
                r=await self.client.post('/v1/edit-plans',json=body)
                self.assertEqual(r.status_code,422);call.assert_not_called();self.assertNotIn('must-not-echo',r.text)
    async def test_content_length_validation(self):
        for length,expected in [('invalid',400),('-1',400),('12000000',413)]:
            r=await self.client.post('/v1/edit-plans',content=b'{}',headers={'content-length':length})
            self.assertEqual(r.status_code,expected)
    async def test_duplicate_is_idempotent_and_changed_payload_rejected(self):
        with patch.object(server,'propose',new_callable=AsyncMock,return_value={'candidate':'fixture'}) as call:
            a=await self.client.post('/v1/edit-plans',json=self.body)
            b=await self.client.post('/v1/edit-plans',json=self.body)
            self.assertEqual(a.json(),b.json());self.assertEqual(call.await_count,1)
            self.body['snapshot']['userText']='changed'
            self.assertEqual((await self.client.post('/v1/edit-plans',json=self.body)).status_code,409)
    async def test_failure_does_not_cache_or_keep_inflight(self):
        with patch.object(server,'propose',new_callable=AsyncMock,side_effect=ModelFailure('model_timeout')):
            r=await self.client.post('/v1/edit-plans',json=self.body)
            self.assertEqual(r.status_code,502);self.assertFalse(server.inflight);self.assertFalse(server.completed)
    async def test_inflight_and_rate_limit(self):
        server.inflight.add(self.body['snapshot']['requestId'])
        self.assertEqual((await self.client.post('/v1/edit-plans',json=self.body)).status_code,409)
        server.inflight.add('other')
        self.assertEqual((await self.client.post('/v1/edit-plans',json=self.body)).status_code,429)

if __name__=='__main__':unittest.main(verbosity=2)
