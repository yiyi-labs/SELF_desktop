"""One finite continuation: local room factors + newly exposed neck appearance.
No face geometry/appearance, hair, clothing, K/F/C or body motion update.
The input factorization failed its screens; it is never declared a good baseline.
"""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch,cv2
from reconstruction_complete_context import load_complete
from reconstruction_kernel_factorization import LocalKernelTransaction
from reconstruction_components_v3 import sha,save_json
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import make_frame,masked_mean
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint
from run_haze_shared_surface import export_state

def run(complete,source,out,steps=240):
    out=Path(out);clock=time.perf_counter();data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    source=Path(source);ck=torch.load(source/'candidate-final.pt',map_location='cuda',weights_only=False)
    if ck['contract']['completeAssetHash']!=contract['completeAssetHash']:raise ValueError('source_baseline_changed')
    d=ck['model'];t=lambda key:d['patch.'+key]
    children=GaussianState(t('base'),t('quats'),t('log_scales').exp(),t('opacity').sigmoid(),t('sh'),t('parts'))
    ids=ck['extra']['parentIndices'];uid=ck['extra']['childUID']
    m=LocalKernelTransaction(base,ids,children,uid);m.load_state_dict(d,strict=True)
    for k,v in d.items():
        if not torch.equal(v,m.state_dict()[k]):raise ValueError('source_restore_inexact')
    for p in m.parameters():p.requires_grad_(False)
    train=ck['extra']['config']['train'];evaluated=ck['extra']['config']['evaluate'];names_neck=set(extra['meta']['names'])
    active=base.is_neck;neck=base.patch;patch=m.patch
    masks=physical_masks(contract['spec']['prepared'],data,evaluated);old={}
    # Restore base neck is exact to original complete checkpoint; only patch
    # room differed in the input. Loss protection compares the complete scene.
    with torch.no_grad():
        for n in evaluated:
            r=base.render(make_frame(data,n,crop=False));old[n]={k:r[k].cpu().numpy() for k in ('rgb','alpha','q')}
    rates={'room_sh':(patch.sh,.002),'room_alpha':(patch.opacity,.004),'room_scale':(patch.log_scales,.0006),
        'room_rotation':(patch.quats,.0002),'neck_sh':(neck.sh,.0015),'neck_alpha':(neck.opacity,.004),'neck_scale':(neck.log_scales,.0006)}
    ops={k:torch.optim.Adam([p],lr=lr) for k,(p,lr) in rates.items()};sampler=FrameSampler(train,100103)
    initial={k:v.detach().clone() for k,v in m.state_dict().items()}
    contract.update(factorCheckpointHash=sha(source/'candidate-final.pt'),newOptimizerWarmStart=True)
    for file in ('run_complete_exposed_recovery.py','reconstruction_complete_context.py','reconstruction_kernel_factorization.py'):
        shutil.copyfile(Path(__file__).with_name(file),out/'algorithm-source'/file)
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')}
    config=dict(steps=steps,train=train,neckValidTrainingNames=sorted(names_neck),evaluate=evaluated,
        nativeFullFrame=True,allComponentsVisible=True,faceHairClothAndMotionFixed=True,
        roomGeometryFixed=True,neckGeometryFixed=True,
        sourceStatus='rejected factorization used only as diagnostic continuation',published=False)
    save_json(out/'config.json',config);save_json(out/'contract.json',contract)
    def checkpoint(label,step):save_checkpoint(out/(label+'.pt'),m,ops,{'views':sampler},stage='exposed-neck-recovery',step=step,
        contract=contract,strategy={'events':[],'topology':'unchanged factorization'},
        extra=dict(sourceContinuity=extra,config=config,parentIndices=ids,childUID=uid))
    def assess(label):
        folder=out/(label+'-images');folder.mkdir();rows={}
        with torch.no_grad():
            for n in evaluated:
                r=m.render(make_frame(data,n,crop=False));rgb=r['rgb'].cpu().numpy();alpha=r['alpha'].cpu().numpy();q=r['q'].cpu().numpy();target=data['rgb'][n];before=old[n];row={}
                for part in ('face','hair','neck','cloth','room'):
                    mask=masks[n][part]
                    if mask.any():row[part]=dict(rgb=float(np.abs(rgb-target).mean(-1)[mask].mean()),baselineRgb=float(np.abs(before['rgb']-target).mean(-1)[mask].mean()),
                        alpha=float(alpha[mask].mean()),baselineAlpha=float(before['alpha'][mask].mean()),holeBelow08=float((alpha[mask]<.8).mean()),baselineHoleBelow08=float((before['alpha'][mask]<.8).mean()),
                        qRoom=float(q[...,0][mask].mean()),baselineQRoom=float(before['q'][...,0][mask].mean()))
                rows[n]=row;cv2.imwrite(str(folder/(n+'.png')),cv2.cvtColor((np.clip(np.concatenate([target,before['rgb'],rgb],1),0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
                np.savez_compressed(folder/(n+'.npz'),rgb=rgb,alpha=alpha,q=q)
        save_json(folder/'metrics.json',rows);return rows
    checkpoint('initial',0);initmetrics=assess('initial');curve=[];torch.cuda.reset_peak_memory_stats();start=time.perf_counter()
    for step in range(1,steps+1):
        for p,_ in rates.values():p.requires_grad_(True)
        for op in ops.values():op.zero_grad(set_to_none=True)
        n=sampler.next();f=make_frame(data,n,crop=False);r=m.render(f)
        error=(r['rgb']-f['rgb']).abs().mean(-1);before=old[n];before_err=(torch.tensor(before['rgb'],device='cuda')-f['rgb']).abs().mean(-1)
        loss=error.sum()*0
        for part,weight in [('face',1.),('hair',.35),('neck',.6),('cloth',.5),('room',1.)]:
            mask=torch.tensor(masks[n][part],device='cuda')
            loss+=weight*(masked_mean(error,mask)+.1*valid_window_structure(r['rgb'],f['rgb'],mask))
            if part!='neck':
                loss+=4*masked_mean((error-before_err-.003).clamp_min(0),mask)
            loss+=3*masked_mean((torch.tensor(before['alpha'],device='cuda')-r['alpha']-.01).clamp_min(0).square(),mask)
        # Keep previously clean observations clean. This does not assert all
        # room contribution is invalid or force q_room to zero.
        face=torch.tensor(masks[n]['face'],device='cuda')
        priorq=torch.tensor(before['q'][...,0],device='cuda').clamp_min(.025)
        loss+=.25*masked_mean((r['q'][...,0]-priorq).clamp_min(0),face)
        loss+=.0002*patch.sh[:,1:].square().mean()
        if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
        loss.backward()
        for p,_ in rates.values():
            if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient')
        for key in ('sh','opacity','log_scales'):
            p=getattr(neck,key)
            if p.grad is not None:
                p.grad[~active]=0
                if n not in names_neck:p.grad.zero_()
        for key,op in ops.items():
            if key.startswith('neck_') and n not in names_neck:continue
            op.step()
        with torch.no_grad():
            patch.log_scales.copy_(torch.maximum(torch.minimum(patch.log_scales,initial['patch.log_scales']+np.log(1.1)),initial['patch.log_scales']+np.log(.9)))
            neck.log_scales.copy_(torch.maximum(torch.minimum(neck.log_scales,initial['baseline.patch.log_scales']+np.log(1.1)),initial['baseline.patch.log_scales']+np.log(.9)))
        if step==steps//2:checkpoint('mid',step)
        if step==1 or step%60==0:curve.append(dict(step=step,name=n,loss=float(loss.detach())));print(json.dumps(curve[-1]),flush=True)
        if time.perf_counter()-start>720 or torch.cuda.memory_allocated()/1048576>7100:raise ValueError('finite_budget')
    checkpoint('candidate-final',steps);final=assess('final');failures=[]
    allowed={'patch.sh','patch.opacity','patch.log_scales','patch.quats','baseline.patch.sh','baseline.patch.opacity','baseline.patch.log_scales'}
    for k,v in m.state_dict().items():
        if k in allowed:
            if k.startswith('baseline.patch.') and not torch.equal(v[~active],initial[k][~active]):raise ValueError('cloth_changed')
        elif not torch.equal(v,initial[k]):raise ValueError('protected_parameter:'+k)
    for n,row in final.items():
        for part,v in row.items():
            if v['rgb']>v['baselineRgb']+.003:failures.append(part+'_rgb:'+n)
            if v['alpha']<v['baselineAlpha']-.015:failures.append(part+'_coverage:'+n)
            if v['holeBelow08']>v['baselineHoleBelow08']+.02:failures.append(part+'_holes:'+n)
    ref=contract['reference'];f=base.baseline.adjusted_frame(make_frame(data,ref,crop=False));s=m.state(f);asset=out/'candidate-research-only.ply';export_state(s,asset)
    side=dict(np.load(source/'candidate-identities.npz'));side['asset_hash']=np.array(sha(asset));np.savez_compressed(out/'candidate-identities.npz',**side)
    display=json.loads((source/'display.json').read_text());display['assets']=[dict(label='exposed',ply=str(asset.resolve()),hash=sha(asset),count=len(s.means))];save_json(out/'display.json',display)
    result=dict(sourceHash=data['sourceHash'],reference=ref,assetHash=sha(asset),pointCount=len(s.means),baselineAssetHash=contract['completeAssetHash'],initial=initmetrics,final=final,failures=failures,curve=curve,protectedFieldsExact=True,steps=steps,totalSeconds=time.perf_counter()-clock,trainEvalSeconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,transactionAccepted=False,releaseQualityPassed=False,published=False)
    save_json(out/'result.json',result);restore_checkpoint(out/'initial.pt',m,ops,{'views':sampler},contract=contract,device='cuda');checkpoint('restored',0)
    if any(not torch.equal(v,m.state_dict()[k]) for k,v in initial.items()):raise ValueError('restore_inexact')
    print('EXPOSED_RECOVERY_COMPLETE_NOT_PUBLISHED',len(failures),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--source',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    try:run(a.complete,a.source,a.out)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(message=str(e),traceback=traceback.format_exc(),published=False))
        raise