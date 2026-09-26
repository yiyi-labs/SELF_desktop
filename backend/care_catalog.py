"""Source-linked care choices; none is a calibrated appearance effect."""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_RECORDS = {item['product_id']: item for item in json.loads(
    (_ROOT / 'shared/products/audit-v2/products_cn.json').read_text(encoding='utf-8'))}
_ROUTINES = {
    'cream': '清洁后轻轻铺开；具体用量和使用频率看实物包装。',
    'serum': '清洁后按实物包装说明使用，之后可按习惯叠加面霜。',
    'eye': '在眼周轻轻点开，避开眼内；具体用量看实物包装。',
    'sunscreen': '日间按实物包装说明均匀涂抹，户外留意补涂。',
    'cleanser': '清洁时轻柔带过，随后充分冲净。',
}
_ROUTINES_EN = {
    'cream': 'Smooth on gently after cleansing; follow the package for amount and frequency.',
    'serum': 'Use after cleansing as directed on the package, then add cream if that suits your routine.',
    'eye': 'Pat gently around the eyes, avoiding the eyes themselves; follow the package for amount.',
    'sunscreen': 'Apply evenly by day as directed on the package and reapply outdoors.',
    'cleanser': 'Cleanse gently, then rinse thoroughly.',
}

_SKIN_CONCERNS = ('痘', '痘印', '疤', '泛红', '敏感', '干燥', '粗糙', '暗沉', 'acne', 'pimple', 'blemish', 'scar', 'redness')


def care_intent(text: str) -> bool:
    value = text.lower()
    return any(word in value for word in ('养护', '护理', '怎么用', '如何用', '护肤', 'olay', '玉兰油',
        'care', 'routine', '保湿', '防晒', '洁面', '洗脸', '清洁', *_SKIN_CONCERNS))


def care_options(text: str, enabled: bool, language: str = 'zh') -> list[dict]:
    if not enabled:
        return []
    value = text.lower()
    # The reviewed face-care entries are not lip or eye makeup colours.
    if any(word in value for word in ('唇', '口红', '唇色', 'lip', '眼影', '眼线', '睫毛', '眉')):
        return []
    if value.strip() in {'1', '2', '3', '试一下', '试试', '这个', '这款', '它'}:
        return []
    if not any(word in value for word in ('脸', '面部', '皮肤', '肤', '额头', '鼻', '保湿', '护肤', '护理', '养护',
                                          'olay', '玉兰油', 'face', 'cheek', 'skin', 'forehead', 'nose', 'care', 'moistur', *_SKIN_CONCERNS)):
        return []
    if any(word in value for word in ('痘', 'acne', 'pimple', 'blemish')):
        # A cleanser is a routine step, never a claimed acne treatment.
        ids = ['CN029']
    elif any(word in value for word in ('防晒', '紫外线', 'sun')):
        ids = ['CN013']
    elif any(word in value for word in ('眼周', '眼下', '眼霜', 'eye')):
        ids = ['CN024']
    elif any(word in value for word in ('洁面', '洗脸', '清洁', 'cleanse')):
        ids = ['CN029']
    else:
        ids = ['CN001', 'CN005']
    result = []
    for product_id in ids:
        record = _RECORDS[product_id]
        assert record['record_status'] in {'brand_2026_observed', 'catalog_only'}
        result.append({'productId': product_id, 'name': record['marketing_name'],
                       'category': record['category_id'], 'source': record['primary_url'],
                       'ordinaryUse': (_ROUTINES_EN if language == 'en' else _ROUTINES)[record['category_id']]})
    return result


def allowed_care_ids(text: str, enabled: bool) -> set[str]:
    return {item['productId'] for item in care_options(text, enabled)}


def care_usage(text: str, enabled: bool, product_id: str, language: str = 'zh') -> str:
    return next((item['ordinaryUse'] for item in care_options(text, enabled, language)
                 if item['productId'] == product_id), '')


def care_reason(product_id: str, language: str = 'zh', request_text: str = '') -> str:
    if any(word in request_text.lower() for word in ('痘', 'acne', 'pimple', 'blemish')):
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
