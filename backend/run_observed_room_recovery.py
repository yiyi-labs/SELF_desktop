"""Native full-scene recovery of a finite observed room surface hypothesis.

Old room is replaced only in this isolated candidate, not copied in to conceal
holes. The original human, cameras and source checkpoint remain bitwise fixed.
An incomplete candidate is rejected, never installed or published.
"""
from pathlib import Path
import argparse,json,shutil,time
import cv2,numpy as np,torch
from reconstruction_evidence_stage import load_stage
from reconstruction_components_v3 import FreeComponent,exact_state_hash,save_json,sha
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_portrait_pipeline import draw,make_frame,masked_mean
from run_haze_shared_surface import export_state
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_observed_coverage import balanced_region_mean
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint


class ObservedRoomStage(torch.nn.Module):
    def __init__(self,base,arrays):
        super().__init__();self.baseline=base;self.scale=base.scale
        t=lambda x,dtype=torch.float32:torch.as_tensor(x,device='cuda',dtype=dtype)
        s=GaussianState(*[t(arrays[k]) for k in ('means','quats','scales','opacity','sh')],t(arrays['parts'],torch.long))
        self.room_surface=FreeComponent(s,t(arrays['uid'],torch.long),t(arrays['support']), 'world',0.)
    def state(self,frame):
        f=self.baseline.adjusted_frame(frame)
        if f['C'] is None:raise ValueError('no_world_camera')
        return joined_state(self.baseline.head_state(f).to_world(f['C'],f['F'],self.scale),self.room_surface.state(),self.baseline.body_state(f['name']))
    def render(self,frame):
        f=self.baseline.adjusted_frame(frame);h,w=f['rgb'].shape[:2]
        return draw(self.state(frame),f['C'],f['K'],w,h,unit_scale=self.scale)


@torch.no_grad()
def evaluate(model,data,names,masks,folder,*,baseline=False):
    folder.mkdir(exist_ok=False);rows={}
    for name in names:
        f=make_frame(data,name,crop=False);r=model.render(f,'T2') if baseline else model.render(f)
        rgb=r['rgb'].cpu().numpy();q=r['q'].cpu().numpy();alpha=r['alpha'].cpu().numpy();target=data['rgb'][name];err=np.abs(rgb-target).mean(-1)
        rows[name]={}
        for label,index in [('face',1),('hair',2),('neck',4),('cloth',4),('room',0)]:
            mask=masks[name][label]
            if not mask.any():continue
            tile_errors=[]
            for y in range(0,mask.shape[0],96):
                for x in range(0,mask.shape[1],96):
                    mm=mask[y:y+96,x:x+96]
                    if mm.sum()>=64:tile_errors.append(float(err[y:y+96,x:x+96][mm].mean()))
            rows[name][label]=dict(rgb=float(err[mask].mean()),alpha=float(q[...,index][mask].mean()),
                below08=float((q[...,index][mask]<.8).mean()),qRoom=float(q[...,0][mask].mean()),
                structure=float(valid_window_structure(r['rgb'],f['rgb'],torch.as_tensor(mask,device='cuda'))),
                tileErrorP90=float(np.quantile(tile_errors,.9)) if tile_errors else None)
        if float((r['q'].sum(-1)-r['alpha']).abs().max())>1e-4:raise ValueError('q_conservation')
        cv2.imwrite(str(folder/(name+'.jpg')),cv2.cvtColor((np.concatenate([target,rgb.clip(0,1)],1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        np.savez_compressed(folder/(name+'.npz'),rgb=rgb,alpha=alpha,q=q)
    save_json(folder/'metrics.json',rows);return rows


def run(stage,surface,out,steps=360):
    started=time.perf_counter();out=Path(out);torch.manual_seed(100103);np.random.seed(100103)
    data,plan,base,contract=load_stage(stage,out);folder=Path(surface);a=dict(np.load(folder/'surface.npz'));meta=json.loads((folder/'result.json').read_text())
    if str(a['source_hash'])!=data['sourceHash'] or meta['component']!='room':raise ValueError('wrong_source_or_component')
    names=sorted(meta['names'])
    if set(names)&set(plan['development']+plan['audit']) or any(n not in data['worlds'] or data['local'][n]['role']!='train' for n in names):raise ValueError('invalid_training_observations')
    checks=list(dict.fromkeys(names+[n for n in plan['development']+plan['audit'] if n in data['worlds']]))
    masks=physical_masks(contract['spec']['prepared'],data,checks);model=ObservedRoomStage(base,a);frozen=exact_state_hash(base)
    for p in model.parameters():p.requires_grad_(False)
    rates=dict(sh=.003,opacity=.01,log_scales=.001)
    for key in rates:getattr(model.room_surface,key).requires_grad_(True)
    optim={k:torch.optim.Adam([getattr(model.room_surface,k)],lr=v) for k,v in rates.items()};sampler=FrameSampler(names,100103)
    before={k:v.detach().clone() for k,v in model.room_surface.state_dict().items()}
    config=dict(steps=steps,seed=100103,rates=rates,topology='fixed observed surface; no density or parent growth',
        fixedGeometry=True,fullNativeCanvas=True,oldRoomHiddenOnlyInRejectedCandidate=True,allPersonComponentsVisible=True,
        regionTilePixels=96,regionBalance=.25,sourceColourOnly=True,trainNames=names,checks=checks,
        rejection=dict(rgbIncrease=.003,regionP90Increase=.008,coverageDrop=.02,structureIncrease=.003),published=False)
    for name in ('run_observed_room_recovery.py','reconstruction_observed_coverage.py'):
        shutil.copyfile(Path(__file__).with_name(name),out/'algorithm-source'/name)
    contract.update(surfaceHash=sha(folder/'surface.npz'),config=config,sources={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')})
    save_json(out/'config.json',config);save_json(out/'contract.json',contract)
    def checkpoint(label,step):
        save_checkpoint(out/(label+'.pt'),model,optim,{'views':sampler},stage='observed_room_recovery',step=step,contract=contract,
            strategy={'events':[],'fixedTopology':True},extra={'arrays':a,'roomMetadata':base.room.metadata,'bodySources':base.body_sources})
    checkpoint('initial',0);baseline=evaluate(base,data,checks,masks,out/'baseline-images',baseline=True)
    initial=evaluate(model,data,checks,masks,out/'initial-images');torch.cuda.reset_peak_memory_stats();train_start=time.perf_counter();curve=[]
    for step in range(1,steps+1):
        for op in optim.values():op.zero_grad(set_to_none=True)
        name=sampler.next();f=make_frame(data,name,crop=False);r=model.render(f);mask=torch.as_tensor(masks[name]['room'],device='cuda')
        error=(r['rgb']-f['rgb']).abs().mean(-1)
        loss=balanced_region_mean(error,mask)+.12*valid_window_structure(r['rgb'],f['rgb'],mask)+.025*balanced_region_mean((1-r['q'][...,0]).square(),mask)
        # Other observed components retain true-image supervision. No white
        # fog is preserved by distilling an erroneous old RGB target.
        person=torch.as_tensor(masks[name]['face']|masks[name]['hair']|masks[name]['neck']|masks[name]['cloth'],device='cuda')
        loss+=.2*masked_mean(error,person)+.05*masked_mean(r['q'][...,0].square(),torch.as_tensor(masks[name]['face'],device='cuda'))+model.room_surface.regularizer()
        if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
        loss.backward()
        for key,op in optim.items():
            if not torch.isfinite(getattr(model.room_surface,key).grad).all():raise ValueError('nonfinite_gradient:'+key)
            op.step()
        with torch.no_grad():
            model.room_surface.log_scales.copy_(torch.maximum(torch.minimum(model.room_surface.log_scales,before['log_scales']+np.log(1.25)),before['log_scales']-np.log(1.25)))
        if step==1 or step%60==0:
            curve.append(dict(step=step,name=name,loss=float(loss.detach())));print(json.dumps(curve[-1]),flush=True)
        if step==steps//2:checkpoint('mid',step)
        if time.perf_counter()-train_start>900 or torch.cuda.memory_allocated()/1048576>7100:raise ValueError('finite_budget_exceeded')
    train_seconds=time.perf_counter()-train_start;checkpoint('candidate-final',steps);final=evaluate(model,data,checks,masks,out/'final-images')
    failures=[]
    for name in checks:
        for label,row in final[name].items():
            old=baseline[name][label]
            if row['rgb']>old['rgb']+.003:failures.append(name+':'+label+':rgb')
            if row['alpha']<old['alpha']-.02:failures.append(name+':'+label+':coverage')
            if row['structure']>old['structure']+.003:failures.append(name+':'+label+':structure')
            if row['tileErrorP90'] is not None and row['tileErrorP90']>old['tileErrorP90']+.008:failures.append(name+':'+label+':weak_regions')
    if exact_state_hash(base)!=frozen:raise ValueError('protected_state_changed')
    ref=data['reference'];f=base.adjusted_frame(make_frame(data,ref,crop=False))
    with torch.no_grad():s=model.state(f);export_state(s,out/'candidate-research-only.ply')
    asset=out/'candidate-research-only.ply';uids=np.r_[base.portrait.stable_uid.cpu().numpy(),a['uid'],np.arange(len(base.body['means']))]
    namespaces=np.r_[np.zeros(len(base.portrait.role),np.int64),np.full(len(a['uid']),3,np.int64),np.full(len(base.body['means']),2,np.int64)]
    if len(np.unique(np.c_[namespaces,uids],axis=0))!=len(s.means):raise ValueError('identity_collision')
    np.savez_compressed(out/'candidate-identities.npz',asset_sha256=np.array(sha(asset)),source_hash=np.array(data['sourceHash']),point_id=np.arange(len(s.means)),component=s.parts.cpu().numpy(),source_uid=uids,source_namespace=namespaces,reference=np.array(ref))
    inv=torch.linalg.inv(f['C']).cpu().numpy();h,w=f['rgb'].shape[:2]
    save_json(out/'display.json',dict(assets=[dict(label='candidate',ply=str(asset.resolve()),hash=sha(asset),count=len(s.means))],K=f['K'].cpu().tolist(),C=f['C'].cpu().tolist(),width=w,height=h,camera=inv[:3,3].tolist(),target=(inv[:3,3]+inv[:3,2]).tolist(),up=(-inv[:3,1]).tolist(),near=.01*base.scale,far=1e10*base.scale,reference=ref,sourceHash=data['sourceHash']))
    changes={k:float((v-before[k]).abs().mean()) for k,v in model.room_surface.state_dict().items() if v.dtype.is_floating_point}
    result=dict(sourceHash=data['sourceHash'],reference=ref,baseline=baseline,initial=initial,final=final,failures=failures,curve=curve,changes=changes,
        fixedPersonHash=frozen,baselineExact=True,geometrySupported=False,transactionAccepted=False,published=False,
        points=len(s.means),roomPoints=len(a['means']),assetHash=sha(asset),seconds=time.perf_counter()-started,trainingSeconds=train_seconds,
        allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
        limits='Same predicted-depth pool, not independently validated physical room. Fixed geometry test does not fix face/hair/body motion or reconstruct unseen space.')
    save_json(out/'result.json',result)
    restore_checkpoint(out/'initial.pt',model,optim,{'views':sampler},contract=contract,device='cuda');checkpoint('restored',0)
    exact=all(torch.equal(v,model.room_surface.state_dict()[k]) for k,v in before.items())
    if not exact or exact_state_hash(base)!=frozen:raise ValueError('restoration_failed')
    save_json(out/'restoration.json',dict(initialParametersExact=exact,baseExact=True,published=False))
    print(json.dumps(dict(failures=len(failures),seconds=result['seconds'],trainingSeconds=train_seconds,allocatedMiB=result['allocatedMiB'])),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('stage','surface','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--steps',type=int,default=360);a=p.parse_args()
    try:run(a.stage,a.surface,a.out,a.steps)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(message=str(e),traceback=traceback.format_exc(),published=False))
        raise
