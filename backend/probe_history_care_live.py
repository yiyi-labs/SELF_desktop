"""Real DeepSeek image+tool probe with an original, nonpersonal drawing."""
import asyncio
import io
import json
import time
from pathlib import Path

from PIL import Image, ImageDraw
from contracts import Region
from deepseek_client import ModelFailure, propose
from probe_multi_region_live import ProbeTransport
from test_contracts import snapshot


async def main() -> int:
    image = Image.new('RGB', (512, 512), (20, 31, 53))
    draw = ImageDraw.Draw(image)
    draw.ellipse((160, 70, 360, 410), fill=(203, 163, 137))
    draw.ellipse((178, 192, 257, 275), outline=(192, 225, 252), width=5)
    draw.text((205, 220), '1', fill='white')
    data = io.BytesIO(); image.save(data, format='PNG')
    s = snapshot(); s.requestId='care-'+str(int(time.time())); s.snapshotId=s.requestId
    s.userText='脸颊做通用数字试色：柔玫瑰，轻一点。顺便给 OLAY 日常护理建议，不说产品会产生这个颜色。'
    s.regions=[Region(regionId='gs-selected-1',description='数字1是用户手工圈出的脸颊区域',semantic='manual')]
    s.layers=[]; s.annotatedRegionId='gs-selected-1'; s.annotatedRegionIds=['gs-selected-1']
    s.careAdviceRequested=True
    transport=ProbeTransport()
    evidence={'image':'original nonpersonal drawing','sentPersonalPixels':False,'passed':False}
    try:
        result=await propose(s,[data.getvalue(),data.getvalue()],transport=transport)
        plan=result['plan'];guide=plan.get('careGuide')
        evidence.update({'decision':plan['decision'],'operationCount':len(plan['operations']),
                         'careProductId':guide['productId'] if guide else None,
                         'careWhy':guide['whyHere'] if guide else None,
                         'careHow':guide['howToUse'] if guide else None,
                         'model':result['modelEvidence']['returnedModel'],
                         'passed':plan['decision']=='edit' and len(plan['operations'])==1 and
                                  plan['operations'][0]['regionId']=='gs-selected-1' and
                                  guide is not None and guide['productId'] in {'CN001','CN005'}})
    except ModelFailure as error:
        evidence['error']=str(error)
        if transport.raw:
            choice=(transport.raw.get('choices') or [{}])[0]
            evidence['finishReason']=choice.get('finish_reason')
            calls=choice.get('message',{}).get('tool_calls') or []
            evidence['toolCount']=len(calls)
            if calls:
                evidence['toolArguments']=calls[0].get('function',{}).get('arguments','')[:4000]
    path=Path(__file__).resolve().parents[1]/'artifacts/history-care-live.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:value for key,value in evidence.items() if key!='toolArguments'},ensure_ascii=False))
    return 0 if evidence['passed'] else 2


if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
