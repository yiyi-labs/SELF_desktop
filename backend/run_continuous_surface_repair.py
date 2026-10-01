"""Complete-scene bounded neck geometry/appearance control, research only.
The restored human, clothing and room always participate in one rasterization.
No producer defaults, publisher or USB imports. No unknown body pose is fitted.
"""
from pathlib import Path
import argparse,json,time,shutil
import cv2,numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_surface_continuity import (SharedDisplacementField,continuous_motion,
    projected_transition_gradient,select_skin_contacts)
from reconstruction_components_v3 import FreeComponent,pick,save_json,sha,exact_state_hash
from reconstruction_portrait_model import GaussianState,joined_state,scaled_head_transform
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_continuity_surface import blend_rigid_state,physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,rng_state,restore_rng
from run_haze_shared_surface import export_state

class NeckSurfaceStage(torch.nn.Module):
    def __init__(self,base,data,reference,transport):
        super().__init__();self.baseline=base;self.scale=base.scale;self.transport=transport
        f=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));ids=torch.where(base.is_neck)[0]
        self.register_buffer('ids',ids);initial=pick(base.patch.state(),ids)
        self.patch=FreeComponent(initial,base.patch.source_ids[ids],base.patch.support[ids],'world-reference',0.)
        cam=initial.means@f['C'][:3,:3].T+f['C'][:3,3]
        metric=float((cam[:,2]/f['K'][0,0]).median());self.metric=metric
        self.field=SharedDisplacementField(initial.means,metric*4,24)
        original=base.patch.base;reference_cam=original@f['C'][:3,:3].T+f['C'][:3,3];q=reference_cam@f['K'].T;y=q[:,1]/q[:,2]
        top,bottom=torch.quantile(y[base.is_neck],torch.tensor([.05,.95],device=y.device))
        gradient=projected_transition_gradient(original,f['C'],f['K'],float(top),float(bottom),base.is_neck)[ids]
        self.register_buffer('weight',base.neck_weight[ids]);self.register_buffer('gradient',gradient)
        full=base.state(f);start=len(full.means)-len(base.patch.base);self.register_buffer('full_ids',ids+start)
        head=base.baseline.head_state(f).to_world(f['C'],f['F'],self.scale)
        head_skin=base.keep_head&((head.parts==1)|(head.parts==4))
        upper=torch.where(self.weight>.75)[0];a,b,record=select_skin_contacts(initial.means[upper].cpu().numpy(),head.means[head_skin].cpu().numpy(),f['K'].cpu().numpy(),f['C'].cpu().numpy())
        self.register_buffer('contact_ids',upper[torch.as_tensor(a,device=ids.device)])
        self.register_buffer('contact_target',head.means[head_skin][torch.as_tensor(b,device=ids.device)].detach())
        self.contact_record=record;self.last_jacobian=None
    def state(self,f):
        full=self.baseline.state(f)
        # The legacy window restriction is explicit. Outside it the frozen
        # candidate is shown for regression only, without guessed motion.
        if f['name'] not in self.baseline.body_motion.timestamps:return full
        s=self.patch.state();means,Jfield=self.field(s.means)
        local=GaussianState(means,s.quats,s.scales,s.opacity,s.sh,s.parts)
        H=scaled_head_transform(f['C'],f['F'],self.scale)@self.baseline.inverse_head_reference
        B=self.baseline.body_motion.matrix(f['name'])
        if self.transport:
            moved,J=continuous_motion(local,H,B,self.weight,self.gradient,field_jacobian=Jfield)
            self.last_jacobian=J
        else:
            moved=blend_rigid_state(local,H,B,self.weight);self.last_jacobian=Jfield
        keep=torch.ones(len(full.means),device=means.device,dtype=torch.bool);keep[self.full_ids]=False
        return joined_state(pick(full,keep),moved)
    def render(self,f):
        f=self.baseline.baseline.adjusted_frame(f);h,w=f['rgb'].shape[:2]
        return draw(self.state(f),f['C'],f['K'],w,h,unit_scale=self.scale)
    def regularizer(self):
        positions,J=self.field(self.patch.state().means)
        loss=.01*self.field.regularizer()
        if len(self.contact_ids):loss+=.0005*((positions[self.contact_ids]-self.contact_target)/self.metric).square().sum(-1).mean()
        if self.last_jacobian is not None:
            singular=torch.linalg.svdvals(self.last_jacobian)
            loss+=.05*((.7-singular).clamp_min(0).square()+(singular-1.4).clamp_min(0).square()).mean()
            loss+=.1*(.25-torch.linalg.det(self.last_jacobian)).clamp_min(0).square().mean()
        return loss


def write_image(path,images):
    image=np.clip(np.concatenate(images,1),0,1);cv2.imwrite(str(path),cv2.cvtColor((image*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))

def evaluate_complete(model,data,names,masks,folder,old=None):
    folder=Path(folder);folder.mkdir(exist_ok=False);rows={};records={}
    with torch.no_grad():
        for name in names:
            r=model.render(make_frame(data,name,crop=False));rgb=r['rgb'].cpu().numpy();q=r['q'].cpu().numpy();alpha=r['alpha'].cpu().numpy();target=data['rgb'][name]
            records[name]=dict(rgb=rgb,q=q,alpha=alpha);row={}
            for part,index in [('face',1),('hair',2),('neck',4),('cloth',4),('room',0)]:
                mask=masks[name][part]
                if not mask.any():continue
                error=np.abs(rgb-target).mean(-1)
                row[part]=dict(rgb=float(error[mask].mean()),q=float(q[...,index][mask].mean()),qRoom=float(q[...,0][mask].mean()),alpha=float(alpha[mask].mean()),holes=float((alpha[mask]<.8).mean()))
                if old is not None:row[part]['pixelRegressionP90']=float(np.quantile((error-np.abs(old[name]['rgb']-target).mean(-1))[mask],.9))
            rows[name]=row
            if float((r['q'].sum(-1)-r['alpha']).abs().max())>1e-4:raise ValueError('contribution_conservation')
            write_image(folder/(name+'.png'),[target]+([old[name]['rgb']] if old else [])+[rgb])
            np.savez_compressed(folder/(name+'.npz'),rgb=rgb,alpha=alpha,q=q)
    save_json(folder/'metrics.json',rows);return records,rows


def regression_screen(before,after):
    errors=[]
    for name,parts in before.items():
        for part,row in parts.items():
            b=after[name][part]
            if b['rgb']>row['rgb']+.003:errors.append(part+'_rgb:'+name)
            if b['alpha']<row['alpha']-.015:errors.append(part+'_coverage:'+name)
            if b['holes']>row['holes']+.02:errors.append(part+'_holes:'+name)
    return errors


def export_complete_candidate(model,base,data,reference,out,source_side,keep,append_uid,append_namespace,result):
    f=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));s=model.state(f)
    export_state(s,out/'candidate-research-only.ply');h=sha(out/'candidate-research-only.ply')
    uid=np.r_[source_side['source_uid'][keep],append_uid];ns=np.r_[source_side['source_namespace'][keep],np.full(len(append_uid),append_namespace)]
    if len(uid)!=len(s.means) or len(np.unique(np.c_[ns,uid],axis=0))!=len(uid):raise ValueError('stable_identity_mismatch')
    np.savez_compressed(out/'candidate-identities.npz',point_id=np.arange(len(uid)),source_uid=uid,source_namespace=ns,component=s.parts.cpu().numpy(),asset_hash=np.array(h),source_hash=np.array(data['sourceHash']),reference=np.array(reference))
    inv=torch.linalg.inv(f['C']).cpu().numpy();height,width=f['rgb'].shape[:2]
    save_json(out/'display.json',dict(assets=[dict(label=out.name,ply=str((out/'candidate-research-only.ply').resolve()),hash=h,count=len(uid))],K=f['K'].cpu().tolist(),C=f['C'].cpu().tolist(),width=width,height=height,camera=inv[:3,3].tolist(),target=(inv[:3,3]+inv[:3,2]).tolist(),up=(-inv[:3,1]).tolist(),near=.01*base.scale,far=1e10*base.scale,reference=reference,sourceHash=data['sourceHash'],published=False))
    result.update(assetHash=h,pointCount=len(uid),sourceHash=data['sourceHash'],reference=reference)


def run(complete,out,steps=200):
    out=Path(out);clock=time.perf_counter();torch.manual_seed(100103);np.random.seed(100103)
    data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    for name in ('run_continuous_surface_repair.py','reconstruction_surface_continuity.py','reconstruction_complete_context.py'):
        shutil.copyfile(Path(__file__).with_name(name),out/'algorithm-source'/name)
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')};save_json(out/'contract.json',contract)
    names=list(extra['meta']['names']);reference=contract['reference']
    evaluation=list(dict.fromkeys(names+[reference]+[n for n in plan['development']+plan['audit'] if n in data['worlds']]))
    masks=physical_masks(contract['spec']['prepared'],data,evaluation);baseline_hash=exact_state_hash(base)
    old,before=evaluate_complete(base,data,evaluation,masks,out/'baseline-images')
    side=dict(np.load(Path(complete)/'candidate-identities.npz'));random=rng_state();summary={}
    config=dict(steps=steps,geometrySteps=80,appearanceSteps=steps-80,train=names,evaluate=evaluation,reference=reference,fieldBoundNativePixels=4,controls=24,
        sameImageBackwardBudget=True,topology='fixed exact source identities',nativeFullFrame=True,allComponentsVisible=True,
        fixed='F,K,C,identity,scale,clothing,room,hair',outsideWindow='explicit frozen unknown diagnostic; no extrapolated B',published=False)
    if steps<=80:raise ValueError('appearance_recovery_budget_required')
    save_json(out/'config.json',config)
    for label,transport in [('rigid-control',False),('strain-candidate',True)]:
        folder=out/label;folder.mkdir();shutil.copyfile(out/'spec.json',folder/'spec.json')
        model=NeckSurfaceStage(base,data,reference,transport)
        for p in model.parameters():p.requires_grad_(False)
        initial={k:v.detach().clone() for k,v in model.state_dict().items()}
        rates={'sh':.002,'opacity':.006,'log_scales':.001,'quats':.0003}
        ops={k:torch.optim.Adam([getattr(model.patch,k)],lr=lr) for k,lr in rates.items()}
        ops['surface']=torch.optim.Adam([model.field.delta],lr=.015)
        sampler=FrameSampler(names,100103);restore_rng(random);curve=[]
        save_json(folder/'contacts.json',model.contact_record);save_json(folder/'config.json',dict(config,transportCovariance=transport))
        def checkpoint(label,step):
            save_checkpoint(folder/(label+'.pt'),model,ops,{'views':sampler},stage='continuous-neck-surface',step=step,contract=contract,
                strategy={'events':[],'topology':'fixed'},extra=dict(sourceContinuity=extra,config=config,transport=transport,neckUID=side['source_uid'][model.full_ids.cpu().numpy()]))
        checkpoint('initial',0);_,init_metrics=evaluate_complete(model,data,evaluation,masks,folder/'initial-images',old)
        start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
        for step in range(1,steps+1):
            geometry=step<=80
            model.field.delta.requires_grad_(geometry)
            for key in rates:getattr(model.patch,key).requires_grad_(not geometry)
            for op in ops.values():op.zero_grad(set_to_none=True)
            name=sampler.next();f=make_frame(data,name,crop=False);r=model.render(f);error=(r['rgb']-f['rgb']).abs().mean(-1)
            neck=torch.tensor(masks[name]['neck'],device='cuda');loss=masked_mean(error,neck)+.12*valid_window_structure(r['rgb'],f['rgb'],neck)
            loss+=.03*masked_mean((1-r['q'][...,4]).square(),neck)+model.regularizer()
            # Real original pixels guard all previously effective contents.
            for part,weight in [('face',1.),('hair',.5),('cloth',1.),('room',.5)]:
                mask=torch.tensor(masks[name][part],device='cuda');old_error=torch.tensor(np.abs(old[name]['rgb']-data['rgb'][name]).mean(-1),device='cuda')
                loss+=weight*masked_mean((error-old_error-.003).clamp_min(0),mask)
            if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
            loss.backward()
            for n,p in model.named_parameters():
                if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient:'+n)
            if geometry:ops['surface'].step()
            else:
                for k in rates:ops[k].step()
            with torch.no_grad():model.patch.log_scales.clamp_(initial['patch.log_scales']+np.log(.8),initial['patch.log_scales']+np.log(1.2))
            if step==steps//2:checkpoint('mid',step)
            if step==1 or step%40==0:
                row=dict(step=step,name=name,geometry=geometry,loss=float(loss.detach()));curve.append(row);print(label,json.dumps(row),flush=True)
            if time.perf_counter()-start>600 or torch.cuda.memory_allocated()/1048576>7100:raise ValueError('finite_resource_budget')
        checkpoint('candidate-final',steps);_,after=evaluate_complete(model,data,evaluation,masks,folder/'final-images',old)
        failures=regression_screen(before,after)
        keep=np.ones(len(side['point_id']),bool);ix=model.full_ids.cpu().numpy();keep[ix]=False
        result=dict(baseline=before,initial=init_metrics,final=after,failures=failures,curve=curve,steps=steps,
            contacts=model.contact_record,parameterChanges={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if not k.startswith('baseline.') and v.is_floating_point()},
            trainEvalSeconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
            frozenBaselineExact=exact_state_hash(base)==baseline_hash,geometrySupported=False,transactionAccepted=False,releaseQualityPassed=False,published=False)
        export_complete_candidate(model,base,data,reference,folder,side,keep,side['source_uid'][ix],3,result)
        save_json(folder/'result.json',result);summary[label]={k:result[k] for k in ('assetHash','failures','trainEvalSeconds','allocatedMiB','reservedMiB')}
        restore_checkpoint(folder/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda');checkpoint('restored',0)
        if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()):raise ValueError('state_restore_changed')
        if exact_state_hash(base)!=baseline_hash:raise ValueError('protected_baseline_changed')
        del model,ops;torch.cuda.empty_cache();print(label,'FINISHED',json.dumps(summary[label]),flush=True)
    save_json(out/'result.json',dict(branches=summary,seconds=time.perf_counter()-clock,baselineAssetHash=contract['completeAssetHash'],published=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--out',required=True);p.add_argument('--steps',type=int,default=200);a=p.parse_args()
    try:run(a.complete,a.out,a.steps)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise
