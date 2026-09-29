"""Finite portrait-priority stages, called only by the isolated v3 runner.

No job protocol or publishing code. Consumes existing observations, retaining
local-only F. This is a research implementation, not an E1--E5 quality waiver.
"""
from __future__ import annotations
import copy,json,math,random,shutil,time
from pathlib import Path
import cv2
import numpy as np
import torch
from reconstruction_components_v3 import load_v3_prepared,save_json,sha,exact_state_hash
from reconstruction_portrait_pipeline import initialize_scene,make_frame,draw,head_loss,metrics,masked_mean
from reconstruction_portrait_model import CandidateTransaction,joined_state
from reconstruction_research_state import (FrameSampler,BoundedHeadPose,save_checkpoint,
    restore_checkpoint,validate_research_manifest,rng_state,restore_rng,rigid_component_state,ensure_point_lineage,replace_face_with_lineage)
from reconstruction_reference_static import (StaticGaussians,BudgetedStaticStrategy,
    static_loss,static_regularization,valid_window_structure,valid_static_mask)


def validate_config(c):
    required={'seed','face_steps','room_steps','joint_frozen_steps','joint_steps','audit_names',
        'max_face_views','stage_seconds','max_allocated_mib','face_split_steps','face_split_parents',
        'recovery_steps','room_refine_start','room_refine_stop','room_refine_every','room_reset_steps',
        'room_max_points','room_max_growth','geometry_archives'}
    if set(c)!=required:raise ValueError('explicit_config_fields_required:'+str(sorted(required^set(c))))
    if not 600<=c['face_steps']<=1500 or not 700<=c['room_steps']<=1500:raise ValueError('finite_training_budget')
    if not 0<=c['joint_frozen_steps']<=300 or not 0<=c['joint_steps']<=300:raise ValueError('finite_joint_budget')
    if not 16<=c['max_face_views']<=40 or not 1<=c['recovery_steps']<=48:raise ValueError('finite_view_recovery_budget')
    if not 0<c['face_split_parents']<=256 or len(c['face_split_steps'])>2:raise ValueError('bounded_face_topology')
    if any(s<250 or s+c['recovery_steps']>c['face_steps']-150 for s in c['face_split_steps']):raise ValueError('face_recovery_interval')
    if c['room_refine_stop']>c['room_steps']-200 or any(s>c['room_refine_stop']-100 for s in c['room_reset_steps']):
        raise ValueError('room_recovery_interval')
    if not 0<c['room_max_growth']<=2048 or not 22020<=c['room_max_points']<=60000:raise ValueError('finite_room_density')
    if not 0<c['stage_seconds']<=2400 or not 0<c['max_allocated_mib']<=7100:raise ValueError('finite_resource_budget')
    if len(c['audit_names'])<3 or len(set(c['audit_names']))!=len(c['audit_names']):raise ValueError('predeclared_audit_required')
    return c


def observation_plan(data,c):
    audit=set(c['audit_names']); development={n for n,r in data['local'].items() if r['role']=='development'}
    if not audit<=data['local'].keys() or audit&development:raise ValueError('audit_observation_contract')
    if audit&set(data['train']):raise ValueError('audit_colours_in_prepared_room_seeds')
    faces=data['geometry'].faces.numpy();tri=faces[data['geometry'].landmark_faces.numpy()]
    bary=data['geometry'].barycentric.numpy();indices=data['geometry'].landmark_indices.numpy()
    rows=[]
    for name,row in data['local'].items():
        if row['role']!='train' or name in audit:continue
        m=data['labels'][name];mask=m['face_core']&~m['unknown_or_occluded']
        gray=cv2.cvtColor(data['rgb'][name],cv2.COLOR_RGB2GRAY)
        sharp=float(np.mean(cv2.Laplacian(gray,cv2.CV_32F)[mask]**2)) if mask.any() else 0.
        points=(row['mesh'][tri]*bary[:,:,None]).sum(1)
        camera=points@row['F'][:3,:3].T+row['F'][:3,3]
        uv=camera@data['K'].T;uv=uv[:,:2]/uv[:,2:]
        errors=np.linalg.norm(uv-row['marks'][indices],axis=1);residual=float(np.median(errors))
        center=-row['F'][:3,:3].T@row['F'][:3,3]
        angle=float(np.arctan2(center[0],center[2]))
        coverage=int(mask.sum());valid=bool(coverage>1000 and np.isfinite(camera).all() and (camera[:,2]>.05).all() and residual<15)
        mouth=float(np.linalg.norm(row['marks'][13]-row['marks'][14]))
        score=np.log1p(sharp*1000)*np.sqrt(coverage)/(1+residual)
        rows.append(dict(name=name,angleRadians=angle,sharpness=sharp,landmarkMedianPx=residual,
            visibleFacePixels=coverage,mouthOpeningPixels=mouth,score=float(score),eligible=valid,
            worldAvailable=name in data['worlds']))
    eligible=sorted([r for r in rows if r['eligible']],key=lambda x:x['angleRadians'])
    # Angular strata retain weaker directions; score only chooses within a stratum.
    groups=np.array_split(np.arange(len(eligible)),min(c['max_face_views'],len(eligible)))
    selected=[max((eligible[i] for i in g),key=lambda r:r['score'])['name'] for g in groups if len(g)]
    if len(selected)<8:raise ValueError('insufficient_reliable_local_observations')
    return {'train':selected,'development':sorted(development),'audit':sorted(audit),'ranking':rows,
        'auditScope':'predeclared_for_this_warm_start_run; historical_research_may_have_inspected_frames; not_global_blind',
        'worldRequiredForFace':False}


class ResearchModel(torch.nn.Module):
    def __init__(self,scene,data,names):
        super().__init__();self.portrait=scene.portrait;self.scale=scene.scale
        ensure_point_lineage(self.portrait)
        self.pose=BoundedHeadPose(names,data['reference'],device=self.portrait.sh.device)
        self.reference=data['reference']
        self.body_pose=BoundedHeadPose(data['train'],data['reference'],device=self.portrait.sh.device,degrees=2.,translation=.01*self.scale)
        part=scene.environment_parts;select=part==0
        self.room=StaticGaussians({k:v[select] for k,v in scene.environment.items()},
            {k:v[select.cpu().numpy()] for k,v in scene.environment_sources.items()},
            torch.as_tensor(data['room']['support'],device=part.device))
        if not np.array_equal(scene.environment_sources['id'][select.cpu().numpy()],data['room']['source_id']):
            raise ValueError('static_support_identity_order_mismatch')
        # Body remains a separately identified reference hypothesis. Its actual
        # geometry/colour can update in joint; no rigid head-F is applied to it.
        body=part==4
        self.body=torch.nn.ParameterDict({k:torch.nn.Parameter(v[body].detach().clone()) for k,v in scene.environment.items()})
        self.register_buffer('body_initial_means',self.body['means'].detach().clone())
        self.register_buffer('body_initial_scales',self.body['scales'].detach().clone())
        self.body_sources={k:v[body.cpu().numpy()] for k,v in scene.environment_sources.items()}
    def adjusted_frame(self,frame):return {**frame,'F':self.pose(frame['name'],frame['F'])}
    def render(self,frame,stage):
        from reconstruction_fullframe import draw_frame
        frame=self.adjusted_frame(frame);head=self.portrait.local_state(frame['mesh']);h,w=frame['rgb'].shape[:2]
        if stage=='T0':return draw_frame(head,frame['F'],frame)
        if frame['C'] is None:raise ValueError('missing_evidenced_world_C')
        head=head.to_world(frame['C'],frame['F'],self.scale)
        if stage!='T1':head=joined_state(head,self.room.state(),self.body_state(frame['name']))
        return draw_frame(head,frame['C'],frame,unit_scale=self.scale)
    def body_state(self,name=None):
        from reconstruction_portrait_model import GaussianState
        p=self.body
        state=GaussianState(p['means'],torch.nn.functional.normalize(p['quats'],dim=-1),p['scales'].exp(),
            p['opacities'].sigmoid(),p['sh'],torch.full((len(p['means']),),4,device=p['means'].device,dtype=torch.long))
        if not len(p['means']):return state
        name=name or self.reference
        raw=self.body_pose.delta[self.body_pose.index[name]].tanh() if name in self.body_pose.index and name!=self.reference else torch.zeros(6,device=p['means'].device)
        pivot=self.body_initial_means.median(0).values
        # Independent upper-body correction: NEVER reuse head F. The bounded
        # fit is a research motion hypothesis, not solved neck/cloth anatomy.
        return rigid_component_state(state,raw[:3]*(2*np.pi/180/np.sqrt(3)),raw[3:]*(.01*self.scale/np.sqrt(3)),pivot)


def face_optimizer(model):
    rates={'embedding':.0002,'normal_offset':.000015,'surface_residual':.000008,'hair_delta':.00002,
        'sh':.0015,'opacity_logits':.004,'log_scales':.001,'quats':.0002}
    return torch.optim.Adam([{'params':[p],'lr':rates[n],'name':n} for n,p in model.portrait.named_parameters()])


def face_regularizer(portrait,frame):
    r=portrait.soft_regularization(frame['mesh'])
    return (.0007*r['skinSoftBand']+.00015*r['sharedSurfaceSmooth']+.00006*r['sharedIdentityResidual']+
        .00003*r['normalOffsetChangePixels']+.0005*portrait.sh[:,1:].square().mean()+
        .0002*(portrait.log_scales-portrait.initial_log_scales).square().mean())


def check_budget(start,c):
    if time.perf_counter()-start>c['stage_seconds']:raise RuntimeError('finite_stage_wall_budget_reached')
    if torch.cuda.memory_allocated()/1024**2>c['max_allocated_mib']:raise RuntimeError('finite_stage_VRAM_budget_reached')


def set_face_phase(p,step,recovery=False):
    # Fixed structure appearance warm-up, then alternating rather than all DOF.
    geometry=not recovery and step>=180 and step%4==3
    for name,value in p.named_parameters():
        value.requires_grad_(name in ('sh','opacity_logits','log_scales','quats') or
            (geometry and name in ('embedding','normal_offset','surface_residual','hair_delta')))
    return geometry


@torch.no_grad()
def audit_face(model,data,plan,out):
    out.mkdir(parents=True,exist_ok=False);results={}
    for name in plan['development']+plan['audit']+[plan['train'][0]]:
        frame=make_frame(data,name);render=model.render(frame,'T0')
        row=metrics(render,frame);row['use']='audit' if name in plan['audit'] else 'development' if name in plan['development'] else 'train'
        row['K']=frame['K'].cpu().tolist();row['F']=model.adjusted_frame(frame)['F'].cpu().tolist();row['crop']=frame['rectangle']
        results[name]=row
        rgb=render['rgb'].cpu().numpy();target=frame['rgb'].cpu().numpy()
        np.savez_compressed(out/(name+'.npz'),rgb=rgb,alpha=render['alpha'].cpu().numpy(),q=render['q'].cpu().numpy())
        comparison=np.concatenate((target,np.clip(rgb,0,1)),axis=1)
        cv2.imwrite(str(out/name),cv2.cvtColor((comparison*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    save_json(out/'metrics.json',results);return results


def child_support(model,data,names,ids,bary):
    p=model.portrait;support=torch.zeros(len(ids),device=ids.device,dtype=torch.long)
    with torch.no_grad():
        for name in names:
            frame=make_frame(data,name);F=model.adjusted_frame(frame)['F']
            triangles=(frame['mesh']+p.surface_residual)[p.faces[ids]]
            xyz=(triangles*bary[:,:,None]).sum(1)
            normal=torch.nn.functional.normalize(torch.linalg.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),dim=-1)
            camera=xyz@F[:3,:3].T+F[:3,3];uv=camera@frame['K'].T;uv=uv[:,:2]/uv[:,2:].clamp_min(1e-8)
            ix=uv[:,0].round().long();iy=uv[:,1].round().long();h,w=frame['rgb'].shape[:2]
            inside=(camera[:,2]>.05)&(ix>=0)&(iy>=0)&(ix<w)&(iy<h)&((normal@F[:3,:3].T*-camera).sum(1)>0)
            ix=ix.clamp(0,w-1);iy=iy.clamp(0,h-1)
            mask=frame['masks']['face_core']&~frame['masks']['unknown_or_occluded']&~frame['masks']['glasses_visible']
            support+=(inside&mask[iy,ix]).long()
    # Projected, front-facing photo support is not independent depth truth.
    return support>=3


def pose_landmark_loss(model,data,frame):
    g=data['geometry'];d=frame['mesh'].device
    triangles=(frame['mesh']+model.portrait.surface_residual)[g.faces[g.landmark_faces].to(d)]
    xyz=(triangles*g.barycentric.to(d)[:,:,None]).sum(1)
    F=model.adjusted_frame(frame)['F'];camera=xyz@F[:3,:3].T+F[:3,3]
    projected=camera@frame['K'].T;uv=projected[:,:2]/projected[:,2:].clamp_min(.0001)
    target=torch.as_tensor(data['local'][frame['name']]['marks'][g.landmark_indices.numpy()],device=d,dtype=uv.dtype)
    x0,y0,_,_=frame['rectangle'];target=target-torch.tensor([x0,y0],device=d)
    target/=frame['nativeScale']
    error=torch.linalg.vector_norm(uv-target,dim=1)
    selected=torch.arange(len(error),device=d)%5!=0
    # Independent landmark subset is logged rather than fitted. This remains
    # local evidence, not a new world camera or independent final audit.
    loss=torch.nn.functional.huber_loss(error[selected]/5,torch.zeros_like(error[selected]),reduction='mean')
    return loss,{'poseLandmarkTrainMedianPx':float(error[selected].detach().median()),
                 'poseLandmarkCheckMedianPx':float(error[~selected].detach().median())}


def train_face(model,data,plan,c,out,contract):
    optim=face_optimizer(model);poseoptim=torch.optim.Adam(model.pose.parameters(),lr=.003)
    sampler=FrameSampler(plan['train'],c['seed']);optimizers={'face':optim,'pose':poseoptim};samplers={'face':sampler}
    start=time.perf_counter();curve=[];events=[];initial={n:p.detach().clone() for n,p in model.portrait.named_parameters()}
    save=lambda label,step:save_checkpoint(out/(label+'.pt'),model,optimizers,samplers,stage='face',step=step,
        contract=contract,extra={'plan':plan,'events':events,'reference':data['reference'],'bodySources':model.body_sources,
            'roomMetadata':model.room.metadata,'warmStartNoHistoricalAdam':True})
    save('face-initial',0)
    def update(step,recovery=False):
        frame=make_frame(data,sampler.next());geometry=set_face_phase(model.portrait,step,recovery)
        model.pose.delta.requires_grad_(not recovery and step>=180 and step%4==1)
        optim.zero_grad(set_to_none=True);poseoptim.zero_grad(set_to_none=True)
        rendered=model.render(frame,'T0');image,parts=head_loss(rendered,frame)
        landmark_loss,landmark_report=pose_landmark_loss(model,data,frame)
        loss=image+face_regularizer(model.portrait,frame)+.0005*model.pose.regularizer()+.003*landmark_loss
        if not torch.isfinite(loss):raise RuntimeError('nonfinite_face_loss')
        loss.backward();torch.nn.utils.clip_grad_norm_(model.portrait.parameters(),10.)
        optim.step();poseoptim.step()
        if geometry:model.portrait.walk(optim)
        return {'step':step,'frame':frame['name'],'localOnly':frame['C'] is None,'loss':float(loss.detach()),**parts,**landmark_report}
    @torch.no_grad()
    def topology_audit():
        result={}
        for name in plan['development']+[plan['train'][0]]:
            f=make_frame(data,name);m=metrics(model.render(f,'T0'),f)['face'];result[name]={'hole':m['hole'],'rgb':m['fixedRgbL1']}
        return result
    for step in range(1,c['face_steps']+1):
        check_budget(start,c);row=update(step)
        if step in c['face_split_steps']:
            p=model.portrait;n=p.surface_count
            # Native projected width + actual image gradient, limited to skin.
            gradient=p.sh.grad[:n].norm(dim=(1,2)) if p.sh.grad is not None else torch.zeros(n,device=p.sh.device)
            width=p.log_scales[:n].detach().exp().max(1).values/p.metric_per_pixel[:n]
            candidates=torch.where((p.role[:n]==0)&(width>1.5)&(gradient>0))[0]
            selected=candidates[torch.argsort(gradient[candidates]*width[candidates],descending=True)[:c['face_split_parents']]]
            if len(selected):
                rng=rng_state();sample_state=copy.deepcopy(sampler.state_dict())
                try:
                    with CandidateTransaction(p,optim) as tx:
                        event=tx.run(lambda:replace_face_with_lineage(p,optim,selected,
                            lambda ids,bary:child_support(model,data,plan['train'],ids,bary)),
                            lambda i:update(step,recovery=True),topology_audit,recovery_steps=c['recovery_steps'])
                except ValueError as error:event={'accepted':False,'reason':str(error)}
                if not event['accepted']:restore_rng(rng);sampler.load_state_dict(sample_state)
                events.append({'step':step,**event})
        if step%50==0 or step==1 or step==c['face_steps']:
            curve.append(row);print(json.dumps({'stage':'face',**row}),flush=True)
        if step==c['face_steps']//2:save('face-mid',step)
    save('face-final',c['face_steps']);audit_face(model,data,plan,out/'face-final-images')
    change={n:{'shapeBefore':list(initial[n].shape),'shapeAfter':list(p.shape),
        'meanAbsoluteChange':float((p.detach()-initial[n]).abs().mean()) if p.shape==initial[n].shape else None} for n,p in model.portrait.named_parameters()}
    result={'steps':c['face_steps'],'recoveryOptimizerSteps':sum(e.get('recoverySteps',0) for e in events),
        'seconds':time.perf_counter()-start,'curve':curve,'topology':events,'parameterChanges':change,
        'poseMaxRaw':float(model.pose.delta.detach().abs().max()),'qualityApproved':False}
    save_json(out/'face-training.json',result);return result


def train_room(model,data,c,out,contract):
    names=list(data['train']);sampler=FrameSampler(names,c['seed']+1);room=model.room
    strategy=BudgetedStaticStrategy(start=c['room_refine_start'],stop=c['room_refine_stop'],every=c['room_refine_every'],
        max_points=c['room_max_points'],max_growth=c['room_max_growth'],reset_steps=c['room_reset_steps'])
    extent=float(torch.linalg.vector_norm(room.params['means'].detach()-room.params['means'].detach().median(0).values,dim=1).quantile(.9))
    optim=room.optimizers(extent);strategy.check_sanity(room.params,optim);state=strategy.initialize_for(room,extent)
    start=time.perf_counter();curve=[];head_hash=exact_state_hash(model.portrait)
    scheduler=torch.optim.lr_scheduler.ExponentialLR(optim['means'],gamma=.1**(1/c['room_steps']))
    save=lambda label,step:save_checkpoint(out/(label+'.pt'),model,{'room_'+k:v for k,v in optim.items()},
        {'room':sampler},stage='room',step=step,contract=contract,strategy=state,scheduler=scheduler.state_dict(),
        extra={'reference':data['reference'],'bodySources':model.body_sources})
    save('room-initial',0)
    for step in range(1,c['room_steps']+1):
        check_budget(start,c);frame=make_frame(data,sampler.next(),crop=False,half=True)
        for op in optim.values():op.zero_grad(set_to_none=True)
        h,w=frame['rgb'].shape[:2];render=draw(room.state(),frame['C'],frame['K'],w,h,unit_scale=data['scale'])
        strategy.step_pre_backward(room.params,optim,state,step,render['info'])
        image,parts=static_loss(render,frame);loss=image+static_regularization(room,state)
        if not torch.isfinite(loss):raise RuntimeError('nonfinite_static_loss')
        loss.backward();torch.nn.utils.clip_grad_norm_(room.parameters(),10.)
        for op in optim.values():op.step()
        scheduler.step();strategy.step_post_backward(room.params,optim,state,step,render['info'],packed=True)
        if step%50==0 or step==1 or step==c['room_steps']:
            row={'step':step,'frame':frame['name'],'points':len(room.params['means']),**parts};curve.append(row)
            print(json.dumps({'stage':'room',**row}),flush=True)
        if step==c['room_steps']//2:save('room-mid',step)
    room.metadata={k:state[k] for k in room.metadata};save('room-final',c['room_steps'])
    if exact_state_hash(model.portrait)!=head_hash:raise RuntimeError('room_training_changed_head')
    result={'steps':c['room_steps'],'seconds':time.perf_counter()-start,'curve':curve,'strategyEvents':state['events'],
        'allVisibleStaticPixels':True,'seedSupportMaskUsedInLoss':False,'portraitFrozenAndPreserved':True,
        'densityParameters':'means/log_scale/quaternion/logit_opacity/SH1; source metadata follows topology',
        'qualityApproved':False}
    save_json(out/'room-training.json',result);return result

@torch.no_grad()
def audit_world(model,data,out):
    out.mkdir(parents=True,exist_ok=False);result={}
    for name in data['development']+[data['reference']]:
        f=make_frame(data,name,crop=False,half=True);images={s:model.render(f,s) for s in ('T0','T1','T2')}
        row={s:metrics(v,f) for s,v in images.items()}
        row['T0_T1']={k:float((images['T0'][k]-images['T1'][k]).abs().max()) for k in ('rgb','alpha','q','depth')}
        row['C']=f['C'].cpu().tolist();row['F']=model.adjusted_frame(f)['F'].cpu().tolist();row['K']=f['K'].cpu().tolist()
        room=draw(model.room.state(),f['C'],f['K'],f['rgb'].shape[1],f['rgb'].shape[0],unit_scale=data['scale'])
        _,row['roomOnly']=static_loss(room,f);result[name]=row
        rgb=images['T2']['rgb'].cpu().numpy()
        np.savez_compressed(out/(name+'.npz'),rgb=rgb,alpha=images['T2']['alpha'].cpu().numpy(),q=images['T2']['q'].cpu().numpy())
        cv2.imwrite(str(out/name),cv2.cvtColor((np.concatenate((f['rgb'].cpu().numpy(),np.clip(rgb,0,1)),1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    save_json(out/'metrics.json',result);return result


def train_joint(model,data,plan,c,out,contract,stage,steps):
    # Research input contract permits experimentation. E1--E5 quality remains
    # unapproved. Every world forward includes ALL represented components.
    manifest=validate_research_manifest(data,data['reference'],data['train'])
    manifest['limitations']=['bounded independent upper-body motion fit; neck continuity still not validated',
        'legacy hair volume remains unaccepted','glasses remain partly in old bound detail points']
    save_json(out/(stage+'-manifest.json'),manifest)
    faceopt=face_optimizer(model);roomopts=model.room.optimizers(data['scale'])
    bodyopt=torch.optim.Adam([{'params':[p],'lr':.0001*data['scale'] if n=='means' else .001} for n,p in model.body.items()]+[{'params':[model.body_pose.delta],'lr':.002}])
    model.pose.delta.requires_grad_(False)
    optimizers={'face':faceopt,'body':bodyopt,**{'room_'+k:o for k,o in roomopts.items()}}
    sampler=FrameSampler(data['train'],c['seed']+2);local=FrameSampler(plan['train'],c['seed']+3)
    samplers={'world':sampler,'local':local};before=exact_state_hash(model.portrait);curve=[];start=time.perf_counter()
    for step in range(1,steps+1):
        check_budget(start,c)
        for op in optimizers.values():op.zero_grad(set_to_none=True)
        if stage=='T3':
            for p in model.portrait.parameters():p.requires_grad_(False)
        else:set_face_phase(model.portrait,step) # limited appearance only in short joint
        wf=make_frame(data,sampler.next(),crop=False,half=True);render=model.render(wf,'T2')
        err=(render['rgb']-wf['rgb']).abs().mean(-1);m=wf['masks']
        roomloss,_=static_loss(render,wf)
        cloth=m['neck_cloth_visible']&~m['unknown_or_occluded']
        bodyloss=masked_mean(err,cloth)+.04*masked_mean((1-render['alpha']).square(),cloth)
        face=m['face_core']|m['face_boundary']|m['glasses_visible']
        # Room contamination is not the only constraint: actual face RGB and
        # coverage remain explicit, so transparent faces cannot win this term.
        loss=roomloss+.6*bodyloss+1.5*masked_mean(err,face)+.06*masked_mean((1-render['q'][...,1:4].sum(-1)).square(),face)
        loss+=.03*masked_mean(render['q'][...,0],face)
        if stage=='T4':
            lf=make_frame(data,local.next())
            # Use full common composition in the native ROI when world C is
            # evidenced; local-only F observations still supervise the person.
            lr=model.render(lf,'T2' if lf['C'] is not None else 'T0')
            head_view={**lr,'alpha':lr['q'][...,1:4].sum(-1)}
            local_loss,_=head_loss(head_view,lf);loss+=local_loss+face_regularizer(model.portrait,lf)
        displacement=(model.body['means']-model.body_initial_means)/(.02*data['scale'])
        loss+=.002*displacement.square().mean()+.002*model.body_pose.regularizer()
        loss+=.003*(model.body['scales']-model.body_initial_scales-math.log(2)).clamp_min(0).square().mean()
        if not torch.isfinite(loss):raise RuntimeError('nonfinite_joint_loss')
        loss.backward()
        for op in optimizers.values():op.step()
        if step%30==0 or step==1 or step==steps:
            row={'step':step,'frame':wf['name'],'loss':float(loss.detach()),'roomLoss':float(roomloss.detach()),'bodyLoss':float(bodyloss.detach())}
            curve.append(row);print(json.dumps({'stage':stage,**row}),flush=True)
    if stage=='T3' and exact_state_hash(model.portrait)!=before:raise RuntimeError('T3_changed_frozen_portrait')
    save_checkpoint(out/(stage+'-final.pt'),model,optimizers,samplers,stage=stage,step=steps,contract=contract,
        extra={'roomMetadata':model.room.metadata,'bodySources':model.body_sources,'reference':data['reference']})
    result={'steps':steps,'seconds':time.perf_counter()-start,'curve':curve,'allGroupsEveryWorldForward':True,
        'bodyMotionSolved':False,'bodyMotionBoundDegrees':2.,'bodyMotionBoundWorldTranslation':.01*data['scale'],
        'bodyPoseParameterMax':float(model.body_pose.delta.detach().abs().max()),'releaseQualityPassed':False}
    save_json(out/(stage+'-training.json'),result);return result


def run_priority(args):
    """Explicit opt-in in existing research runner; never changes production."""
    import gsplat
    out=args.output.resolve();private=Path(__file__).resolve().parent/'.sources'
    if not out.is_relative_to(private):raise ValueError('isolated_private_output_required')
    if out.exists():raise FileExistsError('new_run_id_required')
    c=validate_config(json.loads(args.portrait_priority_config.read_text(encoding='utf-8-sig')))
    out.mkdir(parents=True);save_json(out/'config.json',c)
    source=out/'algorithm-source';source.mkdir()
    files=['reconstruction_portrait_priority.py','reconstruction_reference_static.py','reconstruction_research_state.py',
        'reconstruction_portrait_model.py','reconstruction_portrait_pipeline.py','reconstruction_components_v3.py',
        'reconstruction_shared_v2.py','reconstruction_components_v2.py','flame_open_model.py','run_reconstruction_v3.py']
    for name in files:shutil.copyfile(Path(__file__).with_name(name),source/name)
    save_json(out/'code-hashes.json',{n:sha(source/n) for n in files})
    save_json(out/'runtime.json',{'torch':torch.__version__,'gsplat':gsplat.__version__,
        'cudaAvailable':torch.cuda.is_available(),'actualTrainingStarted':False})
    if not torch.cuda.is_available():
        save_json(out/'failure.json',{'status':'GPU_unavailable_no_training','published':False});raise RuntimeError('GPU_unavailable_no_training')
    if gsplat.__version__!='1.5.3':raise ValueError('pinned_gsplat_1_5_3_required')
    random.seed(c['seed']);np.random.seed(c['seed']);torch.manual_seed(c['seed']);torch.cuda.reset_peak_memory_stats()
    started=time.perf_counter();stage='load';model=None
    try:
        prepared=args.prepared.resolve();data=load_v3_prepared(prepared);plan=observation_plan(data,c)
        save_json(out/'observations.json',plan)
        # Audit colours are not used by initializer votes or pixel scale either.
        for n in plan['audit']:data['local'][n]['role']='audit'
        backup=out/'input-snapshot';backup.mkdir()
        inputs=[prepared/'preparation.json',prepared/'local_geometry.npz',prepared/'static_surface_seeds.npz',
            prepared/'cloth_supported_seeds.npz',Path(data['appearance'])]
        inputs.extend(Path(p) for p in c['geometry_archives'])
        for i,p in enumerate(inputs):
            if not p.is_file():raise FileNotFoundError('required_full_geometry_archive:'+str(p))
            shutil.copyfile(p,backup/(str(i)+'-'+p.name))
        shutil.copyfile(prepared/'cloth_supported_seeds.npz',out/'cloth_supported_seeds.npz')
        scene=initialize_scene(data,out);model=ResearchModel(scene,data,plan['train']);del scene
        contract={'sourceSha256':data['sourceHash'],'appearanceSha256':data['appearanceHash'],'modelSha256':data['modelHash'],
            'inputSnapshots':{p.name:sha(p) for p in backup.iterdir()},
            'observationFiles':{str(p.relative_to(prepared)):sha(p) for n in data['local'] for p in (prepared/'rectified_observations'/n,prepared/'rectified_observations'/(n+'.npz'))},
            'codeSha256':{n:sha(source/n) for n in files},'reference':data['reference'],
            'coordinate':'head-local-sh1; F,K,C retained; common world scale once',
            'observationsSha256':sha(out/'observations.json'),'configurationSha256':sha(out/'config.json'),
            'warmStart':'old900 contains no Adam/shared residual; zero NEW residual declared, all imported detail retained',
            'newGeometry':'shared residual and bounded pose; shape/expression fixed via archived meshes/fit coefficients'}
        save_json(out/'contract.json',contract)
        save_json(out/'runtime.json',{'torch':torch.__version__,'gsplat':gsplat.__version__,'cudaAvailable':True,
            'device':torch.cuda.get_device_name(),'actualTrainingStarted':True})
        audit_face(model,data,plan,out/'face-initial-images');audit_world(model,data,out/'world-initial-images')
        stage='face';face=train_face(model,data,plan,c,out,contract)
        stage='room';room=train_room(model,data,c,out,contract)
        audit_world(model,data,out/'world-after-room-images')
        joint={}
        for name,steps in [('T3',c['joint_frozen_steps']),('T4',c['joint_steps'])]:
            if steps:stage=name;joint[name]=train_joint(model,data,plan,c,out,contract,name,steps)
        audit_face(model,data,plan,out/'face-after-joint-images');audit_world(model,data,out/'world-final-images')
        result={'face':face,'room':room,'joint':joint,'seconds':time.perf_counter()-started,
            'allocatedPeakMiB':torch.cuda.max_memory_allocated()/1024**2,'reservedPeakMiB':torch.cuda.max_memory_reserved()/1024**2,
            'qualityApproved':False,'published':False,'exportStatus':'requires_geometry_and_fixed_asset_handoff_review',
            'remaining':['independent accessory structure','observed body motion/neck continuity','fixed PLY continuous-view handoff','actual visual acceptance']}
        save_json(out/'result.json',result)
    except Exception as error:
        save_json(out/'failure.json',{'stage':stage,'error':repr(error),'seconds':time.perf_counter()-started,
            'published':False,'allocatedPeakMiB':torch.cuda.max_memory_allocated()/1024**2})
        raise
