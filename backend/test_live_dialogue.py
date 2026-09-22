"""Explicit paid two-turn test using a public licensed scan, never the host camera."""
import asyncio,json,sys,time
from pathlib import Path
from contracts import Snapshot,DialogueTurn
from deepseek_client import propose,ModelFailure
from test_contracts import snapshot

async def main():
    root=Path(__file__).resolve().parents[1]
    folder=root/'docs/evidence/interaction-camera';folder.mkdir(exist_ok=True,parents=True)
    image=(root/'docs/evidence/overhaul/tablet-release-native/native-face.png').read_bytes()
    s=snapshot();s.requestId='dialogue-'+str(int(time.time()));s.snapshotId=s.requestId
    s.layers=[];s.regions=[s.regions[0].model_copy(update={'regionId':'selected-cheek','semantic':'manual','description':'用户当前手工圈定的范围'})];s.annotatedRegionId='selected-cheek'
    s.userText='我想在刚圈选的这里试一点通用数字颜色，淡淡的就好。有哪些颜色可以选？只问颜色就好。'
    results=[]
    try:
        first=await propose(s,[image]);p=first['plan'];results.append(first)
        assert p['decision']=='clarify' and len(p['choices'])>=2 and not p['operations'], 'Expected one color question with choices'
        s.dialogue=[DialogueTurn(userText=s.userText,reply=p['question'] or p['shortMessage'],choices=p['choices'])]
        s.userText='1';s.resolvedChoice=p['choices'][0];s.requestId+='-next';s.snapshotId=s.requestId
        second=await propose(s,[image]);p2=second['plan'];results.append(second)
        assert p2['decision']=='edit' and len(p2['operations'])==1,'Numeric selection did not resolve'
        assert p2['operations'][0]['regionId']=='selected-cheek','Selected region changed'
        assert p2['operations'][0]['intensityLevel']=='light','Prior requested strength lost'
        assert not p2['explanationRefs'],'Unsolicited product placement'
        assert all(not any(key in x['plan']['shortMessage']+x['plan']['question'] for key in ['rose','terracotta','regionId']) for x in results)
        status='passed';error=''
    except (ModelFailure,AssertionError) as e:status='failed';error=str(e)
    (folder/'live-dialogue.json').write_text(json.dumps({'status':status,'error':error,'source':'Public CC-BY-3 scan; no webcam media uploaded. Two real HTTPS vision/tool calls.','calls':results},ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'status':status,'error':error,'calls':len(results)},ensure_ascii=False))
    return 0 if status=='passed' else 1
if __name__=='__main__':sys.exit(asyncio.run(main()))
