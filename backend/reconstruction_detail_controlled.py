"""Bounded native-pixel refinement; isolated research, no production importer.

Geometry/component labels remain hypotheses. Original RGB is never sharpened.
Reuses gsplat 1.5.3 and the previous full-state/lineage implementation.
"""
from __future__ import annotations
import copy,json,math,time
from pathlib import Path
import cv2
import numpy as np
import torch
import torch.nn.functional as F
from reconstruction_portrait_model import GaussianState,CandidateTransaction,joined_state
from reconstruction_portrait_priority import (ResearchModel,face_optimizer,face_regularizer,
    set_face_phase,pose_landmark_loss,child_support,check_budget)
from reconstruction_portrait_pipeline import make_frame,draw,head_loss,metrics,masked_mean
from reconstruction_reference_static import BudgetedStaticStrategy,static_loss,static_regularization,valid_static_mask,valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,rng_state,restore_rng,replace_face_with_lineage
from reconstruction_components_v3 import save_json,exact_state_hash
from reconstruction_fullframe import draw_frame

COMPONENTS=('skin_face','hair','glasses','neck_shoulders','clothing_upper')


def pixel_structure(prediction,target,mask):
    """Actual signed pixel differences, only where BOTH pixels are observed.
    No edges formed against fabricated black, no postprocess contrast/texture.
    """
    total=prediction.sum()*0
    for dim in (0,1):
        a=[slice(None)]*3;b=a.copy();a[dim]=slice(1,None);b[dim]=slice(None,-1)
        ma=[slice(None)]*2;mb=ma.copy();ma[dim]=slice(1,None);mb[dim]=slice(None,-1)
        valid=mask[tuple(ma)]&mask[tuple(mb)]
        err=((prediction[tuple(a)]-prediction[tuple(b)])-(target[tuple(a)]-target[tuple(b)])).abs().mean(-1)
        total+=masked_mean(err,valid)*.5
    return total


@torch.no_grad()
def component_votes(model,data,names):
    p=model.portrait;n=len(p.role);d=p.sh.device;votes=torch.zeros(n,4,device=d,dtype=torch.long)
    for name in names:
        f=make_frame(data,name);s=p.local_state(f['mesh']);xyz=s.means@f['F'][:3,:3].T+f['F'][:3,3]
        uv=xyz@f['K'].T;uv=uv[:,:2]/uv[:,2:].clamp_min(1e-8);x=uv[:,0].round().long();y=uv[:,1].round().long()
        h,w=f['rgb'].shape[:2];inside=(xyz[:,2]>.05)&(x>=0)&(x<w)&(y>=0)&(y<h)
        x=x.clamp(0,w-1);y=y.clamp(0,h-1);m=f['masks'];inside&=~m['unknown_or_occluded'][y,x]
        for i,key in enumerate(('face_core','hair_visible','glasses_visible','neck_cloth_visible')):
            votes[:,i]+=(inside&m[key][y,x]).long()
    # Classification of existing hypotheses is not independent visibility/depth.
    labels=torch.zeros(n,device=d,dtype=torch.long);labels[p.role==2]=1
    count=votes.sum(1).clamp_min(1);strong=lambda k:(votes[:,k]>=3)&(votes[:,k].float()/count>.6)&(p.role!=2)
    labels[strong(2)]=2;labels[strong(3)]=3
    origins=p.origin_index
    if len(origins.unique())!=n:raise ValueError('initial_component_origin_identity_required')
    table=torch.full((int(origins.max())+1,),-1,device=d,dtype=torch.long);table[origins]=labels
    return table,votes


class DetailModel(ResearchModel):
    def enable_components(self,data,names):
        table,votes=component_votes(self,data,names);self.register_buffer('component_origin',table)
        self.register_buffer('component_votes_initial',votes)
        # Existing glasses points can move in three head-local dimensions,
        # independently of skin normal. This does NOT solve unseen frame arms.
        self.glasses_local=torch.nn.Parameter(torch.zeros(len(table),3,device=table.device))
        metric=torch.zeros(len(table),device=table.device);metric[self.portrait.origin_index]=self.portrait.metric_per_pixel.detach()
        self.register_buffer('glass_metric_origin',metric)
    def head_state(self,frame):
        p=self.portrait;s=p.local_state(frame['mesh']);fine=self.component_origin[p.origin_index]
        glass=fine==2
        delta=self.glasses_local[p.origin_index].tanh()*self.glass_metric_origin[p.origin_index,None]*3/math.sqrt(3)
        means=s.means+delta*glass[:,None]
        parts=torch.ones_like(fine);parts[fine==1]=2;parts[glass]=3;parts[fine==3]=4
        return GaussianState(means,s.quats,s.scales,s.opacity,s.sh,parts)
    def render(self,frame,stage):
        f=self.adjusted_frame(frame);head=self.head_state(f);h,w=f['rgb'].shape[:2]
        if stage=='T0':return draw_frame(head,f['F'],f)
        if f['C'] is None:raise ValueError('no_measured_world_camera')
        head=head.to_world(f['C'],f['F'],self.scale)
        if stage!='T1':head=joined_state(head,self.room.state(),self.body_state(f['name']))
        return draw_frame(head,f['C'],f,unit_scale=self.scale)
    def component_manifest(self):
        labels=self.component_origin[self.portrait.origin_index]
        return {'counts':{k:int((labels==i).sum()) if i<4 else len(self.body['means']) for i,k in enumerate(COMPONENTS)},
            'semantics':'training-only projected votes; not independent depth or segmentation truth',
            'hair':'head-local free offset; legacy volume still unvalidated',
            'glasses':'bounded independent 3D offset on inherited seeds; absent if no reliable votes',
            'neck_shoulders':'observed existing bound neck subset; shoulder geometry not solved',
            'clothing_upper':'measured body seeds, not secretly room; semantic neck/cloth ambiguity remains',
            'pointInheritance':'origin_index retained through real parent replacement'}


def face_detail_loss(rendered,frame):
    base,report=head_loss(rendered,frame);m=frame['masks']
    valid=(m['face_core']|m['face_boundary']|m['glasses_visible'])&~m['unknown_or_occluded']
    structure=valid_window_structure(rendered['rgb'],frame['rgb'],valid)
    gradients=pixel_structure(rendered['rgb'],frame['rgb'],valid)
    return base+.25*structure+.35*gradients,{**report,'validSSIM':float(structure.detach()),'signedEdgeError':float(gradients.detach())}


@torch.no_grad()
def evaluate_face(model,data,plan,out):
    out.mkdir(exist_ok=False);rows={}
    names=plan['development']+plan['audit']+plan.get('new_audit',[])+[plan['train'][0]]
    for name in names:
        f=make_frame(data,name);r=model.render(f,'T0');m=metrics(r,f)
        use='train' if name in plan['train'] else 'new_audit' if name in plan.get('new_audit',[]) else 'review_audit' if name in plan['audit'] else 'development'
        m.update(use=use,crop=f['rectangle'],K=f['K'].cpu().tolist(),F=model.adjusted_frame(f)['F'].cpu().tolist())
        valid=f['masks']['face_core']|f['masks']['face_boundary']|f['masks']['glasses_visible']
        m['face']['edgeError']=float(pixel_structure(r['rgb'],f['rgb'],valid));m['face']['structure']=float(valid_window_structure(r['rgb'],f['rgb'],valid))
        from reconstruction_shared_v2 import boxes
        local={};a,b,c,d=f['rectangle']
        for key,box in boxes(data,name).items():
            if box is None:continue
            x0,y0,x1,y1=box;x0=max(0,x0-a);x1=min(c-a,x1-a);y0=max(0,y0-b);y1=min(d-b,y1-b)
            if x1<=x0 or y1<=y0:continue
            mask=(f['masks']['hair_visible'] if key=='hair' else valid)[y0:y1,x0:x1]
            err=(r['rgb'][y0:y1,x0:x1]-f['rgb'][y0:y1,x0:x1]).abs().mean(-1)
            local[key]=float(masked_mean(err,mask))
        m['local']=local;rows[name]=m
        np.savez_compressed(out/(name+'.npz'),rgb=r['rgb'].cpu().numpy(),q=r['q'].cpu().numpy(),alpha=r['alpha'].cpu().numpy())
        image=np.concatenate([f['rgb'].cpu().numpy(),r['rgb'].clamp(0,1).cpu().numpy()],1)
        cv2.imwrite(str(out/name),cv2.cvtColor((image*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    save_json(out/'metrics.json',rows);return rows


def train_portrait(model,data,plan,c,out,contract):
    optimizer=face_optimizer(model);poseopt=torch.optim.Adam(model.pose.parameters(),lr=.003)
    glassesopt=torch.optim.Adam([model.glasses_local],lr=.002)
    sampler=FrameSampler(plan['train'],c['seed']);optim={'face':optimizer,'pose':poseopt,'glasses':glassesopt}
    start=time.perf_counter();events=[];curve=[];initial={n:p.detach().clone() for n,p in model.named_parameters()}
    def save(label,step):save_checkpoint(out/(label+'.pt'),model,optim,{'face':sampler},stage='portrait_refine_v1',step=step,contract=contract,
        extra={'events':events,'plan':plan,'components':model.component_manifest(),'roomMetadata':model.room.metadata,'bodySources':model.body_sources})
    save('initial',0);evaluate_face(model,data,plan,out/'initial-images')
    def update(step,recovery=False):
        geometry=set_face_phase(model.portrait,step,recovery)
        model.pose.delta.requires_grad_(not recovery and step>=180 and step%4==1)
        model.glasses_local.requires_grad_(geometry)
        for op in optim.values():op.zero_grad(set_to_none=True)
        records=[]
        # Accumulate two different angular-stratified observations before Adam;
        # no extra hidden optimizer steps and no held-out colour gradients.
        for _ in range(2):
            f=make_frame(data,sampler.next());r=model.render(f,'T0');image,parts=face_detail_loss(r,f)
            landmarks,lr=pose_landmark_loss(model,data,f)
            loss=image+face_regularizer(model.portrait,f)+.003*landmarks+.0005*model.pose.regularizer()
            loss+=.0003*model.glasses_local.tanh().square().mean()
            if not torch.isfinite(loss):raise RuntimeError('nonfinite_face_refinement')
            (loss*.5).backward();records.append({'name':f['name'],**parts,**lr})
        torch.nn.utils.clip_grad_norm_(model.portrait.parameters(),10.)
        for op in optim.values():op.step()
        if geometry:model.portrait.walk(optimizer)
        return {'step':step,'views':records,'geometryUpdated':geometry}
    @torch.no_grad()
    def coverage():
        ans={}
        for n in plan['development']+[plan['train'][0]]:
            f=make_frame(data,n);v=metrics(model.render(f,'T0'),f)['face'];ans[n]={'hole':v['hole'],'rgb':v['fixedRgbL1']}
        return ans
    for step in range(1,c['face_steps']+1):
        check_budget(start,c);row=update(step)
        if step in c['face_split_steps']:
            p=model.portrait;n=p.surface_count;grad=p.sh.grad[:n].norm(dim=(1,2));width=p.log_scales[:n].detach().exp().max(1).values/p.metric_per_pixel[:n]
            eligible=torch.where((p.role[:n]==0)&(model.component_origin[p.origin_index[:n]]==0)&(width>1.5)&(grad>0))[0]
            ids=eligible[torch.argsort(grad[eligible]*width[eligible],descending=True)[:c['face_split_parents']]]
            if len(ids):
                rng=rng_state();ss=copy.deepcopy(sampler.state_dict());extra={k:v.detach().clone() for k,v in model.named_parameters() if not k.startswith('portrait.')}
                try:
                    with CandidateTransaction(p,optimizer) as tx:
                        event=tx.run(lambda:replace_face_with_lineage(p,optimizer,ids,lambda t,b:child_support(model,data,plan['train'],t,b)),
                            lambda i:update(step,True),coverage,recovery_steps=c['recovery_steps'])
                except ValueError as exc:event={'accepted':False,'reason':str(exc)}
                # Recovery freezes pose/glasses; verify transaction scope.
                for k,v in extra.items():
                    if not torch.equal(v,dict(model.named_parameters())[k].detach()):raise RuntimeError('recovery_changed_external_parameters:'+k)
                if not event['accepted']:restore_rng(rng);sampler.load_state_dict(ss)
                events.append({'step':step,**event})
        if step%50==0 or step==1:curve.append(row);print(json.dumps({'stage':'portrait',**row}),flush=True)
        if step==c['face_steps']//2:save('mid',step)
    save('final',c['face_steps']);evaluate_face(model,data,plan,out/'final-images')
    changes={n:{'beforeShape':list(initial[n].shape),'afterShape':list(v.shape),
        'meanAbsChange':float((v.detach()-initial[n]).abs().mean()) if v.shape==initial[n].shape else None} for n,v in model.named_parameters()}
    result={'steps':c['face_steps'],'recoverySteps':sum(e.get('recoverySteps',0) for e in events),'viewsPerStep':2,
        'seconds':time.perf_counter()-start,'events':events,'curve':curve,'changes':changes,'components':model.component_manifest(),'published':False}
    save_json(out/'result.json',result);return result


class NativeStaticStrategy(BudgetedStaticStrategy):
    """Pinned AbsGS statistics, locally bounded replacement, no global scale shrink."""
    def __init__(self,**kw):
        super().__init__(**kw);self.absgrad=True;self.grow_grad2d=.0008
        self.refine_scale2d_stop_iter=self.refine_stop_iter;self.grow_scale2d=.025
    @torch.no_grad()
    def _grow_gs(self,params,optimizers,state,step):
        from gsplat.strategy.ops import duplicate,split
        n=len(params['means']);limit=min(self.max_growth,self.max_points-n)
        if limit<=0:return 0,0
        score=state['grad2d']/state['count'].clamp_min(1)
        eligible=torch.where((score>self.grow_grad2d)&(state['count']>=3))[0]
        ids=eligible[torch.argsort(score[eligible],descending=True)[:limit]]
        large=(params['scales'].exp().max(-1).values>self.grow_scale3d*state['scene_scale'])|(state['radii']>self.grow_scale2d)
        dupli=torch.zeros(n,device=score.device,dtype=torch.bool);dupli[ids[~large[ids]]]=True
        divide=torch.zeros_like(dupli);divide[ids[large[ids]]]=True
        nd=int(dupli.sum());ns=int(divide.sum())
        if nd:
            parent=state['point_uid'][dupli].clone();duplicate(params=params,optimizers=optimizers,state=state,mask=dupli)
            self._assign_child_ids(state,n,nd,parent)
            p=params['opacities'];opa=1-torch.sqrt(1-p[:n][dupli].sigmoid())
            p[torch.where(dupli)[0]]=torch.logit(opa.clamp(1e-6,1-1e-6));p[n:]=torch.logit(opa.clamp(1e-6,1-1e-6))
            for v in optimizers['opacities'].state.get(p,{}).values():
                if isinstance(v,torch.Tensor) and v.shape==p.shape:v[torch.where(dupli)[0]]=0
        if ns:
            divide=torch.cat((divide,torch.zeros(nd,device=score.device,dtype=torch.bool)))
            parent=state['point_uid'][divide].clone().repeat(2);rest=len(divide)-ns
            split(params=params,optimizers=optimizers,state=state,mask=divide,revised_opacity=True)
            self._assign_child_ids(state,rest,2*ns,parent)
        return nd,ns


@torch.no_grad()
def evaluate_room(model,data,out):
    out.mkdir(exist_ok=False);rows={}
    for name in data['development']:
        f=make_frame(data,name,crop=False);h,w=f['rgb'].shape[:2]
        r=draw(model.room.state(),f['C'],f['K'],w,h,unit_scale=data['scale']);_,m=static_loss(r,f)
        valid=valid_static_mask(f);m['edgeError']=float(pixel_structure(r['rgb'],f['rgb'],valid));m['K']=f['K'].cpu().tolist();m['C']=f['C'].cpu().tolist()
        rows[name]=m;np.savez_compressed(out/(name+'.npz'),rgb=r['rgb'].cpu().numpy(),alpha=r['alpha'].cpu().numpy(),q=r['q'].cpu().numpy())
        im=np.concatenate((f['rgb'].cpu().numpy(),r['rgb'].clamp(0,1).cpu().numpy()),1)
        cv2.imwrite(str(out/name),cv2.cvtColor((im*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    save_json(out/'metrics.json',rows);return rows


def train_static(model,data,c,out,contract):
    room=model.room;sampler=FrameSampler(data['train'],c['seed']+1)
    strategy=NativeStaticStrategy(start=c['room_refine_start'],stop=c['room_refine_stop'],every=c['room_refine_every'],
        max_points=c['room_max_points'],max_growth=c['room_max_growth'],reset_steps=c['room_reset_steps'])
    extent=float((room.params['means'].detach()-room.params['means'].detach().median(0).values).norm(dim=1).quantile(.9))
    ops=room.optimizers(extent);strategy.check_sanity(room.params,ops);state=strategy.initialize_for(room,extent)
    scheduler=torch.optim.lr_scheduler.ExponentialLR(ops['means'],gamma=.1**(1/c['room_steps']))
    head_hash=exact_state_hash(model.portrait);start=time.perf_counter();curve=[]
    def save(label,step):save_checkpoint(out/(label+'.pt'),model,{'room_'+k:v for k,v in ops.items()},{'room':sampler},
        stage='room_fullimg_v1',step=step,contract=contract,strategy=state,scheduler=scheduler.state_dict(),extra={'roomMetadata':{k:state[k] for k in room.metadata},'bodySources':model.body_sources})
    save('initial',0);evaluate_room(model,data,out/'initial-images')
    for step in range(1,c['room_steps']+1):
        check_budget(start,c);f=make_frame(data,sampler.next(),crop=False);h,w=f['rgb'].shape[:2]
        for op in ops.values():op.zero_grad(set_to_none=True)
        r=draw(room.state(),f['C'],f['K'],w,h,unit_scale=data['scale'],absgrad=True)
        strategy.step_pre_backward(room.params,ops,state,step,r['info'])
        image,parts=static_loss(r,f);edge=pixel_structure(r['rgb'],f['rgb'],valid_static_mask(f))
        loss=image+.25*edge+static_regularization(room,state)
        if not torch.isfinite(loss):raise RuntimeError('nonfinite_native_static_loss')
        loss.backward();torch.nn.utils.clip_grad_norm_(room.parameters(),10.)
        for op in ops.values():op.step()
        scheduler.step();strategy.step_post_backward(room.params,ops,state,step,r['info'],packed=True)
        if step%50==0 or step==1:
            row={'step':step,'frame':f['name'],'points':len(room.params['means']),'edge':float(edge.detach()),**parts};curve.append(row);print(json.dumps({'stage':'native_room',**row}),flush=True)
        if step==c['room_steps']//2:save('mid',step)
    room.metadata={k:state[k] for k in room.metadata};save('final',c['room_steps']);evaluate_room(model,data,out/'final-images')
    if exact_state_hash(model.portrait)!=head_hash:raise RuntimeError('static_stage_changed_portrait')
    result={'steps':c['room_steps'],'seconds':time.perf_counter()-start,'events':state['events'],'curve':curve,
        'nativeFullImage':True,'actualAbsgrad':True,'postTopologyRecovery':c['room_steps']-c['room_refine_stop'],
        'points':len(room.params['means']),'published':False}
    save_json(out/'result.json',result);return result
