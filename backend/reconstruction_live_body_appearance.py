"""Finite opaque-body colour recovery with all geometry/transmission frozen."""
from pathlib import Path
import hashlib
import json
import random
import time
import copy
import numpy as np
import torch


def tensor_hash(value):
    return hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def body_preservation_decision(before,after):
    """Fixed-mask, per-observation gate; never average away one bad neck view.

    The caller must establish identical source/camera/mask provenance first.
    These tolerances are fixed for future candidate transactions. Applying
    this later-added gate to an earlier diagnostic is retrospective, not a
    pre-registered test. The gate is necessary, not sufficient: geometry,
    other views and visual quality retain their separate checks.
    """
    limits={'rgbL1Increase':.001,'nativeGradientAbsoluteIncrease':.0001,
            'nativeGradientRelativeIncrease':.02,'personContributionDecrease':.005}
    failures=[];changes={}
    if not before or set(before)!=set(after):
        return dict(accepted=False,failures=['observation_set_mismatch'],limits=limits)
    examined=0
    for name,regions in before.items():
        changes[name]={}
        for region in ('opaque_cloth','opaque_body_skin'):
            if region not in regions or region not in after[name]:
                failures.append(name+':'+region+':missing_region');continue
            a=regions[region];b=after[name][region]
            if a.get('pixels')!=b.get('pixels'):
                failures.append(name+':'+region+':fixed_domain_changed');continue
            if not a.get('pixels'):continue
            keys=('premultRgbL1','nativeGradientL1','qPersonMean')
            if any(key not in row or row[key] is None or not np.isfinite(row[key]) for row in (a,b) for key in keys):
                failures.append(name+':'+region+':nonfinite_or_missing_metric');continue
            examined+=1
            delta={key:b[key]-a[key] for key in keys};changes[name][region]=delta
            prefix=name+':'+region
            if delta['premultRgbL1']>limits['rgbL1Increase']:failures.append(prefix+':rgb_regression')
            bound=max(limits['nativeGradientAbsoluteIncrease'],a['nativeGradientL1']*limits['nativeGradientRelativeIncrease'])
            if delta['nativeGradientL1']>bound:failures.append(prefix+':native_structure_regression')
            if delta['qPersonMean'] < -limits['personContributionDecrease']:failures.append(prefix+':person_coverage_regression')
    if not examined:failures.append('no_opaque_body_observation')
    return dict(accepted=not failures,failures=failures,limits=limits,changes=changes,
                independentVisualAndDevelopmentChecksStillRequired=True,
                sourceCameraAndMaskIdentityMustBeCheckedByCaller=True)


def snapshot_body_transaction(scene,optimizer=None):
    """Full fixed-topology state, not just the changed SH rows."""
    return {'model':{key:value.detach().clone() for key,value in scene.state_dict().items()},
            'optimizer':copy.deepcopy(optimizer.state_dict()) if optimizer is not None else None,
            'requiresGrad':{key:value.requires_grad for key,value in scene.named_parameters()},
            'pythonRng':random.getstate(),'numpyRng':copy.deepcopy(np.random.get_state()),
            'torchRng':torch.get_rng_state().clone(),
            'cudaRng':torch.cuda.get_rng_state_all() if torch.cuda.is_initialized() else None}


def reject_body_transaction(scene,snapshot,decision,optimizer=None):
    if decision.get('accepted') is True:return False
    scene.load_state_dict(snapshot['model'],strict=True)
    for key,value in scene.state_dict().items():
        if not torch.equal(value,snapshot['model'][key]):raise AssertionError('body_transaction_restore:'+key)
    if optimizer is not None:
        if snapshot['optimizer'] is None:optimizer.state.clear()
        else:optimizer.load_state_dict(snapshot['optimizer'])
    for key,value in scene.named_parameters():
        value.requires_grad_(snapshot['requiresGrad'][key]);value.grad=None
    random.setstate(snapshot['pythonRng']);np.random.set_state(snapshot['numpyRng'])
    torch.set_rng_state(snapshot['torchRng'])
    if snapshot['cudaRng'] is not None:torch.cuda.set_rng_state_all(snapshot['cudaRng'])
    return True


def restore_opaque_body_appearance(scene,data,output,*,steps=120,learning_rate=.008):
    from reconstruction_portrait_pipeline import make_frame,masked_mean,surface_contract,write_json,ENGINE_VERSION
    from reconstruction_live_opaque_person import opaque_person_loss
    from reconstruction_live_skin_compositing import observation_parameter_step
    if not scene.dense_surface or not getattr(scene,'opaque_person',False):
        raise ValueError('body_appearance_requires_dense_common_opaque_scene')
    if not 1<=steps<=120 or learning_rate!=.008:
        raise ValueError('body_appearance_predeclared_finite_budget')
    names=sorted(scene.body_train_names)
    if len(names)<3 or any(name not in data['worlds'] or data['local'][name]['role']!='train' for name in names):
        raise ValueError('body_appearance_requires_measured_training_window')
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    before={key:value.detach().clone() for key,value in scene.state_dict().items()}
    for parameter in scene.parameters():parameter.requires_grad_(False)
    parameter=scene.environment['sh'];parameter.requires_grad_(True)
    selected=scene.environment_parts==4
    if not selected.any():raise ValueError('body_appearance_missing_body_points')
    initial=parameter.detach().clone()
    optimizer=torch.optim.Adam([parameter],lr=learning_rate,eps=1e-8)
    frozen_hashes={key:tensor_hash(value) for key,value in before.items()}
    curve=[];start=time.perf_counter()
    def checkpoint(label,completed):
        npstate=np.random.get_state()
        torch.save(dict(engineVersion=ENGINE_VERSION,sourceSha256=data['sourceHash'],
            model=scene.state_dict(),surfaceContract=surface_contract(scene,data),
            environmentSources={key:torch.as_tensor(value) for key,value in scene.environment_sources.items()},
            optimizer=optimizer.state_dict(),stage='opaque-body-colour-recovery',step=completed,
            resumeKind='new_Adam_fixed_geometry_body_SH_only',
            rng=dict(torch=torch.get_rng_state(),cuda=torch.cuda.get_rng_state_all(),python=random.getstate(),
                     numpy=dict(kind=npstate[0],keys=npstate[1].tolist(),pos=npstate[2],hasGauss=npstate[3],cached=npstate[4])),
            sampler=dict(names=names,nextStep=completed),strategy=dict(topologyChanged=False,densityEnabled=False),
            selected=selected,parameterHashes={key:tensor_hash(value) for key,value in scene.state_dict().items()},
            initialParameterHashes=frozen_hashes,curve=curve),out/('body-colour-'+label+'.pt'))
    checkpoint('init',0)
    for step in range(steps):
        name=names[step%len(names)];frame=make_frame(data,name,crop=False)
        optimizer.zero_grad(set_to_none=True)
        rendered=scene.render(frame,'T2')
        mask=frame['masks']['observed_neck_cloth']
        rgb=masked_mean((rendered['rgb']-frame['rgb']).abs().mean(-1),mask)
        conditional,details=opaque_person_loss(rendered,frame,scope='body')
        regularizer=.0005*parameter[selected,1:].square().mean()
        loss=.7*rgb+conditional+regularizer
        if not torch.isfinite(loss):raise ValueError('body_appearance_nonfinite')
        loss.backward()
        observation_parameter_step(optimizer,{'sh':parameter},selected)
        if step%20==0 or step+1==steps:
            row=dict(step=step+1,frame=name,loss=float(loss.detach()),rgb=float(rgb.detach()),
                     opaque=details,shMeanChange=float((parameter[selected]-initial[selected]).abs().mean().detach()))
            curve.append(row);print(json.dumps(dict(stage='body-colour',**row)),flush=True)
        if step+1==steps//2:checkpoint('mid',step+1)
    for key,value in scene.state_dict().items():
        if key=='environment.sh':
            if not torch.equal(value[~selected],before[key][~selected]):raise AssertionError('body_appearance_room_colour_changed')
        elif not torch.equal(value,before[key]):raise AssertionError('body_appearance_frozen_parameter_changed:'+key)
    checkpoint('final',steps);torch.cuda.synchronize()
    report=dict(stage='opaque-body-colour-recovery',steps=steps,learningRate=learning_rate,
        names=names,selectedCount=int(selected.sum()),selectedUidHash=tensor_hash(scene.environment_uid[selected]),
        seconds=time.perf_counter()-start,geometryAndAlphaBitwiseUnchanged=True,
        headHairAndRoomParametersBitwiseUnchanged=True,
        shMeanChange=float((parameter[selected]-initial[selected]).abs().mean().detach()),
        initialParameterHashes=frozen_hashes,finalParameterHashes={key:tensor_hash(value) for key,value in scene.state_dict().items()},
        status='diagnostic_not_accepted_or_published',extraBudgetNotFairProductionAB=True,curve=curve)
    write_json(out/'report.json',report)
    return report
