"""Explicit paid evidence test. Original color fixture only, no personal imagery."""
import asyncio
import sys
import io
import json
import httpx
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image
from deepseek_client import propose,ModelFailure
from test_contracts import snapshot

class EvidenceTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport=httpx.AsyncHTTPTransport();self.evidence={}
    async def handle_async_request(self,request):
        response=await self.transport.handle_async_request(request)
        data=await response.aread()
        if response.status_code==200:
            raw=json.loads(data);self.evidence={'model':raw.get('model'),'choices':raw.get('choices'),'usage':raw.get('usage')}
        return response
    async def aclose(self):
        await self.transport.aclose()

async def main():
    effect='--effect' in sys.argv
    followup='--followup' in sys.argv
    s=snapshot();s.requestId='cn-product-'+str(int(datetime.now().timestamp()));s.snapshotId=s.requestId
    s.userText='请介绍 OLAY 水光小白瓶50ml 的已核实资料，说明配方、浓度和真实上脸效果是否有证据。请引用提供的资料，不要提出编辑。'
    if effect:s.userText='请根据 OLAY 水光小白瓶50ml 的真实产品参数，修改我圈出的地方，不要只是通用染色。'
    if followup:s.userText='那就试一下这款';s.productContextIds=['olay-cn-waterglow-50ml']
    out=io.BytesIO();Image.new('RGB',(32,32),(210,203,220)).save(out,format='PNG')
    evidence={'testedAt':datetime.now(timezone.utc).isoformat(),'input':'original nonpersonal 32x32 color fixture','test':'mainland information does not become a calibrated edit'}
    transport=EvidenceTransport()
    try:
        result=await propose(s,[out.getvalue()],transport=transport);plan=result['plan']
        evidence['result']=result
        evidence['pass']=plan['decision'] in (['explain','clarify'] if effect or followup else ['explain']) and not plan['operations'] and 'olay-cn-waterglow-50ml' in plan['explanationRefs']
    except ModelFailure as e:
        evidence.update({'pass':False,'error':str(e),'syntheticProbeResponseOnly':transport.evidence})
    path=Path(__file__).resolve().parents[1]/('docs/evidence/overhaul/live-product-effect.json' if effect else 'docs/evidence/overhaul/live-product.json')
    if followup:path=path.with_name('live-product-followup.json')
    evidence['userText']=s.userText
    if path.exists():path.with_name('live-product-attempt-'+str(int(datetime.now().timestamp()))+'.json').write_bytes(path.read_bytes())
    path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=True,indent=2))
    return 0 if evidence['pass'] else 2

if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
