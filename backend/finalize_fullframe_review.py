"""Offline review and byte-exact full-state rollback. Keeps failed candidates."""
from pathlib import Path
import argparse,json,shutil,hashlib
import torch,numpy as np
from reconstruction_components_v3 import save_json,sha

def run(root,occlusion,evaluation):
    metrics=json.loads((evaluation/'patch-metrics.json').read_text());r0=metrics['R0'];r2=metrics['R2'];bad=[]
    for name,row in r2.items():
        if row['use']=='train' or row['pixels']<50:continue
        old=r0[name]
        if row['patchL1']>old['patchL1']+.002 or row['patchL1']>old['patchL1']*1.05+.0001 or row['patchEdge']>old['patchEdge']*1.03:
            bad.append({'name':name,'before':old,'after':row})
    assert bad,'this review command is specifically for the recorded rejected candidate'
    target=root/'R2/review-rollback.pt'
    if target.exists():raise FileExistsError(target)
    shutil.copyfile(root/'R2/initial.pt',target);assert sha(target)==sha(root/'R2/initial.pt')
    ck=torch.load(target,map_location='cpu',weights_only=False);candidate=torch.load(root/'R2/candidate-final.pt',map_location='cpu',weights_only=False)
    retired=torch.tensor(candidate['extra']['mutation']['retiredUIDs']);assert torch.isin(retired,ck['model']['portrait.stable_uid']).all()
    # Copying the complete snapshot restores Adam bindings/RNG/sampling state,
    # not only positions. Original candidate checkpoint/asset remain separate.
    initial=occlusion/'initial.pt';source=root.parent/'fullframe-surface-patch-20260929-a/R0-frozen.pt';shutil.copyfile(source,initial)
    restored=occlusion/'review-rollback.pt';shutil.copyfile(initial,restored)
    assert sha(restored)==sha(source)
    decision={'R2':{'accepted':False,'failedLocalViews':bad,'visual':'no clear recovered source texture; some cheek regions acquire incorrect gradients; no multi-view detail acceptance',
        'rollback':str(target),'rollbackSha256':sha(target),'byteExactInitialState':True,'retiredParentsRestored':len(retired),'failedCandidateRetained':True},
        'O1':{'accepted':False,'reason':'face visibility improves but room hole ratio grows by 16.14 to 53.16 percentage points across five development views',
        'rollback':str(restored),'rollbackSha256':sha(restored),'byteExactR0State':True,'failedCandidateRetained':True},
        'productionChanged':False,'published':False,'newT3T4':False}
    save_json(root/'review-decision.json',decision);print(json.dumps({'R2RejectedViews':len(bad),'R2FullStateRollback':True,'O1FullStateRollback':True}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('occlusion',type=Path);p.add_argument('evaluation',type=Path);a=p.parse_args();run(a.run,a.occlusion,a.evaluation)
