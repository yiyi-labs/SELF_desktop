"""Check every displayed OLAY identity has a traceable, nonempty product image."""
import json
import re
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
records = (ROOT / 'entry/src/main/ets/services/OlayDiscoveryRepository.ets').read_text(encoding='utf-8')
photos = (ROOT / 'entry/src/main/ets/services/OlayPhotoRepository.ets').read_text(encoding='utf-8')
ids = set(re.findall(r'"id": "(CN\d{3})"', records))
mapped = dict(re.findall(r"case '(CN\d{3})':return \$r\('app\.media\.(olay_cn\d{3})'\);", photos))
thumbnails = dict(re.findall(r"case '(CN\d{3})':return \$r\('app\.media\.(olay_thumb_cn\d{3})'\);", photos))
retail = json.loads((ROOT / 'shared/products/olay-retail-image-manifest.json').read_text(encoding='utf-8'))
press = json.loads((ROOT / 'shared/products/olay-official-image-manifest.json').read_text(encoding='utf-8'))
documented = {item['productId'] for item in retail['items']} | {item['productId'] for item in press['images']}
assert ids == set(mapped) == set(thumbnails) == documented, (ids - set(mapped), ids - set(thumbnails), ids - documented)
assert len(ids) == 63
assert all(item['retailSources'] and all(source['listingUrl'].startswith('https://item.jd.com/')
                                         for source in item['retailSources']) for item in retail['items'])
assert {item['productId'] for item in retail['items'] if item['mappingStatus'] == 'series_reference'} == {'CN010', 'CN022'}
for resource in set(mapped.values()):
    path = ROOT / 'entry/src/main/resources/base/media' / f'{resource}.png'
    with Image.open(path) as image:
        assert max(image.size) == 512 and min(image.size) > 300, path
        assert image.mode == 'RGBA', path
        alpha = image.getchannel('A')
        assert alpha.getextrema() == (0, 255), path
        assert alpha.point(lambda value: 255 if value > 30 else 0).getbbox(), path
for product_id, resource in thumbnails.items():
    assert resource == mapped[product_id].replace('olay_', 'olay_thumb_')
    path = ROOT / 'entry/src/main/resources/base/media' / f'{resource}.png'
    with Image.open(path) as image:
        assert image.size == (96, 96), path
        assert image.mode == 'RGBA', path
print(f'OLAY packshots: {len(ids)} records, {len(set(mapped.values()))} local resources, all source-linked')
