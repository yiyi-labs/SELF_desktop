"""Frozen complete-pool replay: distinguish quota holes from support holes."""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch
from reconstruction_evidence_stage import load_stage
from reconstruction_components_v3 import exact_state_hash,save_json,sha
from reconstruction_continuity_surface import physical_masks
from run_observed_room_recovery import ObservedRoomStage,evaluate


def run(stage,pool,out):
    start=time.perf_counter();out=Path(out);data,plan,base,contract=load_stage(stage,out)
    a=dict(np.load(pool))
    if str(a['source_hash'])!=data['sourceHash']:raise ValueError('pool_source_changed')
    frozen=exact_state_hash(base);model=ObservedRoomStage(base,a)
    for p in model.parameters():p.requires_grad_(False)
    names=list(dict.fromkeys([data['reference']]+[n for n in plan['development'] if n in data['worlds']]))
    masks=physical_masks(contract['spec']['prepared'],data,names);torch.cuda.reset_peak_memory_stats()
    rows=evaluate(model,data,names,masks,out/'full-pool-images')
    if exact_state_hash(base)!=frozen:raise ValueError('base_changed')
    shutil.copyfile(__file__,out/Path(__file__).name)
    save_json(out/'result.json',dict(sourceHash=data['sourceHash'],poolHash=sha(pool),poolPoints=len(a['means']),
        metrics=rows,trainingSteps=0,optimizerCreated=False,parameterChanges=False,
        seconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
        limitation='All existing accepted predicted-depth hypotheses, not all true observed room geometry. Same initial point values, no global scale/opacity change.',published=False))
    print('FULL_POOL_FROZEN_REPLAY_COMPLETE',len(a['means']),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('stage','pool','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.stage,a.pool,a.out)
