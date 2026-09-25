"""Source-attributed CN product identity research, never rendering parameters."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1] / 'shared/products/audit-v2'
PRODUCTS = json.loads((ROOT / 'products_cn.json').read_text(encoding='utf-8'))
COVERAGE = json.loads((ROOT / 'coverage.json').read_text(encoding='utf-8'))
RECHECKS = {entry['source_id']: entry for entry in json.loads((ROOT / 'source_rechecks.json').read_text(encoding='utf-8'))}

def normalize(value: str) -> str:
    return re.sub(r'[\W_]+', '', value.casefold())

def brand_observed_records() -> list[dict]:
    return [record for record in PRODUCTS if record['record_status'] == 'brand_2026_observed'
            and record['default_product_retrieval']]

def identity_lookup(user_text: str) -> list[dict]:
    """Only exact variant names; broad family queries must remain ambiguous."""
    query = normalize(user_text)
    if not query or len(query) < 5:
        return []
    matched = [record for record in brand_observed_records()
               if len(normalize(record['marketing_name'])) >= 5
               and normalize(record['marketing_name']) in query]
    result = []
    for record in matched[:3]:
        source = next((RECHECKS[id] for id in record['source_ids'] if id in RECHECKS), None)
        result.append({
            'productId': record['product_id'], 'name': record['marketing_name'],
            'market': 'CN-mainland', 'specification': '具体规格未核实',
            'usageSummary': '公开资料中的产品身份；不是在售、配方或使用后外观保证。',
            'source': record['primary_url'], 'retrievedAt': record['checked_on'],
            'evidenceType': '品牌公开线索；范围以来源复核状态为准',
            'sourceRecheckStatus': source['status'] if source else 'not_rechecked',
            'recordKind': 'research-identity', 'availability': 'not-verified',
            'inci': None, 'formulaRevision': None, 'physicalParameters': None,
            'efficacyCalibration': None, 'canRenderProductEffect': False,
        })
    return result

assert len(PRODUCTS) == 74 and COVERAGE['calibrated_render_profiles'] == 0
