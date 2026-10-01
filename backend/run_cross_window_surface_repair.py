"""Finite actual-MVS hair replacement and equal-budget old-patch control.
Does not alter production: complete frozen scene exported only for diagnostics.
"""
from pathlib import Path
import argparse,json,time,shutil
import numpy as np,torch
from reconstruction_complete_context import load_complete
from build_cross_window_surface import build_surface,retirement
from reconstruction_components_v3 import FreeComponent,pick,sha,save_json,exact_state_hash
from reconstruction_portrait_model import GaussianState,joined_state,quaternion_matrix
from reconstruction_surface_continuity import matrix_quaternion
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,rng_state,restore_rng
from run_measured_head_surface_repair import relative_appearance
from run_continuous_surface_repair import evaluate_complete,regression_screen,export_complete_candidate,write_image

class NativeHairStage(torch.nn.Module):
    def __init__(self,base,data,ids,state,uids,support,candidate):
        super().__init__();self.baseline=base;self.scale=base.scale;self.candidate=candidate
        self.register_buffer('ids',ids);self.register_buffer('head_rows',torch.searchsorted(torch.where(base.keep_head)[0],ids))
        self.patch=FreeComponent(state,uids,support,'head-local',0.)
        self.register_buffer('initial_rotation',quaternion_matrix(state.quats).detach().clone());self.register_buffer('initial_scales',state.scales.detach().clone());self.register_buffer('initial_opacity',state.opacity.detach().clone());self.register_buffer('initial_sh',state.sh.detach().clone())
    def head_patch(self,f):
        p=self.patch.state()
        if self.candidate:return p
        current=pick(self.baseline.baseline.head_state(f),self.ids)
        s=relative_appearance(current,p,self.initial_scales,self.initial_opacity,self.initial_sh,self.patch.opacity)
        q=matrix_quaternion(quaternion_matrix(current.quats)@self.initial_rotation.transpose(-1,-2)@quaternion_matrix(p.quats))
        return GaussianState(s.means,q,s.scales,s.opacity,s.sh,s.parts)
    def render_local(self,f):
        f=self.baseline.baseline.adjusted_frame(f);keep=self.baseline.keep_head.clone();keep[self.ids]=False
        s=joined_state(pick(self.baseline.baseline.head_state(f),keep),self.head_patch(f));h,w=f['rgb'].shape[:2]
        return draw(s,f['F'],f['K'],w,h)
    def state(self,f):
        s=self.baseline.state(f);keep=torch.ones(len(s.means),device='cuda',dtype=torch.bool);keep[self.head_rows]=False
        return joined_state(pick(s,keep),self.head_patch(f).to_world(f['C'],f['F'],self.scale))
    def render(self,f):
        f=self.baseline.baseline.adjusted_frame(f);h,w=f['rgb'].shape[:2];return draw(self.state(f),f['C'],f['K'],w,h,unit_scale=self.scale)

@torch.no_grad()
def local_assessment(model,base,data,names,masks,out):
    out=Path(out);out.mkdir();rows={}
    for n in names:
        f=make_frame(data,n,crop=False);adjusted=base.baseline.adjusted_frame(f);h,w=f['rgb'].shape[:2]
        old=draw(pick(base.baseline.head_state(adjusted),base.keep_head),adjusted['F'],adjusted['K'],w,h);r=model.render_local(f)
        rgb=r['rgb'].cpu().numpy();prior=old['rgb'].cpu().numpy();target=data['rgb'][n];q=r['q'].cpu().numpy();oldq=old['q'].cpu().numpy();row={}
        for part,index in [('hair',2),('face',1)]:
            m=masks[n][part];row[part]=dict(beforeL1=float(np.abs(prior-target).mean(-1)[m].mean()),afterL1=float(np.abs(rgb-target).mean(-1)[m].mean()),beforeContribution=float(oldq[...,index][m].mean()),afterContribution=float(q[...,index][m].mean()))
        rows[n]=row;ys,xs=np.where(masks[n]['face']|masks[n]['hair']);x0=max(0,int(xs.min())-24);x1=min(w,int(xs.max())+25);y0=max(0,int(ys.min())-24);y1=min(h,int(ys.max())+25)
        write_image(out/(n+'.png'),[a[y0:y1,x0:x1] for a in [target,prior,rgb]])
        np.savez_compressed(out/(n+'.npz'),rgb=rgb[y0:y1,x0:x1],alpha=r['alpha'].cpu().numpy()[y0:y1,x0:x1],q=q[y0:y1,x0:x1],rectangle=[x0,y0,x1,y1])
    save_json(out/'metrics.json',rows);return rows


def run(complete,mvs,out,steps=240):
    out=Path(out);clock=time.perf_counter();torch.manual_seed(100106);np.random.seed(100106);data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    for name in ('run_cross_window_surface_repair.py','build_cross_window_surface.py','reconstruction_surface_consensus.py','prepare_measured_hair_mvs.py','reconstruction_room_surface_repair.py','run_continuous_surface_repair.py','run_native_head_surface_repair.py'):
        shutil.copyfile(Path(__file__).with_name(name),out/'algorithm-source'/name)
    a,proposal=build_surface(mvs,data,plan,base,out);ids=retirement(a,data,plan,base,out);proposal['names']=list(dict.fromkeys(n for n in plan['train'] if n in data['local']));save_json(out/'proposal.json',proposal)
    contract.update(MVSInputs=proposal['windows'],sources={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')});save_json(out/'contract.json',contract)
    train=proposal['names'];evaluation=list(dict.fromkeys(train+[contract['reference']]+plan['development']+plan['audit']));world_eval=[n for n in evaluation if n in data['worlds']]
    masks=physical_masks(contract['spec']['prepared'],data,evaluation);old,before=evaluate_complete(base,data,world_eval,masks,out/'baseline-full');random=rng_state();baseline_hash=exact_state_hash(base)
    ids=torch.as_tensor(ids,device='cuda');f=base.baseline.adjusted_frame(make_frame(data,data['reference'],crop=False));parent=pick(base.baseline.head_state(f),ids);t=lambda x:torch.as_tensor(x,device='cuda',dtype=torch.float32)
    new=GaussianState(t(a['means']),t(a['quats']),t(a['scales']),t(a['opacity']),t(a['sh']),torch.full((len(a['means']),),2,device='cuda',dtype=torch.long))
    side=dict(np.load(Path(complete)/'candidate-identities.npz'));old_uid=base.baseline.portrait.stable_uid[ids];summary={};config=dict(steps=steps,train=train,evaluate=evaluation,worldEvaluate=world_eval,positionsFixed=True,covarianceTrainable=True,F_K_C_fixed=True,scaleRange=[.8,1.2],nativeFullFrame=True,oldUnknownHairKept=True,allHeadPartsVisible=True,allPartsInT2=True,maximumNewPoints=6000,published=False)
    save_json(out/'config.json',config)
    for label,state,uid,support,candidate,namespace in [('old-patch-control',parent,old_uid,torch.ones(len(ids),device='cuda'),False,0),('actual-surface-candidate',new,torch.as_tensor(a['uid'],device='cuda'),t(a['support']),True,6)]:
        folder=out/label;folder.mkdir();shutil.copyfile(out/'spec.json',folder/'spec.json');model=NativeHairStage(base,data,ids,state,uid,support,candidate)
        for p in model.parameters():p.requires_grad_(False)
        initial={k:v.detach().clone() for k,v in model.state_dict().items()};rates={'sh':.002,'opacity':.005,'log_scales':.001,'quats':.0003};ops={k:torch.optim.Adam([getattr(model.patch,k)],lr=lr) for k,lr in rates.items()}
        for k in rates:getattr(model.patch,k).requires_grad_(True)
        sampler=FrameSampler(train,100106);restore_rng(random);curve=[]
        def ck(name,step):save_checkpoint(folder/(name+'.pt'),model,ops,{'views':sampler},stage='cross-window-MVS-hair',step=step,contract=contract,strategy={'events':[],'topology':'finite measured surface replacement'},extra=dict(sourceContinuity=extra,config=config,ids=ids,candidate=candidate,proposal=proposal,surface=a))
        ck('initial',0);local_init=local_assessment(model,base,data,evaluation,masks,folder/'initial-local');_,initial_full=evaluate_complete(model,data,world_eval,masks,folder/'initial-full',old);start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
        for step in range(1,steps+1):
            for op in ops.values():op.zero_grad(set_to_none=True)
            n=sampler.next();f=make_frame(data,n,crop=False);r=model.render_local(f);hair=torch.tensor(masks[n]['hair'],device='cuda');face=torch.tensor(masks[n]['face'],device='cuda');err=(r['rgb']-f['rgb']).abs().mean(-1)
            loss=masked_mean(err,hair)+.12*valid_window_structure(r['rgb'],f['rgb'],hair)+.025*masked_mean((1-r['q'][...,2]).square(),hair)+.5*masked_mean(err,face)+.05*masked_mean(r['q'][...,2].square(),face)+model.patch.regularizer()
            if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
            loss.backward()
            for k,p in model.patch.named_parameters():
                if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient:'+k)
            for op in ops.values():op.step()
            with torch.no_grad():model.patch.log_scales.clamp_(initial['patch.log_scales']+np.log(.8),initial['patch.log_scales']+np.log(1.2))
            if step==steps//2:ck('mid',step)
            if step==1 or step%60==0:row=dict(step=step,name=n,loss=float(loss.detach()));curve.append(row);print(label,json.dumps(row),flush=True)
            if time.perf_counter()-start>600 or torch.cuda.memory_allocated()/1048576>6500:raise ValueError('finite_resource_budget')
        ck('candidate-final',steps);local_final=local_assessment(model,base,data,evaluation,masks,folder/'final-local');_,after=evaluate_complete(model,data,world_eval,masks,folder/'final-full',old)
        failures=regression_screen(before,after);result=dict(baseline=before,initial=initial_full,final=after,localInitial=local_init,localFinal=local_final,steps=steps,curve=curve,failures=failures,trainEvalSeconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
            parameterChanges={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if k.startswith('patch.') and v.is_floating_point()},frozenBaselineExact=exact_state_hash(base)==baseline_hash,transactionAccepted=False,releaseQualityPassed=False,published=False)
        keep=np.ones(len(side['point_id']),bool);keep[model.head_rows.cpu().numpy()]=False;export_complete_candidate(model,base,data,contract['reference'],folder,side,keep,uid.cpu().numpy(),namespace,result);save_json(folder/'result.json',result)
        summary[label]={k:result[k] for k in ('assetHash','pointCount','failures','trainEvalSeconds','allocatedMiB','reservedMiB')};restore_checkpoint(folder/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda');ck('restored',0)
        if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()) or exact_state_hash(base)!=baseline_hash:raise ValueError('hair_transaction_restore_failed')
        del model,ops;torch.cuda.empty_cache();print(label,'FINISHED',json.dumps(summary[label]),flush=True)
    save_json(out/'result.json',dict(branches=summary,seconds=time.perf_counter()-clock,sourceHash=data['sourceHash'],published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--mvs',required=True,nargs='+');p.add_argument('--out',required=True);p.add_argument('--steps',type=int,default=240);a=p.parse_args()
    try:run(a.complete,a.mvs,a.out,a.steps)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise
