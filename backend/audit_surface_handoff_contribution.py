"""Exact alpha*T attribution of frozen full-scene room kernels, train-only.
Not deletion permission. Original source snapshots/assets remain unchanged.
"""
from pathlib import Path
import argparse,json,shutil
import numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_portrait_pipeline import make_frame
from reconstruction_continuity_surface import physical_masks
from reconstruction_surface_patch import weights
from reconstruction_components_v3 import save_json

def run(complete,out):
    out=Path(out);data,plan,base,contract=load_complete(complete,out)
    train=[n for n in plan['train'] if n in data['worlds']]
    names=[train[i] for i in np.unique(np.linspace(0,len(train)-1,min(8,len(train))).round().astype(int))]
    masks=physical_masks(contract['spec']['prepared'],data,names)
    score=None;per=[]
    for name in names:
        f=base.baseline.adjusted_frame(make_frame(data,name,crop=False));state=base.state(f);h,w=f['rgb'].shape[:2]
        mask=torch.tensor(masks[name]['face']|masks[name]['hair']|masks[name]['neck']|masks[name]['cloth'],device='cuda')
        v,info=weights(state,f['C'],f['K'],w,h,mask,unit_scale=base.scale)
        np.savez_compressed(out/(name+'.npz'),C=f['C'].cpu().numpy(),K=f['K'].cpu().numpy(),mask=mask.cpu().numpy(),room=masks[name]['room'],**{k:v.cpu().numpy() for k,v in info.items()})
        v/=mask.sum().clamp_min(1);v[state.parts!=0]=0
        score=v.clone() if score is None else score+v
        per.append(dict(name=name,roomContribution=float(v.sum())))
    score/=len(names);np.save(out/'room-contribution.npy',score.cpu().numpy())
    ref=base.baseline.adjusted_frame(make_frame(data,contract['reference'],crop=False));s=base.state(ref)
    order=torch.argsort(score,descending=True)[:30]
    rows=[dict(index=int(i),contribution=float(score[i]),axes=s.scales[i].cpu().tolist(),mean=s.means[i].cpu().tolist()) for i in order]
    report=dict(sourceHash=data['sourceHash'],completeCheckpointHash=contract['completeCheckpointHash'],trainOnlyNames=names,
        masks='face/hair/neck/cloth',scoreMeaning='actual sorted alpha*T normalized by observed mask',top=rows,views=per,selectionOnly=True,published=False)
    save_json(out/'result.json',report);shutil.copyfile(__file__,out/Path(__file__).name);print(json.dumps(report),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.complete,a.out)