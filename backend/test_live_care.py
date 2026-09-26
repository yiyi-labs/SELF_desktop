"""Paid vision/tool probe with a synthetic face drawing, never a personal image."""
import asyncio
import io
import json
import time
from pathlib import Path
from PIL import Image, ImageDraw
from deepseek_client import propose, ModelFailure
from test_contracts import snapshot


async def main():
    root = Path(__file__).resolve().parents[1]
    image = Image.new('RGB', (320, 320), '#e4e0dc')
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 35, 250, 280), fill='#bc8d75')
    draw.ellipse((125, 105, 145, 115), fill='#342f31')
    draw.ellipse((180, 105, 200, 115), fill='#342f31')
    draw.ellipse((153, 177, 163, 187), fill='#b26060')
    data = io.BytesIO();image.save(data, format='PNG')
    reports = []
    for label, utterance in [('acne', '我圈了这颗痘痘，想知道怎么温和养护。'),
                             ('care', '刚圈选的这块脸颊怎么养护？希望看看可观察的变化。')]:
        s = snapshot()
        s.requestId = f'care-{label}-{int(time.time())}'
        s.snapshotId = s.requestId
        s.userText = utterance
        s.careAdviceRequested = True
        s.regions = [s.regions[0].model_copy(update={'regionId':'selected-face','semantic':'manual',
            'description':'用户手工圈出的面部区域'})]
        s.annotatedRegionId = 'selected-face'
        s.layers = []
        try:
            plan = (await propose(s, [data.getvalue()]))['plan']
            guide = plan.get('careGuide')
            allowed = ('CN029',) if label == 'acne' else ('CN001', 'CN005')
            passed = bool(guide and guide['productId'] in allowed
                          and plan['decision'] != 'edit' and not plan['operations'])
            reports.append({'case':label,'status':'passed' if passed else 'failed',
                'decision':plan['decision'],'productId':guide['productId'] if guide else None,
                'message':plan['shortMessage']})
        except ModelFailure as error:
            reports.append({'case':label,'status':'failed','error':str(error)})
    output=root/'artifacts/live-care-20260926.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    print(json.dumps(reports,ensure_ascii=False))
    try:
        output.write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    except PermissionError:
        # Some restricted Python hosts cannot write even inside the workspace.
        # The caller can capture the already printed, nonpersonal summary.
        pass
    return 0 if all(item['status']=='passed' for item in reports) else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
