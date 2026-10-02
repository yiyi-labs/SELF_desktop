"""Finite native-pixel geometry/control comparison of a preserved complete scene.
No topology deletion, no per-frame warp, no renderer/production default changes.
"""
from pathlib import Path
import argparse,json,time,shutil
import numpy as np,torch,cv2,pycolmap
from reconstruction_complete_context import load_complete
from reconstruction_shared_scene_geometry import LayeredSurfaceField,surface_normals,polar_frame,replace_same_order,move_sh,bounded_singular_values
from reconstruction_surface_continuity import transport_covariance
from reconstruction_portrait_model import GaussianState
from reconstruction_components_v3 import FreeComponent,pick,save_json,sha,exact_state_hash
from reconstruction_portrait_pipeline import make_frame,masked_mean
from reconstruction_dense_contract import project,unproject,bilinear
from reconstruction_ray_surface import sample_mask
from reconstruction_canonical_surface import draw_covariance
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,rng_state,restore_rng
from run_continuous_surface_repair import evaluate_complete,regression_screen
from run_haze_shared_surface import export_state


class SharedRoomStage(torch.nn.Module):
    def __init__(self,base,data,reference,geometry):
        super().__init__();self.baseline=base;self.scale=base.scale;self.geometry=geometry
        f=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));s=base.state(f)
        ids=torch.where(s.parts==0)[0];self.register_buffer('ids',ids)
        old=pick(s,ids);self.patch=FreeComponent(old,ids,torch.ones(len(ids),device=ids.device),'world-reference',0.)
        n,t=surface_normals(old);self.register_buffer('normal',n);self.register_buffer('thickness',t)
        z=(old.means@f['C'][:3,:3].T+f['C'][:3,3])[:,2]
        metric=z.abs().clamp_min(.01*self.scale)/f['K'][0,0]
        self.register_buffer('metric',metric)
        self.field=LayeredSurfaceField(old.means,n,t,metric,controls=96)
        self.last_J=None
    def state_covariance(self,f):
        full=self.baseline.state(f);s=self.patch.state();cov=full.covariance()
        if self.geometry:
            means,J=self.field(s.means,self.normal,self.thickness);R=polar_frame(J)
            # Rendering uses explicit covariance. Eigen-factorization here was
            # discarded by the renderer and created avoidable CUDA workspace.
            moved=GaussianState(means,s.quats,s.scales,s.opacity,move_sh(s.sh,R),s.parts)
            # Full covariance gradients, not a detached eigenvector approximation.
            cov=cov.clone();cov[self.ids]=J@s.covariance()@J.transpose(-1,-2)
            self.last_J=J
        else:
            moved=s;cov=cov.clone();cov[self.ids]=s.covariance()
        return replace_same_order(full,self.ids,moved),cov
    @torch.no_grad()
    def state(self,f):
        full,cov=self.state_covariance(f)
        if not self.geometry:return full
        s=self.patch.state();means,J=self.field(s.means,self.normal,self.thickness);R=polar_frame(J)
        # Only export needs standard quaternion/scale factors; keep point order.
        pieces=[]
        for start in range(0,len(s.means),512):
            ids=slice(start,start+512);pieces.append(transport_covariance(pick(s,ids),J[ids],means[ids],R[ids]))
        from reconstruction_portrait_model import joined_state
        return replace_same_order(full,self.ids,joined_state(*pieces))
    def render(self,frame):
        f=self.baseline.baseline.adjusted_frame(frame);s,c=self.state_covariance(f);h,w=f['rgb'].shape[:2]
        return draw_covariance(s,c,f['C'],f['K'],w,h,unit_scale=self.scale)


def static_anchors(data,train,masks,limit=384):
    """Read real COLMAP track IDs and native undistorted measurements, no matches.
    One X is shared across views; cameras/scale remain untouched.
    """
    mapping=pycolmap.Reconstruction(data['staticMap']);records=[]
    for pid,p in sorted(mapping.points3D.items()):
        if p.error>2.5:continue
        obs=[]
        for e in p.track.elements:
            im=mapping.images[e.image_id];n=im.name
            if n not in train:continue
            ray=mapping.cameras[im.camera_id].cam_from_img(im.points2D[e.point2D_idx].xy)
            q=data['K']@np.r_[ray,1.];uv=q[:2]/q[2]
            if not sample_mask(masks[n]['room'],uv[None])[0]:continue
            re,z=project(np.asarray(p.xyz)[None],data['K'],data['worlds'][n])
            if z[0]<=0 or np.linalg.norm(re[0]-uv)>3:continue
            obs.append(dict(name=n,uv=uv.tolist()))
        if len(obs)>=3:records.append(dict(pointID=int(pid),xyz=np.asarray(p.xyz).tolist(),observations=obs))
    # Deterministic distributed source identities, not best development RGB.
    if len(records)>limit:
        ids=np.floor(np.arange(limit)*len(records)/limit).astype(int);records=[records[i] for i in ids]
    return records


def shared_depth_targets(room,data,train,priors,masks):
    """Associate existing material points with visible source observations.
    Three-view agreement is a conditional geometry prior, never measured truth.
    RGB losses remain full-room even when a point has no depth support.
    """
    x=room.means.cpu().numpy();targets=[];used=[]
    for n in train:
        path=Path(priors)/(n+'.npz')
        if not path.exists():continue
        a=np.load(path);uv,z=project(x,data['K'],data['worlds'][n]);d=bilinear(a['room_depth'],uv)
        valid=(z>0)&np.isfinite(d)&(d>0)&sample_mask(a['room_valid'],uv)&sample_mask(masks[n]['room'],uv)
        t=unproject(uv,np.where(valid,d,np.nan),data['K'],data['worlds'][n]);t[~valid]=np.nan
        targets.append(t);used.append(n)
    if not targets:raise ValueError('no_saved_train_depth_observations')
    a=np.stack(targets);count=np.isfinite(a[...,0]).sum(0)
    # Avoid empty-slice warnings; only assign supported observations.
    indices=np.where(count>=3)[0];target=np.zeros_like(x);spread=np.zeros(len(x))
    for i in indices:
        xx=a[:,i];xx=xx[np.isfinite(xx).all(1)];target[i]=np.median(xx,0)
        spread[i]=np.quantile(np.linalg.norm(xx-target[i],axis=1),.9)
    distance=np.linalg.norm(target-x,axis=1)
    metric=np.median([np.maximum(project(x,data['K'],data['worlds'][n])[1],1e-6)/data['K'][0,0] for n in used],axis=0)
    accepted=(count>=3)&(spread<metric*8)&(distance<metric*48)
    ids=np.where(accepted)[0]
    return ids,target[ids],dict(observations=used,supportedPoints=len(ids),rawThreeView=int((count>=3).sum()),
        worldScatterP90NativePixels=float(np.quantile(spread[ids]/metric[ids],.9)) if len(ids) else None,
        independentTruth=False,RGBPixelsDiscarded=0)


def run(complete,priors,out,steps=240):
    if not 160<=steps<=320:raise ValueError('finite_budget_160_to_320')
    out=Path(out);clock=time.perf_counter();torch.manual_seed(100221);np.random.seed(100221)
    data,plan,base,contract=load_complete(complete,out);source_extra=contract.pop('sourceExtra')
    reference=contract['reference'];train=[n for n in plan['train'] if n in data['worlds']]
    evaluation=list(dict.fromkeys(list(base.body_motion.timestamps)+[reference]+[n for n in plan['development']+plan['audit'] if n in data['worlds']]))
    allnames=list(dict.fromkeys(train+evaluation));masks=physical_masks(contract['spec']['prepared'],data,allnames)
    protected=exact_state_hash(base);side=dict(np.load(Path(complete)/'candidate-identities.npz'))
    for n in ('reconstruction_shared_scene_geometry.py','run_shared_scene_geometry.py'):
        shutil.copyfile(Path(__file__).with_name(n),out/'algorithm-source'/n)
    anchors=static_anchors(data,train,masks);save_json(out/'static-anchors.json',anchors)
    proto=SharedRoomStage(base,data,reference,False)
    with torch.no_grad():depth_ids,depth_target,depth_report=shared_depth_targets(proto.patch.state(),data,train,priors,masks)
    save_json(out/'depth-association.json',depth_report)
    xyz=torch.tensor([r['xyz'] for r in anchors],device='cuda',dtype=torch.float32)
    from scipy.spatial import cKDTree
    _,near=cKDTree(proto.patch.base.cpu().numpy()).query(xyz.cpu().numpy())
    normals=proto.normal[torch.tensor(near,device='cuda')];thickness=proto.thickness[torch.tensor(near,device='cuda')]
    di=torch.tensor(depth_ids,device='cuda');dt=torch.tensor(depth_target,device='cuda',dtype=torch.float32)
    anchor_by_name={n:[(i,o['uv']) for i,a in enumerate(anchors) for o in a['observations'] if o['name']==n] for n in train}
    save_json(out/'config.json',dict(steps=steps,geometrySteps=steps//2,appearanceSteps=steps-steps//2,seed=100221,train=train,
        development=plan['development'],fixedRegression=plan['audit'],fullSceneEvaluation=evaluation,
        geometry='one fixed material field shared across all train cameras; 96 layer-guarded controls',
        bound='32 native pixels per node coordinate; not 32 pixel Euclidean ball',topology='fixed; no deletion, duplication or density',
        depthPrior='existing conditional multiview cache; not truth',realStaticAnchors=len(anchors),
        nativeCanvas=[1080,1920],allComponentsCommonForward=True,bodyMotion='unchanged unverified source hypothesis',
        trainingReadinessNotPublication=True,published=False))
    contract.update(sources={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')},
        priorManifestHash=sha(Path(priors)/'manifest.json'),staticAnchorHash=sha(out/'static-anchors.json'))
    save_json(out/'contract.json',contract)
    old,before=evaluate_complete(base,data,evaluation,masks,out/'baseline-images')
    training_guard={}
    with torch.no_grad():
        for n in train:
            r=base.render(make_frame(data,n,crop=False));err=(r['rgb']-torch.tensor(data['rgb'][n],device='cuda')).abs().mean(-1)
            training_guard[n]=(err.cpu(),r['alpha'].cpu())
    summary={};random=rng_state();del proto;torch.cuda.empty_cache()
    for label,geometry in [('appearance-control',False),('shared-geometry',True)]:
        folder=out/label;folder.mkdir();restore_rng(random)
        model=SharedRoomStage(base,data,reference,geometry)
        for p in model.parameters():p.requires_grad_(False)
        rates={'sh':.002,'opacity':.003,'log_scales':.0007}
        ops={k:torch.optim.Adam([getattr(model.patch,k)],lr=v) for k,v in rates.items()}
        ops['field']=torch.optim.Adam([model.field.delta],lr=.01)
        sampler=FrameSampler(train,100221);initial={k:v.detach().clone() for k,v in model.state_dict().items()}
        def checkpoint(tag,step):
            save_checkpoint(folder/(tag+'.pt'),model,ops,{'views':sampler},stage=label,step=step,contract=contract,
                strategy={'events':[],'topology':'fixed all source identities'},extra=dict(sourceContinuity=source_extra,geometry=geometry,sourceIdentities=side))
        checkpoint('initial',0);_,init=evaluate_complete(model,data,evaluation,masks,folder/'initial-images',old)
        initial_diff=max(abs(init[n][p]['rgb']-before[n][p]['rgb']) for n in before for p in before[n])
        if initial_diff>1e-5:raise ValueError('initial_full_frame_not_exact:'+str(initial_diff))
        curve=[];start=time.perf_counter();torch.cuda.reset_peak_memory_stats();geometry_count=0
        for step in range(1,steps+1):
            phase=geometry and step<=steps//2
            model.field.delta.requires_grad_(phase)
            for k in rates:getattr(model.patch,k).requires_grad_(not phase)
            for op in ops.values():op.zero_grad(set_to_none=True)
            name=sampler.next();f=make_frame(data,name,crop=False);r=model.render(f);err=(r['rgb']-f['rgb']).abs().mean(-1)
            room=torch.tensor(masks[name]['room'],device='cuda');old_err,old_alpha=training_guard[name];old_err=old_err.to('cuda');old_alpha=old_alpha.to('cuda')
            loss=masked_mean(err,room)+.12*valid_window_structure(r['rgb'],f['rgb'],room)
            # Keep real visible background coverage without distilling old haze RGB.
            loss+=.3*masked_mean((old_alpha-r['alpha']-.005).clamp_min(0).square(),room)
            for part,weight in [('face',8.),('hair',4.),('neck',5.),('cloth',5.)]:
                mask=torch.tensor(masks[name][part],device='cuda')
                loss+=weight*masked_mean((err-old_err-.002).clamp_min(0),mask)
                loss+=.2*masked_mean((old_alpha-r['alpha']-.005).clamp_min(0).square(),mask)
            if phase:
                p,J=model.field(model.patch.base,model.normal,model.thickness)
                if len(di):loss+=.03*torch.nn.functional.smooth_l1_loss((p[di]-dt)/(model.metric[di,None]*32),torch.zeros_like(dt))
                a,_=model.field(xyz,normals,thickness);obs=anchor_by_name[name]
                if obs:
                    ai=torch.tensor([i for i,_ in obs],device='cuda');target=torch.tensor([u for _,u in obs],device='cuda',dtype=torch.float32)
                    cam=a[ai]@f['C'][:3,:3].T+f['C'][:3,3];uv=cam@f['K'].T;uv=uv[:,:2]/uv[:,2:]
                    loss+=.002*torch.nn.functional.huber_loss(uv,target,delta=1.)
                singular=bounded_singular_values(J);loss+=.05*((.7-singular).clamp_min(0).square()+(singular-1.3).clamp_min(0).square()).mean()
                loss+=.03*(.4-torch.linalg.det(J)).clamp_min(0).square().mean()+.002*model.field.regularizer()
            else:loss+=.001*(model.patch.log_scales-initial['patch.log_scales']).square().mean()+.0002*model.patch.sh[:,1:].square().mean()
            if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
            loss.backward()
            for n,p in model.named_parameters():
                if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient:'+n)
            if phase:ops['field'].step();geometry_count+=1
            else:
                for k in rates:ops[k].step()
            with torch.no_grad():model.patch.log_scales.clamp_(initial['patch.log_scales']+np.log(.9),initial['patch.log_scales']+np.log(1.1))
            if step==steps//2:checkpoint('mid',step)
            if step==1 or step%40==0:
                row=dict(step=step,name=name,geometry=phase,loss=float(loss.detach()));curve.append(row);print(label,json.dumps(row),flush=True)
            if time.perf_counter()-start>720 or torch.cuda.max_memory_allocated()/1048576>6144:raise ValueError('finite_resource_budget')
        actual_training_seconds=time.perf_counter()-start;training_allocated=torch.cuda.max_memory_allocated()/1048576;training_reserved=torch.cuda.max_memory_reserved()/1048576
        checkpoint('candidate-final',steps);_,after=evaluate_complete(model,data,evaluation,masks,folder/'final-images',old)
        failures=regression_screen(before,after);f=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));s=model.state(f)
        export_state(s,folder/'candidate-research-only.ply');h=sha(folder/'candidate-research-only.ply')
        np.savez_compressed(folder/'candidate-identities.npz',**{k:v for k,v in side.items() if k!='asset_hash'},asset_hash=np.array(h))
        inv=torch.linalg.inv(f['C']).cpu().numpy();height,width=f['rgb'].shape[:2]
        save_json(folder/'display.json',dict(assets=[dict(label=label,ply=str((folder/'candidate-research-only.ply').resolve()),hash=h,count=len(s.means))],K=f['K'].cpu().tolist(),C=f['C'].cpu().tolist(),width=width,height=height,camera=inv[:3,3].tolist(),target=(inv[:3,3]+inv[:3,2]).tolist(),up=(-inv[:3,1]).tolist(),near=.01*base.scale,far=1e10*base.scale,reference=reference,sourceHash=data['sourceHash'],published=False))
        moved,_=model.field(model.patch.base,model.normal,model.thickness)
        result=dict(baseline=before,initial=init,final=after,failures=failures,curve=curve,steps=steps,geometrySteps=geometry_count,
            maxGeometryShiftNativePixels=float(((moved-model.patch.base)/model.metric[:,None]).norm(dim=-1).max()) if geometry else 0.,
            parameterChanges={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if not k.startswith('baseline.') and v.is_floating_point()},
            trainingSeconds=actual_training_seconds,trainEvaluationExportSeconds=time.perf_counter()-start,allocatedMiB=training_allocated,reservedMiB=training_reserved,
            assetHash=h,sourceHash=data['sourceHash'],reference=reference,pointCount=len(s.means),
            frozenBaselineExact=exact_state_hash(base)==protected,geometrySupported=False,transactionAccepted=False,releaseQualityPassed=False,published=False)
        save_json(folder/'result.json',result);summary[label]={k:result[k] for k in ('failures','geometrySteps','trainingSeconds','allocatedMiB','reservedMiB','assetHash')}
        restore_checkpoint(folder/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda');checkpoint('restored',0)
        if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()) or exact_state_hash(base)!=protected:raise ValueError('protected_restore_changed')
        del model,ops;torch.cuda.empty_cache();print(label,'FINISHED',json.dumps(summary[label]),flush=True)
    save_json(out/'result.json',dict(branches=summary,seconds=time.perf_counter()-clock,published=False,baselineAssetHash=contract['completeAssetHash']))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('complete','priors','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--steps',type=int,default=240);a=p.parse_args()
    try:run(a.complete,a.priors,a.out,a.steps)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise