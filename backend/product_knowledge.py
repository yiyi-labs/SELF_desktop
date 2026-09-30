"""One identity/dossier join for AI and the care constellation.

All 74 research records are searchable. Historical/search-only identities stay
labelled and are never unsolicited recommendations or appearance parameters.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'shared/products/audit-v2'
RECORDS = {p['product_id']: p for p in json.loads((ROOT / 'products_cn.json').read_text(encoding='utf-8'))}
DOSSIERS = {p['dossier_id']: p for p in json.loads((ROOT / 'product_dossiers_cn.json').read_text(encoding='utf-8'))}
if RECORDS.keys() != DOSSIERS.keys():
    raise RuntimeError('product_dossier_join_incomplete')


def normalize(value: str) -> str:
    return re.sub(r'[\W_]+', '', value.casefold())


def identity_index() -> list[dict]:
    return [{'productId': p['product_id'], 'name': p['marketing_name'],
             'category': p['category_id'], 'family': p['family'],
             'status': p['record_status'], 'source': p['primary_url'],
             'recommendable': p['record_status'] in {'brand_2026_observed', 'catalog_only'}}
            for p in RECORDS.values()]


def product_detail(product_id: str) -> dict:
    p, dossier = RECORDS[product_id], DOSSIERS[product_id]
    return {'productId': product_id, 'name': p['marketing_name'], 'category': p['category_id'],
            'market': 'CN-mainland', 'specification': '具体规格以实物包装为准',
            'usageSummary': '有来源的产品身份与品类资料；具体用法以实物包装为准',
            'source': p['primary_url'], 'retrievedAt': p['checked_on'],
            'evidenceType': p['record_status'], 'recordKind': 'research-identity',
            'availability': 'not-verified', 'inci': p.get('full_inci'),
            'formulaRevision': p.get('formula_version_id'), 'physicalParameters': None,
            'efficacyCalibration': None, 'canRenderProductEffect': False,
            'facts': dossier['facts'], 'claims': dossier['claims'],
            'ingredientHighlights': dossier['ingredient_highlights'],
            'offers': dossier['offers'], 'sourceLinks': dossier['source_links'],
            'fieldCoverage': dossier['field_coverage']}


def exact_identities(text: str) -> list[dict]:
    query = normalize(text)
    matches = [p for p in RECORDS.values() if len(normalize(p['marketing_name'])) >= 4
               and normalize(p['marketing_name']) in query]
    matches.sort(key=lambda p: len(normalize(p['marketing_name'])), reverse=True)
    return [product_detail(p['product_id']) for p in matches[:3]]


def contextual_products(ids: list[str]) -> list[dict]:
    return [product_detail(i) for i in ids if i in RECORDS][:3]
