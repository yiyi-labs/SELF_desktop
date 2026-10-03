"""Calibrate observed hair appearance against the frozen, complete scene.

Black-background head fitting cannot identify colour and opacity separately.
This phase never creates hair, changes its volume, or hides other components.
"""
from pathlib import Path
import time
import torch


def masked_parameter_step(optimizer, parameters, allowed, frozen):
    for name,p in parameters.items():
        if p.grad is not None:p.grad[~allowed]=0
    torch.nn.utils.clip_grad_norm_(list(parameters.values()),10.)
    optimizer.step()
    with torch.no_grad():
        for name,p in parameters.items():p[~allowed]=frozen[name][~allowed]


def restore_hair_in_scene(scene,data,out,steps=180):
    import json
    from reconstruction_portrait_pipeline import (make_frame,full_frame_draw,masked_mean,
        write_json,ENGINE_VERSION,surface_contract)
    from reconstruction_portrait_model import GaussianState
    if not scene.dense_surface or not getattr(scene,'dense_hair',False):raise ValueError('hair_composite_requires_observed_full_scene')
    if not 1<=steps<=240:raise ValueError('hair_composite_bounded_budget')
    out=Path(out);hair=scene.portrait.role==2
    before={n:p.detach().clone() for n,p in scene.named_parameters()}
    parameters={'sh':scene.portrait.sh,'opacity':scene.portrait.opacity_logits}
    frozen={n:p.detach().clone() for n,p in parameters.items()}
    for p in scene.parameters():p.requires_grad_(False)
    masks={};protected={};views=[]
    with torch.no_grad():
        state=scene.environment_state();room=state.parts==0
        room_state=GaussianState(*(getattr(state,k)[room] for k in ('means','quats','scales','opacity','sh','parts')))
        for name in data['train']:
            frame=make_frame(data,name,crop=False)
            background=full_frame_draw(room_state,frame['C'],frame,unit_scale=scene.scale)
            # Alpha is only numerical coverage eligibility. The room comes
            # from the validated, explicitly typed source-surface contract;
            # its depth remains conditional, not an independent measurement.
            valid=frame['masks']['hair_visible'] & ~frame['masks']['unknown_or_occluded']
            valid &= (background['alpha']>.9)&torch.isfinite(background['depth'])&(background['depth']>0)
            if int(valid.sum())<256:continue
            r=scene.render(frame,'T2')
            face=frame['masks']['face_core']|frame['masks']['glasses_visible']
            masks[name]=valid.cpu();protected[name]=(face.cpu(),r['rgb'][face].cpu())
            views.append(name)
    if len(views)<3:
        report={'stage':'hair-composite','steps':0,'status':'insufficient_frozen_background_support',
                'qualifiedViews':views,'geometryChanged':False,'modelChanged':False}
        write_json(out/'hair-composite-training.json',report);return report
    for p in parameters.values():p.requires_grad_(True)
    optimizer=torch.optim.Adam([{'params':[parameters['sh']],'lr':.0015},
                                {'params':[parameters['opacity']],'lr':.01}],eps=1e-8)
    def checkpoint(label,step):
        torch.save({'engineVersion':ENGINE_VERSION,'sourceSha256':data['sourceHash'],
            'model':scene.state_dict(),'optimizer':optimizer.state_dict(),'stage':'hair-composite','step':step,
            'surfaceContract':surface_contract(scene,data),'rng':torch.get_rng_state(),'cudaRng':torch.cuda.get_rng_state(),
            'sampler':{'names':views,'nextStep':step},'topologyChanged':False},out/('hair-composite-'+label+'.pt'))
    checkpoint('init',0);start=time.perf_counter();curve=[]
    for step in range(steps):
        name=views[step%len(views)];frame=make_frame(data,name,crop=False)
        optimizer.zero_grad(set_to_none=True);r=scene.render(frame,'T2')
        mask=masks[name].to(r['rgb'].device);face,target=protected[name];face=face.to(mask.device)
        rgb=masked_mean((r['rgb']-frame['rgb']).abs().mean(-1),mask)
        preservation=(r['rgb'][face]-target.to(mask.device)).abs().mean()
        prior=(parameters['sh'][hair,1:]-frozen['sh'][hair,1:]).square().mean()
        loss=rgb+2*preservation+.001*prior
        if not torch.isfinite(loss):raise ValueError('hair_composite_nonfinite')
        loss.backward();masked_parameter_step(optimizer,parameters,hair,frozen)
        with torch.no_grad():
            parameters['opacity'][hair]=parameters['opacity'][hair].clamp(frozen['opacity'][hair]-2,frozen['opacity'][hair]+2)
        if step%30==0 or step==steps-1:
            row={'stage':'hair-composite','step':step+1,'frame':name,'rgbLoss':float(rgb.detach()),'facePreservation':float(preservation.detach())}
            curve.append(row);print(json.dumps(row),flush=True)
        if step+1==steps//2:checkpoint('mid',step+1)
    for name,p in scene.named_parameters():
        if name in ('portrait.sh','portrait.opacity_logits'):
            if not torch.equal(p[~hair],before[name][~hair]):raise AssertionError('hair_composite_changed_nonhair:'+name)
        elif not torch.equal(p,before[name]):raise AssertionError('hair_composite_changed_frozen_parameter:'+name)
    torch.cuda.synchronize();checkpoint('state',steps)
    report={'stage':'hair-composite','steps':steps,'seconds':time.perf_counter()-start,'curve':curve,
        'qualifiedViews':views,'geometryChanged':False,'modelChanged':True,'allComponentsRendered':True,
        'appearanceOnlyNotHairVolumeRepair':True,'protectedNonHairParametersBitwiseUnchanged':True,
        'opacityLogitMeanChange':float((parameters['opacity'][hair]-frozen['opacity'][hair]).detach().abs().mean()),
        'hairShMeanChange':float((parameters['sh'][hair]-frozen['sh'][hair]).detach().abs().mean()),
        'backgroundDepthRemainsConditional':True}
    write_json(out/'hair-composite-training.json',report);return report
