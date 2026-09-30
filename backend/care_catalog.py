"""Source-linked care choices; none is a calibrated appearance effect."""
import re
from product_knowledge import RECORDS as _RECORDS, exact_identities

_ROUTINES = {
    'cream': '清洁后轻轻铺开；具体用量和使用频率看实物包装。',
    'serum': '清洁后按实物包装说明使用，之后可按习惯叠加面霜。',
    'eye': '在眼周轻轻点开，避开眼内；具体用量看实物包装。',
    'sunscreen': '日间按实物包装说明均匀涂抹，户外留意补涂。',
    'cleanser': '清洁时轻柔带过，随后充分冲净。',
    'toner': '清洁后轻轻涂开，具体用法和频率看实物包装。',
    'emulsion': '清洁后轻轻铺开，具体用量和顺序看实物包装。',
    'mask': '按实物包装说明使用，留意使用时长与是否需要冲洗。',
    'set': '按套装内各单品的实物说明分别使用，不把套装视为单一配方。',
    'body_lotion': '在身体皮肤上轻轻涂开，具体用量看实物包装。',
    'body_scrub': '仅按实物包装说明用于身体，避免用在眼周或已破损的皮肤上。',
    'body_cleanser': '按实物包装说明清洁身体，随后充分冲净。',
    'body_tint': '按实物包装说明用于身体，先在小范围查看色彩。',
}
_ROUTINES_EN = {
    'cream': 'Smooth on gently after cleansing; follow the package for amount and frequency.',
    'serum': 'Use after cleansing as directed on the package, then add cream if that suits your routine.',
    'eye': 'Pat gently around the eyes, avoiding the eyes themselves; follow the package for amount.',
    'sunscreen': 'Apply evenly by day as directed on the package and reapply outdoors.',
    'cleanser': 'Cleanse gently, then rinse thoroughly.',
    'toner': 'Apply gently after cleansing; follow the package for method and frequency.',
    'emulsion': 'Smooth on gently after cleansing; follow the package for amount and order.',
    'mask': 'Follow the package for duration and whether to rinse off.',
    'set': 'Follow each item’s own instructions; a set is not a single formula.',
    'body_lotion': 'Smooth onto body skin as directed on the package.',
    'body_scrub': 'Use on the body as directed; avoid the eye area and broken skin.',
    'body_cleanser': 'Cleanse the body as directed, then rinse thoroughly.',
    'body_tint': 'Use on the body as directed; check the colour on a small area first.',
}

_SKIN_CONCERNS = ('痘', '痘印', '疤', '泛红', '敏感', '干燥', '粗糙', '暗沉', 'acne', 'pimple', 'blemish', 'scar', 'redness')


def care_intent(text: str) -> bool:
    value = text.lower()
    return any(word in value for word in ('保养', '养护', '护理', '怎么用', '如何用', '护肤', '眼霜', 'olay', '玉兰油',
        'care', 'routine', '保湿', '防晒', '洁面', '洗脸', '清洁', *_SKIN_CONCERNS))


def products_declined(text: str) -> bool:
    return bool(re.search(r'(?:不要|不用|不想|别|不买).{0,8}(?:推荐|产品|商品|买|olay|玉兰油)|no products|no recommendations|don.t recommend', text, re.I))


def care_feedback(text: str) -> bool:
    return bool(re.search(r'刺痛|过敏|不舒服|太贵|已经有|已有|买过|sting|irritat|already (?:have|use)|too expensive', text, re.I))


def care_options(text: str, enabled: bool, language: str = 'zh', area: str = '', concern: str = '') -> list[dict]:
    if not enabled or products_declined(text) or care_feedback(text):
        return []
    value = text.lower()
    if area == 'eye' and concern == 'blemish':
        return []
    # The reviewed face-care entries are not lip or eye makeup colours.
    if any(word in value for word in ('唇', '口红', '唇色', 'lip', '眼影', '眼线', '睫毛', '眉')):
        return []
    if value.strip() in {'1', '2', '3', '试一下', '试试', '这个', '这款', '它'}:
        return []
    if not area and not exact_identities(text) and not any(word in value for word in ('脸', '面部', '皮肤', '肤', '额头', '鼻', '眼', '保养', '保湿', '护肤', '护理', '养护',
                                          'olay', '玉兰油', 'face', 'cheek', 'skin', 'forehead', 'nose', 'care', 'moistur', *_SKIN_CONCERNS)):
        return []
    if any(word in value for word in ('痘', 'acne', 'pimple', 'blemish')) or concern == 'blemish':
        # A cleanser is a routine step, never a claimed acne treatment.
        categories = {'cleanser', 'cream'}
    elif any(word in value for word in ('防晒', '紫外线', 'sun')):
        categories = {'sunscreen'}
    elif any(word in value for word in ('眼', 'eye')) or area == 'eye':
        categories = {'eye'}
    elif any(word in value for word in ('洁面', '洗脸', '清洁', 'cleanse')):
        categories = {'cleanser'}
    elif area == 'body' or any(word in value for word in ('身体', '身体乳', '沐浴', 'body')):
        categories = {'body_lotion', 'body_cleanser', 'body_scrub', 'body_tint'}
    elif area in {'lips', 'brow'}:
        return []
    else:
        # Before vision analysis, every facial category is available, including
        # eyes. Validation narrows the choice using the returned observation.
        categories = {'cream', 'serum', 'toner', 'emulsion', 'mask', 'sunscreen', 'cleanser'}
        if not area or area == 'unknown':
            categories.add('eye')
    exact = {p['productId'] for p in exact_identities(text)}
    ids = [p['product_id'] for p in _RECORDS.values()
           if p['record_status'] in {'brand_2026_observed', 'catalog_only'}
           and p['category_id'] in categories and (not exact or p['product_id'] in exact)]
    if concern == 'blemish' or any(word in value for word in ('痘', 'acne', 'pimple', 'blemish')):
        ids.sort(key=lambda i: _RECORDS[i]['category_id'] != 'cleanser')
    result = []
    for product_id in ids:
        record = _RECORDS[product_id]
        assert record['record_status'] in {'brand_2026_observed', 'catalog_only'}
        result.append({'productId': product_id, 'name': record['marketing_name'],
                       'category': record['category_id'], 'source': record['primary_url'],
                       'ordinaryUse': (_ROUTINES_EN if language == 'en' else _ROUTINES)[record['category_id']]})
    return result


def allowed_care_ids(text: str, enabled: bool, area: str = '', concern: str = '') -> set[str]:
    return {item['productId'] for item in care_options(text, enabled, area=area, concern=concern)}


def care_usage(text: str, enabled: bool, product_id: str, language: str = 'zh') -> str:
    return (_ROUTINES_EN if language == 'en' else _ROUTINES)[_RECORDS[product_id]['category_id']]


def care_reason(product_id: str, language: str = 'zh', request_text: str = '') -> str:
    if any(word in request_text.lower() for word in ('痘', 'acne', 'pimple', 'blemish')):
        if _RECORDS[product_id]['category_id'] == 'cream':
            return ('A gentle moisturizing step is daily care, not an acne treatment.' if language == 'en'
                    else '轻轻做日常保湿，不揉搓这处；面霜不是祛痘治疗。')
        return ('Start with a gentle cleansing step; this cleanser is not an acne treatment.' if language == 'en'
                else '先轻柔清洁这处，不揉搓；洁面不是祛痘治疗。')
    category = _RECORDS[product_id]['category_id']
    if language == 'en':
        return {
            'eye': 'Give the eye area a gentle place in your daily routine.',
            'sunscreen': 'Daytime care can include a simple sun-protection step.',
            'cleanser': 'A gentle cleanse can be one small part of your daily routine.',
        }.get(category, 'Make room for a calm daily-care step and notice how your skin feels.')
    return {
        'eye': '眼周也可以有轻柔的日常节奏，留意自己喜欢的舒适感。',
        'sunscreen': '白天可以把防晒放进日常节奏里，慢慢找到适合自己的方式。',
        'cleanser': '清洁这一步放轻一些，留意自己喜欢的肤感。',
    }.get(category, '这处也可以有自己的日常护理节奏，留意自己喜欢的肤感。')
