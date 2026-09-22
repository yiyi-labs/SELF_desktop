"""Reviewed mainland channel facts. Unknown formulas must stay unknown."""
import json
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'shared/products/olay-cn-catalog.json').read_text(encoding='utf-8'))

def lookup(user_text: str, context_ids: list[str] | None = None) -> list[dict]:
    continuation = user_text.strip() in ('1','2','3') or any(word in user_text for word in ('这款','这个','它','试一下','试试','淡一点','参数','效果'))
    explicit = any(word in user_text.lower() for word in ['olay','玉兰油','产品','护肤','小白瓶','超红瓶','黑管'])
    if not explicit and not (continuation and context_ids):return []
    score = lambda p: sum(k.lower() in user_text.lower() for k in p['keywords'])
    matches = sorted(CATALOG['records'], key=score, reverse=True)
    # Generic "OLAY" is not consent to promote whichever records happen to be
    # first in a catalog. Clarify the user's requested item/concern first.
    matches = [p for p in matches if score(p)>0]
    if not matches and continuation and context_ids and not explicit:
        matches = [p for p in CATALOG['records'] if p['productId'] in context_ids]
    return [{key:p[key] for key in ('productId','name','market','specification','usageSummary','source',
                                  'retrievedAt','evidenceType','recordKind','availability','inci','formulaRevision',
                                  'physicalParameters','efficacyCalibration') } for p in matches[:3]]

def allowed_refs(user_text: str, context_ids: list[str] | None = None) -> set[str]:
    return {p['productId'] for p in lookup(user_text, context_ids)}

def requests_product_effect(user_text: str, context_ids: list[str] | None = None) -> bool:
    value=user_text.lower()
    return any(term in value for term in ('olay','玉兰油','产品','护肤','小白瓶','超红瓶','黑管')) or bool(lookup(user_text,context_ids))
