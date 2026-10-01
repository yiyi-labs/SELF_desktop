"""Hair/neck independent real optimization on the complete scene. No publisher."""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch,cv2
from reconstruction_complete_context import load_complete
from reconstruction_observed_attachment import rebind_hair,contact_pairs,exterior_patch
from reconstruction_components_v3 import FreeComponent,pick,sha,save_json
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_detail_controlled import pixel_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint
from run_haze_shared_surface import export_state

class HairExterior(torch.nn.Module):
    def __init__(self,base,ids,a):
        super().__init__();self.baseline=base;self.scale=base.scale
        self.register_buffer('ids',torch.as_tensor(ids,device='cuda',dtype=torch.long))
        t=lambda x:torch.as_tensor(x,device='cuda',dtype=torch.float32);n=len(a['means'])
        s=GaussianState(t(a['means']),t(a['quats']),t(a['scales']),t(a['opacity']),t(a['sh']),torch.full((n,),2,device='cuda',dtype=torch.long))
        self.patch=FreeComponent(s,torch.as_tensor(a['uid'],device='cuda'),t(a['support']),'head-local',torch.median(s.scales.min(-1).values)*.75)
    def state(self,f):
        full=self.baseline.state(f);original=torch.where(self.baseline.keep_head)[0]
        keep=torch.ones(len(full.means),device='cuda',dtype=torch.bool)
        keep[:len(original)]=~torch.isin(original,self.ids)
        return joined_state(pick(full,keep),self.patch.state().to_world(f['C'],f['F'],self.scale))
    def render(self,f):
        f=self.baseline.baseline.adjusted_frame(f);h,w=f['rgb'].shape[:2]
        return draw(self.state(f),f['C'],f['K'],w,h,unit_scale=self.scale)
    def render_local(self,f):
        f=self.baseline.baseline.adjusted_frame(f)
        head=self.baseline.baseline.head_state(f)
        keep=self.baseline.keep_head.clone();keep[self.ids]=False
        state=joined_state(pick(head,keep),self.patch.state())
        h,w=f['rgb'].shape[:2]
        return draw(state,f['F'],f['K'],w,h)

def run(complete,out,component,surface=None,steps=240,local_hair_training=False,dense_exterior=False):
    if component!='hair' and (local_hair_training or dense_exterior):raise ValueError('hair_option_requires_hair')
    clock=time.perf_counter();out=Path(out);torch.manual_seed(100102);np.random.seed(100102)
    data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    for file in ('run_complete_attachment_recovery.py','reconstruction_observed_attachment.py','reconstruction_complete_context.py'):
        shutil.copyfile(Path(__file__).with_name(file),out/'algorithm-source'/file)
    ref=contract['reference'];f=base.baseline.adjusted_frame(make_frame(data,ref,crop=False))
    names=extra['meta']['names'] if component=='neck' else json.loads((Path(surface)/'result.json').read_text())['names']
    names=[n for n in names if n in data['worlds']]
    if not names or any(n not in plan['train'] for n in names):raise ValueError('training_role_mismatch')
    evaluation=list(dict.fromkeys(names+[ref]+[n for n in plan['development']+plan['audit'] if n in data['worlds']]))
    masks=physical_masks(contract['spec']['prepared'],data,evaluation);contact=None;ids=np.empty(0,int);source_indices=None;source_parents=None;surface_hash=None
    if component=='hair':
        a=dict(np.load(Path(surface)/'surface.npz'))
        if str(a['source_hash'])!=data['sourceHash']:raise ValueError('hair_source')
        local=base.baseline.head_state(f);oldids=torch.where((local.parts==2)&base.keep_head)[0].cpu().numpy()
        obs=[dict(role='train',K=data['K'],F=base.baseline.adjusted_frame(make_frame(data,n,crop=False))['F'].cpu().numpy(),hair=masks[n]['hair']) for n in names]
        selected,ix,proposal=rebind_hair(local.means[oldids].cpu().numpy(),obs,a);ids=oldids[selected]
        surface_hash=sha(Path(surface)/'surface.npz')
        source_parents=ids.copy()
        if dense_exterior:
            ix,parent_rows,dense=exterior_patch(local.means[oldids].cpu().numpy(),obs,a,selected,ix)
            source_parents=oldids[parent_rows]
            proposal['exteriorPatch']=dense
        source_indices=ix.copy()
        save_json(out/'proposal.json',proposal)
        if len(ids)<32:raise ValueError('insufficient_exterior_support')
        n=len(a['means']);a={k:v[ix] if v.ndim and len(v)==n else v for k,v in a.items()}
        # Stable old-point identities; predictions are proposals, not new sources.
        if not dense_exterior:a['uid']=base.baseline.portrait.stable_uid[ids].cpu().numpy()
        m=HairExterior(base,ids,a);active=torch.ones(len(a['means']),device='cuda',dtype=torch.bool)
    else:
        m=base;active=base.is_neck.clone();state=m.patch_state(f);neck=torch.where(active)[0]
        head=m.baseline.head_state(f).to_world(f['C'],f['F'],m.scale);hid=torch.where((head.parts==4)&m.keep_head)[0]
        cam=state.means@f['C'][:3,:3].T+f['C'][:3,3];q=cam@f['K'].T;y=q[:,1]/q[:,2];metric=float(torch.median(cam[neck,2]/f['K'][0,0]))
        ni,hi=contact_pairs(state.means[neck].cpu().numpy(),head.means[hid].cpu().numpy(),metric,y[neck].cpu().numpy())
        contact=(neck[torch.as_tensor(ni,device='cuda')],hid[torch.as_tensor(hi,device='cuda')])
        save_json(out/'proposal.json',dict(contacts=len(ni),noSkinClothWeld=True,clothFrozen=True,priorNotMeasuredTruth=True,outsideWindowMotion='unchanged unknown diagnostic'))
    patch=m.patch
    for p in m.parameters():p.requires_grad_(False)
    initial={k:v.detach().clone() for k,v in m.state_dict().items()};pin={k:v.detach().clone() for k,v in patch.state_dict().items()}
    rates={'sh':.002,'opacity':.006,'log_scales':.001,'quats':.0003,'offset':.001}
    ops={k:torch.optim.Adam([getattr(patch,k)],lr=lr) for k,lr in rates.items()};sampler=FrameSampler(names,100102)
    config=dict(denseExterior=dense_exterior,localHairTraining=local_hair_training,component=component,steps=steps,train=names,evaluate=evaluation,activePoints=int(active.sum()),nativeFullFrame=True,allComponentsVisibleDuringEvaluation=True,allComponentsVisibleDuringTraining=not local_hair_training,trainingSpace='head-only T0' if local_hair_training else 'complete T2',scaleRange=[.8,1.2],geometryStart=40,geometryStop=160,geometryEvery=4,published=False)
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')};save_json(out/'contract.json',contract);save_json(out/'config.json',config)
    def ck(label,step):save_checkpoint(out/(label+'.pt'),m,ops,{'views':sampler},stage=component,step=step,contract=contract,strategy={'events':[],'topology':'fixed semantic attachment'},extra=dict(sourceContinuity=extra,config=config,active=active,contact=contact,retiredHair=ids,sourceIndices=source_indices,sourceParentRows=source_parents,surfaceHash=surface_hash))
    old={}
    with torch.no_grad():
        for n in evaluation:
            r=base.render(make_frame(data,n,crop=False));old[n]={k:r[k].cpu().numpy() for k in ('rgb','alpha','q')}
    def assess(label):
        folder=out/(label+'-images');folder.mkdir();rows={}
        with torch.no_grad():
            for n in evaluation:
                r=m.render(make_frame(data,n,crop=False));rgb=r['rgb'].cpu().numpy();alpha=r['alpha'].cpu().numpy();q=r['q'].cpu().numpy();target=data['rgb'][n];before=old[n];row={}
                for part in ('face','hair','neck','cloth','room'):
                    mask=masks[n][part]
                    if not mask.any():continue
                    row[part]=dict(rgb=float(np.abs(rgb-target).mean(-1)[mask].mean()),baselineRgb=float(np.abs(before['rgb']-target).mean(-1)[mask].mean()),alpha=float(alpha[mask].mean()),baselineAlpha=float(before['alpha'][mask].mean()),holeBelow08=float((alpha[mask]<.8).mean()),baselineHoleBelow08=float((before['alpha'][mask]<.8).mean()))
                if float((r['q'].sum(-1)-r['alpha']).abs().max())>1e-4:raise ValueError('q_conservation')
                rows[n]=row;cv2.imwrite(str(folder/(n+'.png')),cv2.cvtColor((np.clip(np.concatenate([target,before['rgb'],rgb],1),0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR));np.savez_compressed(folder/(n+'.npz'),rgb=rgb,alpha=alpha,q=q)
        save_json(folder/'metrics.json',rows);return rows
    def assess_local(label):
        if not local_hair_training or component!='hair':return None
        folder=out/('local-'+label);folder.mkdir();rows={}
        with torch.no_grad():
            for n in evaluation:
                f=base.baseline.adjusted_frame(make_frame(data,n,crop=False))
                oldhead=pick(base.baseline.head_state(f),base.keep_head)
                h,w=f['rgb'].shape[:2];b=draw(oldhead,f['F'],f['K'],w,h);r=m.render_local(f)
                row={}
                for part,index in [('hair',2),('face',1)]:
                    mask=torch.tensor(masks[n][part],device='cuda')
                    row[part]=dict(rgb=float(masked_mean((r['rgb']-f['rgb']).abs().mean(-1),mask)),
                        baselineRgb=float(masked_mean((b['rgb']-f['rgb']).abs().mean(-1),mask)),
                        contribution=float(masked_mean(r['q'][...,index],mask)),
                        baselineContribution=float(masked_mean(b['q'][...,index],mask)))
                rows[n]=row
                cv2.imwrite(str(folder/(n+'.png')),cv2.cvtColor((np.clip(np.concatenate([data['rgb'][n],b['rgb'].cpu().numpy(),r['rgb'].cpu().numpy()],1),0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        save_json(folder/'metrics.json',rows);return rows
    local_initial=assess_local('initial')
    ck('initial',0);initmetrics=assess('initial');curve=[];torch.cuda.reset_peak_memory_stats();start=time.perf_counter()
    for step in range(1,steps+1):
        geometry=40<=step<=160 and step%4==0
        for k in rates:getattr(patch,k).requires_grad_(geometry if k=='offset' else not geometry)
        for op in ops.values():op.zero_grad(set_to_none=True)
        n=sampler.next();f=make_frame(data,n,crop=False);r=m.render_local(f) if local_hair_training and component=='hair' else m.render(f);mask=torch.tensor(masks[n][component],device='cuda')
        error=(r['rgb']-f['rgb']).abs().mean(-1);loss=masked_mean(error,mask)+.12*valid_window_structure(r['rgb'],f['rgb'],mask)+.2*pixel_structure(r['rgb'],f['rgb'],mask)
        loss+=2*masked_mean((torch.tensor(old[n]['alpha'],device='cuda')-r['alpha']-.01).clamp_min(0).square(),mask)+.0002*patch.sh[:,1:].square().mean()
        if local_hair_training and component=='hair':
            empty=torch.tensor(masks[n]['room'],device='cuda')
            face=torch.tensor(masks[n]['face'],device='cuda')
            loss+=.08*masked_mean((1-r['q'][...,2]).square(),mask)
            loss+=.04*masked_mean(r['alpha'].square(),empty)
            loss+=.3*masked_mean(error,face)+.08*masked_mean(r['q'][...,2].square(),face)
        else:
            protected=torch.tensor(masks[n]['face']|masks[n]['cloth']|masks[n]['room'],device='cuda');olderror=(torch.tensor(old[n]['rgb'],device='cuda')-f['rgb']).abs().mean(-1)
            loss+=2*masked_mean((error-olderror-.005).clamp_min(0),protected)
        if component=='neck' and geometry and len(contact[0]):
            af=m.baseline.adjusted_frame(f);s=m.patch_state(af);head=m.baseline.head_state(af).to_world(af['C'],af['F'],m.scale)
            loss+=.01*torch.nn.functional.smooth_l1_loss((s.means[contact[0]]-head.means[contact[1]])/m.scale,torch.zeros_like(s.means[contact[0]]),beta=.002)
        if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
        loss.backward()
        for p in patch.parameters():
            if p.grad is not None:
                if not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient')
                p.grad[~active]=0
        if geometry:ops['offset'].step()
        else:
            for k in rates:
                if k!='offset':ops[k].step()
        with torch.no_grad():patch.log_scales.copy_(torch.maximum(torch.minimum(patch.log_scales,pin['log_scales']+np.log(1.2)),pin['log_scales']+np.log(.8)))
        if step==steps//2:ck('mid',step)
        if step==1 or step%60==0:curve.append(dict(step=step,name=n,geometry=geometry,loss=float(loss.detach())));print(json.dumps(curve[-1]),flush=True)
        if time.perf_counter()-start>720 or torch.cuda.memory_allocated()/1048576>7100:raise ValueError('finite_budget')
    ck('candidate-final',steps);final=assess('final');local_final=assess_local('final');failures=[]
    for n,row in final.items():
        for part,v in row.items():
            if v['rgb']>v['baselineRgb']+.003:failures.append(part+'_rgb:'+n)
            if v['alpha']<v['baselineAlpha']-.015:failures.append(part+'_coverage:'+n)
            if v['holeBelow08']>v['baselineHoleBelow08']+.02:failures.append(part+'_holes:'+n)
    for k,v in m.state_dict().items():
        if k in ('patch.offset','patch.log_scales','patch.quats','patch.opacity','patch.sh'):
            if not torch.equal(v[~active],initial[k][~active]):raise ValueError('protected_patch_rows:'+k)
        elif not torch.equal(v,initial[k]):raise ValueError('protected_parameter:'+k)
    f=base.baseline.adjusted_frame(make_frame(data,ref,crop=False));s=m.state(f);asset=out/'candidate-research-only.ply';export_state(s,asset)
    side=dict(np.load(Path(complete)/'candidate-identities.npz'));keep=np.ones(len(side['point_id']),bool)
    if component=='hair':
        orig=torch.where(base.keep_head)[0].cpu().numpy();keep[:len(orig)]=~np.isin(orig,ids)
        uid=np.r_[side['source_uid'][keep],a['uid']];space=np.r_[side['source_namespace'][keep],np.full(len(a['uid']),5)]
    else:uid=side['source_uid'];space=side['source_namespace']
    if len(np.unique(np.c_[space,uid],axis=0))!=len(uid):raise ValueError('UID_collision')
    np.savez_compressed(out/'candidate-identities.npz',point_id=np.arange(len(uid)),source_uid=uid,source_namespace=space,component=s.parts.cpu().numpy(),asset_hash=np.array(sha(asset)),source_hash=np.array(data['sourceHash']),reference=np.array(ref))
    inv=torch.linalg.inv(f['C']).cpu().numpy();h,w=f['rgb'].shape[:2]
    save_json(out/'display.json',dict(assets=[dict(label=component,ply=str(asset.resolve()),hash=sha(asset),count=len(s.means))],K=f['K'].cpu().tolist(),C=f['C'].cpu().tolist(),width=w,height=h,camera=inv[:3,3].tolist(),target=(inv[:3,3]+inv[:3,2]).tolist(),up=(-inv[:3,1]).tolist(),near=.01*m.scale,far=1e10*m.scale,reference=ref,sourceHash=data['sourceHash'],published=False))
    result=dict(localInitial=local_initial,localFinal=local_final,sourceHash=data['sourceHash'],reference=ref,assetHash=sha(asset),pointCount=len(s.means),baselineAssetHash=contract['completeAssetHash'],initial=initmetrics,final=final,failures=failures,curve=curve,parameterChanges={k:float((v-pin[k]).abs().mean()) for k,v in patch.state_dict().items() if v.is_floating_point()},frozenOtherComponentsExact=True,steps=steps,totalSeconds=time.perf_counter()-clock,trainEvalSeconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,transactionAccepted=False,releaseQualityPassed=False,published=False)
    save_json(out/'result.json',result);restore_checkpoint(out/'initial.pt',m,ops,{'views':sampler},contract=contract,device='cuda');ck('restored',0)
    if any(not torch.equal(v,m.state_dict()[k]) for k,v in initial.items()):raise ValueError('restore_inexact')
    print('ATTACHMENT_COMPLETE_NOT_PUBLISHED',component,len(failures),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--out',required=True);p.add_argument('--component',choices=['hair','neck'],required=True);p.add_argument('--surface');p.add_argument('--steps',type=int,default=240);p.add_argument('--local-hair-training',action='store_true');p.add_argument('--dense-exterior',action='store_true');a=p.parse_args()
    try:run(a.complete,a.out,a.component,a.surface,a.steps,a.local_hair_training,a.dense_exterior)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise