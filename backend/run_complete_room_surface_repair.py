"""Equal-budget old-kernel vs measured local room-surface training.
Preserves the complete restored person and all unselected room points.
"""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_room_surface_repair import verified_surface_samples,RoomSurfaceStage
from reconstruction_components_v3 import pick,sha,save_json,exact_state_hash
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import make_frame,masked_mean
from reconstruction_surface_patch import weights
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,rng_state,restore_rng
from run_continuous_surface_repair import evaluate_complete,regression_screen,export_complete_candidate


def run(complete,mvs,out,steps=240,proposal_domain='world-ellipsoid'):
    out=Path(out);clock=time.perf_counter();torch.manual_seed(100104);np.random.seed(100104)
    data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    for name in ('run_complete_room_surface_repair.py','reconstruction_room_surface_repair.py','run_continuous_surface_repair.py'):
        shutil.copyfile(Path(__file__).with_name(name),out/'algorithm-source'/name)
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')};save_json(out/'contract.json',contract)
    world_train=sorted(n for n in plan['train'] if n in data['worlds']);selection=world_train[::max(1,len(world_train)//8)]
    masks=physical_masks(contract['spec']['prepared'],data,world_train)
    room=base.baseline.room.state();N=len(room.means);scores=torch.zeros(N,device='cuda');count=scores.clone()
    room_ids=torch.where(base.keep_room)[0];start=int(base.keep_head.sum())
    for n in selection:
        f=base.baseline.adjusted_frame(make_frame(data,n,crop=False));s=base.state(f);mask=torch.tensor(masks[n]['face'],device='cuda')
        contribution,_=weights(s,f['C'],f['K'],f['fullSize'][0],f['fullSize'][1],mask,unit_scale=base.scale)
        value=contribution[start:start+len(room_ids)]/mask.sum().clamp_min(1);scores[room_ids]+=value;count[room_ids]+=(value>1e-5)
    eligible=torch.where(base.keep_room&(scores>1e-4)&(count>=2))[0];ordered=eligible[torch.argsort(scores[eligible],descending=True)][:4]
    if not len(ordered):raise ValueError('no_repeatable_room_pollution')
    ids=ordered.cpu().numpy();parent=pick(room,ordered)
    save_json(out/'parent-proposal.json',dict(indices=ids.tolist(),scores=scores[ordered].cpu().tolist(),observations=count[ordered].cpu().tolist(),selection=selection,domain=proposal_domain))
    a,proposal=verified_surface_samples(mvs,data,plan,(parent.means.cpu().numpy(),parent.quats.cpu().numpy(),parent.scales.cpu().numpy()),8000,proposal_domain=proposal_domain)
    coverage=np.bincount(a['lineage'],minlength=len(ids));valid_parent=np.flatnonzero(coverage>=32)
    if not len(valid_parent):raise ValueError('no_parent_has_actual_local_surface_support')
    keep=np.isin(a['lineage'],valid_parent);a={k:v[keep] if getattr(v,'ndim',0)>0 and len(v)==len(keep) else v for k,v in a.items()}
    ids=ids[valid_parent];ordered=torch.as_tensor(ids,device='cuda');parent=pick(room,ordered)
    proposal.update(parentIndices=ids.tolist(),parentUID=base.baseline.room.metadata['point_uid'][ordered].cpu().tolist(),surfacePointsByOriginalParent=coverage.tolist(),
        allUnselectedPointsKept=True,noEntireFamilyDeletion=True,noGlobalScaleOpacityChange=True)
    save_json(out/'proposal.json',proposal);np.savez_compressed(out/'measured-surface.npz',**a)
    train=list(dict.fromkeys(proposal['names']+world_train[::max(1,len(world_train)//12)]))
    evaluation=list(dict.fromkeys(train+[contract['reference']]+[n for n in plan['development']+plan['audit'] if n in data['worlds']]))
    masks=physical_masks(contract['spec']['prepared'],data,evaluation);old,before=evaluate_complete(base,data,evaluation,masks,out/'baseline-images')
    t=lambda x:torch.as_tensor(x,device='cuda',dtype=torch.float32)
    new=GaussianState(t(a['means']),t(a['quats']),t(a['scales']),t(a['opacity']),t(a['sh']),torch.zeros(len(a['means']),device='cuda',dtype=torch.long))
    parent_uid=base.baseline.room.metadata['point_uid'][ordered].cpu().numpy();side=dict(np.load(Path(complete)/'candidate-identities.npz'))
    source_hash=exact_state_hash(base);random=rng_state();summary={}
    config=dict(steps=steps,train=train,evaluate=evaluation,parentIndices=ids.tolist(),proposal=proposal,
        allComponentsVisible=True,nativeFullFrame=True,fixedPersonExact=True,geometryFrozen=True,
        loss='all original valid physical parts and full room pixels, missing pixels included',scaleRange=[.8,1.2],published=False)
    save_json(out/'config.json',config)
    for label,state,uid,support,namespace in [('old-kernel-control',parent,parent_uid,np.ones(len(ids)),1),('surface-candidate',new,a['uid'],a['support'],5)]:
        folder=out/label;folder.mkdir();shutil.copyfile(out/'spec.json',folder/'spec.json')
        model=RoomSurfaceStage(base,ids,state,uid,support)
        for p in model.parameters():p.requires_grad_(False)
        initial={k:v.detach().clone() for k,v in model.state_dict().items()}
        rates={'sh':.003,'opacity':.008,'log_scales':.001,'quats':.0003};ops={k:torch.optim.Adam([getattr(model.patch,k)],lr=lr) for k,lr in rates.items()}
        for k in rates:getattr(model.patch,k).requires_grad_(True)
        sampler=FrameSampler(train,100104);restore_rng(random);curve=[]
        def checkpoint(name,step):save_checkpoint(folder/(name+'.pt'),model,ops,{'views':sampler},stage='measured-room-surface',step=step,contract=contract,
            strategy={'events':[],'topology':'finite surface replacement'},extra=dict(sourceContinuity=extra,config=config,surface=a if label=='surface-candidate' else None,
            parentIndices=ids,childUID=uid,initialPatch={k:v for k,v in initial.items() if k.startswith('patch.')},roomMetadata=base.baseline.room.metadata))
        checkpoint('initial',0);_,initial_metrics=evaluate_complete(model,data,evaluation,masks,folder/'initial-images',old)
        start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
        for step in range(1,steps+1):
            for op in ops.values():op.zero_grad(set_to_none=True)
            n=sampler.next();f=make_frame(data,n,crop=False);r=model.render(f);error=(r['rgb']-f['rgb']).abs().mean(-1);loss=error.sum()*0
            for part,weight in [('face',1.),('hair',.35),('neck',.5),('cloth',.5),('room',1.)]:
                mask=torch.tensor(masks[n][part],device='cuda')
                if mask.any():loss+=weight*(masked_mean(error,mask)+.1*valid_window_structure(r['rgb'],f['rgb'],mask))
            valid=torch.zeros_like(error,dtype=torch.bool)
            for part in masks[n]:valid|=torch.tensor(masks[n][part],device='cuda')
            oldalpha=torch.tensor(old[n]['alpha'],device='cuda');priorerror=torch.tensor(np.abs(old[n]['rgb']-data['rgb'][n]).mean(-1),device='cuda')
            roommask=torch.tensor(masks[n]['room'],device='cuda')
            loss+=3*masked_mean((oldalpha-r['alpha']-.015).clamp_min(0).square(),valid)
            loss+=2*masked_mean((error-priorerror-.01).clamp_min(0),roommask)+model.patch.regularizer()
            if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
            loss.backward()
            for key,p in model.patch.named_parameters():
                if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient:'+key)
            for op in ops.values():op.step()
            with torch.no_grad():model.patch.log_scales.clamp_(initial['patch.log_scales']+np.log(.8),initial['patch.log_scales']+np.log(1.2))
            if step==steps//2:checkpoint('mid',step)
            if step==1 or step%60==0:
                row=dict(step=step,name=n,loss=float(loss.detach()));curve.append(row);print(label,json.dumps(row),flush=True)
            if time.perf_counter()-start>720 or torch.cuda.memory_allocated()/1048576>7100:raise ValueError('finite_resource_budget')
        checkpoint('candidate-final',steps);_,after=evaluate_complete(model,data,evaluation,masks,folder/'final-images',old)
        failures=regression_screen(before,after);keep=np.ones(len(side['point_id']),bool);keep[model.full_ids.cpu().numpy()]=False
        result=dict(baseline=before,initial=initial_metrics,final=after,failures=failures,curve=curve,steps=steps,
            parameterChanges={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if k.startswith('patch.') and v.is_floating_point()},
            trainEvalSeconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
            frozenBaselineExact=exact_state_hash(base)==source_hash,transactionAccepted=False,releaseQualityPassed=False,published=False)
        export_complete_candidate(model,base,data,contract['reference'],folder,side,keep,uid,namespace,result)
        save_json(folder/'result.json',result);summary[label]={k:result[k] for k in ('assetHash','pointCount','failures','trainEvalSeconds','allocatedMiB','reservedMiB')}
        restore_checkpoint(folder/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda');checkpoint('restored',0)
        if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()):raise ValueError('room_transaction_restore_failed')
        if exact_state_hash(base)!=source_hash:raise ValueError('complete_scene_changed')
        del model,ops;torch.cuda.empty_cache();print(label,'FINISHED',json.dumps(summary[label]),flush=True)
    save_json(out/'result.json',dict(branches=summary,seconds=time.perf_counter()-clock,baselineAssetHash=contract['completeAssetHash'],published=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--mvs',required=True);p.add_argument('--out',required=True);p.add_argument('--steps',type=int,default=240);p.add_argument('--proposal-domain',choices=['world-ellipsoid','projected-surface'],default='world-ellipsoid');a=p.parse_args()
    try:run(a.complete,a.mvs,a.out,a.steps,a.proposal_domain)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise
