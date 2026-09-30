"""Frozen-context native clothing surface recovery with research-only rollback.
DA3 body geometry remains a static short-window hypothesis, not solved motion.
Existing head (incl. neck/glasses/hair) and room always share T2 compositing.
"""
import argparse,json,time,shutil
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_evidence_stage import load_stage
from reconstruction_components_v3 import FreeComponent,pick,save_json,sha,exact_state_hash
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_detail_controlled import pixel_structure
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint
from reconstruction_patch_transaction import compare_patch_views,PatchTransaction
from run_haze_shared_surface import export_state


class BodySurfaceStage(torch.nn.Module):
    def __init__(self,baseline,arrays,retired):
        super().__init__();self.baseline=baseline;self.scale=baseline.scale
        t=lambda x,dtype=torch.float32:torch.as_tensor(x,device='cuda',dtype=dtype)
        s=GaussianState(*(t(arrays[k],torch.long if k=='parts' else torch.float32) for k in ('means','quats','scales','opacity','sh','parts')))
        self.patch=FreeComponent(s,t(arrays['uid'],torch.long),t(arrays['support']),'world-reference',torch.median(s.scales[:,:2])*1.5)
        self.register_buffer('keep_body',torch.ones(len(baseline.body['means']),dtype=torch.bool,device='cuda'))
        self.keep_body[torch.as_tensor(retired,device='cuda',dtype=torch.long)]=False
    def render(self,f,stage='T2'):
        if stage=='T0':return self.baseline.render(f,'T0')
        f=self.baseline.adjusted_frame(f)
        if f['C'] is None:raise ValueError('no_measured_world_C')
        state=joined_state(self.baseline.head_state(f).to_world(f['C'],f['F'],self.scale),self.baseline.room.state(),pick(self.baseline.body_state(f['name']),self.keep_body),self.patch.state())
        h,w=f['rgb'].shape[:2];return draw(state,f['C'],f['K'],w,h,unit_scale=self.scale)
    def reference_state(self,f):
        f=self.baseline.adjusted_frame(f)
        return joined_state(self.baseline.head_state(f).to_world(f['C'],f['F'],self.scale),self.baseline.room.state(),pick(self.baseline.body_state(f['name']),self.keep_body),self.patch.state())


@torch.no_grad()
def parent_scope(base,data,names):
    """Retire only old body kernels whose ACTUAL gsplat projected radius bounds
    fit into the reliable body mask in every chosen observation. Not centres.
    This conservative scope is a proposal; actual complete-scene checks decide.
    """
    n=len(base.body['means']);votes=np.zeros(n,int);unsafe=np.zeros(n,bool)
    for name in names:
        f=make_frame(data,name,crop=False);body=base.body_state(name);h,w=f['rgb'].shape[:2]
        info=draw(body,f['C'],f['K'],w,h,unit_scale=base.scale)['info']
        ids=info['gaussian_ids'].cpu().numpy();uv=info['means2d'].cpu().numpy();r=info['radii'].cpu().numpy()
        if uv.ndim==3:uv=uv[0]
        radius=r.max(-1) if r.ndim==2 else r
        mask=(f['masks']['neck_cloth_visible']&~f['masks']['unknown_or_occluded']).cpu().numpy().astype(np.uint8)
        distance=cv2.distanceTransform(mask,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)
        for i,p,rad in zip(ids,uv,radius):
            x,y=np.rint(p).astype(int)
            if rad<=0:continue
            safe=0<=x<w and 0<=y<h and distance[y,x]>float(rad)+2
            votes[int(i)]+=int(safe);unsafe[int(i)]|=not safe
    return np.flatnonzero((votes==len(names))&~unsafe)


@torch.no_grad()
def assess(model,data,names,out):
    out.mkdir(exist_ok=False);records={};stats={}
    for name in names:
        f=make_frame(data,name,crop=False);r=model.render(f,'T2');m=f['masks'];valid=~m['unknown_or_occluded']
        image=np.concatenate([f['rgb'].cpu().numpy(),r['rgb'].clamp(0,1).cpu().numpy()],axis=1)
        cv2.imwrite(str(out/(name+'.jpg')),cv2.cvtColor((image*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        rgb=r['rgb'].cpu().numpy();target=f['rgb'].cpu().numpy();q=r['q'].cpu().numpy();row={}
        for label,mask,indices in [('cloth',m['neck_cloth_visible'],[4]),('face',m['face_core']|m['face_boundary'],[1]),('hair',m['hair_visible'],[2]),('glasses',m['glasses_visible'],[3]),('room',m['room_visible'],[0])]:
            mask=(mask&valid).cpu().numpy()
            if not mask.any():continue
            alpha=q[...,indices].sum(-1);wrong=q[...,4] if label in ('face','hair','glasses','room') else np.zeros_like(alpha)
            records[name+':'+label]=dict(rgb=rgb,alpha=alpha,target=target,foreground=wrong,mask=mask)
            row[label]=dict(rgb=float(np.abs(rgb-target).mean(-1)[mask].mean()),alpha=float(alpha[mask].mean()),missing=float((alpha[mask]<.8).mean()))
        stats[name]=row
    save_json(out/'metrics.json',stats);return records,stats


def run(manifest,surface,out,steps=240):
    start=time.perf_counter();out=Path(out);data,plan,base,contract=load_stage(manifest,out)
    for n in ('run_guarded_body_recovery.py','reconstruction_patch_transaction.py','build_body_surface_hypothesis.py'):shutil.copyfile(Path(__file__).with_name(n),out/'algorithm-source'/n)
    surface=Path(surface);meta=json.loads((surface/'result.json').read_text());arr=dict(np.load(surface/'body-world.npz'))
    if str(arr['source_hash'])!=data['sourceHash'] or meta['sourceHash']!=data['sourceHash']:raise ValueError('body_source_mismatch')
    names=meta['names'];forbidden=set(plan['development']+plan['audit'])
    if set(names)&forbidden or any(data['local'][n]['role']!='train' or n not in data['worlds'] for n in names):raise ValueError('body_role_or_world_camera_invalid')
    retired=parent_scope(base,data,names);trial=BodySurfaceStage(base,arr,retired);sampler=FrameSampler(names,93043)
    for p in trial.parameters():p.requires_grad_(False)
    rates={'sh':.003,'opacity':.008,'log_scales':.002,'quats':.0005};ops={k:torch.optim.Adam([getattr(trial.patch,k)],lr=v) for k,v in rates.items()}
    for k in rates:getattr(trial.patch,k).requires_grad_(True)
    contract.update(surfaceHash=sha(surface/'body-world.npz'),geometrySupported=meta['geometrySupported'],sources={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')})
    config=dict(steps=steps,seed=93043,nativeFullFrame=True,allComponentsVisible=True,staticBodyHypothesis=True,offsetFrozen=True,baselineFrozen=True,topology='fixed',density='disabled finite representation study',retiredParents=retired.tolist(),published=False)
    save_json(out/'config.json',config);save_json(out/'contract.json',contract)
    baseHash=exact_state_hash(base);before={n:p.detach().clone() for n,p in trial.patch.named_parameters()};initial_scales=trial.patch.log_scales.detach().clone()
    extra=dict(config=config,sourceArrays=arr,roomMetadata=base.room.metadata,bodySources=base.body_sources)
    def save(label,step):save_checkpoint(out/(label+'.pt'),trial,ops,{'body':sampler},stage='guarded_body_recovery',step=step,contract=contract,strategy={'topology':'fixed','events':[]},extra=extra)
    save('initial',0)
    save_checkpoint(out/'original-context.pt',base,{}, {'body':sampler},stage='original_context_before_trial',step=0,contract=contract,strategy={'topology':'original_R0','events':[]},extra=dict(sourceCheckpoint=contract['spec']['checkpoint'],sourceCheckpointHash=contract['checkpointHash'],sourceOptimizer='not_resumed; original source checkpoint retained',roomMetadata=base.room.metadata,bodySources=base.body_sources))
    # The selected training window plus all original reliable dev/reg world views.
    evalNames=list(dict.fromkeys(names+[n for n in plan['development']+plan['audit'] if n in data['worlds']]))
    oldRecords,oldMetrics=assess(base,data,evalNames,out/'R0-images');_,initMetrics=assess(trial,data,evalNames,out/'initial-images')
    torch.cuda.reset_peak_memory_stats();curve=[];trainStart=time.perf_counter()
    for step in range(1,steps+1):
        for op in ops.values():op.zero_grad(set_to_none=True)
        f=make_frame(data,sampler.next(),crop=False);r=trial.render(f,'T2');m=f['masks'];valid=m['neck_cloth_visible']&~m['unknown_or_occluded']
        error=(r['rgb']-f['rgb']).abs().mean(-1)
        loss=masked_mean(error,valid)+.25*valid_window_structure(r['rgb'],f['rgb'],valid)+.25*pixel_structure(r['rgb'],f['rgb'],valid)+.04*masked_mean((1-r['q'][...,4]).square(),valid)+trial.patch.regularizer()
        outside=(m['face_core']|m['face_boundary']|m['hair_visible']|m['glasses_visible']|m['room_visible'])&~m['unknown_or_occluded']
        loss+=.05*masked_mean(r['q'][...,4].square(),outside)
        if not torch.isfinite(loss):raise ValueError('nonfinite_body_loss')
        loss.backward()
        for n,p in trial.named_parameters():
            if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_body_gradient:'+n)
        for op in ops.values():op.step()
        with torch.no_grad():trial.patch.log_scales.copy_(torch.maximum(torch.minimum(trial.patch.log_scales,initial_scales+np.log(1.25)),initial_scales-np.log(1.25)))
        if step==1 or step%40==0:row=dict(step=step,name=f['name'],loss=float(loss.detach()));curve.append(row);print(json.dumps(row),flush=True)
        if step==steps//2:save('mid',step)
        if time.perf_counter()-trainStart>600 or torch.cuda.memory_allocated()/1048576>7100:raise ValueError('finite_body_resource_budget')
    save('candidate-final',steps);newRecords,newMetrics=assess(trial,data,evalNames,out/'final-images');screen=compare_patch_views(oldRecords,newRecords)
    if exact_state_hash(base)!=baseHash:raise ValueError('frozen_context_changed')
    # Identity transaction: surviving old fields remain exact. New UIDs never
    # alias the old body index namespace. Full checkpoint carries optimizer/RNG.
    ref=base.body_state(data['reference']);old={k:getattr(ref,k).cpu().numpy() for k in GaussianState.__dataclass_fields__};old['uid']=np.arange(len(ref.means),dtype=np.int64)
    new={k:getattr(trial.patch.state(),k).detach().cpu().numpy() for k in GaussianState.__dataclass_fields__};new['uid']=arr['uid']
    transaction=PatchTransaction(old,retired,new);chosen=transaction.decide(screen,geometry_supported=meta['geometrySupported'])
    save_json(out/'screen.json',screen);np.savez_compressed(out/'decision-body.npz',**chosen,source_hash=np.array(data['sourceHash']))
    f=make_frame(data,data['reference'],crop=False);export_state(trial.reference_state(f),out/'candidate-research-only.ply')
    result=dict(sourceHash=data['sourceHash'],names=names,pointCount=len(arr['means']),retiredParents=len(retired),curve=curve,baseline=oldMetrics,initial=initMetrics,final=newMetrics,screenPassed=screen['passed'],failures=screen['failures'],geometrySupported=meta['geometrySupported'],transactionAccepted=transaction.decision,baselineExact=True,parameterChanges={n:float((p.detach()-before[n]).abs().mean()) for n,p in trial.patch.named_parameters()},seconds=time.perf_counter()-start,trainingSeconds=time.perf_counter()-trainStart,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,assetHash=sha(out/'candidate-research-only.ply'),releaseQualityPassed=False,published=False)
    if not transaction.decision:
        restore_checkpoint(out/'initial.pt',trial,ops,{'body':sampler},contract=contract,device='cuda');save('restored-trial-initial',0)
        restore_checkpoint(out/'original-context.pt',base,{}, {'body':sampler},contract=contract,device='cuda')
        if exact_state_hash(base)!=baseHash:raise ValueError('original_context_rollback_changed')
        save_checkpoint(out/'restored-original.pt',base,{}, {'body':sampler},stage='rejected_trial_original_context',step=0,contract=contract,strategy={'topology':'original_R0','events':[]},extra=dict(roomMetadata=base.room.metadata,bodySources=base.body_sources,sourceCheckpointHash=contract['checkpointHash']))
        result['originalContextRestored']=True
    save_json(out/'result.json',result)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('stage','surface','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.stage,a.surface,a.out)
