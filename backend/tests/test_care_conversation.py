"""Regression scenarios from selecting eyes and asking how to care for them."""
import io
import json
import os
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from care_catalog import care_options, care_intent
from contracts import Plan, Snapshot, validate_plan
from deepseek_client import ModelFailure, propose, request_body
from product_catalog import lookup
from product_knowledge import RECORDS, DOSSIERS, identity_index, product_detail
from response_quality import repeats
from story_conversation import ConversationRequest, converse
from test_contracts import snapshot, response


def selected(text='这里怎么保养？', dialogue=None):
    return Snapshot.model_validate({**snapshot().model_dump(), 'userText': text,
        'careAdviceRequested': True, 'annotatedRegionId': 'circle-1',
        'regions': [{'regionId': 'circle-1', 'description': '用户圈选的第1处'}],
        'layers': [], 'dialogue': dialogue or []})


def eye_plan(message='你圈的是眼周。清洁时放轻动作，避免揉搓；眼霜可以作为一个可选的日常步骤。'):
    return {'decision': 'explain', 'shortMessage': message, 'operations': [],
        'explanationRefs': [], 'question': '', 'selectionObservations': [
            {'regionId': 'circle-1', 'area': 'eye', 'concern': 'none', 'confidence': 'clear', 'basis': 'image'}]}


class KnowledgeCoverage(unittest.TestCase):
    def test_entire_constellation_and_dossiers_join(self):
        self.assertEqual(set(RECORDS), set(DOSSIERS))
        self.assertEqual(len(identity_index()), 74)
        for product_id, record in RECORDS.items():
            with self.subTest(product_id=product_id):
                info = product_detail(product_id)
                self.assertEqual(info['name'], record['marketing_name'])
                self.assertTrue(info['source'].startswith('https://'))
                self.assertEqual(info['facts'], DOSSIERS[product_id]['facts'])
                self.assertEqual(info['ingredientHighlights'], DOSSIERS[product_id]['ingredient_highlights'])
                self.assertIn(product_id, {p['productId'] for p in lookup('介绍 OLAY '+record['marketing_name'])})
                self.assertFalse(info['canRenderProductEffect'])

    def test_all_live_browser_categories_reachable_without_guessing_formula(self):
        for product_id, record in RECORDS.items():
            if record['record_status'] not in {'brand_2026_observed', 'catalog_only'}:
                continue
            area = 'body' if record['category_id'].startswith('body_') else ''
            items = care_options('OLAY '+record['marketing_name']+' 的护理用法', True, area=area)
            # Sets can be explained as separate products, not one skin routine.
            if record['category_id'] != 'set':
                self.assertIn(product_id, {p['productId'] for p in items}, product_id)

    def test_eyes_and_generic_care_are_first_class_intents(self):
        self.assertTrue(care_intent('怎么保养'))
        self.assertTrue(care_options('这里怎么保养', True))
        eye_ids = {p['productId'] for p in care_options('眼睛怎么保养', True)}
        self.assertIn('CN008', eye_ids)
        self.assertIn('CN024', eye_ids)
        self.assertTrue(all(RECORDS[i]['category_id'] == 'eye' for i in eye_ids))

    def test_image_anatomy_controls_the_care_category(self):
        p = validate_plan(Plan.model_validate(eye_plan()), selected())
        self.assertEqual(RECORDS[p.careGuide.productId]['category_id'], 'eye')
        bad = eye_plan(); bad['careGuide'] = {'productId': 'CN001', 'whyHere': '这是一件面霜护理的选择。', 'howToUse': '清洁后按包装说明轻轻使用。'}
        self.assertRaises(ValueError, validate_plan, Plan.model_validate(bad), selected())
        for area in ('cheek', 'forehead', 'nose', 'chin'):
            raw = eye_plan(); raw['selectionObservations'][0]['area'] = area
            checked = validate_plan(Plan.model_validate(raw), selected())
            self.assertNotEqual(RECORDS[checked.careGuide.productId]['category_id'], 'eye')
        raw = eye_plan(); raw['selectionObservations'][0].update(area='cheek', concern='blemish')
        checked = validate_plan(Plan.model_validate(raw), selected())
        self.assertEqual(RECORDS[checked.careGuide.productId]['category_id'], 'cleanser')
        self.assertEqual(checked.operations, [])

    def test_unknown_and_unselected_anatomy_cannot_become_certain(self):
        raw = eye_plan(); raw['selectionObservations'][0]['regionId'] = 'unselected'
        self.assertRaises(ValueError, validate_plan, Plan.model_validate(raw), selected())
        raw = eye_plan(); raw['selectionObservations'][0]['confidence'] = 'uncertain'
        self.assertRaises(ValueError, validate_plan, Plan.model_validate(raw), selected())

    def test_recommendations_stop_when_declined_or_already_offered(self):
        previous = [{'userText': '这里怎么保养', 'reply': '可考虑一件眼霜。', 'productIds': ['CN008']}]
        result = validate_plan(Plan.model_validate(eye_plan()), selected('平时应该怎么清洁？', previous))
        self.assertIsNone(result.careGuide)
        self.assertIsNone(validate_plan(Plan.model_validate(eye_plan()), selected('不要推荐产品，只讲保养')).careGuide)
        self.assertEqual(care_options('只想聊聊', True), [])
        self.assertEqual(care_options('想试柔玫瑰唇色', True), [])
        self.assertEqual(care_options('OLAY 用了刺痛怎么办', True), [])
        self.assertEqual(care_options('我已经有眼霜了，怎么保养', True), [])
        follow = selected('这款眼霜怎么用？', previous)
        follow.productContextIds = ['CN008']
        self.assertIsNone(validate_plan(Plan.model_validate(eye_plan()), follow).careGuide)

    def test_unverified_amount_and_tint_cannot_replace_care(self):
        for message in ('取米粒大小的眼霜，早晚各使用一次。', '先让这一处透一点颜色，边缘轻轻散开。'):
            with self.subTest(message=message):
                self.assertRaises(ValueError, validate_plan, Plan.model_validate(eye_plan(message)), selected())

    def test_uncertain_selection_offers_no_guessed_product(self):
        raw = eye_plan('这一处在当前画面里看不清，先用轻柔清洁的方式照顾。')
        raw['selectionObservations'][0].update(area='unknown', confidence='uncertain')
        self.assertIsNone(validate_plan(Plan.model_validate(raw), selected()).careGuide)

    def test_followup_keeps_identity_and_complete_dossier(self):
        info = lookup('这款怎么用？', ['CN008'])[0]
        self.assertEqual(info['productId'], 'CN008')
        self.assertIn('fieldCoverage', info)
        self.assertEqual(lookup('我想聊聊鼻子', ['CN008']), [])

    def test_repetition_detects_same_answer_and_question(self):
        self.assertTrue(repeats('你想关注哪一处？', ['你想关注哪一处?']))
        self.assertTrue(repeats('先轻轻清洁眼周。', ['先轻轻清洁眼周。 再看自己的感受。']))
        self.assertFalse(repeats('洗脸时别来回揉搓眼周，冲洗后轻轻按干。', ['你圈的是眼周。']))


class ModelQuality(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only', 'DEEPSEEK_BASE_URL': 'https://example.test'})
        self.env.start()
        image = io.BytesIO(); Image.new('RGB', (16,16), 'white').save(image, format='PNG')
        self.image = image.getvalue()

    async def asyncTearDown(self):
        self.env.stop()

    async def test_eye_selection_gets_eye_product_without_brand_prompt(self):
        bodies = []
        def handle(req):
            bodies.append(json.loads(req.content))
            return httpx.Response(200, json=response(eye_plan()))
        result = await propose(selected(), [self.image, self.image], httpx.MockTransport(handle))
        self.assertEqual(result['plan']['careGuide']['productId'], 'CN008')
        context = json.loads(bodies[0]['messages'][1]['content'][0]['text'])
        self.assertEqual(len(context['productIdentityIndex']), 74)
        self.assertIn('CN008', {p['productId'] for p in context['careOptions']})
        self.assertEqual(len(bodies), 1)

    async def test_repeated_plan_repaired_once_before_display(self):
        old = '你圈的是眼周。清洁时放轻动作，避免揉搓。'
        calls = []
        def handle(req):
            calls.append(req)
            return httpx.Response(200, json=response(eye_plan(old if len(calls)==1 else '洗脸时别来回擦眼周，冲洗后轻轻按干；现有眼霜按包装说明点开即可。')))
        s = selected('应该怎么清洁？', [{'userText': '这里怎么保养', 'reply': old, 'productIds': ['CN008']}])
        result = await propose(s, [self.image], httpx.MockTransport(handle))
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(result['plan']['shortMessage'], old)
        self.assertIsNone(result['plan']['careGuide'])

    async def test_repeated_response_never_reaches_user(self):
        old = '清洁时放轻动作，不要反复揉搓眼周。'
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=response(eye_plan(old))))
        with self.assertRaisesRegex(ModelFailure, 'repeated_response'):
            await propose(selected('怎么清洁', [{'userText': 'hi', 'reply': old}]), [self.image], transport)

    async def test_missing_region_analysis_repaired_without_inventing_anatomy(self):
        calls = []
        def handle(req):
            calls.append(req)
            raw = eye_plan()
            if len(calls)==1: raw.pop('selectionObservations')
            return httpx.Response(200, json=response(raw))
        result = await propose(selected(), [self.image], httpx.MockTransport(handle))
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['plan']['selectionObservations'][0]['area'], 'eye')

    async def test_text_care_uses_connected_eye_identity_and_repairs_repeat(self):
        old = '你平时在意眼周哪些感受？'
        calls = []
        def handle(req):
            calls.append(json.loads(req.content))
            return httpx.Response(200, json={'choices': [{'message': {'content': old if len(calls)==1 else '清洁时少揉搓眼周；如果想加一个护理步骤，可以看看淡纹黑管眼霜，沿眼周轻轻点开，具体用量看包装。'}}]})
        req = ConversationRequest(schemaVersion=1, requestId='story-12345678', sessionId='session-12345678',
            assetId='a'*32, userText='眼睛怎么保养？', turns=[{'userText': '怎么护理', 'reply': old}])
        result = await converse(req, httpx.MockTransport(handle))
        self.assertEqual(result['evidenceRefs'], ['CN008'])
        self.assertEqual(len(calls), 2)
        self.assertNotIn('image_url', json.dumps(calls))


if __name__ == '__main__':
    unittest.main()
