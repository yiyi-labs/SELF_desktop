"""Finite complete-scene depth-envelope recovery; no deployment/publication.
Control and candidate share pixels, initialization, rates, steps and topology.
Only the observation-based surface objective differs. Every physical group is
in the same native full-frame rasterization. No feature mask restricts RGB.
"""
from pathlib import Path
import argparse,json,time,shutil
import cv2,numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_components_v3 import FreeComponent,pick,sha,save_json,exact_state_hash
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import make_frame,masked_mean,draw
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,rng_state,restore_rng
from reconstruction_ray_surface import draw_moments,moment_error,transport_patch,collect_observed_depth
from run_continuous_surface_repair import evaluate_complete,regression_screen
from run_haze_shared_surface import export_state


class ObservedSurfaceStage(torch.nn.Module):
    def __init__(self,base,data,side):
        super().__init__();self.baseline=base;self.scale=base.scale;self.patches=torch.nn.ModuleDict()
        f=base.baseline.adjusted_frame(make_frame(data,data['reference'],crop=False));s=base.state(f)
        self.reference={};self.bounds={}
        for label,part in [('room',0),('body',4)]:
            ids=torch.where(s.parts==part)[0];self.register_buffer(label+'_ids',ids)
            p=pick(s,ids);z=(p.means@f['C'][:3,:3].T+f['C'][:3,3])[:,2]
            bound=float(z[z>0].median())*(.03 if part==0 else .006)/np.sqrt(3)
            patch=FreeComponent(p,torch.tensor(side['point_id'][ids.cpu().numpy()],device='cuda'),torch.ones(len(ids),device='cuda'),'reference-world',bound)
            self.patches[label]=patch;self.reference[label]=p;self.bounds[label]=bound
            # Use initial serialization exactly for transport deltas.
            initial=patch.state()
            for k in GaussianState.__dataclass_fields__:self.register_buffer(label+'_initial_'+k,getattr(initial,k).detach().clone())
    def state(self,f):
        s=self.baseline.state(f);values={k:getattr(s,k).clone() for k in GaussianState.__dataclass_fields__}
        for label,patch in self.patches.items():
            ids=getattr(self,label+'_ids');current=pick(s,ids)
            ref=GaussianState(*(getattr(self,label+'_initial_'+k) for k in GaussianState.__dataclass_fields__))
            p=transport_patch(current,ref,patch)
            for k in values:
                if k!='parts':values[k][ids]=getattr(p,k)
        return GaussianState(**values)
    def render(self,f):
        f=self.baseline.baseline.adjusted_frame(f);h,w=f['rgb'].shape[:2]
        return draw_moments(self.state(f),f['C'],f['K'],w,h,self.scale)


def observed_loss(r,f,mask,old,body_active):
    err=(r['rgb']-f['rgb']).abs().mean(-1);loss=err.sum()*0
    for part,weight in [('room',.8)]+([('cloth',1.),('neck',1.)] if body_active else []):
        m=mask[part];loss+=weight*(masked_mean(err,m)+.12*valid_window_structure(r['rgb'],f['rgb'],m))
        # Real full-frame alpha preservation, not q-room-as-geometry.
        loss+=.12*masked_mean((old['alpha']-.005-r['alpha']).clamp_min(0),m)
    for part,weight in [('face',3.),('hair',2.),('cloth',1.5),('neck',2.)]:
        loss+=weight*masked_mean((err-old['error']-.001).clamp_min(0),mask[part])
    return loss


def surface_objective(r,priors,mask,scale,body_active):
    loss=r['rgb'].sum()*0;detail={}
    for layer,index in [('room',0)]+([('cloth',4)] if body_active else []):
        if layer not in priors:continue
        d,valid=priors[layer];d=d/scale
        eligible=valid&(r['q'][...,index].detach()>.02)
        e=moment_error(r['q'][...,index],r['first'][...,index],r['second'][...,index],d)
        value=masked_mean(torch.sqrt(e+1e-6),eligible);loss+=.15*value
        detail[layer+'DepthEnvelope']=float(value.detach())
    # Interior positive observations are distinct from unknown/occluded pixels.
    person=mask['face']|mask['hair']|mask['cloth']|mask['neck']
    interior=~torch.nn.functional.max_pool2d((~person).float()[None,None],11,1,5)[0,0].bool()
    loss+=.04*masked_mean(r['q'][...,0],interior)
    if body_active:
        empty=~torch.nn.functional.max_pool2d((~mask['room']).float()[None,None],11,1,5)[0,0].bool()
        loss+=.04*masked_mean(r['q'][...,4],empty)
    return loss,detail


def diagnostic(model,data,names,masks,priors,folder):
    folder=Path(folder);folder.mkdir(exist_ok=False);rows={}
    with torch.no_grad():
        for n in names:
            r=model.render(make_frame(data,n,crop=False));row={}
            for layer,index in [('room',0),('cloth',4)]:
                m=torch.tensor(masks[n][layer],device='cuda');q=r['q'][...,index]
                mean=r['first'][...,index]/q.clamp_min(1e-5)
                variance=(r['second'][...,index]/q.clamp_min(1e-5)-mean.square()).clamp_min(0)
                ok=m&(q>.02)
                ratio=variance.sqrt()/mean.abs().clamp_min(1e-4)
                row[layer]=dict(depthSpreadRelative=float(masked_mean(ratio,ok)),q=float(masked_mean(q,m)),holes=float(masked_mean((r['alpha']<.8).float(),m)))
                if n in priors and layer in priors[n]:
                    d,valid=priors[n][layer];dv=torch.tensor(d,device='cuda')/model.scale;v=torch.tensor(valid,device='cuda')&ok
                    e=moment_error(q,r['first'][...,index],r['second'][...,index],dv)
                    row[layer]['conditionalDepthEnvelope']=float(masked_mean(e.sqrt(),v));row[layer]['depthPixels']=int(v.sum())
            rows[n]=row
    save_json(folder/'moments.json',rows);return rows


def run(complete,depth,out,steps=300):
    out=Path(out);clock=time.perf_counter();torch.manual_seed(100201);np.random.seed(100201)
    data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    for filename in ('run_ray_surface_repair.py','reconstruction_ray_surface.py','reconstruction_complete_context.py','reconstruction_components_v3.py','reconstruction_continuity_surface.py','reconstruction_portrait_pipeline.py','reconstruction_portrait_model.py'):
        shutil.copyfile(Path(__file__).with_name(filename),out/'algorithm-source'/filename)
    frozen=exact_state_hash(base);side=dict(np.load(Path(complete)/'candidate-identities.npz'))
    train=[n for n in plan['train'] if n in data['worlds']];body_names=extra['meta']['names']
    names=list(dict.fromkeys([contract['reference']]+body_names+plan['development']+plan['audit']));names=[n for n in names if n in data['worlds']]
    masks=physical_masks(contract['spec']['prepared'],data,list(dict.fromkeys(train+names)))
    priors,prior_records=collect_observed_depth(depth,data,train,masks,body_names,out/'surface-observations')
    old,before=evaluate_complete(base,data,names,masks,out/'baseline-images')
    baseline_train={}
    with torch.no_grad():
        for n in train:
            r=base.render(make_frame(data,n,crop=False));baseline_train[n]=dict(error=(r['rgb']-torch.tensor(data['rgb'][n],device='cuda')).abs().mean(-1).cpu(),alpha=r['alpha'].cpu())
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')};contract['depthManifestHash']=sha(Path(depth)/'manifest.json')
    save_json(out/'contract.json',contract)
    config=dict(steps=steps,train=train,bodyTrainingWindow=body_names,evaluate=names,fullNativeFrame=True,fullObservedRoomRGB=True,
        sameStepSamplerSeed=100201,topology='fixed, no prune/split/reset',headFrozen=True,poseAndCameraFrozen=True,
        groupRates=dict(offset=.004,log_scales=.0015,quats=.0005,opacity=.003,sh=.002),
        bound='room 3% median reference depth vector; body .6%; no per-frame scale',
        scaleBounds=[.4,1.5],alphaBounds='initial +/- .15',warmup=30,geometryStop=220,
        objectiveDelta='conditional depth envelopes + positive observed semantic interiors',
        depthIsConditionalNotTruth=True,unknownRetainsRGB=True,releaseQualityPassed=False,published=False)
    save_json(out/'config.json',config);random=rng_state();results={}
    for label in ('control','surface'):
        folder=out/label;folder.mkdir();shutil.copyfile(out/'spec.json',folder/'spec.json')
        model=ObservedSurfaceStage(base,data,side)
        for p in model.parameters():p.requires_grad_(False)
        rates=config['groupRates'];params={g+'.'+k:getattr(patch,k) for g,patch in model.patches.items() for k in rates}
        ops={k:torch.optim.Adam([p],lr=rates[k.split('.')[-1]]) for k,p in params.items()}
        initial={k:v.clone() for k,v in model.state_dict().items()};sampler=FrameSampler(train,100201);restore_rng(random)
        conf=dict(config,branch=label);save_json(folder/'config.json',conf);save_json(folder/'contract.json',contract)
        def ck(name,step):save_checkpoint(folder/(name+'.pt'),model,ops,{'views':sampler},stage='observed-ray-surface',step=step,contract=contract,strategy={'topology':'fixed','events':[]},extra=dict(config=conf,sourceContinuity=extra))
        ck('initial',0)
        with torch.no_grad():
            f=make_frame(data,contract['reference'],crop=False);a=base.render(f);b=model.render(f)
            initdiff={k:float((a[k]-b[k]).abs().max()) for k in ('rgb','q','alpha')}
            af=base.baseline.adjusted_frame(f); sa=base.state(af); sb=model.state(af)
            state_diff={k:float((getattr(sa,k)-getattr(sb,k)).abs().max()) for k in GaussianState.__dataclass_fields__}
            save_json(folder/'initial-render-check.json',dict(image=initdiff,state=state_diff))
        if max(initdiff.values())>2e-5:raise ValueError('initial_not_restored:'+str(initdiff))
        initial_diag=diagnostic(model,data,names,masks,priors,folder/'initial-moments')
        torch.cuda.reset_peak_memory_stats();started=time.perf_counter();curve=[];sampled=[]
        for step in range(1,steps+1):
            n=sampler.next();sampled.append(n);body_active=n in body_names
            geometry=config['warmup']<step<=min(config['geometryStop'],steps-60)
            for key,p in params.items():p.requires_grad_((not key.startswith('body.') or body_active) and (geometry or key.split('.')[-1] in ('sh','opacity')))
            for op in ops.values():op.zero_grad(set_to_none=True)
            f=make_frame(data,n,crop=False);r=model.render(f);mask={k:torch.tensor(v,device='cuda') for k,v in masks[n].items()}
            prior={k:(torch.tensor(d,device='cuda'),torch.tensor(v,device='cuda')) for k,(d,v) in priors.get(n,{}).items()}
            previous={k:v.to('cuda') for k,v in baseline_train[n].items()}
            loss=observed_loss(r,f,mask,previous,body_active);terms={}
            if label=='surface':v,terms=surface_objective(r,prior,mask,model.scale,body_active);loss+=v
            loss+=sum(.001*p.offset.tanh().square().mean()+.001*(p.log_scales-getattr(model,g+'_initial_scales').log()).square().mean()+.0001*p.sh[:,1:].square().mean() for g,p in model.patches.items())
            if not torch.isfinite(loss):raise ValueError('nonfinite_surface_loss')
            loss.backward()
            for key,p in params.items():
                if p.requires_grad and (p.grad is None or not torch.isfinite(p.grad).all()):raise ValueError('nonfinite_or_missing_gradient:'+key)
            for op in ops.values():op.step()
            with torch.no_grad():
                for g,p in model.patches.items():
                    initialscale=getattr(model,g+'_initial_scales');p.log_scales.clamp_((initialscale*.4).log(),(initialscale*1.5).log())
                    alpha=getattr(model,g+'_initial_opacity');p.opacity.clamp_(torch.logit((alpha-.15).clamp(.001,.999)),torch.logit((alpha+.15).clamp(.001,.999)))
            if step==steps//2:ck('mid',step)
            if step==1 or step%60==0:
                row=dict(step=step,name=n,loss=float(loss.detach()),geometry=geometry,**terms);curve.append(row);print(json.dumps(dict(branch=label,**row)),flush=True)
            if time.perf_counter()-started>900 or torch.cuda.max_memory_allocated()/1048576>6500:raise ValueError('surface_resource_budget')
        trainseconds=time.perf_counter()-started;ck('candidate-final',steps)
        _,after=evaluate_complete(model,data,names,masks,folder/'final-images',old)
        final_diag=diagnostic(model,data,names,masks,priors,folder/'final-moments')
        f=base.baseline.adjusted_frame(make_frame(data,contract['reference'],crop=False));state=model.state(f)
        asset=folder/'candidate-research-only.ply';export_state(state,asset);h=sha(asset)
        np.savez_compressed(folder/'candidate-identities.npz',**{**side,'asset_hash':np.array(h),'asset_sha256':np.array(h)})
        display=json.loads((Path(complete)/'display.json').read_text());display['assets']=[dict(label=label,ply=str(asset.resolve()),hash=h,count=len(state.means))];save_json(folder/'display.json',display)
        changes={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if k.startswith('patches.') and v.is_floating_point()}
        result=dict(baseline=before,final=after,initialDifference=initdiff,initialMoments=initial_diag,finalMoments=final_diag,
            failures=regression_screen(before,after),parameterChanges=changes,steps=steps,curve=curve,sampled=sampled,
            trainSeconds=trainseconds,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
            sourceHash=data['sourceHash'],reference=contract['reference'],assetHash=h,pointCount=len(state.means),headExactlyFrozen=exact_state_hash(base)==frozen,
            transactionAccepted=False,releaseQualityPassed=False,published=False)
        save_json(folder/'result.json',result);results[label]=result
        restore_checkpoint(folder/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda')
        if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()) or exact_state_hash(base)!=frozen:raise ValueError('complete_restore_failed')
        ck('restored',0);print(json.dumps(dict(branch=label,seconds=trainseconds,failures=result['failures'],assetHash=h)),flush=True)
        del model,ops,params;torch.cuda.empty_cache()
    save_json(out/'result.json',dict(branches={k:{x:v[x] for x in ('assetHash','steps','trainSeconds','failures','allocatedMiB','reservedMiB')} for k,v in results.items()},sourceHash=data['sourceHash'],sameSampleOrder=results['control']['sampled']==results['surface']['sampled'],seconds=time.perf_counter()-clock,published=False,releaseQualityPassed=False))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('complete','depth','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--steps',type=int,default=300);a=p.parse_args()
    try:run(a.complete,a.depth,a.out,a.steps)
    except Exception as e:
        import traceback
        if Path(a.out).exists():save_json(Path(a.out)/'failure.json',dict(error=str(e),traceback=traceback.format_exc(),published=False))
        raise
