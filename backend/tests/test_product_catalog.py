import io
import json
import unittest
from PIL import Image
from product_catalog import CATALOG, lookup, requests_product_effect
from contracts import Plan, Region, validate_plan
from deepseek_client import request_body
from test_contracts import snapshot, plan

class ProductFacts(unittest.TestCase):
    def test_generic_tint_negation_does_not_unlock_named_product(self):
        self.assertFalse(requests_product_effect('通用数字试色，不是产品效果'))
        self.assertTrue(requests_product_effect('OLAY 小白瓶通用数字试色，不是产品效果'))
    def test_new_effect_cannot_move_to_another_known_region(self):
        s=snapshot().model_copy(update={'annotatedRegionId':'user-circle'})
        s.regions.append(Region(regionId='user-circle',description='用户本次圈选'))
        with self.assertRaisesRegex(ValueError,'selected_region_mismatch'):
            validate_plan(Plan.model_validate(plan()),s)

    def test_no_fabricated_parameters(self):
        self.assertEqual(CATALOG['coverage'], 'partial')
        self.assertEqual(len({r['productId'] for r in CATALOG['records']}), len(CATALOG['records']))
        for record in CATALOG['records']:
            self.assertEqual(record['market'], 'CN-mainland')
            self.assertEqual(record['calibrationProfile'], '')
            for field in ['inci','formulaRevision','physicalParameters','efficacyCalibration']:
                self.assertIsNone(record[field])

    def test_regular_conversation_does_not_inject_products(self):
        self.assertEqual(lookup('我不喜欢这里'), [])
        self.assertEqual(lookup('唇色淡一点'), [])
        self.assertEqual(lookup('我想了解OLAY，请先询问我的需求'), [])

    def test_product_request_cannot_become_generic_tint(self):
        s=snapshot().model_copy(update={'userText':'请根据OLAY水光小白瓶50ml的参数修改圈出的区域'})
        with self.assertRaisesRegex(ValueError,'product_effect_not_calibrated'):
            validate_plan(Plan.model_validate(plan()),s)

    def test_generic_tint_cannot_smuggle_product_card(self):
        p=plan();p['explanationRefs']=['olay-cn-waterglow-50ml']
        with self.assertRaisesRegex(ValueError,'product_effect_not_calibrated'):
            validate_plan(Plan.model_validate(p),snapshot())

    def test_product_followup_retains_identity_and_blocks_tint(self):
        ids=['olay-cn-waterglow-50ml']
        self.assertEqual(lookup('那就试一下这款',ids)[0]['productId'],ids[0])
        s=snapshot().model_copy(update={'userText':'那就试一下这款','productContextIds':ids})
        with self.assertRaisesRegex(ValueError,'product_effect_not_calibrated'):
            validate_plan(Plan.model_validate(plan()),s)
        self.assertEqual(lookup('我不喜欢自己的鼻子',ids),[])
        self.assertEqual(lookup('介绍OLAY黑管精华',ids)[0]['productId'],'olay-cn-black-serum-series')

    def test_only_supplied_information_can_be_cited(self):
        s = snapshot().model_copy(update={'userText':'OLAY 水光小白瓶50ml资料'})
        found = lookup(s.userText)
        self.assertEqual(found[0]['productId'], 'olay-cn-waterglow-50ml')
        p = Plan(decision='explain',shortMessage='页面标注50ml，配方尚未核实。',operations=[],
                 explanationRefs=[found[0]['productId']],question='')
        validate_plan(p,s)
        with self.assertRaises(ValueError):
            validate_plan(p,snapshot())

    def test_real_request_context_includes_unknowns_and_source(self):
        out = io.BytesIO(); Image.new('RGB',(16,16),'white').save(out,format='PNG')
        s = snapshot().model_copy(update={'userText':'介绍玉兰油黑管精华资料'})
        body = request_body(s,[out.getvalue()],'deepseek-flash')
        context = json.loads(body['messages'][1]['content'][0]['text'])
        info = context['productInformation'][0]
        self.assertIsNone(info['physicalParameters'])
        self.assertIn('jd.com',info['source'])
        self.assertEqual(info['availability'],'not-verified')
