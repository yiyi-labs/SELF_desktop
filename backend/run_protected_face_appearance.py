"""Full native face appearance/covariance branch, independent of rejected depth.
Existing bound geometry and expression remain; no new world-joint face update.
"""
from pathlib import Path
import argparse,json,time,shutil
import numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_components_v3 import pick,sha,save_json,exact_state_hash
from reconstruction_portrait_pipeline import make_frame,masked_mean
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint
from run_native_head_surface_repair import NativeHairStage,local_assessment
from run_continuous_surface_repair import evaluate_complete,regression_screen
from reconstruction_asset_order import replace_rows
from run_haze_shared_surface import export_state


class FixedOrderFaceStage(NativeHairStage):
    def state(self,f):
        original=self.baseline.state(f)
        return replace_rows(original,self.head_patch(f).to_world(f['C'],f['F'],self.scale),self.head_rows)


def run(complete,out,steps=240):
    out=Path(out);clock=time.perf_counter();torch.manual_seed(100108)
    data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    for name in ('run_protected_face_appearance.py','run_native_head_surface_repair.py','run_measured_head_surface_repair.py','reconstruction_asset_order.py'):
        shutil.copyfile(Path(__file__).with_name(name),out/'algorithm-source'/name)
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')};save_json(out/'contract.json',contract)
    train=[n for n in plan['train'] if n in data['local']]
    evaluation=list(dict.fromkeys([contract['reference']]+plan['development']+plan['audit']))
    masks=physical_masks(contract['spec']['prepared'],data,list(dict.fromkeys(train+evaluation)))
    world=[n for n in evaluation if n in data['worlds']]
    f=base.baseline.adjusted_frame(make_frame(data,data['reference'],crop=False));state=base.baseline.head_state(f)
    ids=torch.where(base.keep_head&(state.parts==1))[0];parent=pick(state,ids);uid=base.baseline.portrait.stable_uid[ids]
    model=FixedOrderFaceStage(base,data,ids,parent,uid,torch.ones(len(ids),device='cuda'),False)
    for p in model.parameters():p.requires_grad_(False)
    frozen=exact_state_hash(base);initial={k:v.clone() for k,v in model.state_dict().items()}
    rates=dict(sh=.002,opacity=.0015,log_scales=.0004,quats=.0001)
    ops={k:torch.optim.Adam([getattr(model.patch,k)],lr=lr) for k,lr in rates.items()}
    for k in rates:getattr(model.patch,k).requires_grad_(True)
    sampler=FrameSampler(train,100108);side=dict(np.load(Path(complete)/'candidate-identities.npz'))
    config=dict(train=train,evaluate=evaluation,steps=steps,topology='fixed existing face IDs and binding',pointCountFixed=True,facePoints=len(ids),
        positionsFixed=True,originalExpressionMotionKept=True,nativeFullFrame=True,scaleRange=[1/1.1,1.1],maximumAlphaChange=.03,
        headOnlyTraining=True,allHeadPartsVisible=True,fullSceneEvaluation=True,newWorldJointUpdate=False,published=False)
    save_json(out/'config.json',config)
    def ck(label,step):save_checkpoint(out/(label+'.pt'),model,ops,{'views':sampler},stage='protected-native-face',step=step,contract=contract,strategy=dict(events=[],topology='fixed'),extra=dict(config=config,sourceContinuity=extra,ids=ids))
    old,before=evaluate_complete(base,data,world,masks,out/'baseline-full')
    local_init=local_assessment(model,base,data,evaluation,masks,out/'initial-local')
    # Protect the observed hair/eyes/accessory relation using source pixels,
    # never by repainting them with nearby skin.
    ck('initial',0);curve=[];start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    for step in range(1,steps+1):
        for op in ops.values():op.zero_grad(set_to_none=True)
        n=sampler.next();f=make_frame(data,n,crop=False);r=model.render_local(f)
        face=torch.tensor(masks[n]['face'],device='cuda');hair=torch.tensor(masks[n]['hair'],device='cuda');err=(r['rgb']-f['rgb']).abs().mean(-1)
        loss=masked_mean(err,face)+.12*valid_window_structure(r['rgb'],f['rgb'],face)+.25*masked_mean(err,hair)
        loss+=.002*(model.patch.sh[:,1:]-model.initial_sh[:,1:]).square().mean()
        if not torch.isfinite(loss):raise ValueError('nonfinite_face_loss')
        loss.backward()
        for k in rates:
            p=getattr(model.patch,k)
            if p.grad is None or not torch.isfinite(p.grad).all():raise ValueError('nonfinite_face_gradient')
            ops[k].step()
        with torch.no_grad():
            model.patch.log_scales.clamp_(initial['patch.log_scales']-np.log(1.1),initial['patch.log_scales']+np.log(1.1))
            model.patch.opacity.clamp_(torch.logit((model.initial_opacity-.03).clamp(.001,.999)),torch.logit((model.initial_opacity+.03).clamp(.001,.999)))
        if step==steps//2:ck('mid',step)
        if step==1 or step%60==0:
            row=dict(step=step,name=n,loss=float(loss.detach()));curve.append(row);print(json.dumps(row),flush=True)
        if time.perf_counter()-start>600 or torch.cuda.memory_allocated()/1048576>6500:raise ValueError('face_resource_budget')
    ck('candidate-final',steps);local_final=local_assessment(model,base,data,evaluation,masks,out/'final-local')
    _,final=evaluate_complete(model,data,world,masks,out/'final-full',old);failures=regression_screen(before,final)
    result=dict(baseline=before,final=final,localInitial=local_init,localFinal=local_final,steps=steps,curve=curve,failures=failures,
        trainEvalSeconds=time.perf_counter()-start,seconds=time.perf_counter()-clock,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
        parameterChanges={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if k.startswith('patch.') and v.is_floating_point()},
        frozenBaselineExact=exact_state_hash(base)==frozen,geometryRepaired=False,transactionAccepted=False,releaseQualityPassed=False,published=False)
    f=base.baseline.adjusted_frame(make_frame(data,contract['reference'],crop=False))
    asset=out/'candidate-research-only.ply';export_state(model.state(f),asset);result.update(assetHash=sha(asset),pointCount=len(side['point_id']),sourceHash=data['sourceHash'],reference=contract['reference'])
    np.savez_compressed(out/'candidate-identities.npz',**{**side,'asset_hash':np.array(result['assetHash'])})
    display=json.loads((Path(complete)/'display.json').read_text());display['assets']=[dict(label='fixed order face research',ply=str(asset.resolve()),hash=result['assetHash'],count=len(side['point_id']))];save_json(out/'display.json',display)
    save_json(out/'result.json',result)
    restore_checkpoint(out/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda')
    if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()) or exact_state_hash(base)!=frozen:raise ValueError('face_restore_failed')
    ck('restored',0);print(json.dumps({k:result[k] for k in ('assetHash','failures','seconds','allocatedMiB','reservedMiB')}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--out',required=True);p.add_argument('--steps',type=int,default=240);a=p.parse_args()
    try:run(a.complete,a.out,a.steps)
    except Exception as e:
        import traceback
        if Path(a.out).exists():save_json(Path(a.out)/'failure.json',dict(message=str(e),traceback=traceback.format_exc(),published=False))
        raise
