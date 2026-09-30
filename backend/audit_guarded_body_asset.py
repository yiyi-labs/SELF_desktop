"""Derive exact original context/asset identities from a rejected body trial.
No training. Restored-trial-initial is distinguished from original topology.
"""
import argparse,json,shutil
from pathlib import Path
import numpy as np,torch
from reconstruction_evidence_stage import load_stage
from audit_portrait_priority_handoff import restore_tensors
from reconstruction_components_v3 import save_json,sha,exact_state_hash
from reconstruction_research_state import save_checkpoint,FrameSampler,restore_rng
from audit_dense_surface_asset import run as asset_audit


def run(folder,out):
    folder=Path(folder);out=Path(out);spec=folder/'spec.json';data,plan,base,contract=load_stage(spec,out)
    shutil.copyfile(__file__,out/Path(__file__).name);before=exact_state_hash(base)
    final=torch.load(folder/'candidate-final.pt',map_location='cuda',weights_only=False);initial=torch.load(folder/'initial.pt',map_location='cuda',weights_only=False)
    context={k.removeprefix('baseline.'):v for k,v in final['model'].items() if k.startswith('baseline.')};rest={k.removeprefix('baseline.'):v for k,v in initial['model'].items() if k.startswith('baseline.')}
    if context.keys()!=base.state_dict().keys() or any(not torch.equal(v,base.state_dict()[k]) or not torch.equal(v,rest[k]) for k,v in context.items()):raise ValueError('original_context_changed')
    restore_tensors(base,context);restore_rng(initial['rng']);sampler=FrameSampler(initial['samplers']['body']['names'],0);sampler.load_state_dict(initial['samplers']['body'])
    save_checkpoint(out/'restored-original.pt',base,{}, {'body':sampler},stage='derived_original_context_rollback',step=0,contract=contract,strategy={'topology':'original_R0','events':[]},extra=dict(roomMetadata=base.room.metadata,bodySources=base.body_sources,sourceTrialHash=sha(folder/'candidate-final.pt'),sourceCheckpoint=contract['spec']['checkpoint'],sourceOptimizer='not_resumed; unchanged R0 file retained'))
    ref=data['reference'];chosen=dict(np.load(folder/'decision-body.npz'));original=base.body_state(ref)
    for key in original.__dataclass_fields__:
        if not np.array_equal(chosen[key],getattr(original,key).cpu().numpy()):raise ValueError('decision_body_not_original:'+key)
    if exact_state_hash(base)!=before:raise ValueError('restored_original_hash_changed')
    adapter=out/'asset-contract';adapter.mkdir();shutil.copyfile(folder/'candidate-research-only.ply',adapter/'candidate-research-only.ply');shutil.copyfile(spec,adapter/'spec.json')
    # These integers are exact inherited identities, not nearest-neighbour joins.
    ck=final['model'];keep=ck['keep_body'].cpu().numpy();head=ck['baseline.portrait.stable_uid'].cpu().numpy();body=np.flatnonzero(keep);room=base.room.metadata['point_uid'].cpu().numpy();new=ck['patch.source_ids'].cpu().numpy()
    uid=np.r_[head,room,body,new];namespace=np.r_[np.zeros(len(head),np.int64),np.ones(len(room),np.int64),np.full(len(body),2,np.int64),np.full(len(new),3,np.int64)]
    fine=ck['baseline.component_origin'][ck['baseline.portrait.origin_index']].cpu().numpy();parts=np.ones(len(head),np.int64);parts[fine==1]=2;parts[fine==2]=3;parts[fine==3]=4;parts=np.r_[parts,np.zeros(len(room),np.int64),np.full(len(body)+len(new),4,np.int64)]
    assetHash=sha(adapter/'candidate-research-only.ply');np.savez_compressed(adapter/'candidate-identities.npz',point_id=np.arange(len(uid)),source_uid=uid,source_namespace=namespace,component=parts,asset_sha256=np.array(assetHash))
    save_json(adapter/'result.json',dict(reference=ref,sourceHash=data['sourceHash'],originalTrialHash=sha(folder/'result.json'),assetRole='unaccepted_clothing_motion_research',published=False));asset_audit(adapter,out/'draw')
    save_json(out/'result.json',dict(originalContextExact=True,decisionBodyExact=True,fieldCount=len(context),originalStateHash=before,sourceCheckpointHash=contract['checkpointHash'],sourceTrialHash=sha(folder/'candidate-final.pt'),assetHash=assetHash,reference=ref,sourceHash=data['sourceHash'],originalOptimizer='not_resumed; source immutable',trialInitializationIsNotOriginalTopology=True,published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.folder,a.out)
