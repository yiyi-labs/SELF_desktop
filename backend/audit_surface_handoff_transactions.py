"""Individual finite room transactions, TRAIN-only selection, zero updates.
Reject before recovery if complete content cannot be transferred.
"""
from pathlib import Path
import argparse,json,shutil
import numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_components_v3 import save_json,exact_state_hash
from reconstruction_continuity_surface import physical_masks
from reconstruction_portrait_pipeline import make_frame
from run_surface_handoff_repair import RoomHandoffStage
from run_continuous_surface_repair import evaluate_complete,regression_screen
from reconstruction_dense_contract import project
from reconstruction_ray_surface import sample_mask

def run(complete,source,attribution,out):
    out=Path(out);data,plan,base,contract=load_complete(complete,out);original=exact_state_hash(base)
    source=Path(source);pool=dict(np.load(source/'replacement.npz'));retired=pool.pop('retired');pool.pop('source_hash')
    names=json.loads((Path(attribution)/'result.json').read_text())['trainOnlyNames']
    if set(names)-set(plan['train']):raise ValueError('nontraining_selection')
    evidence=[dict(np.load(Path(attribution)/(n+'.npz'))) for n in names]
    masks=physical_masks(contract['spec']['prepared'],data,names)
    old,before=evaluate_complete(base,data,names,masks,out/'baseline-images')
    f=base.baseline.adjusted_frame(make_frame(data,contract['reference'],crop=False));rows=[]
    for parent in retired:
        votes=np.zeros(len(pool['means']),np.int16)
        for e in evidence:
            i=np.flatnonzero(e['gaussian_ids']==parent)
            if len(i)!=1:continue
            uv,z=project(pool['means'],e['K'],e['C']);d=uv-e['means2d'][i[0]];a,b,c=e['conics'][i[0]]
            power=a*d[:,0]**2+2*b*d[:,0]*d[:,1]+c*d[:,1]**2
            votes+=((z>0)&(power<9)&sample_mask(e['room'],uv)).astype(np.int16)
        ids=np.flatnonzero(votes>=2);arr={k:v[ids] for k,v in pool.items()}
        folder=out/('parent-'+str(parent));folder.mkdir()
        model=RoomHandoffStage(base,f,np.array([parent]),arr,False)
        _,after=evaluate_complete(model,data,names,masks,folder/'images',old)
        fail=regression_screen(before,after)
        delta={part:float(np.mean([after[n][part]['rgb']-before[n][part]['rgb'] for n in names])) for part in ('face','hair','neck','cloth','room')}
        row=dict(parent=int(parent),newPoints=len(ids),trainingRGBDelta=delta,failures=fail,trainingScreenPassed=not fail,
            updates=0,releaseQualityPassed=False,published=False)
        save_json(folder/'result.json',row);rows.append(row);print(json.dumps(row),flush=True)
        del model;torch.cuda.empty_cache()
    if original!=exact_state_hash(base):raise ValueError('immutable_baseline_changed')
    save_json(out/'result.json',dict(proposals=rows,selectionUsesTrainingOnly=True,names=names,sourceHash=data['sourceHash'],
        noOptimizer=True,baselineExact=True,trainingSteps=0,published=False,releaseQualityPassed=False))
    shutil.copyfile(__file__,out/Path(__file__).name)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('complete','source','attribution','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.complete,a.source,a.attribution,a.out)