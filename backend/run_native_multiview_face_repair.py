"""Train-only native texture tracks constrain one shared surface and bounded F.
Every physical track keeps one triangle/bary anchor; all source/target pixels
participate symmetrically. Third observations diagnose geometry before colour
recovery. Fixed regressions remain fixed; no new world cameras are invented.
"""
import argparse,json,time,shutil
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_evidence_stage import load_stage
from reconstruction_photometric_surface import PhotometricSurfaceModel
from reconstruction_continuity_surface import physical_masks
from reconstruction_native_measurements import native_measurement
from reconstruction_patch_correspondence import intersect
from reconstruction_portrait_pipeline import make_frame,masked_mean
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,rng_state,restore_rng
from reconstruction_components_v3 import save_json,sha
from reconstruction_reference_static import valid_window_structure
from reconstruction_detail_controlled import pixel_structure
from run_dense_surface_training import evaluation


@torch.no_grad()
def measurements(model,data,plan,depth_manifest,masks):
    spec=json.loads(Path(depth_manifest).read_text());rows=[r for r in spec['observations'] if r['group']=='head-local' and r['imageName'] in plan['train']]
    if spec['sourceHash']!=data['sourceHash']:raise ValueError('observation_source')
    groups={}
    for r in rows:groups.setdefault(r['window'],[]).append(r)
    records=[];counts=[];faces=model.portrait.faces.cpu().numpy();K=data['K']
    for wi,rr in groups.items():
        rr=sorted(rr,key=lambda r:r['timestampSeconds']);candidates=[]
        for r in rr:
            n=r['imageName'];near=[t for t in rr if abs(t['timestampSeconds']-r['timestampSeconds'])<=3.5]
            if len(near)<3:continue
            gray=cv2.cvtColor(data['rgb'][n],cv2.COLOR_RGB2GRAY);mask=masks[n]['face']
            score=float(cv2.Laplacian(gray,cv2.CV_32F)[mask].var()) if mask.any() else 0
            candidates.append((score,n,near))
        if not candidates:continue
        _,source,near=max(candidates,key=lambda v:v[0]);f=model.adjusted_frame(make_frame(data,source,crop=False))
        source_mesh=(f['mesh']+model.surface_base).cpu().numpy();F=f['F'].cpu().numpy()
        im=(data['rgb'][source]*255).round().astype(np.uint8);gray=cv2.cvtColor(im,cv2.COLOR_RGB2GRAY)
        mask=cv2.erode(masks[source]['face'].astype(np.uint8),np.ones((19,19),np.uint8))
        seeds=cv2.goodFeaturesToTrack(gray,140,.005,5,mask=mask*255,blockSize=3)
        if seeds is None:continue
        accepted=0;reject={}
        for number,uv in enumerate(seeds[:,0]):
            hit=intersect(source_mesh,faces,F,K,uv)
            if hit is None:continue
            ti,bary=hit;obs=[dict(name=source,uv=uv.tolist(),sigma=.5,source=True)]
            for t in near:
                name=t['imageName']
                if name==source:continue
                ft=model.adjusted_frame(make_frame(data,name,crop=False));tri=(ft['mesh']+model.surface_base)[model.portrait.faces[ti]].cpu().numpy();x=(tri*bary[:,None]).sum(0)
                cam=x@ft['F'][:3,:3].cpu().numpy().T+ft['F'][:3,3].cpu().numpy();q=cam@K.T;proposal=q[:2]/q[2]
                if cam[2]<=0:continue
                try:
                    target=cv2.cvtColor((data['rgb'][name]*255).round().astype(np.uint8),cv2.COLOR_RGB2GRAY)
                    p,quality=native_measurement(gray,target,uv,proposal)
                    xy=np.rint(p).astype(int);h,w=gray.shape
                    if not(0<=xy[0]<w and 0<=xy[1]<h and masks[name]['face'][xy[1],xy[0]]):raise ValueError('physical_surface_boundary')
                    obs.append(dict(name=name,uv=p.tolist(),sigma=float(.5+quality['fb']),source=False,quality=quality))
                except ValueError as e:reject[str(e)]=reject.get(str(e),0)+1
                except cv2.error:reject['native_ecc_nonconvergence']=reject.get('native_ecc_nonconvergence',0)+1
            if len(obs)>=3:
                records.append(dict(id=f'{wi}:{source}:{number}',triangle=ti,bary=bary.tolist(),observations=obs,withheld=len(obs)-1));accepted+=1
        counts.append(dict(window=wi,source=source,names=[r['imageName'] for r in near],seeds=len(seeds),accepted=accepted,rejections=reject))
    return records,counts


def anchor_errors(model,data,records,withheld=False):
    K=torch.tensor(data['K'],device='cuda',dtype=torch.float32);result=[];groups={}
    for track in records:
        for i,o in enumerate(track['observations']):
            if (i==track['withheld'])!=withheld:continue
            groups.setdefault(o['name'],[]).append((track,o))
    # One differentiable mesh/transport per view; vectorizing the SAME anchors
    # avoids recomputing a whole FLAME mesh for each observation/track.
    for name,rows in groups.items():
        local=data['local'][name];mesh=torch.as_tensor(local['mesh'],device='cuda',dtype=torch.float32)
        delta=model.posed_delta({'mesh':mesh,'name':name});ids=torch.tensor([t['triangle'] for t,_ in rows],device='cuda')
        bary=torch.tensor([t['bary'] for t,_ in rows],device='cuda',dtype=torch.float32)
        xyz=((mesh+model.surface_base+delta)[model.portrait.faces[ids]]*bary[...,None]).sum(1)
        F=model.pose(name,torch.as_tensor(local['F'],device='cuda',dtype=torch.float32));cam=xyz@F[:3,:3].T+F[:3,3];q=cam@K.T
        error=q[:,:2]/q[:,2:]-torch.tensor([o['uv'] for _,o in rows],device='cuda',dtype=torch.float32)
        result.extend((e,float(o['sigma']),o['source'],name) for e,(_,o) in zip(error,rows))
    return result


def stats(errors):
    if not errors:return dict(count=0)
    a=np.array([float(e.detach().norm()) for e,_,_,_ in errors]);src=np.array([s for _,_,s,_ in errors])
    return dict(count=len(a),median=float(np.median(a)),p90=float(np.quantile(a,.9)),sourceP90=float(np.quantile(a[src],.9)) if src.any() else None,perObservation=[dict(name=n,error=float(e.detach().norm()),source=s) for e,_,s,n in errors])


def run(stage,depth_manifest,out,appearance_steps=180):
    start=time.perf_counter();out=Path(out);data,plan,m,contract=load_stage(stage,out,model_class=PhotometricSurfaceModel)
    for n in ('run_native_multiview_face_repair.py','reconstruction_continuity_surface.py'):shutil.copyfile(Path(__file__).with_name(n),out/'algorithm-source'/n)
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')}
    contract['measurementManifestHash']=sha(depth_manifest)
    masks=physical_masks(contract['spec']['prepared'],data,plan['train']);records,counts=measurements(m,data,plan,depth_manifest,masks)
    save_json(out/'measurements.json',dict(sourceHash=data['sourceHash'],records=records,counts=counts,independentPixels=True,measurementChannels='native RGB converted to grayscale for ECC only; original RGB retained for training',initialDepth='ray intersection with soft prior, not depth ground truth'))
    initial={k:v.detach().clone() for k,v in m.state_dict().items()};random=rng_state();p=m.portrait;allowed=torch.unique(p.faces[torch.tensor([r['triangle'] for r in records],device='cuda',dtype=torch.long)].reshape(-1)) if records else torch.empty(0,device='cuda',dtype=torch.long)
    # A continuous two-ring chart around all real tracks, shared across images.
    active=torch.zeros(len(m.active_vertices),device='cuda',dtype=torch.bool);active[allowed]=True
    for _ in range(2):used=active[p.faces].any(-1);active[p.faces[used].reshape(-1)]=True
    boundary=p.edges[active[p.edges[:,0]]!=active[p.edges[:,1]]];active[torch.unique(boundary.reshape(-1))]=False;m.active_vertices.copy_(active)
    initial={k:v.detach().clone() for k,v in m.state_dict().items()};raw=evaluation(m,data,plan,out/'baseline-images')
    before=stats(anchor_errors(m,data,records));third_before=stats(anchor_errors(m,data,records,True));results={}
    config=dict(geometrySteps=160,appearanceSteps=appearance_steps,seed=93071,sharedTrackAnchors=True,sourceAndTargets=True,KIdentityScaleExpressionWorldCFixed=True,poseRawDeltaBound=.2,normalNativePixelBound=3,topology='fixed',published=False)
    save_json(out/'config.json',config);save_json(out/'contract.json',contract)
    for label,geometry in [('appearance-control',False),('measured-surface',True)]:
        folder=out/label;folder.mkdir();m.load_state_dict(initial);restore_rng(random);m._transport_cache.clear()
        for v in m.parameters():v.requires_grad_(False)
        rates={'sh':.0015,'opacity_logits':.004,'log_scales':.001,'quats':.0002};ops={k:torch.optim.Adam([getattr(p,k)],lr=v) for k,v in rates.items()};ops['surface']=torch.optim.Adam([m.surface_control],lr=.002);ops['pose']=torch.optim.Adam([m.pose.delta],lr=.003)
        sampler=FrameSampler(plan['train'],93071);extra=dict(config=config,records=records,roomMetadata=m.room.metadata,bodySources=m.body_sources)
        def save(n,step):save_checkpoint(folder/(n+'.pt'),m,ops,{'views':sampler},stage=label,step=step,contract=contract,strategy={'events':[],'topology':'fixed'},extra=extra)
        save('initial',0);curve=[];torch.cuda.reset_peak_memory_stats();clock=time.perf_counter();steps=0;geometry_accepted=False
        if geometry and len(records)>=8:
            m.surface_control.requires_grad_(True)
            for step in range(config['geometrySteps']):
                # First half holds every F fixed; second half permits bounded F.
                m.pose.delta.requires_grad_(step>=80)
                for op in ops.values():op.zero_grad(set_to_none=True)
                errors=anchor_errors(m,data,records);loss=sum(torch.nn.functional.smooth_l1_loss(e/s,torch.zeros_like(e),beta=1.) for e,s,_,_ in errors)/len(errors)
                u=m.surface_control.tanh();loss+=.003*u.square().mean()+.01*(u[p.edges[:,0]]-u[p.edges[:,1]]).square().mean()+.02*(m.pose.delta-initial['pose.delta']).square().mean()
                if not torch.isfinite(loss):raise ValueError('nonfinite_geometry_loss')
                loss.backward()
                for parameter in (m.surface_control,m.pose.delta):
                    if parameter.grad is not None and not torch.isfinite(parameter.grad).all():raise ValueError('nonfinite_geometry_gradient')
                ops['surface'].step()
                if step>=80:ops['pose'].step()
                with torch.no_grad():m.pose.delta.copy_(torch.maximum(torch.minimum(m.pose.delta,initial['pose.delta']+.2),initial['pose.delta']-.2))
                if step%40==0:curve.append(dict(step=step,phase='geometry',loss=float(loss.detach())));print(label,json.dumps(curve[-1]),flush=True)
                if time.perf_counter()-clock>600:raise ValueError('finite_geometry_budget')
            after=stats(anchor_errors(m,data,records));third=stats(anchor_errors(m,data,records,True));save('geometry-candidate',160)
            geometry_accepted=bool(after['p90']<=before['p90']+.5 and third['p90']<=third_before['p90']+.5 and after['sourceP90']<=1. and after['median']<before['median'])
            if not geometry_accepted:m.load_state_dict(initial);m._transport_cache.clear()
        else:after=before;third=third_before
        for v in m.parameters():v.requires_grad_(False)
        for k in rates:getattr(p,k).requires_grad_(True)
        skin=(m.component_origin[p.origin_index]==0)&(p.role!=2)
        for step in range(1,appearance_steps+1):
            for op in ops.values():op.zero_grad(set_to_none=True)
            f=make_frame(data,sampler.next(),crop=False);r=m.render(f,'T0');valid=(f['masks']['face_core']|f['masks']['face_boundary'])&~f['masks']['glasses_visible']&~f['masks']['unknown_or_occluded'];err=(r['rgb']-f['rgb']).abs().mean(-1)
            loss=masked_mean(err,valid)+.12*valid_window_structure(r['rgb'],f['rgb'],valid)+.2*pixel_structure(r['rgb'],f['rgb'],valid)+.03*masked_mean((1-r['alpha']).square(),valid)+.0005*p.sh[:,1:].square().mean()
            if not torch.isfinite(loss):raise ValueError('nonfinite_face_loss')
            loss.backward()
            for k in rates:
                v=getattr(p,k)
                if v.grad is not None:
                    if not torch.isfinite(v.grad).all():raise ValueError('nonfinite_face_gradient')
                    v.grad[~skin]=0
                ops[k].step()
            with torch.no_grad():p.log_scales.copy_(torch.maximum(torch.minimum(p.log_scales,initial['portrait.log_scales']+np.log(1.2)),initial['portrait.log_scales']-np.log(1.2)))
            if step==appearance_steps//2:save('mid',step)
            if step==1 or step%60==0:print(label,json.dumps(dict(step=step,phase='appearance',loss=float(loss.detach()))),flush=True)
            if time.perf_counter()-clock>900:raise ValueError('finite_face_budget')
        save('candidate-final',appearance_steps);final=evaluation(m,data,plan,folder/'final-images');failures=[]
        for n in plan['development']+plan['audit']:
            for region in ('face','hair','glasses'):
                if final[n][region]['fixedRgbL1']>raw[n][region]['fixedRgbL1']+(.001 if region=='face' else .003):failures.append(region+':'+n)
        results[label]=dict(metrics=final,failures=failures,geometryAcceptedForAppearance=geometry_accepted,fitBefore=before,fitAfter=after,thirdBefore=third_before,thirdAfter=third,seconds=time.perf_counter()-clock,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,releaseQualityPassed=False)
        restore_checkpoint(folder/'initial.pt',m,ops,{'views':sampler},contract=contract,device='cuda');save('restored',0)
    save_json(out/'result.json',dict(sourceHash=data['sourceHash'],records=len(records),counts=counts,branches=results,seconds=time.perf_counter()-start,published=False,completeScenePassed=False))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('stage','depth-manifest','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args()
    try:run(a.stage,a.depth_manifest,a.out)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise
