"""Opt-in real DeepSeek vision/tool probe with two original nonpersonal circles."""
import asyncio
import io
import json
import time
import httpx
from pathlib import Path
from PIL import Image, ImageDraw
from deepseek_client import propose, ModelFailure
from contracts import Region
from test_contracts import snapshot

class ProbeTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport=httpx.AsyncHTTPTransport()
        self.raw={}
    async def handle_async_request(self,request):
        response=await self.transport.handle_async_request(request)
        data=await response.aread()
        if response.status_code==200:
            self.raw=json.loads(data)
        return httpx.Response(response.status_code,headers=response.headers,content=data,request=request)
    async def aclose(self):
        await self.transport.aclose()

async def main() -> int:
    image = Image.new('RGB',(640,480),(18,25,39))
    draw = ImageDraw.Draw(image)
    draw.ellipse((110,140,240,270),outline=(178,218,250),width=5)
    draw.ellipse((390,140,520,270),outline=(218,187,243),width=5)
    draw.text((165,190),'1',fill='white')
    draw.text((445,190),'2',fill='white')
    data=io.BytesIO();image.save(data,format='PNG')
    s=snapshot();s.requestId='multi-'+str(int(time.time()));s.snapshotId=s.requestId
    s.userText='对两个已经圈出的地方一起做通用数字试色：第一处柔玫瑰、第二处暖陶棕，都要轻一点。两处各提一个操作。'
    s.regions=[Region(regionId='gs-selected-1',description='图中数字1手工圈选',semantic='manual'),
               Region(regionId='gs-selected-2',description='图中数字2手工圈选',semantic='manual')]
    s.layers=[];s.annotatedRegionId='';s.annotatedRegionIds=['gs-selected-1','gs-selected-2']
    evidence={'input':'original nonpersonal two-circle fixture','sentPersonalPixels':False,'passed':False}
    transport=ProbeTransport()
    try:
        result=await propose(s,[data.getvalue(),data.getvalue()],transport=transport)
        plan=result['plan'];mapping={op['regionId']:op['presetId'] for op in plan['operations']}
        evidence.update({'decision':plan['decision'],'operationCount':len(plan['operations']),
                         'regionPresets':mapping,'returnedModel':result['modelEvidence']['returnedModel'],
                         'passed':plan['decision']=='edit' and mapping=={'gs-selected-1':'rose','gs-selected-2':'terracotta'}})
    except ModelFailure as error:
        evidence['error']=str(error)
        if transport.raw:
            choice=(transport.raw.get('choices') or [{}])[0]
            evidence['finishReason']=choice.get('finish_reason')
            calls=choice.get('message',{}).get('tool_calls') or []
            evidence['toolCount']=len(calls)
            if calls:
                evidence['toolArguments']=calls[0].get('function',{}).get('arguments','')[:4000]
    path=Path(__file__).resolve().parents[1]/'artifacts/multi-region-live.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except PermissionError:
        evidence['evidenceFile']='write_denied_by_local_filesystem'
    print(json.dumps(evidence,ensure_ascii=True))
    return 0 if evidence['passed'] else 2

if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
