"""Reviewed mainland channel facts. Unknown formulas must stay unknown."""
import json
import re
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
    # A clearly separate daily-care question can accompany a generic colour
    # preview in one conversation. It still cannot authorize a product effect.
    separate_care = ('通用数字试色' in value and
        re.search(r'(?:顺便|另外|同时|独立).{0,24}(?:olay|玉兰油).{0,16}(?:护理|养护|使用建议)',value) and
        not re.search(r'(?:用|靠|按).{0,10}(?:olay|玉兰油).{0,16}(?:达到|做出|涂成|变成|还原)',value))
    if separate_care:
        return False
    if any(term in value for term in ('olay','玉兰油','小白瓶','超红瓶','黑管')):
        return True
    # A request explicitly framed as generic digital colour is not a product
    # effect merely because it says "not a product effect". A named product
    # above never gains this exception.
    generic = '通用数字试色' in value and re.search(r'(?:不是|非|不按|不根据).{0,8}(?:产品|护肤)',value)
    if generic:
        return False
    return any(term in value for term in ('产品','护肤')) or bool(lookup(user_text,context_ids))
