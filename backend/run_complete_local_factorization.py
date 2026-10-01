"""Finite complete-scene, local-kernel A/B. Never publishes any candidate."""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch,cv2
from reconstruction_complete_context import load_complete
from reconstruction_kernel_factorization import quadrature_children,LocalKernelTransaction
from reconstruction_components_v3 import pick,sha,save_json,exact_state_hash
from reconstruction_portrait_pipeline import make_frame,masked_mean
from reconstruction_surface_patch import weights
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,rng_state,restore_rng
from run_haze_shared_surface import export_state

def png(path,images):
    cv2.imwrite(str(path),cv2.cvtColor((np.clip(np.concatenate(images,1),0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))

def run(complete,out,steps=300,max_parents=4):
    out=Path(out);clock=time.perf_counter()
    torch.manual_seed(100101);np.random.seed(100101)
    data,plan,base,contract=load_complete(complete,out)
    extra=contract.pop('sourceExtra')
    for name in ('run_complete_local_factorization.py','reconstruction_complete_context.py','reconstruction_kernel_factorization.py'):
        shutil.copyfile(Path(__file__).with_name(name),out/'algorithm-source'/name)
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')}
    train=[n for n in plan['train'] if n in data['worlds']]
    # Uniform observation identities, not a fixed video or fixed favourable ROI.
    train=train[::max(1,len(train)//12)]
    evaluated=list(dict.fromkeys(train+[contract['reference']]+[n for n in plan['development']+plan['audit'] if n in data['worlds']]))
    masks=physical_masks(contract['spec']['prepared'],data,evaluated)
    N=len(base.baseline.room.state().means)
    scores=torch.zeros(N,device='cuda');count=torch.zeros(N,device='cuda');reference=contract['reference']
    names=train[::max(1,len(train)//6)]
    head_count=int(base.keep_head.sum());room_ids=torch.where(base.keep_room)[0]
    for n in names:
        f=base.baseline.adjusted_frame(make_frame(data,n,crop=False));s=base.state(f)
        mask=torch.tensor(masks[n]['face'],device='cuda')
        contribution,info=weights(s,f['C'],f['K'],f['fullSize'][0],f['fullSize'][1],mask,unit_scale=base.scale)
        room=contribution[head_count:head_count+len(room_ids)]/mask.sum().clamp_min(1)
        scores[room_ids]+=room;count[room_ids]+=(room>1e-5).float()
    eligible=base.keep_room&(scores>1e-4)&(count>=2)
    ordered=torch.where(eligible)[0];ordered=ordered[torch.argsort(scores[ordered],descending=True)][:max_parents]
    if not len(ordered):raise ValueError('no_repeatable_room_contributors')
    ids=ordered.cpu().numpy();room=base.baseline.room.state();uid=base.baseline.room.metadata['point_uid'][ordered].cpu().numpy()
    parent=pick(room,ordered);children,newuid,meta=quadrature_children(parent,uid,order=7,fraction=.45)
    config=dict(steps=steps,seed=100101,train=train,evaluate=evaluated,parentIndices=ids.tolist(),
        parentUID=uid.tolist(),contributions=scores[ordered].cpu().tolist(),selection='actual full-frame alpha*T on training face; >=2 observations; at most four kernels',
        factorization=meta,allComponentsVisible=True,nativeFullFrame=True,
        loss='original pixels, equal part normalization, per-pixel coverage/content protection',
        scaleRange=[.7,1.3],boundedPositionStart=180,positionEvery=5,
        developmentUsedForSelection=False,baselineStatus='complete research candidate, not quality passed',
        published=False)
    save_json(out/'config.json',config);save_json(out/'contract.json',contract)
    old={}
    with torch.no_grad():
        for n in evaluated:
            f=make_frame(data,n,crop=False);r=base.render(f)
            old[n]={'rgb':r['rgb'].cpu().numpy(),'alpha':r['alpha'].cpu().numpy(),'q':r['q'].cpu().numpy()}
    state_before=exact_state_hash(base); random=rng_state(); results={}
    for label,state,identities in [('control',parent,uid),('factorized',children,newuid)]:
        folder=out/label;folder.mkdir()
        shutil.copyfile(out/'spec.json',folder/'spec.json')
        m=LocalKernelTransaction(base,ids,state,identities)
        for p in m.parameters():p.requires_grad_(False)
        init={k:v.detach().clone() for k,v in m.patch.state_dict().items()}
        rates={'sh':.003,'opacity':.008,'log_scales':.001,'quats':.0003,'offset':.001}
        ops={k:torch.optim.Adam([getattr(m.patch,k)],lr=lr) for k,lr in rates.items()}
        sampler=FrameSampler(train,100101); restore_rng(random);curve=[]
        def checkpoint(name,step):
            save_checkpoint(folder/(name+'.pt'),m,ops,{'views':sampler},stage='local-room-'+label,
                step=step,contract=contract,strategy={'events':[],'topology':label+' inherited covariance transaction'},
                extra={'config':config,'sourceContinuity':extra,'parentIndices':ids,'childUID':identities,
                       'parentUID':uid,'initialPatch':init,'roomMetadata':base.baseline.room.metadata})
        def evaluate(stage):
            destination=folder/(stage+'-images');destination.mkdir()
            result={}
            with torch.no_grad():
                for n in evaluated:
                    f=make_frame(data,n,crop=False);r=m.render(f); rgb=r['rgb'].cpu().numpy();alpha=r['alpha'].cpu().numpy();q=r['q'].cpu().numpy()
                    target=data['rgb'][n]; row={}
                    for part,index in [('face',1),('hair',2),('neck',4),('cloth',4),('room',0)]:
                        mask=masks[n][part]
                        if not mask.any():continue
                        a=old[n];error=np.abs(rgb-target).mean(-1);before=np.abs(a['rgb']-target).mean(-1)
                        row[part]=dict(rgb=float(error[mask].mean()),baselineRgb=float(before[mask].mean()),
                            q=float(q[...,index][mask].mean()),baselineQ=float(a['q'][...,index][mask].mean()),
                            qRoom=float(q[...,0][mask].mean()),baselineQRoom=float(a['q'][...,0][mask].mean()),
                            alpha=float(alpha[mask].mean()),baselineAlpha=float(a['alpha'][mask].mean()),
                            holeBelow08=float((alpha[mask]<.8).mean()),baselineHoleBelow08=float((a['alpha'][mask]<.8).mean()),
                            pixelRegressionP90=float(np.quantile((error-before)[mask],.9)))
                    conservation=float((r['q'].sum(-1)-r['alpha']).abs().max())
                    if conservation>1e-4:raise ValueError('q_conservation')
                    result[n]=row
                    png(destination/(n+'.png'),[target,old[n]['rgb'],rgb])
                    np.savez_compressed(destination/(n+'.npz'),rgb=rgb,alpha=alpha,q=q)
            save_json(destination/'metrics.json',result);return result
        checkpoint('initial',0);initial=evaluate('initial')
        torch.cuda.reset_peak_memory_stats();trainclock=time.perf_counter()
        for step in range(1,steps+1):
            geometry=step>=180 and step%5==0
            for k in rates:getattr(m.patch,k).requires_grad_(geometry if k=='offset' else not geometry)
            for op in ops.values():op.zero_grad(set_to_none=True)
            n=sampler.next();f=make_frame(data,n,crop=False);r=m.render(f)
            error=(r['rgb']-f['rgb']).abs().mean(-1);loss=error.sum()*0
            for part,weight in [('face',1.),('hair',.35),('neck',.5),('cloth',.5),('room',1.)]:
                mask=torch.tensor(masks[n][part],device='cuda')
                if mask.any():
                    loss+=weight*(masked_mean(error,mask)+.1*valid_window_structure(r['rgb'],f['rgb'],mask))
            roommask=torch.tensor(masks[n]['room'],device='cuda')
            oldrgb=torch.tensor(old[n]['rgb'],device='cuda');oldalpha=torch.tensor(old[n]['alpha'],device='cuda')
            priorerror=(oldrgb-f['rgb']).abs().mean(-1)
            # Protect all known content; don't distil the old veiled RGB.
            valid=torch.zeros_like(roommask)
            for part in ('face','hair','neck','cloth','room'):valid|=torch.tensor(masks[n][part],device='cuda')
            loss+=3*masked_mean((oldalpha-r['alpha']-.015).clamp_min(0).square(),valid)
            loss+=2*masked_mean((error-priorerror-.01).clamp_min(0),roommask)
            loss+=.0002*m.patch.sh[:,1:].square().mean()+.002*m.patch.offset.tanh().square().mean()
            if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
            loss.backward()
            for k,p in m.patch.named_parameters():
                if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient:'+k)
            if geometry:ops['offset'].step()
            else:
                for k in rates:
                    if k!='offset':ops[k].step()
            with torch.no_grad():
                m.patch.log_scales.copy_(torch.maximum(torch.minimum(m.patch.log_scales,init['log_scales']+np.log(1.3)),init['log_scales']+np.log(.7)))
            if step==steps//2:checkpoint('mid',step)
            if step==1 or step%60==0:
                curve.append(dict(step=step,name=n,geometry=geometry,loss=float(loss.detach())))
                print(label,json.dumps(curve[-1]),flush=True)
            if time.perf_counter()-trainclock>720 or torch.cuda.memory_allocated()/1048576>7100:
                raise ValueError('finite_resource_budget')
        checkpoint('candidate-final',steps);final=evaluate('final')
        failures=[]
        for n in evaluated:
            for part,row in final[n].items():
                if row['rgb']>row['baselineRgb']+.003:failures.append(part+'_rgb:'+n)
                if row['alpha']<row['baselineAlpha']-.015:failures.append(part+'_coverage:'+n)
                if row['holeBelow08']>row['baselineHoleBelow08']+.02:failures.append(part+'_holes:'+n)
        f=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));s=m.state(f)
        asset=folder/'candidate-research-only.ply';export_state(s,asset)
        source_side=dict(np.load(Path(complete)/'candidate-identities.npz'))
        oldids=torch.where(base.keep_room)[0].cpu().numpy();keep=np.ones(len(source_side['point_id']),bool)
        keep[head_count:head_count+len(oldids)]=~np.isin(oldids,ids)
        inherited=np.repeat(uid,meta['childrenPerParent']) if label=='factorized' else uid
        uids=np.r_[source_side['source_uid'][keep],identities]
        namespaces=np.r_[source_side['source_namespace'][keep],np.full(len(identities),4)]
        if len(np.unique(np.c_[namespaces,uids],axis=0))!=len(uids):raise ValueError('UID_collision')
        np.savez_compressed(folder/'candidate-identities.npz',point_id=np.arange(len(uids)),
            source_uid=uids,source_namespace=namespaces,component=s.parts.cpu().numpy(),
            parent_uid=np.r_[np.full(keep.sum(),-1),inherited],asset_hash=np.array(sha(asset)),
            source_hash=np.array(data['sourceHash']),reference=np.array(reference))
        inv=torch.linalg.inv(f['C']).cpu().numpy();h,w=f['rgb'].shape[:2]
        save_json(folder/'display.json',dict(assets=[dict(label=label,ply=str(asset.resolve()),hash=sha(asset),count=len(s.means))],
            K=f['K'].cpu().tolist(),C=f['C'].cpu().tolist(),width=w,height=h,camera=inv[:3,3].tolist(),
            target=(inv[:3,3]+inv[:3,2]).tolist(),up=(-inv[:3,1]).tolist(),near=.01*m.scale,far=1e10*m.scale,
            reference=reference,sourceHash=data['sourceHash'],published=False))
        changes={k:float((v-init[k]).abs().mean()) for k,v in m.patch.state_dict().items() if v.is_floating_point()}
        result=dict(sourceHash=data['sourceHash'],reference=reference,assetHash=sha(asset),pointCount=len(s.means),
            baselineAssetHash=contract['completeAssetHash'],initial=initial,final=final,failures=failures,
            curve=curve,parameterChanges=changes,steps=steps,trainEvalSeconds=time.perf_counter()-trainclock,
            allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
            scope='only selected room latent representation; every human/body tensor exact',
            transactionAccepted=False,releaseQualityPassed=False,published=False)
        save_json(folder/'result.json',result);results[label]={k:result[k] for k in ('assetHash','pointCount','failures','trainEvalSeconds','allocatedMiB','reservedMiB')}
        restore_checkpoint(folder/'initial.pt',m,ops,{'views':sampler},contract=contract,device='cuda')
        checkpoint('restored',0)
        if any(not torch.equal(v,m.patch.state_dict()[k]) for k,v in init.items()):
            raise ValueError('local_restore_not_exact')
        if exact_state_hash(base)!=state_before:raise ValueError('protected_scene_changed')
        print(label,'FINISHED',json.dumps(results[label]),flush=True)
    save_json(out/'result.json',dict(sourceHash=data['sourceHash'],baselineAssetHash=contract['completeAssetHash'],
        branches=results,seconds=time.perf_counter()-clock,frozenSceneExact=True,published=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--out',required=True);p.add_argument('--steps',type=int,default=300);a=p.parse_args()
    try:run(a.complete,a.out,a.steps)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise