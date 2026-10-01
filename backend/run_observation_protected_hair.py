"""One equal-budget hair candidate with reliable-empty observation protection.
Reuse exact frozen proposal and candidate initialization; no new MVS/topology.
"""
from pathlib import Path
import argparse,json,time,shutil
import cv2,numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_components_v3 import pick,sha,save_json,exact_state_hash
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,restore_rng
from reconstruction_observation_protection import extra_foreground_loss
from run_cross_window_surface_repair import NativeHairStage,local_assessment
from run_continuous_surface_repair import evaluate_complete,regression_screen,export_complete_candidate

def run(complete,source,out):
    out=Path(out);source=Path(source);start=time.perf_counter()
    data,plan,base,contract=load_complete(complete,out);original=contract.pop('sourceExtra')
    ck=torch.load(source/'initial.pt',map_location='cuda',weights_only=False);oldResult=json.loads((source/'result.json').read_text())
    if ck['contract']['completeCheckpointHash']!=contract['completeCheckpointHash']:raise ValueError('frozen_base_changed')
    extra=ck['extra'];a=extra['surface'];ids=extra['ids'];t=lambda x:torch.as_tensor(x,device='cuda',dtype=torch.float32)
    state=GaussianState(t(a['means']),t(a['quats']),t(a['scales']),t(a['opacity']),t(a['sh']),torch.full((len(a['means']),),2,device='cuda',dtype=torch.long))
    uid=torch.as_tensor(a['uid'],device='cuda');model=NativeHairStage(base,data,ids,state,uid,t(a['support']),True)
    model.load_state_dict(ck['model'],strict=True)
    if any(not torch.equal(v,model.state_dict()[k]) for k,v in ck['model'].items()):raise ValueError('initial_state_not_exact')
    for p in model.parameters():p.requires_grad_(False)
    rates={k:v['param_groups'][0]['lr'] for k,v in ck['optimizers'].items()}
    ops={k:torch.optim.Adam([getattr(model.patch,k)],lr=v) for k,v in rates.items()}
    for k in rates:getattr(model.patch,k).requires_grad_(True)
    config=dict(extra['config']);config.update(reliableEmptyProtectionWeight=.5,reliableEmpty='eroded original confident room pixels; unknown untouched',
        sourceInitialHash=sha(source/'initial.pt'),MVSAndTopologyReused=True,sameInitialState=True,sameSamplingBudget=True)
    train=config['train'];evaluation=config['evaluate'];world=config['worldEvaluate'];steps=config['steps']
    masks=physical_masks(contract['spec']['prepared'],data,evaluation);old,before=evaluate_complete(base,data,world,masks,out/'baseline-full')
    prior={};empty={}
    with torch.no_grad():
        for n in train:
            f=base.baseline.adjusted_frame(make_frame(data,n,crop=False));h,w=f['rgb'].shape[:2]
            r=draw(pick(base.baseline.head_state(f),base.keep_head),f['F'],f['K'],w,h)
            prior[n]=r['q'][...,2].cpu().numpy()
            empty[n]=cv2.erode(masks[n]['room'].astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)
    initial={k:v.clone() for k,v in model.state_dict().items()};baseline_hash=exact_state_hash(base)
    local_init=local_assessment(model,base,data,evaluation,masks,out/'initial-local')
    sampler=FrameSampler(train,100106);sampler.load_state_dict(ck['samplers']['views']);restore_rng(ck['rng'])
    for name in ('run_observation_protected_hair.py','reconstruction_observation_protection.py','run_cross_window_surface_repair.py'):
        shutil.copyfile(Path(__file__).with_name(name),out/'algorithm-source'/name)
    contract.update(originalHairInitialHash=config['sourceInitialHash'],sourceSnapshot={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')});save_json(out/'contract.json',contract);save_json(out/'config.json',config)
    def save(label,step):save_checkpoint(out/(label+'.pt'),model,ops,{'views':sampler},stage='observed-empty-hair-protection',step=step,contract=contract,strategy=dict(events=[],topology='frozen actual cross-window surface'),extra=dict(sourceContinuity=original,sourceHairInitializationHash=config['sourceInitialHash'],config=config,ids=ids,surface=a))
    save('initial',0);curve=[];clock=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    for step in range(1,steps+1):
        for op in ops.values():op.zero_grad(set_to_none=True)
        n=sampler.next();f=make_frame(data,n,crop=False);r=model.render_local(f)
        hair=torch.tensor(masks[n]['hair'],device='cuda');face=torch.tensor(masks[n]['face'],device='cuda');err=(r['rgb']-f['rgb']).abs().mean(-1)
        loss=masked_mean(err,hair)+.12*valid_window_structure(r['rgb'],f['rgb'],hair)+.025*masked_mean((1-r['q'][...,2]).square(),hair)+.5*masked_mean(err,face)+.05*masked_mean(r['q'][...,2].square(),face)+model.patch.regularizer()
        protection=extra_foreground_loss(r['q'][...,2],torch.tensor(prior[n],device='cuda'),torch.tensor(empty[n],device='cuda'))
        loss+=.5*protection
        if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
        loss.backward()
        for p in model.patch.parameters():
            if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient')
        for op in ops.values():op.step()
        with torch.no_grad():model.patch.log_scales.clamp_(initial['patch.log_scales']+np.log(.8),initial['patch.log_scales']+np.log(1.2))
        if step==steps//2:save('mid',step)
        if step==1 or step%60==0:
            row=dict(step=step,name=n,loss=float(loss.detach()),emptyProtection=float(protection.detach()));curve.append(row);print(json.dumps(row),flush=True)
        if time.perf_counter()-clock>600 or torch.cuda.memory_allocated()/1048576>6500:raise ValueError('finite_resource_budget')
    save('candidate-final',steps);local_final=local_assessment(model,base,data,evaluation,masks,out/'final-local');_,after=evaluate_complete(model,data,world,masks,out/'final-full',old)
    failures=regression_screen(before,after)
    result=dict(baseline=before,final=after,localInitial=local_init,localFinal=local_final,steps=steps,curve=curve,failures=failures,sourceHash=data['sourceHash'],reference=contract['reference'],
        controlAssetHash=oldResult['assetHash'],trainEvalSeconds=time.perf_counter()-clock,seconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
        parameterChanges={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if k.startswith('patch.') and v.is_floating_point()},
        frozenBaselineExact=exact_state_hash(base)==baseline_hash,sameInitialState=True,sameSamplingNames=all(r['name']==oldResult['curve'][i]['name'] for i,r in enumerate(curve)),transactionAccepted=False,releaseQualityPassed=False,published=False)
    side=dict(np.load(Path(complete)/'candidate-identities.npz'));keep=np.ones(len(side['point_id']),bool);keep[model.head_rows.cpu().numpy()]=False
    export_complete_candidate(model,base,data,contract['reference'],out,side,keep,uid.cpu().numpy(),6,result);save_json(out/'result.json',result)
    restore_checkpoint(out/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda');save('restored',0)
    if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()) or exact_state_hash(base)!=baseline_hash:raise ValueError('protection_restore_failed')
    print(json.dumps({k:result[k] for k in ('assetHash','failures','seconds','allocatedMiB','reservedMiB','sameSamplingNames')}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('complete','source','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args()
    try:run(a.complete,a.source,a.out)
    except Exception as e:
        import traceback
        if Path(a.out).exists():save_json(Path(a.out)/'failure.json',dict(message=str(e),traceback=traceback.format_exc(),published=False))
        raise