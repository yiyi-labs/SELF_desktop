"""Bounded replacement experiments on the locked COMPLETE scene.

No global opacity/scale changes. Measured-plane proposals and inherited-kernel
controls retain distinct evidence. All components stay in the same forward.
"""
from pathlib import Path
import json,time,copy,shutil,ast
import numpy as np,cv2,torch
import torch.nn.functional as F
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from gsplat import rasterization
from reconstruction_complete_model import load_complete,FreeComponent,pick
from reconstruction_portrait_model import GaussianState,joined_state,evaluate_sh1
from reconstruction_render_contract import make_frame,draw,masked_mean
from reconstruction_static_planes import fit_plane_groups,finite_plane_support
from reconstruction_observation_domains import attach_observation_domains
from reconstruction_checkpoint import file_sha256
from audit_complete_baseline import export_state


def plane_source_members(room, source_id, source_kind, members):
    """Cloned/split kernels retain seed identity, including triangle seeds.

    A sampled seed is attached only when ALL its measured parents belong to
    the same fitted plane. A source family is never itself called a plane.
    """
    result=(source_kind==0)&np.isin(source_id,members)
    sample=room['source_kind']==1
    sample_ids=room['source_id'][sample]
    if len(np.unique(sample_ids))!=len(sample_ids):raise ValueError('ambiguous_surface_seed_identity')
    compatible=np.isin(room['triangle_sources'][sample],members).all(1)
    return result|((source_kind==1)&np.isin(source_id,sample_ids[compatible]))


def target_plane_groups(room, groups, source_id, source_kind, scored_local, scale, *, views=None, masks=None):
    """Fit near ACTUALLY contributing origins, still with distributed tracks.

    The initial global plane list can miss a small physical surface. We do not
    enlarge it arbitrarily or call one track a wall: the same spatial spread,
    residual and min-inlier checks must hold in each bounded neighbourhood.
    """
    anchor=room['source_kind']==0;points=room['xyz'][anchor];pids=room['source_id'][anchor]
    measured={int(pid):i for i,pid in enumerate(pids)}
    sampled={int(pid):tri for pid,tri in zip(room['source_id'][room['source_kind']==1],
        room['triangle_sources'][room['source_kind']==1])}
    tree=cKDTree(points);seen=set();records=[];extra=[]
    for local,score in scored_local[:8]:
        kind=int(source_kind[local]);sid=int(source_id[local]);family=(kind,sid)
        if family in seen:continue
        seen.add(family)
        parents=[sid] if kind==0 else list(sampled.get(sid,[])) if kind==1 else []
        if not parents or any(int(pid) not in measured for pid in parents):
            records.append(dict(source=family,contribution=score,status='missing_measured_ancestry'));continue
        required=np.asarray([measured[int(pid)] for pid in parents])
        near=np.unique(tree.query(points[required],k=min(96,len(points)))[1].reshape(-1))
        found=fit_plane_groups(points[near],scale,max_planes=2)
        accepted=0;alternatives=[]
        for group in found:
            global_indices=near[group['indices']]
            on_plane=np.isin(required,global_indices).all()
            # An erroneous old seed need not lie on its replacement surface.
            # Only accept a different conditional surface when the old seed's
            # TRAIN projections lie within the measured new hull in >=3 views.
            # This tests finite correspondence support, not depth truth.
            overlap=0
            if not on_plane and views is not None:
                from scipy.spatial import ConvexHull,QhullError
                try:hull=ConvexHull((points[global_indices]-group['center'])@group['basis'].T)
                except QhullError:continue
                polygon=points[global_indices[hull.vertices]]
                for name,(C,K) in views.items():
                    cam=polygon@C[:3,:3].T+C[:3,3]
                    p=points[required]@C[:3,:3].T+C[:3,3]
                    if (cam[:,2]<=.01).any() or (p[:,2]<=.01).any():continue
                    uv=cam@K.T;uv=(uv[:,:2]/uv[:,2:]).astype(np.float32)
                    q=p@K.T;q=q[:,:2]/q[:,2:];h,w=masks[name].shape
                    xy=np.rint(q).astype(int)
                    inside=(xy[:,0]>=0)&(xy[:,1]>=0)&(xy[:,0]<w)&(xy[:,1]<h)
                    if not inside.all() or not masks[name][xy[:,1],xy[:,0]].all():continue
                    if all(cv2.pointPolygonTest(uv,tuple(map(float,u)),False)>=0 for u in q):overlap+=1
                if overlap<3:continue
            elif not on_plane:continue
            signature=frozenset(global_indices.tolist())
            if any(len(signature.intersection(g['indices']))/max(1,len(signature))>.9 for g in groups+extra):continue
            extra.append({**group,'indices':global_indices,'replacementSourceFamilies':[family],
                'oldSeedOnPlane':bool(on_plane),'trainHullOverlap':overlap});accepted+=1
            alternatives.append(dict(inliers=len(global_indices),oldSeedOnPlane=bool(on_plane),trainHullOverlap=overlap))
        records.append(dict(source=family,contribution=score,measuredParents=parents,
            neighbourhood=len(near),acceptedPlanes=accepted,alternatives=alternatives,
            status='finite_local_fit' if accepted else 'no_distributed_coplanar_support'))
    return groups+extra,records


def accumulated_candidate_scores(state,frame,ids,scale,mask):
    """True composited per-kernel contributions; chunks only feature channels."""
    result=[];h,w=frame['rgb'].shape[:2]
    with torch.no_grad():
        for chunk in ids.split(24):
            channels=torch.zeros(len(state.means),len(chunk),device=state.means.device)
            channels[chunk,torch.arange(len(chunk),device=state.means.device)]=1
            values,_,_=rasterization(state.means,state.quats,state.scales,state.opacity,channels,
                frame['C'][None],frame['K'][None],w,h,packed=True,sh_degree=None,render_mode='RGB',
                rasterize_mode='classic',near_plane=.01*scale,far_plane=1e10*scale)
            result.append((values[0]*mask[...,None]).sum((0,1))/mask.sum().clamp_min(1))
    return torch.cat(result) if result else torch.empty(0,device=state.means.device)


def choose_resampling(base,data,plan,reference,*,control=False,max_parents=16):
    """A bounded standard-GS representation test, NOT a new surface claim.

    Keeps the third covariance axis at initialization. Splits two inherited axes of a single
    actually contributing source family. True training images must restore
    coverage; alpha splitting is explicitly not a compositing identity.
    """
    frame=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));state=base.state(frame)
    if reference not in plan['train']:raise ValueError('selection_reference_not_training_observation')
    meta=base.baseline.room.metadata;room_ids=torch.where(state.parts==0)[0]
    source_id=meta['source_id'][base.keep_room];kind=meta['source_kind'][base.keep_room]
    with torch.no_grad():
        h,w=frame['rgb'].shape[:2];info=draw(state,frame['C'],frame['K'],w,h,unit_scale=base.scale)['info']
        packed=info['gaussian_ids'];face=frame['masks']['face_core']|frame['masks']['face_boundary']
        yy,xx=torch.where(face);xy=info['means2d'];r=info['radii'];c=info['conics']
        valid=(state.parts[packed]==0)&(r.amax(-1)>96)&(xy[:,0]+r[:,0]>=xx.min())&(xy[:,0]-r[:,0]<=xx.max())
        valid&=(xy[:,1]+r[:,1]>=yy.min())&(xy[:,1]-r[:,1]<=yy.max())
        ids=packed[valid];xy=xy[valid];c=c[valid];dx=xx.float().mean()-xy[:,0];dy=yy.float().mean()-xy[:,1]
        estimate=state.opacity[ids]*torch.exp(-.5*(c[:,0]*dx.square()+2*c[:,1]*dx*dy+c[:,2]*dy.square()).clamp_min(0))
        ids=ids[torch.argsort(estimate,descending=True)[:96]]
        contribution=accumulated_candidate_scores(state,frame,ids,base.scale,face)
        if not len(ids) or contribution.max()<1e-4:raise ValueError('no_actual_wide_kernel_contribution')
        selected=ids[contribution.argmax()];room_position=torch.where(room_ids==selected)[0].item()
        family_sid=source_id[room_position];family_kind=kind[room_position]
        local=torch.where((source_id==family_sid)&(kind==family_kind))[0];ids=room_ids[local]
        scores=accumulated_candidate_scores(state,frame,ids,base.scale,face)
        ids=ids[torch.argsort(scores,descending=True)[:max_parents]]
        old=pick(state,ids)
        from reconstruction_portrait_model import quaternion_matrix
        R=quaternion_matrix(old.quats)
        count=1 if control else 9
        grid=torch.zeros((1,3),device='cuda') if control else torch.tensor(
            [[x,y,0.] for x in (-.6,0.,.6) for y in (-.6,0.,.6)],device='cuda')
        means=old.means[:,None,:]+torch.einsum('nij,nkj->nki',R,grid[None]*old.scales[:,None,:])
        scales=old.scales[:,None,:].repeat(1,count,1)
        if not control:scales[:,:,:2]*=.72
        opacity=old.opacity if control else 1-(1-old.opacity).pow(1/count)
        proposal=dict(xyz=means.reshape(-1,3).cpu().numpy(),scales=scales.reshape(-1,3).cpu().numpy(),
            quats=old.quats.repeat_interleave(count,0).cpu().numpy(),sh=old.sh.repeat_interleave(count,0).cpu().numpy(),
            opacity=opacity.repeat_interleave(count).cpu().numpy(),
            support=meta['support'][base.keep_room][local][torch.argsort(scores,descending=True)[:max_parents]].repeat_interleave(count).cpu().numpy(),
            source_kind=np.full(len(ids)*count,8,np.uint8),source_id=np.arange(len(ids)*count),
            triangle_sources=np.tile([int(family_sid)]*3,(len(ids)*count,1)),
            parent_global_index=ids.repeat_interleave(count).cpu().numpy())
    details=dict(mode='wide-control' if control else 'local-resample',sourceFamily=[int(family_kind),int(family_sid)],
        selectedParents=ids.cpu().tolist(),accumulatedFaceContribution=float(scores.sum()),
        train=[n for n in plan['train'] if n in data['worlds']],
        geometry='inherited Gaussian-volume hypothesis; NOT new independently measured geometry',
        newIndependentEvidence=False,alphaSplitIsExact=False,thirdCovarianceAxisPreservedAtInitialization=True,
        physicalSurfaceNormalVerified=False)
    return ids,proposal,details


def choose_proposal(base,data,plan,reference,*,budget=2048,max_parents=16,diagnostics=None):
    """Training-only geometry and true accumulated contribution, no dev RGB."""
    anchor=data['room']['source_kind']==0;points=data['room']['xyz'][anchor];pids=data['room']['source_id'][anchor]
    groups=fit_plane_groups(points,base.scale)
    train=[n for n in plan['train'] if n in data['worlds']]
    if reference not in train:raise ValueError('selection_reference_not_training_observation')
    if len(train)<3 or not groups:raise ValueError('no_reliable_world_plane_support')
    frame=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));state=base.state(frame)
    room_ids=torch.where(state.parts==0)[0];meta=base.baseline.room.metadata
    if len(room_ids)!=int(base.keep_room.sum()):raise ValueError('additional_room_component_needs_explicit_source_map')
    source_id=meta['source_id'][base.keep_room].cpu().numpy();source_kind=meta['source_kind'][base.keep_room].cpu().numpy()
    wide=torch.zeros(len(state.means),device='cuda');votes=torch.zeros_like(wide,dtype=torch.long)
    # A group invisible in three evenly spaced frames is not necessarily
    # unsupported in the original training observations. No new C is invented.
    detailed=train
    with torch.no_grad():
        for name in detailed:
            f=base.baseline.adjusted_frame(make_frame(data,name,crop=False));s=base.state(f);h,w=f['rgb'].shape[:2]
            info=draw(s,f['C'],f['K'],w,h,unit_scale=base.scale)['info']
            ids=info['gaussian_ids'];radii=info['radii'].amax(-1).float()
            wide[ids]=torch.maximum(wide[ids],radii);votes[ids]+=(radii>96).long()
    # Locate harmful source families before fitting their finite replacement.
    # A bbox/conic estimate only proposes a bounded list; alpha compositing
    # determines actual contribution. Neither is used as a geometric truth.
    ref=base.baseline.adjusted_frame(make_frame(data,reference,crop=False))
    h,w=ref['rgb'].shape[:2];face=ref['masks']['face_core']|ref['masks']['face_boundary']
    with torch.no_grad():
        info=draw(state,ref['C'],ref['K'],w,h,unit_scale=base.scale)['info']
        packed=info['gaussian_ids'];xy=info['means2d'];radius=info['radii'].float()
        yy,xx=torch.where(face);left,right=xx.min(),xx.max();top,bottom=yy.min(),yy.max()
        overlap=(xy[:,0]+radius[:,0]>=left)&(xy[:,0]-radius[:,0]<=right)&(xy[:,1]+radius[:,1]>=top)&(xy[:,1]-radius[:,1]<=bottom)
        valid=overlap&(state.parts[packed]==0)&(votes[packed]>=2)
        selected=packed[valid];uv=xy[valid];conic=info['conics'][valid]
        dx=(xx.float().mean()-uv[:,0]);dy=(yy.float().mean()-uv[:,1])
        estimate=state.opacity[selected]*torch.exp(-.5*(conic[:,0]*dx.square()+2*conic[:,1]*dx*dy+conic[:,2]*dy.square()).clamp_min(0))
        candidate_ids=selected[torch.argsort(estimate,descending=True)[:96]]
        scores=accumulated_candidate_scores(state,ref,candidate_ids,base.scale,face)
    room_index={int(v):i for i,v in enumerate(room_ids.cpu().tolist())}
    order=torch.argsort(scores,descending=True).cpu().tolist()
    scored=[(room_index[int(candidate_ids[i])],float(scores[i])) for i in order if scores[i]>1e-5]
    views={n:(data['worlds'][n],data['K']) for n in train}
    masks={n:data['labels'][n]['observed_room'] for n in train}
    groups,targeted=target_plane_groups(data['room'],groups,source_id,source_kind,scored,base.scale,views=views,masks=masks)
    tags=torch.zeros(len(state.means),len(groups),device='cuda');scopes=[]
    for index,group in enumerate(groups):
        members=pids[group['indices']]
        member=plane_source_members(data['room'],source_id,source_kind,members)
        for kind,sid in group.get('replacementSourceFamilies',[]):member|=(source_kind==kind)&(source_id==sid)
        local=np.flatnonzero(member)
        ids=room_ids[torch.as_tensor(local,device='cuda')];ids=ids[votes[ids]>=2]
        tags[ids,index]=1;scopes.append(ids)
    evidence=dict(targetedPlaneFits=targeted,attributedCandidates=len(candidate_ids),
        projectionObservations=detailed,planeInliers=[len(g['indices']) for g in groups],
        traceableWideCandidates=[len(ids) for ids in scopes],sourceKindCounts={str(k):int((source_kind==k).sum()) for k in np.unique(source_kind)})
    if diagnostics is not None:diagnostics.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    if not any(len(ids) for ids in scopes):raise ValueError('no_traceable_wide_room_kernel_on_measured_planes')
    # Tags share projection, depth sorting and transparency with ALL components.
    with torch.no_grad():
        f=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));s=base.state(f);h,w=f['rgb'].shape[:2]
        rgb=evaluate_sh1(s.sh,s.means-torch.linalg.inv(f['C'])[:3,3])
        features=torch.cat((rgb,F.one_hot(s.parts,5).float(),tags),1)
        image,alpha,info=rasterization(s.means,s.quats,s.scales,s.opacity,features,f['C'][None],f['K'][None],w,h,
            packed=True,sh_degree=None,render_mode='RGB',rasterize_mode='classic',near_plane=.01*base.scale,far_plane=1e10*base.scale)
        face=f['masks']['face_core']|f['masks']['face_boundary'];contributions=image[0,:,:,8:]
        original=draw(s,f['C'],f['K'],w,h,unit_scale=base.scale)
        rgb_difference=(image[0,:,:,:3]-original['rgb']).abs()
        if rgb_difference.max()>.003 or rgb_difference.mean()>1e-5:
            raise ValueError('contribution_diagnostic_changed_rgb_contract')
        if (image[0,:,:,3:8].sum(-1)-alpha[0,:,:,0]).abs().max()>1e-4:
            raise ValueError('contribution_not_conserved')
        if (contributions.sum(-1)-image[0,:,:,3]).max()>1e-4:
            raise ValueError('plane_tags_exceed_room_contribution')
        scores=[float(masked_mean(contributions[...,i],face)) for i in range(len(groups))]
    evidence.update(faceContributions=scores,tagRgbDifferenceMax=float(rgb_difference.max()))
    if diagnostics is not None:diagnostics.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    index=max(range(len(groups)),key=lambda i:scores[i] if len(scopes[i]) else -1)
    if scores[index]<=1e-5:raise ValueError('no_measured_plane_group_contributing_to_face')
    proposal,details=finite_plane_support(data['room'],views,masks,data['rgb'],base.scale,
        budget=budget,stride=10,plane_groups=[groups[index]],grow_observed=False)
    if proposal is None or len(proposal['xyz'])<32:raise ValueError('selected_plane_has_no_supported_finite_surface')
    group=groups[index];ids=scopes[index]
    # Retirement budget applies AFTER attribution. Large off-screen kernels
    # must not displace the ones actually contributing to the target.
    if len(ids)>max_parents:
        importance=accumulated_candidate_scores(s,f,ids,base.scale,face)
        ids=ids[torch.argsort(importance,descending=True)[:max_parents]]
    return ids,proposal,dict(plane=index,independentStaticAnchors=len(group['indices']),
        planeResidualP90=group['residualP90'],planeTolerance=group['tolerance'],
        selectedParents=ids.cpu().tolist(),parentRadius=wide[ids].cpu().tolist(),
        accumulatedFaceContribution=scores[index],allPlaneContributions=scores,
        oldSeedOnPlane=group.get('oldSeedOnPlane'),trainHullOverlap=group.get('trainHullOverlap'),
        proposals=details,train=train,tagRgbDifferenceMax=float(rgb_difference.max()),
        geometry='finite distributed static-track plane hypothesis, not measured dense truth')


class CompleteRoomReplacement(torch.nn.Module):
    def __init__(self,base,data,reference,ids,proposal):
        super().__init__();self.baseline=base;self.scale=base.scale
        frame=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));old=base.state(frame)
        keep=torch.ones(len(old.means),device='cuda',dtype=torch.bool);keep[ids]=False
        self.register_buffer('keep',keep);self.register_buffer('retired_ids',ids)
        xyz=proposal['xyz']
        if 'scales' in proposal:
            scales=proposal['scales'];quats=proposal['quats'];colour=proposal['sh'];opacity=proposal['opacity']
            spacing=scales[:,:2].mean(1)
        else:
            scales,quats,colour,opacity,spacing=self.surface_parameters(proposal)
        t=lambda a:torch.as_tensor(a,device='cuda',dtype=torch.float32)
        state=GaussianState(t(xyz),t(quats),t(scales),t(opacity),t(colour),torch.zeros(len(xyz),device='cuda',dtype=torch.long))
        self.patch=FreeComponent(state,torch.arange(len(xyz),device='cuda'),t(proposal['support']),'world-reference',float(np.median(spacing))*.15)
        with torch.no_grad():self.patch.opacity.copy_(torch.logit(state.opacity.clamp(1e-6,1-1e-6)))
        for parameter in self.patch.parameters():parameter.requires_grad_(False)
        self.register_buffer('initial_scales',t(scales))
        self.register_buffer('source_tracks',torch.as_tensor(proposal['triangle_sources'],device='cuda',dtype=torch.long))
        self.register_buffer('source_kind',torch.as_tensor(proposal.get('source_kind',np.full(len(xyz),7)),device='cuda',dtype=torch.long))
    @staticmethod
    def surface_parameters(proposal):
        xyz=proposal['xyz'];distance=cKDTree(xyz).query(xyz,k=4)[0][:,1:].mean(1)
        positive=distance[distance>0]
        if not len(positive):raise ValueError('duplicate_only_surface')
        spacing=np.maximum(distance,np.median(positive)*.5)
        normals=proposal['surface_normal'];axis=np.tile([1.,0,0],(len(xyz),1));axis[np.abs(normals[:,0])>.9]=[0.,1,0]
        x=np.cross(axis,normals);x/=np.linalg.norm(x,axis=1)[:,None];y=np.cross(normals,x)
        quats=Rotation.from_matrix(np.stack((x,y,normals),-1)).as_quat()[:,[3,0,1,2]].astype(np.float32)
        # Finite surface sampling determines tangent support; normal thickness
        # is independently bounded. This is not a uniform shrink of old points.
        scales=np.c_[spacing*.8,spacing*.8,spacing*.12].astype(np.float32)
        colour=np.zeros((len(xyz),4,3),np.float32)
        from appearance_direction_contract import C0
        colour[:,0]=(proposal['rgb']-.5)/C0
        return scales,quats,colour,np.full(len(xyz),.65,np.float32),spacing
    def state(self,frame):
        return joined_state(pick(self.baseline.state(frame),self.keep),self.patch.state())
    def render(self,frame):
        frame=self.baseline.baseline.adjusted_frame(frame);state=self.state(frame);h,w=frame['rgb'].shape[:2]
        return draw(state,frame['C'],frame['K'],w,h,unit_scale=self.scale)


def structure(pred,target,mask):
    total=pred.sum()*0
    for axis in (0,1):
        a=[slice(None)]*3;b=a.copy();a[axis]=slice(1,None);b[axis]=slice(None,-1)
        valid=mask[tuple(a[:2])]&mask[tuple(b[:2])]
        err=((pred[tuple(a)]-pred[tuple(b)])-(target[tuple(a)]-target[tuple(b)])).abs().mean(-1)
        total+=masked_mean(err,valid)*.5
    return total


def evaluate(model,data,names,out):
    out.mkdir();records={};metrics={}
    with torch.no_grad():
        for name in names:
            frame=make_frame(data,name,crop=False);r=model.render(frame);rgb=r['rgb'].cpu().numpy();a=r['alpha'].cpu().numpy();q=r['q'].cpu().numpy()
            target=data['rgb'][name];error=np.abs(rgb-target).mean(-1);labels=data['labels'][name];metrics[name]={}
            for part,mask in [('face',labels['face_core']|labels['face_boundary']),('hair',labels['hair_visible']),
                              ('body',labels['neck_cloth_visible']),('room',labels['observed_room'])]:
                if mask.any():metrics[name][part]=dict(rgb=float(error[mask].mean()),alpha=float(a[mask].mean()),
                    holes=float((a[mask]<.8).mean()),qRoom=float(q[mask,0].mean()),
                    positiveBrightness=float(np.maximum((rgb-target).mean(-1),0)[mask].mean()))
            records[name]=dict(rgb=rgb,alpha=a,q=q)
            np.savez_compressed(out/(name+'.npz'),**records[name])
            cv2.imwrite(str(out/(name+'.png')),cv2.cvtColor((np.concatenate((target,rgb.clip(0,1)),1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    return records,metrics


def run(out,*,steps=160,manifest=None,mode='surface'):
    out=Path(out).resolve();private=Path(__file__).resolve().parent/'.sources'
    if not out.is_relative_to(private) or out.exists() or not 80<=steps<=240:raise ValueError('bounded_fresh_private_run_required')
    out.mkdir();clock=time.perf_counter();torch.manual_seed(100216);np.random.seed(100216)
    manifest=Path(manifest or Path(__file__).with_name('reconstruction_baseline.json')).resolve()
    data,plan,base,lock,source_checkpoint=load_complete(manifest)
    prepared=Path(lock['prepared'])
    if not prepared.is_absolute():prepared=manifest.parent/prepared
    attach_observation_domains(data,prepared)
    snapshot=out/'algorithm-source';snapshot.mkdir()
    files=['reconstruction_complete_room.py','reconstruction_baseline.json']
    hashes={}
    while files:
        name=files.pop()
        if name in hashes:continue
        path=Path(__file__).parent/name;hashes[name]=file_sha256(path);shutil.copy2(path,snapshot/name)
        if path.suffix=='.py':
            for node in ast.walk(ast.parse(path.read_bytes())):
                imports=([node.module] if isinstance(node,ast.ImportFrom) else
                    [n.name for n in node.names] if isinstance(node,ast.Import) else [])
                for module in imports:
                    candidate=(module or '').split('.')[0]+'.py'
                    if (path.parent/candidate).is_file() and candidate not in hashes:files.append(candidate)
    (out/'source-hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    frozen={k:v.detach().clone() for k,v in base.state_dict().items()}
    if mode=='surface':
        ids,proposal,details=choose_proposal(base,data,plan,lock['reference'],diagnostics=out/'selection-diagnostic.json')
    else:ids,proposal,details=choose_resampling(base,data,plan,lock['reference'],control=mode=='wide-control')
    np.savez_compressed(out/'proposal.npz',**proposal)
    (out/'proposal.json').write_text(json.dumps(details,indent=2),encoding='utf-8')
    model=CompleteRoomReplacement(base,data,lock['reference'],ids,proposal)
    train=details['train'];names=list(dict.fromkeys([lock['reference']]+[n for n in plan['development'] if n in data['worlds']]))
    before,old_metrics=evaluate(base,data,names,out/'baseline')
    _,initial_metrics=evaluate(model,data,names,out/'initial')
    rates={'sh':.002,'opacity':.006,'log_scales':.001,'quats':.0002}
    optimizer=torch.optim.Adam([{'params':[getattr(model.patch,k)],'lr':v,'name':k} for k,v in rates.items()])
    for key in rates:getattr(model.patch,key).requires_grad_(True)
    protected={};curve=[];rng=np.random.default_rng(100216);order=[]
    config=dict(mode=mode,steps=steps,seed=100216,train=train,evaluation=names,reference=lock['reference'],
        maxNewPoints=2048,maxRetiredParents=16,centresAndPosesFrozen=True,covariancesTrainable=True,allComponentsInForward=True,
        baseline=lock,protected='all source model fields + real image regression',renderer='original full-canvas quaternion/scale gsplat1.5.3')
    (out/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    def save(label,step):
        torch.save(dict(schema='self-complete-surface-replacement-1',step=step,model=model.state_dict(),
            optimizer=optimizer.state_dict(),bindings={g['name']:['patch.'+g['name']] for g in optimizer.param_groups},
            rng={'torch':torch.get_rng_state(),'cuda':torch.cuda.get_rng_state_all(),'numpy':copy.deepcopy(rng.bit_generator.state)},
            sampler={'remaining':list(order)},config=config,proposal=proposal,sourceCheckpointHash=lock['files']['checkpoint']['sha256']),out/(label+'.pt'))
    save('initial',0);torch.cuda.reset_peak_memory_stats();training_clock=time.perf_counter()
    for step in range(1,steps+1):
        if not order:order=[str(name) for name in rng.permutation(train)]
        name=order.pop();frame=make_frame(data,name,crop=False);r=model.render(frame);err=(r['rgb']-frame['rgb']).abs().mean(-1)
        m=frame['masks'];room=m['observed_room']
        protected_parts=[m['face_core']|m['face_boundary'],m['hair_visible'],m['neck_cloth_visible']]
        protected_parts=[mask&~m['unknown_or_occluded'] for mask in protected_parts]
        person=protected_parts[0]|protected_parts[1]|protected_parts[2]
        if name not in protected:
            with torch.no_grad():old=base.render(frame)
            protected[name]=dict(error=(old['rgb']-frame['rgb']).abs().mean(-1).detach(),alpha=old['alpha'].detach(),qRoom=old['q'][...,0].detach())
        guard=protected[name]
        loss=masked_mean(err,room)+.2*structure(r['rgb'],frame['rgb'],room)+.04*masked_mean((1-r['alpha']).square(),room)
        # Person RGB is an EVALUATION gate, not a color training target for
        # room kernels. The guard can affect alpha/geometry, never paint skin
        # colors onto room SH. It also does not force all q_room to zero.
        for mask in protected_parts:
            loss+=2*masked_mean((r['q'][...,0]-guard['qRoom']-.005).clamp_min(0),mask)
        loss+=.15*masked_mean((guard['alpha']-r['alpha']-.015).clamp_min(0),room|person)
        loss+=.0002*model.patch.sh[:,1:].square().mean()
        if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
        optimizer.zero_grad(set_to_none=True);loss.backward()
        if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.patch.parameters()):raise ValueError('nonfinite_gradient')
        optimizer.step()
        with torch.no_grad():
            lo=model.initial_scales.log()+np.log(.8);hi=model.initial_scales.log()+np.log(1.25)
            model.patch.log_scales.copy_(torch.minimum(torch.maximum(model.patch.log_scales,lo),hi))
        if step==1 or step%40==0:
            row=dict(step=step,name=name,loss=float(loss.detach()));curve.append(row);print(json.dumps(row),flush=True)
        if step==steps//2:save('mid',step)
        if torch.cuda.max_memory_allocated()/1048576>6656 or time.perf_counter()-training_clock>300:raise ValueError('finite_resource_budget')
    training_seconds=time.perf_counter()-training_clock
    save('final',steps);after,new_metrics=evaluate(model,data,names,out/'final');failures=[]
    for name,row in old_metrics.items():
        for part,before_part in row.items():
            final=new_metrics[name][part]
            if final['rgb']>before_part['rgb']+.003:failures.append(part+'_rgb:'+name)
            if final['alpha']<before_part['alpha']-.015:failures.append(part+'_coverage:'+name)
            if final['holes']>before_part['holes']+.02:failures.append(part+'_holes:'+name)
    unchanged=all(torch.equal(value,base.state_dict()[key]) for key,value in frozen.items())
    if not unchanged:raise ValueError('source_parameters_changed')
    with torch.no_grad():
        frame=base.baseline.adjusted_frame(make_frame(data,lock['reference'],crop=False));state=model.state(frame)
        export_state(state,out/'candidate.ply')
    side_path=Path(lock['files']['identities']['path'])
    if not side_path.is_absolute():side_path=manifest.parent/side_path
    side=dict(np.load(side_path));keep=model.keep.cpu().numpy();count=len(proposal['xyz'])
    preserved={k:v[keep] for k,v in side.items() if v.ndim and len(v)==len(keep)}
    binding=('world-reference; finite measured-track plane hypothesis' if mode=='surface' else
        'world-reference; inherited Gaussian volume, no new measured surface')
    ancestry={'new_parent_global_index':proposal['parent_global_index']} if 'parent_global_index' in proposal else {}
    np.savez_compressed(out/'identity-transaction.npz',**preserved,retired_global_index=ids.cpu().numpy(),
        new_namespace=np.full(count,4,np.int64),new_uid=np.arange(count,dtype=np.int64),
        new_component=np.zeros(count,np.int64),new_source_kind=proposal['source_kind'],
        new_source_id=proposal['source_id'],new_source_tracks=proposal['triangle_sources'],
        new_support=proposal['support'],new_binding=np.asarray(binding),**ancestry)
    result=dict(sourceHash=data['sourceHash'],baselineAssetHash=lock['assetHash'],candidateAssetHash=file_sha256(out/'candidate.ply'),
        oldPoints=lock['pointCount'],newPoints=len(state.means),retiredParents=len(ids),newRepresentationPoints=len(proposal['xyz']),
        baseline=old_metrics,initial=initial_metrics,final=new_metrics,sourceAll67FieldsExact=unchanged,
        optimizerSteps=steps,curve=curve,failures=failures,acceptedForFurtherReview=not failures,
        qualityAccepted=False,releaseApproved=False,published=False,seconds=time.perf_counter()-clock,
        trainingSeconds=training_seconds,allocatedPeakMiB=torch.cuda.max_memory_allocated()/1048576,
        reservedPeakMiB=torch.cuda.max_memory_reserved()/1048576,
        sourceHashes=hashes,manifestHash=file_sha256(manifest))
    (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('newPoints','retiredParents','newRepresentationPoints','failures','seconds','allocatedPeakMiB')},indent=2))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--steps',type=int,default=160);parser.add_argument('--manifest')
    parser.add_argument('--mode',choices=('surface','wide-control','local-resample'),default='surface')
    args=parser.parse_args()
    try:run(args.out,steps=args.steps,manifest=args.manifest,mode=args.mode)
    except Exception as exc:
        folder=Path(args.out)
        if folder.exists():(folder/'failure.json').write_text(json.dumps({'error':str(exc),'published':False}),encoding='utf-8')
        raise
