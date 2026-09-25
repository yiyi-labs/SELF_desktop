import unittest
from product_research import PRODUCTS, COVERAGE, brand_observed_records, identity_lookup

class ResearchBoundary(unittest.TestCase):
    def test_dataset_is_research_not_a_live_complete_catalog(self):
        self.assertEqual(len(PRODUCTS),74)
        self.assertEqual(len(brand_observed_records()),17)
        self.assertFalse(COVERAGE['global_or_mainland_complete_catalog'])
        self.assertEqual(COVERAGE['calibrated_render_profiles'],0)
        self.assertTrue(all(not p['can_render_product_effect'] for p in PRODUCTS))

    def test_only_exact_observed_identity_is_retrieved(self):
        self.assertEqual(identity_lookup('介绍第6代超红瓶·水霜')[0]['productId'],'CN001')
        self.assertEqual(identity_lookup('推荐一款超红瓶'),[])
        self.assertEqual(identity_lookup('我不喜欢脸上的痘痘'),[])
        self.assertFalse(identity_lookup('介绍第6代超红瓶·水霜')[0]['canRenderProductEffect'])
