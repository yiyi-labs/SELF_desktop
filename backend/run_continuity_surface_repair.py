"""Finite physical-layer recovery, common full-frame compositing and rollback.

Each run changes one component. Body has continuous head/torso neck motion;
hair/room use observed exterior proposals. This is not an E1--E5 publisher.
"""
from pathlib import Path
import argparse,json,time,shutil
import cv2,numpy as np,torch
from scipy.spatial import cKDTree
from reconstruction_evidence_stage import load_stage
from reconstruction_components_v3 import FreeComponent,pick,sha,save_json,exact_state_hash
from reconstruction_portrait_model import GaussianState,joined_state,scaled_head_transform
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_reference_static import valid_window_structure
from reconstruction_detail_controlled import pixel_structure
from reconstruction_continuity_surface import (physical_masks,smooth_transition,
    blend_rigid_state,ShortWindowBodyMotion)
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint
from reconstruction_patch_transaction import compare_patch_views
from run_haze_shared_surface import export_state


@torch.no_grad()
def replacement_proposal(base,data,masks,names,arrays,component):
    """Audit-only transaction scope: actual footprint plus surface evidence.
    Unknown/occluded views do not count as a visible empty-space contradiction.
    No colour selection or whole-group deletion. Screen follows the proposal.
    """
    f=make_frame(data,names[len(names)//2],crop=False)
    if component=='room':s=base.room.state();eligible=s.parts==0
    elif component=='body':s=base.head_state(f);eligible=s.parts==4
    else:s=base.head_state(f);eligible=s.parts==2
    n=len(s.means);votes=np.zeros(n,int);bad=np.zeros(n,bool);eligible_np=eligible.cpu().numpy()
    for name in names:
        f=make_frame(data,name,crop=False);state=base.room.state() if component=='room' else base.head_state(f)
        C=f['C'] if component=='room' else f['F'];h,w=f['rgb'].shape[:2]
        info=draw(state,C,f['K'],w,h,unit_scale=base.scale if component=='room' else 1.)['info']
        ids=info['gaussian_ids'].cpu().numpy();uv=info['means2d'].cpu().numpy();rr=info['radii'].cpu().numpy()
        if uv.ndim==3:uv=uv[0]
        radius=rr.max(-1) if rr.ndim==2 else rr
        mask=masks[name]['neck' if component=='body' else component]
        distance=cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
        for i,p,r in zip(ids,uv,radius):
            if not eligible_np[i] or r<=0:continue
            x,y=np.rint(p).astype(int)
            safe=0<=x<w and 0<=y<h and distance[y,x]>float(r)+2
            votes[int(i)]+=int(safe)
            # Visible room pixels refute a head-layer claim; uncertainty does not.
            contradiction=0<=x<w and 0<=y<h and data['labels'][name]['room_visible'][y,x] if component!='room' else False
            bad[int(i)]|=bool(contradiction)
    head_ids=np.flatnonzero((votes>=3)&~bad&eligible_np)
    room_ids=np.empty(0,int)
    if component=='room':
        # A broad kernel needs a close observed surface and an independent
        # covariance-size discrepancy. Its centre alone is never a delete rule.
        points=arrays['means'];tree=cKDTree(points);d,ix=tree.query(s.means.cpu().numpy())
        local=arrays['scales'][ix,:2].max(1);wide=s.scales.cpu().numpy().max(1)>6*local
        compatible=d<6*local
        # This is a finite proposal; preserving real environment is mandatory
        # in the complete-scene screen, not inferred from this proximity test.
        room_ids=np.flatnonzero(wide&compatible)
        if len(room_ids)>64:
            size=s.scales.cpu().numpy().max(1);room_ids=room_ids[np.argsort(size[room_ids])[-64:]]
        head_ids=np.empty(0,int)
    return head_ids,room_ids


class ContinuityStage(torch.nn.Module):
    def __init__(self,base,data,meta,arrays,head_retired,room_retired,body_retired,motion_mode='transition'):
        super().__init__();self.baseline=base;self.scale=base.scale;self.component=meta['component'];self.motion_mode=motion_mode
        t=lambda a,dtype=torch.float32:torch.as_tensor(a,device='cuda',dtype=dtype)
        state=GaussianState(*(t(arrays[k],torch.long if k=='parts' else torch.float32) for k in GaussianState.__dataclass_fields__))
        self.patch=FreeComponent(state,t(arrays['uid'],torch.long),t(arrays['support']),meta['coordinateGroup'],torch.median(state.scales[:,:2])*1.5)
        self.register_buffer('edges',t(arrays['edges'],torch.long));self.register_buffer('is_neck',t(arrays['layer']=='neck',torch.bool))
        for name,count,retired in [('head',len(base.portrait.role),head_retired),('room',len(base.room.state().means),room_retired),('body',len(base.body['means']),body_retired)]:
            keep=torch.ones(count,device='cuda',dtype=torch.bool);keep[t(retired,torch.long)]=False;self.register_buffer('keep_'+name,keep)
        self.body_motion=None
        if self.component=='body':
            names=meta['names'];ref=names[len(names)//2];f=base.adjusted_frame(make_frame(data,ref,crop=False))
            self.body_motion=ShortWindowBodyMotion(meta['timestamps'],ref,torch.median(state.means,0).values,self.scale)
            H=scaled_head_transform(f['C'],f['F'],self.scale);self.register_buffer('inverse_head_reference',torch.linalg.inv(H))
            # Fixed reference coordinates based on observed neck extent.
            cam=state.means@f['C'][:3,:3].T+f['C'][:3,3];uv=cam@f['K'].T;y=uv[:,1]/uv[:,2]
            if int(self.is_neck.sum())<10:raise ValueError('insufficient_neck_surface')
            top,bottom=torch.quantile(y[self.is_neck],torch.tensor([.05,.95],device=y.device))
            weight=smooth_transition(y,float(top),float(bottom));weight=torch.where(self.is_neck,weight,torch.zeros_like(weight))
            self.register_buffer('neck_weight',weight)
    def patch_state(self,f):
        s=self.patch.state()
        if self.component!='body':return s
        if self.motion_mode=='static':return s
        H=scaled_head_transform(f['C'],f['F'],self.scale)@self.inverse_head_reference
        # Outside the fitted short window, B is explicitly unknown. Identity
        # is only a frozen diagnostic hypothesis and never quality acceptance.
        B=self.body_motion.matrix(f['name']) if f['name'] in self.body_motion.timestamps else torch.eye(4,device='cuda')
        return blend_rigid_state(s,H,B,self.neck_weight)
    def state(self,f,local=False):
        head=pick(self.baseline.head_state(f),self.keep_head)
        if self.component=='hair':head=joined_state(head,self.patch.state())
        if local:return head
        if f['C'] is None:raise ValueError('no_world_observation')
        states=[head.to_world(f['C'],f['F'],self.scale),pick(self.baseline.room.state(),self.keep_room),pick(self.baseline.body_state(f['name']),self.keep_body)]
        if self.component!='hair':states.append(self.patch_state(f))
        return joined_state(*states)
    def render(self,frame,stage='T2'):
        f=self.baseline.adjusted_frame(frame);local=stage=='T0';s=self.state(f,local)
        h,w=f['rgb'].shape[:2];return draw(s,f['F'] if local else f['C'],f['K'],w,h,unit_scale=1 if local else self.scale)


@torch.no_grad()
def assess(model,data,names,masks,out,*,local=False):
    out.mkdir(exist_ok=False);rows={};records={}
    for name in names:
        f=make_frame(data,name,crop=False)
        if not local and f['C'] is None:continue
        r=model.render(f,'T0' if local else 'T2');rgb=r['rgb'].cpu().numpy();q=r['q'].cpu().numpy();target=data['rgb'][name]
        panels=[target,np.clip(rgb,0,1)];cv2.imwrite(str(out/(name+'.jpg')),cv2.cvtColor((np.concatenate(panels,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        rows[name]={}
        for label,index in [('face',1),('hair',2),('neck',4),('cloth',4),('room',0)]:
            mask=masks[name][label]
            if not mask.any():continue
            alpha=q[...,index];wrong=q[...,0] if label=='face' else (q[...,4] if label in ('hair','room') else np.zeros_like(alpha))
            records[name+':'+label]=dict(rgb=rgb,alpha=alpha,target=target,foreground=wrong,mask=mask)
            rows[name][label]=dict(rgb=float(np.abs(rgb-target).mean(-1)[mask].mean()),alpha=float(alpha[mask].mean()),alphaBelow08=float((alpha[mask]<.8).mean()),wrongForeground=float(wrong[mask].mean()))
        if float((r['q'].sum(-1)-r['alpha']).abs().max())>1e-4:raise ValueError('contribution_conservation')
        np.savez_compressed(out/(name+'.npz'),rgb=rgb,alpha=r['alpha'].cpu().numpy(),q=q)
    save_json(out/'metrics.json',rows);return records,rows


def run(stage,surface,out,steps=240,motion_mode='transition'):
    start=time.perf_counter();out=Path(out);torch.manual_seed(93061);np.random.seed(93061)
    data,plan,base,contract=load_stage(stage,out);folder=Path(surface);meta=json.loads((folder/'result.json').read_text());a=dict(np.load(folder/'surface.npz'))
    if str(a['source_hash'])!=data['sourceHash'] or meta['sourceHash']!=data['sourceHash']:raise ValueError('surface_source_mismatch')
    names=meta['names'];component=meta['component'];local=component=='hair'
    if set(names)&set(plan['development']+plan['audit']) or any(data['local'][n]['role']!='train' for n in names):raise ValueError('role_leak')
    eval_names=list(dict.fromkeys(names+[n for n in plan['development']+plan['audit'] if local or n in data['worlds']]))
    masks=physical_masks(contract['spec']['prepared'],data,eval_names)
    hi,ri=replacement_proposal(base,data,masks,names,a,component);bi=np.empty(0,int)
    if component=='body':
        from run_guarded_body_recovery import parent_scope
        bi=parent_scope(base,data,names)
    model=ContinuityStage(base,data,meta,a,hi,ri,bi,motion_mode);frozen=exact_state_hash(base)
    for p in model.parameters():p.requires_grad_(False)
    before={n:p.detach().clone() for n,p in model.patch.named_parameters()}
    rates={'sh':.002,'opacity':.006,'log_scales':.0015,'quats':.0003,'offset':.001}
    ops={n:torch.optim.Adam([getattr(model.patch,n)],lr=v) for n,v in rates.items()}
    if model.body_motion is not None and motion_mode=='transition':ops['motion']=torch.optim.Adam([model.body_motion.velocity],lr=.004)
    sampler=FrameSampler(names,93061);config=dict(steps=steps,seed=93061,component=component,motionMode=motion_mode,nativeFullFrame=True,allComponentsVisible=not local,localHeadResearch=local,geometryStart=40,geometryStop=160,geometryEvery=4,topology='finite observed surface transaction; no density',frozenBaseline=True,retiredHead=hi.tolist(),retiredRoom=ri.tolist(),retiredBody=bi.tolist(),motion='bounded shared short-window photometric hypothesis' if component=='body' else 'unchanged',outsideWindowMotion='unknown; frozen identity diagnostic, not extrapolation',published=False)
    for n in ('run_continuity_surface_repair.py','reconstruction_continuity_surface.py','build_continuity_candidates.py'):shutil.copyfile(Path(__file__).with_name(n),out/'algorithm-source'/n)
    contract.update(surfaceHash=sha(folder/'surface.npz'),sources={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')});save_json(out/'contract.json',contract);save_json(out/'config.json',config)
    extra=dict(config=config,arrays=a,meta=meta,roomMetadata=base.room.metadata,bodySources=base.body_sources)
    def save(label,step):save_checkpoint(out/(label+'.pt'),model,ops,{'views':sampler},stage='continuous_'+component,step=step,contract=contract,strategy={'events':[],'topology':'explicit replacement'},extra=extra)
    save('initial',0);old,old_metrics=assess(base,data,eval_names,masks,out/'baseline-images',local=local);_,init=assess(model,data,eval_names,masks,out/'initial-images',local=local)
    initial={n:p.detach().clone() for n,p in model.patch.named_parameters()};curve=[];torch.cuda.reset_peak_memory_stats();train_start=time.perf_counter()
    labels=('neck','cloth') if component=='body' else (component,)
    for step in range(1,steps+1):
        geometry=config['geometryStart']<=step<=config['geometryStop'] and step%config['geometryEvery']==0
        for n in rates:getattr(model.patch,n).requires_grad_(geometry if n=='offset' else not geometry)
        if model.body_motion is not None:model.body_motion.velocity.requires_grad_(geometry and motion_mode=='transition')
        for op in ops.values():op.zero_grad(set_to_none=True)
        name=sampler.next();f=make_frame(data,name,crop=False);r=model.render(f,'T0' if local else 'T2');err=(r['rgb']-f['rgb']).abs().mean(-1);loss=err.sum()*0
        for label in labels:
            mask=torch.as_tensor(masks[name][label],device='cuda');index=4 if component=='body' else (2 if local else 0)
            if not mask.any():continue
            loss+=masked_mean(err,mask)+.12*valid_window_structure(r['rgb'],f['rgb'],mask)+.2*pixel_structure(r['rgb'],f['rgb'],mask)+.025*masked_mean((1-r['q'][...,index]).square(),mask)
        # Protect other observed parts; do not preserve an old wrong-room RGB.
        forbidden=torch.as_tensor(masks[name]['face'],device='cuda')
        index=4 if component=='body' else (2 if local else 0)
        loss+=.05*masked_mean(r['q'][...,index].square(),forbidden)+model.patch.regularizer()
        if geometry and len(model.edges):loss+=.005*(model.patch.offset[model.edges[:,0]]-model.patch.offset[model.edges[:,1]]).square().mean()
        if model.body_motion is not None:loss+=.01*model.body_motion.regularizer()
        if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
        loss.backward()
        for n,p in model.named_parameters():
            if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient:'+n)
        if geometry:
            ops['offset'].step()
            if 'motion' in ops:ops['motion'].step()
        else:
            for n in rates:
                if n!='offset':ops[n].step()
        with torch.no_grad():model.patch.log_scales.copy_(torch.maximum(torch.minimum(model.patch.log_scales,initial['log_scales']+np.log(1.25)),initial['log_scales']-np.log(1.25)))
        if step==1 or step%40==0:
            row=dict(step=step,name=name,geometry=geometry,loss=float(loss.detach()));curve.append(row);print(json.dumps(row),flush=True)
        if step==steps//2:save('mid',step)
        if time.perf_counter()-train_start>900 or torch.cuda.memory_allocated()/1048576>7100:raise ValueError('finite_resource_budget')
    save('candidate-final',steps);new,final=assess(model,data,eval_names,masks,out/'final-images',local=local)
    screen=compare_patch_views(old,new)
    if exact_state_hash(base)!=frozen:raise ValueError('frozen_baseline_changed')
    # Local hair gets an additional full-scene screen; never equate black-head
    # research quality with its world composition.
    full_screen=None
    if local:
        world_names=[n for n in eval_names if n in data['worlds']]
        ob,_=assess(base,data,world_names,masks,out/'baseline-full',local=False)
        ne,_=assess(model,data,world_names,masks,out/'final-full',local=False);full_screen=compare_patch_views(ob,ne)
    reference=model.body_motion.reference if model.body_motion is not None else data['reference']
    ref=base.adjusted_frame(make_frame(data,reference,crop=False));s=model.state(ref);export_state(s,out/'candidate-research-only.ply')
    result=dict(sourceHash=data['sourceHash'],config=config,baseline=old_metrics,initial=init,final=final,screen=screen,fullScreen=full_screen,curve=curve,parameterChanges={n:float((p.detach()-before[n]).abs().mean()) for n,p in model.patch.named_parameters()},motionVelocity=model.body_motion.velocity.detach().cpu().tolist() if model.body_motion else None,geometrySupported=False,transactionAccepted=False,baselineExact=True,seconds=time.perf_counter()-start,trainingAndFinalEvaluationSeconds=time.perf_counter()-train_start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,assetHash=sha(out/'candidate-research-only.ply'),pointCount=len(s.means),releaseQualityPassed=False,published=False)
    save_json(out/'result.json',result)
    oldhead=base.portrait.stable_uid[model.keep_head].cpu().numpy();oldroom=base.room.metadata['point_uid'][model.keep_room].cpu().numpy();oldbody=np.flatnonzero(model.keep_body.cpu().numpy())
    parts=[(oldhead,0)]
    if local:parts.append((a['uid'],3))
    parts.extend([(oldroom,1),(oldbody,2)])
    if not local:parts.append((a['uid'],3))
    uid=np.concatenate([u for u,_ in parts]);namespace=np.concatenate([np.full(len(u),k,np.int64) for u,k in parts])
    if len(uid)!=len(s.means) or len(np.unique(np.c_[namespace,uid],axis=0))!=len(uid):raise ValueError('asset_order_contract')
    np.savez_compressed(out/'candidate-identities.npz',asset_hash=np.array(result['assetHash']),source_hash=np.array(data['sourceHash']),point_id=np.arange(len(s.means)),component=s.parts.cpu().numpy(),source_uid=uid,source_namespace=namespace,reference=np.array(reference))
    inv=torch.linalg.inv(ref['C']).cpu().numpy();eye=inv[:3,3];forward=inv[:3,2];up=-inv[:3,1];h,w=ref['rgb'].shape[:2]
    save_json(out/'display.json',dict(assets=[dict(label=component+'-'+motion_mode,ply=str((out/'candidate-research-only.ply').resolve()),hash=result['assetHash'],count=len(s.means))],K=ref['K'].cpu().tolist(),C=ref['C'].cpu().tolist(),width=w,height=h,camera=eye.tolist(),target=(eye+forward).tolist(),up=up.tolist(),near=.01*model.scale,far=1e10*model.scale,reference=reference,sourceHash=data['sourceHash'],published=False))
    result['reference']=reference;save_json(out/'result.json',result)
    restore_checkpoint(out/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda');save('restored',0)
    if exact_state_hash(base)!=frozen:raise ValueError('rollback_baseline_changed')
    print(json.dumps({k:result[k] for k in ('seconds','allocatedMiB','reservedMiB','pointCount','transactionAccepted')}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('stage','surface','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--steps',type=int,default=240);p.add_argument('--motion-mode',choices=['static','transition'],default='transition');a=p.parse_args()
    if Path(a.out).exists():raise FileExistsError('independent_run_required')
    try:run(a.stage,a.surface,a.out,a.steps,a.motion_mode)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise
