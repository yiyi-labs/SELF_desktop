"""The in-app browser may display identities, never silently promote them to effects."""
import json
import re
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class OlayDiscoveryTest(unittest.TestCase):
    def test_generated_browser_contains_only_presented_cn_identity_states(self):
        rows = json.loads((ROOT / 'shared/products/audit-v2/products_cn.json').read_text(encoding='utf-8'))
        expected = {row['product_id'] for row in rows
                    if row['record_status'] in {'brand_2026_observed', 'catalog_only'}}
        code = (ROOT / 'entry/src/main/ets/services/OlayDiscoveryRepository.ets').read_text(encoding='utf-8')
        current, research = code.split('static researchRecords()', 1)
        actual = set(re.findall(r'"id": "(CN\d+)"', current))
        self.assertEqual(63, len(expected))
        self.assertEqual(expected, actual)
        self.assertEqual({row['product_id'] for row in rows}, actual | set(re.findall(r'"id": "((?:CN|H)\d+)"', research)))
        self.assertIn('"section": "research"', research)
        self.assertTrue(all(not row['can_render_product_effect'] for row in rows if row['product_id'] in actual))

    def test_official_press_cutouts_are_single_product_transparent_assets(self):
        manifest = json.loads((ROOT / 'shared/products/olay-official-image-manifest.json').read_text(encoding='utf-8'))
        self.assertIn('prnasia.com/story/543190-1.shtml', manifest['sourceArticle'])
        images = manifest['images']
        self.assertEqual({'CN001', 'CN002', 'CN003', 'CN004'}, {image['productId'] for image in images})
        self.assertEqual(4, len({image['resource'] for image in images}))
        for image in images:
            data = (ROOT / 'entry/src/main/resources/base/media' / image['resource']).read_bytes()
            self.assertEqual(b'\x89PNG\r\n\x1a\n', data[:8])
            width, height = struct.unpack('>II', data[16:24])
            self.assertLessEqual(max(width, height), 512)
            self.assertEqual(6, data[25])  # RGBA, including transparent background.


if __name__ == '__main__':
    unittest.main()
