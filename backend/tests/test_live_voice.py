"""Explicit paid voice/tone checks. Public sample image; no personal inputs or webcam frames."""
import asyncio,json,sys,time
from pathlib import Path
from deepseek_client import propose,ModelFailure
from test_contracts import snapshot

async def main():
    root=Path(__file__).resolve().parents[2]
    image=(root/'docs/evidence/overhaul/tablet-release-native/native-face.png').read_bytes()
    results=[]
    cases=[('nose-concern','我不太喜欢自己的鼻子，看起来很奇怪，但也不想被改成别人的样子。'),
           ('keep-mole','这颗痣我想留着，只想聊聊，不用修改。')]
    for name,text in cases:
        s=snapshot();s.requestId='voice-'+name+'-'+str(int(time.time()));s.snapshotId=s.requestId;s.userText=text;s.layers=[]
        s.regions=[s.regions[0].model_copy(update={'regionId':'selected-region','semantic':'manual','description':'用户当前圈选范围；部位以用户本次表达为准'})];s.annotatedRegionId='selected-region'
        try:
            result=await propose(s,[image]);p=result['plan']
            passed=not p['operations'] and not p['explanationRefs'] and p['decision']!='edit' and len(p['shortMessage'])<=120
            results.append({'case':name,'input':text,'status':'passed' if passed else 'failed','result':result})
        except ModelFailure as e:results.append({'case':name,'status':'failed','reason':str(e)})
    path=root/'docs/evidence/interaction-camera/live-voice.json';path.write_text(json.dumps({'source':'Public CC-BY-3 sample, original nonpersonal test utterances. Tone requires human review; assertions cover no edits/products and concise reply.','cases':results},ensure_ascii=False,indent=2),'utf-8')
    for r in results:print(json.dumps({'case':r['case'],'status':r['status'],'reply':r.get('result',{}).get('plan',{}).get('shortMessage'),'question':r.get('result',{}).get('plan',{}).get('question')},ensure_ascii=False))
    return 0 if all(r['status']=='passed' for r in results) else 1
if __name__=='__main__':sys.exit(asyncio.run(main()))
