"""Bounded observed opaque-skin compositing recovery, with fixed geometry.

Black and white backdrops are supervision tests, never exported scene content.
Only observed interior skin is expected opaque; hair, lenses and unknown edges
are not. Actual original RGB remains the target, without generated detail.
"""
from pathlib import Path
import json
import hashlib
import time
import cv2
import numpy as np
import torch


def opaque_observation_mask(labels):
    required=('training_skin','face_core','glasses_visible','hair_visible','unknown_or_occluded')
    if any(k not in labels for k in required):
        raise ValueError('opaque_skin_missing_semantics')
    cpu=lambda x:x.detach().cpu().numpy() if isinstance(x,torch.Tensor) else np.asarray(x)
    mask=cpu(labels['training_skin']).astype(bool)&cpu(labels['face_core']).astype(bool)
    mask&=~(cpu(labels['glasses_visible'])|cpu(labels['hair_visible'])|cpu(labels['unknown_or_occluded']))
    y,x=np.where(mask)
    radius=max(1,int(round((x.max()-x.min()+1)*.01))) if len(x) else 1
    return cv2.erode(mask.astype(np.uint8),np.ones((radius*2+1,radius*2+1),np.uint8)).astype(bool)


def backdrop_consistency(rgb,alpha,target,mask):
    """Same opaque observation must match on both known backdrop extremes."""
    if not mask.any():
        return rgb.sum()*0
    black=(rgb[mask]-target[mask]).abs().mean()
    white=(rgb[mask]+1-alpha[mask][:,None]-target[mask]).abs().mean()
    return .5*(black+white)


def protected_observation_mask(labels,opaque):
    cpu=lambda x:x.detach().cpu().numpy() if isinstance(x,torch.Tensor) else np.asarray(x)
    face=cpu(labels['face_core'])|cpu(labels['face_boundary'])
    protected=(cpu(labels['neck_cloth_visible'])|cpu(labels['observed_room']))&~face
    # A landmark oval never overrides actual hair, lenses or unknown evidence.
    protected|=cpu(labels['hair_visible'])|cpu(labels['glasses_visible'])|cpu(labels['unknown_or_occluded'])
    protected|=cpu(labels['training_face'])&~opaque
    return protected.astype(bool)


def preservation_decision(before,after):
    if set(before)!=set(after) or not before:
        return False,['missing_comparable_views']
    failures=[]
    for key,a in before.items():
        b=after[key]
        if not all(np.isfinite(v) for row in (a,b) for v in row.values()):
            failures.append(key+':nonfinite')
            continue
        if b['rgb']>a['rgb']+.001:
            failures.append(key+':observed_skin_rgb')
        if b['hole']>a['hole']+.005:
            failures.append(key+':observed_skin_coverage')
    return not failures,failures


def observed_update_masks(per_view,role,excluded=None):
    """Occluded in one view is not a permanent physical part classification.

    Keep the original per-observation contribution thresholds. A parameter
    needs at least three safe skin observations, and receives no update from
    views where its actual footprint contributes to protected content.
    All-view rendered preservation remains a separate mandatory exit gate.
    """
    support=torch.stack(list(per_view.values())).long().sum(0)
    allowed=(support>=3)&(role.cpu()==0)
    if excluded is not None:
        allowed&=~excluded.cpu()
    return allowed,{name:safe&allowed for name,safe in per_view.items()}


def observation_parameter_step(optimizer,parameters,allowed):
    """Inactive rows retain values/moments; Adam still uses a global step.

    This is a masked global schedule, not per-point bias-correction clocks.
    """
    saved={k:p.detach()[~allowed].clone() for k,p in parameters.items()}
    moments={}
    for key,p in parameters.items():
        if p.grad is not None:
            p.grad[~allowed]=0
        moments[key]={k:v[~allowed].clone() for k,v in optimizer.state.get(p,{}).items()
                      if isinstance(v,torch.Tensor) and v.shape==p.shape}
    torch.nn.utils.clip_grad_norm_(list(parameters.values()),10.)
    optimizer.step()
    with torch.no_grad():
        for key,p in parameters.items():
            p[~allowed]=saved[key]
            for k,v in optimizer.state.get(p,{}).items():
                if isinstance(v,torch.Tensor) and v.shape==p.shape:
                    v[~allowed]=moments[key].get(k,torch.zeros_like(v[~allowed]))


def restore_skin_compositing(scene,data,out,steps=180):
    from portrait_pipeline import make_frame,masked_mean,write_json,surface_contract,ENGINE_VERSION
    from live_neck_appearance import point_region_contributions
    from live_neck_motion import joined_covariant
    if not scene.dense_surface or not 1<=steps<=240:
        raise ValueError('skin_compositing_contract')
    out=Path(out)
    before={k:v.detach().clone() for k,v in scene.state_dict().items()}
    for p in scene.parameters():
        p.requires_grad_(False)
    parameters={'sh':scene.portrait.sh,'opacity':scene.portrait.opacity_logits}
    frozen={k:v.detach().clone() for k,v in parameters.items()}
    count=len(scene.portrait.role)
    support=torch.zeros(count,dtype=torch.long)
    veto=torch.zeros(count,dtype=torch.bool)
    masks={}
    preserved={}
    records=[]
    safe_views={}
    def quality_audit():
        rows={}
        with torch.no_grad():
            for name in data['local']:
                f=make_frame(data,name,crop=False)
                mask=torch.as_tensor(opaque_observation_mask(f['masks']),device=f['rgb'].device)
                for stage in ('T0','T2') if f['C'] is not None else ('T0',):
                    r=scene.render(f,stage)
                    regions={'opaque_skin':mask,'full_face':f['masks']['training_face'],
                        'hair':f['masks']['hair_visible'],'glasses':f['masks']['glasses_visible'],
                        'unknown':f['masks']['unknown_or_occluded']}
                    if stage=='T2':
                        regions.update(room=f['masks']['observed_room'],body=f['masks']['neck_cloth_visible'])
                    for part,domain in regions.items():
                        if int(domain.sum())<32:
                            continue
                        rows[name+':'+stage+':'+part]=dict(rgb=float((r['rgb'][domain]-f['rgb'][domain]).abs().mean()),
                            hole=float((r['alpha'][domain]<.8).float().mean()))
        return rows
    baseline_quality=quality_audit()
    with torch.no_grad():
        for name,row in data['local'].items():
            if row['role']!='train':
                continue
            f=make_frame(data,name,crop=False)
            m=opaque_observation_mask(f['masks'])
            if m.sum()<256:
                continue
            has_world=f['C'] is not None
            local=scene.render(f,'T1' if has_world else 'T0')
            full=scene.render(f,'T2') if has_world else local
            # Known forward attenuation is not repaired by making skin opaque.
            attenuated=(local['q'][...,1]-full['q'][...,1]>2e-5).cpu().numpy()
            front_count=int((m&attenuated).sum())
            m&=(local['q'][...,1]-full['q'][...,1]).abs().cpu().numpy()<=2e-5
            if m.sum()<256:
                continue
            protected=protected_observation_mask(f['masks'],m)
            state=scene.portrait_state(f)
            if has_world:
                state=joined_covariant(state.to_world(f['C'],f['F'],scene.scale),scene.environment_state(f))
                contribution_frame=f
            else:
                contribution_frame={**f,'C':f['F']}
            q=point_region_contributions(state,contribution_frame,m,protected,unit_scale=scene.scale if has_world else 1.)[:count].cpu()
            qualifies=(q[:,0]>=.25)&(q[:,0]>=.9*q[:,2])
            protected_here=(q[:,1]>.01*q[:,2])&(q[:,1]>.05)
            support+=qualifies.long()
            veto|=protected_here
            safe_views[name]=qualifies&~protected_here
            masks[name]=torch.as_tensor(m)
            preserved[name]=(torch.as_tensor(protected),full['rgb'][torch.as_tensor(protected,device=full['rgb'].device)].cpu())
            records.append(dict(imageName=name,pixels=int(m.sum()),worldObservation=has_world,
                observedSkinPixelsAttenuatedByAddedEnvironment=front_count,
                attenuationIsCurrentModelEvidenceNotMeasuredFirstSurface=True))
    if safe_views:
        allowed,view_updates=observed_update_masks(safe_views,scene.portrait.role,getattr(scene,'neck_sh_editable',None))
    else:
        allowed=torch.zeros(count,dtype=torch.bool)
        view_updates={}
    allowed=allowed.to(scene.portrait.sh.device)
    names=list(masks)
    receipt=dict(stage='skin-compositing',steps=0,selectedCount=int(allowed.sum()),views=records,
        geometryChanged=False,artificialSceneBackground=False,unknownAndAccessoriesExcluded=True,
        selectionMode='at_least_three_safe_observations_with_per_view_parameter_updates',
        previousGlobalVetoSelectedCount=int(((support>=3)&~veto&(scene.portrait.role.cpu()==0)).sum()),
        qualifiedUpdateCounts={name:int(rows.sum()) for name,rows in view_updates.items()},
        selectedIdsSha256=hashlib.sha256(torch.where(allowed)[0].cpu().numpy().tobytes()).hexdigest())
    if len(names)<3 or not allowed.any():
        receipt['status']='insufficient_observed_interior_skin'
        write_json(out/'skin-compositing-training.json',receipt)
        return receipt
    for p in parameters.values():
        p.requires_grad_(True)
    optimizer=torch.optim.Adam([{'params':[parameters['sh']],'lr':.0015}, {'params':[parameters['opacity']],'lr':.02}],eps=1e-8)
    def checkpoint(label,step,*,rolled_back=False):
        torch.save(dict(engineVersion=ENGINE_VERSION,sourceSha256=data['sourceHash'],model=scene.state_dict(),
            optimizer=None if rolled_back else optimizer.state_dict(),stage='skin-compositing',step=0 if rolled_back else step,
            attemptedSteps=step,rollbackPerformed=rolled_back,optimizerResumeSupported=not rolled_back,
            resumeKind='restored_parent_model_new_optimizer_required' if rolled_back else 'exact_skin_stage_state',surfaceContract=surface_contract(scene,data),
            rng=torch.get_rng_state(),cudaRng=torch.cuda.get_rng_state(),sampler={'names':names,'nextStep':0 if rolled_back else step},
            selection=receipt,allowedMask=allowed,perViewUpdateMasks=view_updates,topologyChanged=False),out/('skin-compositing-'+label+'.pt'))
    checkpoint('init',0)
    start=time.perf_counter()
    curve=[]
    for step in range(steps):
        name=names[step%len(names)]
        f=make_frame(data,name,crop=False)
        mask=masks[name].to(f['rgb'].device)
        optimizer.zero_grad(set_to_none=True)
        local=scene.render(f,'T1' if f['C'] is not None else 'T0')
        opaque=backdrop_consistency(local['rgb'],local['alpha'],f['rgb'],mask)
        opaque.backward()
        # Sequential native canvases avoid retaining two full-frame graphs.
        full=scene.render(f,'T2' if f['C'] is not None else 'T0')
        other,target=preserved[name]
        other=other.to(mask.device)
        rgb=masked_mean((full['rgb']-f['rgb']).abs().mean(-1),mask)
        preservation=(full['rgb'][other]-target.to(mask.device)).abs().mean() if other.any() else rgb*0
        loss=rgb+2*preservation+.001*(parameters['sh'][allowed,1:]-frozen['sh'][allowed,1:]).square().mean()
        if not torch.isfinite(loss):
            raise ValueError('skin_compositing_nonfinite')
        loss.backward()
        active=view_updates[name].to(allowed.device)
        observation_parameter_step(optimizer,parameters,active)
        with torch.no_grad():
            parameters['opacity'][active]=parameters['opacity'][active].clamp(frozen['opacity'][active]-2,frozen['opacity'][active]+3)
        if step%30==0 or step+1==steps:
            row=dict(stage='skin-compositing',step=step+1,frame=name,rgb=float(rgb.detach()),backdropConsistency=float(opaque.detach()),protected=float(preservation.detach()))
            curve.append(row)
            print(json.dumps(row),flush=True)
        if step+1==steps//2:
            checkpoint('mid',step+1)
    for k,v in scene.state_dict().items():
        if k in ('portrait.sh','portrait.opacity_logits'):
            if not torch.equal(v[~allowed],before[k][~allowed]):
                raise AssertionError('skin_nonselected_changed')
        elif not torch.equal(v,before[k]):
            raise AssertionError('skin_geometry_or_other_part_changed:'+k)
    candidate_quality=quality_audit()
    accepted,failures=preservation_decision(baseline_quality,candidate_quality)
    receipt.update(steps=steps,accepted=accepted,modelChanged=accepted,rollbackPerformed=not accepted,
        baselineQuality=baseline_quality,candidateQuality=candidate_quality,regressionReasons=failures)
    checkpoint('candidate',steps)
    if not accepted:
        scene.load_state_dict(before,strict=True)
        for k,v in scene.state_dict().items():
            if not torch.equal(v,before[k]):
                raise AssertionError('skin_compositing_rollback_failed:'+k)
        optimizer.state.clear()
    checkpoint('state',steps,rolled_back=not accepted)
    torch.cuda.synchronize()
    receipt.update(steps=steps,seconds=time.perf_counter()-start,curve=curve,protectedParametersBitwiseUnchanged=True,
        status='local_numeric_preservation_passed_not_whole_quality' if accepted else 'restored_parent_after_regression',
        appearanceOnly=True,modelChanged=accepted,accepted=accepted,rollbackPerformed=not accepted,
        baselineQuality=baseline_quality,candidateQuality=candidate_quality,regressionReasons=failures,
        validationIsDevelopmentNotBlind=True,allComponentsRendered=True)
    write_json(out/'skin-compositing-training.json',receipt)
    return receipt
