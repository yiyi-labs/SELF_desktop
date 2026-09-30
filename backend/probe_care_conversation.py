"""Live DeepSeek check using a drawn, nonpersonal face and numbered selections."""
import asyncio
import io
import json
from pathlib import Path
from PIL import Image, ImageDraw
import httpx
from contracts import Plan, validate_plan
from deepseek_client import propose, ModelFailure
from product_knowledge import RECORDS
from response_quality import repeats
from test_care_conversation import selected


class ProbeTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport()
        self.raw = {}

    async def handle_async_request(self, request):
        response = await self.transport.handle_async_request(request)
        self.raw = json.loads(await response.aread())
        return response

    async def aclose(self):
        await self.transport.aclose()


async def checked_propose(s, images):
    transport = ProbeTransport()
    try:
        return await propose(s, images, transport)
    except ModelFailure:
        # Only synthetic fixture tool output; never headers, request images or keys.
        args = transport.raw.get('choices', [{}])[0].get('message', {}).get('tool_calls', [{}])[0].get('function', {}).get('arguments', '{}')
        try:
            validate_plan(Plan.model_validate_json(args), s)
        except Exception as diagnostic:
            print('SYNTHETIC_PROBE_DIAGNOSTIC', str(diagnostic), args)
        raise


def fixture(area):
    image = Image.new('RGB', (512,512), '#e7eef5')
    draw = ImageDraw.Draw(image)
    draw.ellipse((100,40,410,476), fill='#e4bca0', outline='#6e5044', width=3)
    for x in (196,314):
        draw.arc((x-39,164,x+39,215), 180, 360, fill='#302823', width=4)
        draw.arc((x-38,164,x+38,215), 0, 180, fill='#302823', width=3)
        draw.ellipse((x-10,177,x+10,199), fill='white')
        draw.ellipse((x-6,179,x+6,195), fill='#302823')
        draw.arc((x-43,141,x+43,171), 190,350, fill='#44322b', width=5)
    draw.line((254,202,244,287,272,287), fill='#8b6657', width=3)
    draw.arc((205,311,308,360), 0,180, fill='#8f4949', width=5)
    if area == 'blemish':
        draw.ellipse((338,254,352,268), fill='#aa4f45', outline='#7f302a', width=2)
    clean = io.BytesIO(); image.save(clean, format='PNG')
    annotated = image.copy(); mark = ImageDraw.Draw(annotated)
    bounds = (149,148,239,224) if area == 'eye' else (323,241,367,282)
    mark.ellipse(bounds, outline='#275fde', width=4)
    mark.rectangle((bounds[0]-2,bounds[1]-26,bounds[0]+20,bounds[1]-4), fill='#275fde')
    mark.text((bounds[0]+4,bounds[1]-24), '1', fill='white')
    output = io.BytesIO(); annotated.save(output, format='PNG')
    return [clean.getvalue(), output.getvalue()]


async def main():
    checks = []
    try:
        s = selected('怎么保养？')
        first = await checked_propose(s, fixture('eye'))
        p = first['plan']
        checks.append({'case': 'eye_selection_without_brand', 'pass':
            p['selectionObservations'][0]['area']=='eye' and p['careGuide'] is not None and
            RECORDS[p['careGuide']['productId']]['category_id']=='eye' and not p['operations'], 'result': first})
        reply = ' '.join([p['shortMessage'], p['question'], p['careGuide']['whyHere'], p['careGuide']['howToUse']]).strip()[:400]
        s = selected('这款眼霜怎么用？', [{'userText': '怎么保养？', 'reply': reply,
            'productIds': [p['careGuide']['productId']] if p['careGuide'] else []}])
        s.productContextIds = [p['careGuide']['productId']] if p['careGuide'] else []
        follow = await checked_propose(s, fixture('eye'))
        checks.append({'case': 'eye_product_followup', 'pass': not repeats(follow['plan']['shortMessage'], [reply])
            and not follow['plan']['operations'] and not any(w in follow['plan']['shortMessage'] for w in ('未绑定','没有绑定')), 'result': follow})
        s.userText = '不要推荐产品，只告诉我日常怎么保养。'
        refused = await checked_propose(s, fixture('eye'))
        checks.append({'case': 'declined_products', 'pass': refused['plan']['careGuide'] is None
            and not refused['plan']['operations'], 'result': refused})
        blemish = await checked_propose(selected('脸颊圈出的这个像痘痘的小凸起，怎么护理？'), fixture('blemish'))
        checks.append({'case': 'cheek_bump_selection', 'pass': blemish['plan']['selectionObservations'][0]['area']=='cheek'
            and blemish['plan']['selectionObservations'][0]['concern']=='blemish' and not blemish['plan']['operations'], 'result': blemish})
    except ModelFailure as error:
        checks.append({'case': 'live_provider', 'pass': False, 'error': str(error)})
    report = {'input': 'Original 512x512 drawn synthetic face; no user portraits, camera data or model files.',
              'checks': checks, 'pass': bool(checks) and all(c['pass'] for c in checks)}
    path = Path(__file__).resolve().parents[1]/'docs/evidence/ai-care-20260930.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
