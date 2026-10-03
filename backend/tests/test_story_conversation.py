"""New journey tests. Existing edit tests do not stand in for these checks."""
import json
import os
import unittest
from unittest.mock import patch

import httpx

import app as server
from story_conversation import ConversationRequest, answer_without_model, converse


def request(text='今天想看看自己'):
    return ConversationRequest(schemaVersion=1, requestId='story-12345678',
        sessionId='session-12345678', assetId='a'*32, userText=text)


class StoryContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        server.story_recent.clear(); server.story_inflight.clear()
        self.env = patch.dict(os.environ, {'SELF_DEV_LOOPBACK': '1', 'SELF_BACKEND_TOKEN': ''})
        self.env.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(
            app=server.app, client=('127.0.0.1', 123)), base_url='http://self')

    async def asyncTearDown(self):
        await self.client.aclose(); self.env.stop()

    async def test_text_request_rejects_media_and_extra_fields(self):
        for key, value in [('images', ['abc']), ('snapshot', {'view': {}})]:
            body = request().model_dump(); body[key] = value
            response = await self.client.post('/v1/conversations', json=body)
            self.assertEqual(response.status_code, 422)
        for text in ['data:image/png;base64,abc', 'look at file_id123']:
            body = request().model_dump(); body['userText'] = text
            self.assertEqual((await self.client.post('/v1/conversations', json=body)).status_code, 422)
        body = request().model_dump(); body['turns'] = [{'userText': 'hi', 'reply': 'data:image/jpeg;base64,abc'}]
        self.assertEqual((await self.client.post('/v1/conversations', json=body)).status_code, 422)

    async def test_auth_and_direct_actions(self):
        with patch.dict(os.environ, {'SELF_BACKEND_TOKEN': 'test-only'}):
            self.assertEqual((await self.client.post('/v1/conversations', json=request().model_dump())).status_code, 401)
        edit = await self.client.post('/v1/conversations', json=request('想试柔玫瑰数字试色').model_dump())
        self.assertEqual(edit.status_code, 200)
        self.assertEqual(edit.json()['kind'], 'edit_entry')
        self.assertNotIn('operations', edit.json())

    async def test_real_product_effect_never_becomes_edit(self):
        result = answer_without_model(request('想看 OLAY 用在我脸上的真实效果'))
        self.assertEqual(result.kind, 'real_effect_boundary')
        self.assertTrue(result.canOfferDigitalPreview)
        self.assertEqual(result.evidenceRefs, [])

    async def test_no_unsolicited_product_and_no_image_in_model_body(self):
        captured = []
        def handle(req):
            body = json.loads(req.content)
            captured.append(body)
            return httpx.Response(200, json={'model': 'test-model', 'choices': [
                {'message': {'content': '可以慢慢转动，停在你想多看一眼的角度。'}}]})
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only', 'DEEPSEEK_BASE_URL': 'https://example.test'}):
            result = await converse(request(), transport=httpx.MockTransport(handle))
        self.assertEqual(result['kind'], 'conversation')
        self.assertEqual(result['evidenceRefs'], [])
        self.assertNotIn('image_url', json.dumps(captured))
        self.assertNotIn('file_id', json.dumps(captured))
        self.assertNotIn('tool', json.dumps(captured))

    async def test_cancellation_response_cannot_execute(self):
        result = answer_without_model(request('今天先这样'))
        self.assertEqual(result.kind, 'closing')
        self.assertFalse(result.canOfferDigitalPreview)


if __name__ == '__main__':
    unittest.main(verbosity=2)
