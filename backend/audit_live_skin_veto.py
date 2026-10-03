"""Frozen full-canvas per-domain attribution of observed-skin selection.

No optimizer, parameter backward, initialization change or threshold change.
Autograd is used only for the existing colour-feature contribution probe.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
import torch


def run(parent, output):
    from reconstruction_portrait_pipeline import (load_prepared, initialize_scene, make_frame,
        surface_contract, surface_contract_matches, digest, write_json)
    from reconstruction_live_face_domain import restore_recorded
    from reconstruction_live_skin_compositing import opaque_observation_mask, protected_observation_mask
    from reconstruction_live_neck_motion import joined_covariant
    from reconstruction_live_neck_appearance import point_region_contributions
    parent=Path(parent).resolve();output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False);started=time.perf_counter();torch.set_num_threads(4)
    if not torch.cuda.is_available():raise RuntimeError('GPU_required_for_actual_compositing_evidence')
    torch.cuda.reset_peak_memory_stats()
    config=json.loads((parent/'config.json').read_text());prepared=Path(config['prepared'])
    if config.get('antialiased') is not False:raise ValueError('audit_requires_actual_classic_contract')
    data=load_prepared(prepared);restore_recorded(data,parent,config)
    checkpoint=torch.load(parent/'trained-state.pt',map_location='cuda',weights_only=True)
    data['reference']=checkpoint['surfaceContract']['reference'];data['dense_manifest']=Path(config['denseSurfaces']['manifestPath'])
    shutil.copyfile(prepared/'cloth_supported_seeds.npz',output/'cloth_supported_seeds.npz')
    scene=initialize_scene(data,output)
    if checkpoint['sourceSha256']!=data['sourceHash'] or not surface_contract_matches(surface_contract(scene,data),checkpoint['surfaceContract']):
        raise ValueError('audit_source_or_surface_contract_changed')
    if 'neck_sh_editable' in checkpoint['model']:scene.register_buffer('neck_sh_editable',checkpoint['model']['neck_sh_editable'].clone())
    scene.load_state_dict(checkpoint['model'],strict=True);scene.portrait.constraint_mode='soft'
    for p in scene.parameters():p.requires_grad_(False)
    n=len(scene.portrait.role);names=[name for name,row in data['local'].items() if row['role']=='train']
    domain_names=['hair','glasses','unknown','neck_room','face_outside_opaque','union']
    support=np.zeros(n,np.int64);production_support=np.zeros(n,np.int64)
    veto={key:np.zeros(n,bool) for key in domain_names};production_veto=np.zeros(n,bool)
    max_ratio={key:np.zeros(n) for key in domain_names};first={key:np.full(n,-1,np.int64) for key in domain_names}
    arrays=[];view_rows=[]
    with torch.no_grad():
        for index,name in enumerate(names):
            f=make_frame(data,name,crop=False);m0=opaque_observation_mask(f['masks']);has_world=f['C'] is not None
            local=scene.render(f,'T1' if has_world else 'T0');full=scene.render(f,'T2') if has_world else local
            attenuation=(local['q'][...,1]-full['q'][...,1]).abs().cpu().numpy()>2e-5
            m=m0&~attenuation;labels={k:v.cpu().numpy() for k,v in f['masks'].items()}
            face=labels['face_core']|labels['face_boundary']
            domains=dict(hair=labels['hair_visible'],glasses=labels['glasses_visible'],
                unknown=labels['unknown_or_occluded'],
                neck_room=(labels['neck_cloth_visible']|labels['observed_room'])&~face,
                face_outside_opaque=labels['training_face']&~m,
                union=protected_observation_mask(labels,m))
            expected=domains['hair']|domains['glasses']|domains['unknown']|domains['neck_room']|domains['face_outside_opaque']
            if not np.array_equal(expected,domains['union']):raise ValueError('audit_union_does_not_match_actual_code')
            state=scene.portrait_state(f)
            if has_world:
                state=joined_covariant(state.to_world(f['C'],f['F'],scene.scale),scene.environment_state(f));cf=f;scale=scene.scale
            else:cf={**f,'C':f['F']};scale=1.
            q_by_domain={}
            for key,domain in domains.items():
                values=point_region_contributions(state,cf,m,domain,unit_scale=scale)[:n].cpu().numpy()
                q_by_domain[key]=values
                hit=(values[:,1]>.01*values[:,2])&(values[:,1]>.05)
                first[key][hit&~veto[key]]=index;veto[key]|=hit
                max_ratio[key]=np.maximum(max_ratio[key],values[:,1]/np.maximum(values[:,2],1e-12))
            q=q_by_domain['union'];qualify=(q[:,0]>=.25)&(q[:,0]>=.9*q[:,2]);support+=qualify
            used=m0.sum()>=256 and m.sum()>=256
            if used:
                production_support+=qualify;production_veto|=(q[:,1]>.01*q[:,2])&(q[:,1]>.05)
            values=np.stack([q_by_domain[key][:,1] for key in domain_names],1)
            arrays.append(dict(positive=q[:,0],all_visible=q[:,2],protected=values))
            row=dict(imageName=name,worldObservation=has_world,opaqueOriginalPixels=int(m0.sum()),
                opaqueAfterAttenuationPixels=int(m.sum()),originalStageWouldUse=bool(used),
                qualifyingPoints=int(qualify.sum()),protectedPixels={k:int(v.sum()) for k,v in domains.items()},
                perDomainVetoPointCount={k:int(((q_by_domain[k][:,1]>.01*q_by_domain[k][:,2])&(q_by_domain[k][:,1]>.05)).sum()) for k in domain_names})
            view_rows.append(row);print(json.dumps(dict(view=index+1,total=len(names),imageName=name)),flush=True)
    role=scene.portrait.role.cpu().numpy();not_neck=np.ones(n,bool)
    if hasattr(scene,'neck_sh_editable'):not_neck&=~scene.neck_sh_editable.cpu().numpy()
    high=(production_support>=3)&(role==0)&not_neck
    production_selected=high&~production_veto
    rows={}
    for key in domain_names[:-1]:
        other=np.logical_or.reduce([veto[k] for k in domain_names[:-1] if k!=key])
        rows[key]=dict(vetoHighSupport=int((high&veto[key]).sum()),
            individuallyUniqueVeto=int((high&veto[key]&~other).sum()),
            firstVetoImageCounts={name:int((high&veto[key]&(first[key]==i)).sum()) for i,name in enumerate(names) if (high&veto[key]&(first[key]==i)).any()},
            maxProtectedFractionQuantiles=np.quantile(max_ratio[key][high],[.1,.5,.9,.99]).tolist() if high.any() else [])
    by_source=[]
    for point in np.flatnonzero(high):
        by_source.append(dict(point=int(point),origin=int(scene.portrait.origin_index[point]),
            supportViews=int(production_support[point]),reasons=[key for key in domain_names[:-1] if veto[key][point]],
            unionVeto=bool(production_veto[point])))
    old=json.loads((parent/'skin-compositing-training.json').read_text())
    if old['selectedCount']!=int(production_selected.sum()):raise ValueError('frozen_replay_does_not_reproduce_recorded_selection')
    for key,value in scene.state_dict().items():
        if not torch.equal(value,checkpoint['model'][key]):raise AssertionError('audit_changed_model:'+key)
    np.savez_compressed(output/'point-contributions.npz',image_names=np.asarray(names),domain_names=np.asarray(domain_names),
        positive=np.stack([a['positive'] for a in arrays]),all_visible=np.stack([a['all_visible'] for a in arrays]),
        protected=np.stack([a['protected'] for a in arrays]),support=production_support,high_support=high,
        source_hash=np.asarray(data['sourceHash']))
    torch.cuda.synchronize()
    result=dict(parent=str(parent),sourceSha256=data['sourceHash'],parentCheckpointSha256=digest(parent/'trained-state.pt'),
        parentAssetSha256=digest(parent/'portrait.gaussian.ply'),scriptSha256=digest(Path(__file__)),
        views=len(names),fullSceneViews=sum(row['worldObservation'] for row in view_rows),
        originalSkippedViews=[row['imageName'] for row in view_rows if not row['originalStageWouldUse']],
        pointCount=n,highSupportSkinCount=int(high.sum()),recordedSelectedCount=old['selectedCount'],
        reproducedSelectedCount=int(production_selected.sum()),perDomain=rows,
        mixedDomainOnlyVeto=int((high&production_veto&~np.logical_or.reduce([veto[k] for k in domain_names[:-1]])).sum()),
        viewRecords=view_rows,points=by_source,modelBitwiseUnchanged=True,optimizerCreated=False,trainingSteps=0,
        overlapWarning='protection domains overlap; their counts must not be summed as disjoint causes',
        seconds=time.perf_counter()-started,allocatedPeakMiB=torch.cuda.max_memory_allocated()/2**20,
        reservedPeakMiB=torch.cuda.max_memory_reserved()/2**20)
    write_json(output/'report.json',result)
    print(json.dumps({k:result[k] for k in ('views','highSupportSkinCount','reproducedSelectedCount','perDomain','mixedDomainOnlyVeto','seconds')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent');p.add_argument('output');run(**vars(p.parse_args()))
