"""Finite room surface replacement, same-budget original representation control.
Complete existing human remains visible and frozen; candidates never publish.
"""
from pathlib import Path
import argparse,json,time,shutil
import numpy as np,torch,cv2
from reconstruction_complete_context import load_complete
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_components_v3 import FreeComponent,pick,save_json,sha,exact_state_hash
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,rng_state,restore_rng
from reconstruction_ray_surface import collect_observed_depth
from reconstruction_surface_handoff import build_room_planes,select_room_transaction
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from run_continuous_surface_repair import evaluate_complete,regression_screen
from run_haze_shared_surface import export_state

class RoomHandoffStage(torch.nn.Module):
    def __init__(self,base,reference,retired,arrays,control=False):
        super().__init__();self.baseline=base;self.scale=base.scale
        state=base.state(reference)
        self.register_buffer('retired',torch.as_tensor(retired,device='cuda'))
        keep=torch.ones(len(state.means),device='cuda',dtype=torch.bool);keep[self.retired]=False;self.register_buffer('keep',keep)
        if control:seed=pick(state,self.retired);uid=torch.as_tensor(retired,device='cuda');support=torch.ones(len(uid),device='cuda')
        else:
            seed=GaussianState(*(torch.as_tensor(arrays[k],device='cuda',dtype=torch.long if k=='parts' else torch.float32) for k in GaussianState.__dataclass_fields__))
            uid=torch.as_tensor(arrays['uid'],device='cuda');support=torch.as_tensor(arrays['support'],device='cuda')
        self.patch=FreeComponent(seed,uid,support,'world-reference',0.)
        self.register_buffer('initial_scales',seed.scales.detach().clone())
        self.register_buffer('initial_alpha',seed.opacity.detach().clone())
        for p in base.parameters():p.requires_grad_(False)
    def state(self,f):return joined_state(pick(self.baseline.state(f),self.keep),self.patch.state())
    def render(self,frame):
        f=self.baseline.baseline.adjusted_frame(frame);h,w=f['rgb'].shape[:2]
        return draw(self.state(f),f['C'],f['K'],w,h,unit_scale=self.scale)


def run(complete,depth,out,steps=320,budget=14000,reuse=None,attribution=None,surface_pool=None,max_parents=6):
    out=Path(out);clock=time.perf_counter();torch.manual_seed(100202);np.random.seed(100202)
    data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra');source_state=exact_state_hash(base)
    shutil.copyfile(Path(__file__),out/'algorithm-source'/Path(__file__).name)
    for name in ('reconstruction_surface_handoff.py','reconstruction_ray_surface.py','run_continuous_surface_repair.py'):
        shutil.copyfile(Path(__file__).with_name(name),out/'algorithm-source'/name)
    train=[n for n in plan['train'] if n in data['worlds']]
    body_names=list(base.body_motion.timestamps)
    names=list(dict.fromkeys([contract['reference']]+body_names+plan['development']+plan['audit']));names=[n for n in names if n in data['worlds']]
    masks=physical_masks(contract['spec']['prepared'],data,list(dict.fromkeys(train+names)))
    motions={n:base.body_motion.matrix(n).detach().cpu().numpy() for n in body_names}
    save_json(out/'motion-contract.json',dict(B={n:v.tolist() for n,v in motions.items()},names=body_names,
        meaning='restored bounded photometric hypothesis; not independently validated',noNewBodyTraining=True,
        unknownOutsideWindow=True,worldCameraScalePreserved=True))
    if reuse is None:
        priors,records=collect_observed_depth(depth,data,train,masks,body_names,out/'motion-consistent-observations',body_motion=motions)
        pool,planes=build_room_planes(data,masks,priors,depth,train,out/'finite-surfaces',budget=budget)
    else:
        reuse=Path(reuse);prior_contract=json.loads((reuse/'contract.json').read_text())
        if prior_contract['completeCheckpointHash']!=contract['completeCheckpointHash'] or prior_contract['sourceHash']!=data['sourceHash']:raise ValueError('different_cached_surface_source')
        pool=dict(np.load(reuse/'finite-surfaces/surface-pool.npz'))
        if str(pool.pop('source_hash'))!=data['sourceHash']:raise ValueError('cached_pool_source_changed')
        save_json(out/'reused-preparation.json',dict(folder=str(reuse.resolve()),poolHash=sha(reuse/'finite-surfaces/surface-pool.npz'),newPreparation=False))
    if surface_pool is not None:
        pool=dict(np.load(surface_pool))
        if str(pool.pop('source_hash'))!=data['sourceHash'] or 'source_image' not in pool:raise ValueError('surface_pool_provenance_missing')
        keep=np.isin(pool['source_image'],train)&(pool['parts']==0)&(pool['support']>=3)
        original_count=len(keep);pool={k:v[keep] for k,v in pool.items()}
        save_json(out/'observed-pool-input.json',dict(path=str(Path(surface_pool).resolve()),hash=sha(surface_pool),before=original_count,count=int(keep.sum()),
            keptSourceImages=sorted(set(pool['source_image'])),roleFilter='current training only',preparationRerun=False,
            geometryMeaning='cached multiview-supported predicted nonplanar surfaces, not independent truth',samePointCountAsPlaneBranch=False))
    ref=base.baseline.adjusted_frame(make_frame(data,contract['reference'],crop=False))
    evidence=None;score=None
    if attribution is not None:
        attribution=Path(attribution);meta=json.loads((attribution/'result.json').read_text())
        if meta['sourceHash']!=data['sourceHash'] or meta['completeCheckpointHash']!=contract['completeCheckpointHash'] or set(meta['trainOnlyNames'])-set(train):raise ValueError('incorrect_attribution_source_or_role')
        score=np.load(attribution/'room-contribution.npy');evidence=[dict(np.load(attribution/(n+'.npz')),imageName=n) for n in meta['trainOnlyNames']]
        save_json(out/'attribution-input.json',dict(folder=str(attribution.resolve()),hash=sha(attribution/'result.json'),trainOnly=True))
    retired,a,proposals=select_room_transaction(base.state(ref),pool,budget=budget,max_parents=max_parents if evidence is not None else 12,projection_evidence=evidence,contribution=score)
    np.savez_compressed(out/'replacement.npz',retired=retired,**a,source_hash=np.array(data['sourceHash']))
    save_json(out/'replacement.json',dict(proposals=proposals,count=len(a['means']),retiredCount=len(retired),
        finiteDomain=True,keptAllOtherComponents=True,geometryQualityPassed=False))
    old,before=evaluate_complete(base,data,names,masks,out/'baseline-images')
    # Cache RGB/alpha only; all native valid pixels remain supervised.
    training={}
    with torch.no_grad():
        for n in train:
            r=base.render(make_frame(data,n,crop=False));training[n]=dict(error=(r['rgb']-torch.tensor(data['rgb'][n],device='cuda')).abs().mean(-1).cpu(),alpha=r['alpha'].cpu())
    config=dict(steps=steps,seed=100202,train=train,evaluate=names,bodyTraining=False,allComponentsVisible=True,
        sameImageBackwardBudget=True,fullNativeFrame=True,roomRGBUsesAllValidPixels=True,
        topology='one finite explicit replacement; no ongoing density',geometry='fixed finite observed planes' if surface_pool is None else 'fixed cached observed local nonplanar surfaces',
        rates=dict(sh=.003,opacity=.004,log_scales=.001),scaleBounds=[.8,1.25],normalThickness='initial .12 of local lattice; max 1.25 initial' if surface_pool is None else 'cached actual normal/tangent axes; no recomputation; max 1.25 initial',
        budget=budget,releaseQualityPassed=False,published=False)
    save_json(out/'config.json',config);contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')}
    save_json(out/'contract.json',contract);random=rng_state();summary={}
    for label,control in [('original-control',True),('surface-replacement',False)]:
        folder=out/label;folder.mkdir();shutil.copyfile(out/'spec.json',folder/'spec.json')
        model=RoomHandoffStage(base,ref,retired,a,control)
        for p in model.parameters():p.requires_grad_(False)
        rates=config['rates'];params={k:getattr(model.patch,k) for k in rates}
        for p in params.values():p.requires_grad_(True)
        ops={k:torch.optim.Adam([p],lr=rates[k]) for k,p in params.items()}
        initial={k:v.detach().clone() for k,v in model.state_dict().items()};sampler=FrameSampler(train,100202);restore_rng(random)
        extra_state=dict(sourceContinuity=extra,retired=retired,arrays=a,control=control,config=config)
        def ck(name,step):save_checkpoint(folder/(name+'.pt'),model,ops,{'views':sampler},stage='finite-room-handoff',step=step,
            contract=contract,strategy={'events':[{'kind':'explicit_surface_replacement','retired':retired.tolist(),'new':len(a['means'])}] if not control else [],'density':'none'},extra=extra_state)
        ck('initial',0);_,initial_metrics=evaluate_complete(model,data,names,masks,folder/'initial-images',old)
        torch.cuda.reset_peak_memory_stats();started=time.perf_counter();curve=[];sampled=[]
        for step in range(1,steps+1):
            for op in ops.values():op.zero_grad(set_to_none=True)
            n=sampler.next();sampled.append(n);f=make_frame(data,n,crop=False);r=model.render(f)
            err=(r['rgb']-f['rgb']).abs().mean(-1);m=torch.as_tensor(masks[n]['room'],device='cuda')
            previous={k:v.to('cuda') for k,v in training[n].items()}
            loss=masked_mean(err,m)+.12*valid_window_structure(r['rgb'],f['rgb'],m)
            loss+=.25*masked_mean((previous['alpha']-.005-r['alpha']).clamp_min(0),m)
            for part,weight in [('face',6.),('hair',4.),('neck',4.),('cloth',4.)]:
                p=torch.as_tensor(masks[n][part],device='cuda')
                loss+=weight*masked_mean((err-previous['error']-.001).clamp_min(0),p)
                loss+=.2*masked_mean((previous['alpha']-.005-r['alpha']).clamp_min(0),p)
            loss+=.001*(model.patch.log_scales-model.initial_scales.log()).square().mean()+.0001*model.patch.sh[:,1:].square().mean()
            if not torch.isfinite(loss):raise ValueError('nonfinite_handoff_loss')
            loss.backward()
            for k,p in params.items():
                if p.grad is None or not torch.isfinite(p.grad).all():raise ValueError('invalid_handoff_gradient:'+k)
            for op in ops.values():op.step()
            with torch.no_grad():
                model.patch.log_scales.clamp_((model.initial_scales*.8).log(),(model.initial_scales*1.25).log())
            if step==steps//2:ck('mid',step)
            if step==1 or step%80==0:
                row=dict(step=step,name=n,loss=float(loss.detach()));curve.append(row);print(json.dumps(dict(branch=label,**row)),flush=True)
            if time.perf_counter()-started>600 or torch.cuda.max_memory_allocated()/1048576>6500:raise ValueError('handoff_resource_budget')
        seconds=time.perf_counter()-started;ck('candidate-final',steps)
        _,after=evaluate_complete(model,data,names,masks,folder/'final-images',old)
        state=model.state(ref);asset=folder/'candidate-research-only.ply';export_state(state,asset);asset_hash=sha(asset)
        side=dict(np.load(Path(complete)/'candidate-identities.npz'));keep=model.keep.cpu().numpy()
        uid=side['source_uid'][keep];namespace=side['source_namespace'][keep]
        new_uid=side['source_uid'][retired] if control else a['uid'];new_ns=side['source_namespace'][retired] if control else np.full(len(new_uid),4)
        uid=np.r_[uid,new_uid];namespace=np.r_[namespace,new_ns]
        if len(uid)!=len(state.means) or len(np.unique(np.c_[namespace,uid],axis=0))!=len(uid):raise ValueError('handoff_uid_mismatch')
        np.savez_compressed(folder/'candidate-identities.npz',point_id=np.arange(len(uid)),source_uid=uid,source_namespace=namespace,
            component=state.parts.cpu().numpy(),asset_hash=np.array(asset_hash),source_hash=np.array(data['sourceHash']),reference=np.array(contract['reference']))
        display=json.loads((Path(complete)/'display.json').read_text());display['assets']=[dict(label=label,ply=str(asset.resolve()),hash=asset_hash,count=len(uid))]
        save_json(folder/'display.json',display)
        changes={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if k.startswith('patch.') and v.is_floating_point()}
        result=dict(baseline=before,initial=initial_metrics,final=after,failures=regression_screen(before,after),steps=steps,curve=curve,sampled=sampled,
            changes=changes,trainSeconds=seconds,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
            sourceHash=data['sourceHash'],reference=contract['reference'],assetHash=asset_hash,count=len(state.means),baselineExact=exact_state_hash(base)==source_state,
            transactionAccepted=False,releaseQualityPassed=False,published=False)
        save_json(folder/'result.json',result);summary[label]={k:result[k] for k in ('failures','assetHash','trainSeconds','allocatedMiB','reservedMiB')}
        restore_checkpoint(folder/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda');ck('restored',0)
        if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()) or exact_state_hash(base)!=source_state:raise ValueError('handoff_restore_failed')
        del model,ops,params;torch.cuda.empty_cache();print(json.dumps(dict(branch=label,finished=True,**summary[label])),flush=True)
    save_json(out/'result.json',dict(branches=summary,seconds=time.perf_counter()-clock,published=False,releaseQualityPassed=False))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('complete','depth','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--reuse');p.add_argument('--attribution');p.add_argument('--surface-pool');p.add_argument('--max-parents',type=int,default=6);p.add_argument('--steps',type=int,default=320);p.add_argument('--budget',type=int,default=14000);a=p.parse_args()
    try:run(a.complete,a.depth,a.out,a.steps,a.budget,a.reuse,a.attribution,a.surface_pool,a.max_parents)
    except Exception as e:
        import traceback
        if Path(a.out).exists():save_json(Path(a.out)/'failure.json',dict(error=str(e),traceback=traceback.format_exc(),published=False))
        raise
