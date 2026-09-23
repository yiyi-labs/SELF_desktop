"""Opt-in real model validation with the public licensed sample only."""
import asyncio,json,time,sys,re
from pathlib import Path
from deepseek_client import propose
from test_contracts import snapshot
async def main():
    root=Path(__file__).resolve().parents[1]
    image=(root/'docs/evidence/overhaul/tablet-release-native/native-face.png').read_bytes()
    s=snapshot();s.responseLanguage='en';s.userText='I want to keep this mole. I just want to talk, no edits.'
    s.requestId='english-'+str(int(time.time()));s.snapshotId=s.requestId
    result=await propose(s,[image]);p=result['plan']
    passed=not p['operations'] and not p['explanationRefs'] and not re.search('[\u4e00-\u9fff]',p['shortMessage']+p['question'])
    path=root/'docs/evidence/camera-fullscreen/live-english.json'
    path.write_text(json.dumps({'source':'Public CC BY 3 sample scan; synthetic message, no private images','passed':passed,'result':result},ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'passed':passed,'reply':p['shortMessage'],'question':p['question']},ensure_ascii=False))
    return 0 if passed else 1
if __name__=='__main__':sys.exit(asyncio.run(main()))
