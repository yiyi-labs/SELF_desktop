"""Generate an in-app, source-linked OLAY identity browser from the audited data.

Research identities are presentation data, never optical parameters or sale claims.
Historical and search-only records are deliberately absent from the current browser.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'shared/products/audit-v2/products_cn.json'
DEST = ROOT / 'entry/src/main/ets/services/OlayDiscoveryRepository.ets'
records = json.loads(SOURCE.read_text(encoding='utf-8'))
included = [r for r in records if r['record_status'] in {'brand_2026_observed', 'catalog_only'}]
assert len(included) == 63
assert len({r['product_id'] for r in included}) == len(included)
assert all(r['market'] == 'CN' and r['primary_url'].startswith('https://') for r in included)

items = []
for record in included:
    items.append({
        'id': record['product_id'],
        'name': record['marketing_name'],
        'category': record['category_id'],
        'family': record['family'],
        'source': record['primary_url'],
        'section': 'brand' if record['record_status'] == 'brand_2026_observed' else 'catalog',
    })

header = '''// Generated from the audited CN identity data by scripts/build-olay-discovery.py.
// These names and sources do not authorize product-effect rendering.
export interface OlayDiscoveryItem {
  id:string;
  name:string;
  category:string;
  family:string;
  source:string;
  section:string;
}
export class OlayDiscoveryRepository {
  static records():OlayDiscoveryItem[]{ return '''
research = [{'id': r['product_id'], 'name': r['marketing_name'], 'category': r['category_id'],
             'family': r['family'], 'source': r['primary_url'], 'section': 'research'}
            for r in records if r not in included]
assert len(items) + len(research) == len(records) == 74
footer = '; }\n  static researchRecords():OlayDiscoveryItem[]{ return ' + json.dumps(research, ensure_ascii=False, indent=2) + '''; }
  static allRecords():OlayDiscoveryItem[]{return OlayDiscoveryRepository.records().concat(OlayDiscoveryRepository.researchRecords());}
}
'''
DEST.write_text(header + json.dumps(items, ensure_ascii=False, indent=2) + footer, encoding='utf-8')
print(f'Generated {len(items)} care identities + {len(research)} historical/research identities; all {len(records)} dossiers linked.')
