"""Training-observation patch selection and transactional surface resampling.

Uses observed forward/backward texture tracks. Triangulation remains conditional
on measured local F; it is not an independent depth sensor or a face truth mesh.
"""
import copy,math
import cv2,numpy as np,torch
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from gsplat.rendering import rasterization
from reconstruction_portrait_model import GaussianState,quaternion_matrix,walk_embeddings,barycentric_of,mesh_adjacency
from reconstruction_portrait_pipeline import make_frame
from reconstruction_research_state import ensure_point_lineage
from reconstruction_components_v3 import save_json
from appearance_direction_contract import C0


def patch_mask(data,name,side):
    marks=data['local'][name]['marks'];m=data['labels'][name];h,w=m['face_core'].shape
    # A nasal-wing/cheek strip, scaled by actual observed eye/lip span.
    # Excludes nostrils, lips, eyelids and glasses. No frame IDs or fixed face coordinates.
    anchor=marks[98 if side=='left' else 327,:2];eye_span=np.linalg.norm(marks[33,:2]-marks[263,:2]);sign=-1 if side=='left' else 1
    a=anchor+np.array([sign*.04*eye_span,-.01*eye_span]);b=anchor+np.array([sign*.30*eye_span,.26*eye_span])
    x0,x1=sorted([int(a[0]),int(b[0])]);y0,y1=sorted([int(a[1]),int(b[1])])
    out=np.zeros((h,w),np.uint8);out[max(0,y0):min(h,y1),max(0,x0):min(w,x1)]=1
    out &= m['face_core'].astype(np.uint8);out[m['glasses_visible']|m['unknown_or_occluded']]=0
    return cv2.erode(out,np.ones((3,3),np.uint8)).astype(bool)


def track_patch(model,data,names,out):
    names=sorted(names);K=data['K'];rows=[];candidates=[]
    for side in ('left','right'):
        for na,nb in zip(names[:-1],names[1:]):
            # Bounded adjacent selected observations, never held-out RGB.
            ma=patch_mask(data,na,side);mb=patch_mask(data,nb,side)
            ia=(data['rgb'][na]*255).round().astype(np.uint8);ib=(data['rgb'][nb]*255).round().astype(np.uint8)
            ga=cv2.cvtColor(ia,cv2.COLOR_RGB2GRAY);gb=cv2.cvtColor(ib,cv2.COLOR_RGB2GRAY)
            p=cv2.goodFeaturesToTrack(ga,100,.01,4,mask=ma.astype(np.uint8)*255,blockSize=5)
            if p is None:continue
            q,ok,_=cv2.calcOpticalFlowPyrLK(ga,gb,p,None,winSize=(21,21),maxLevel=3)
            back,ok2,_=cv2.calcOpticalFlowPyrLK(gb,ga,q,None,winSize=(21,21),maxLevel=3)
            a=p[:,0];b=q[:,0];h,w=ma.shape;xy=np.rint(b).astype(int);inside=(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
            clipped=xy.clip([0,0],[w-1,h-1]);fb=np.linalg.norm(back[:,0]-a,axis=1)
            valid=(ok[:,0]>0)&(ok2[:,0]>0)&(fb<.75)&inside&mb[clipped[:,1],clipped[:,0]]
            a,b=a[valid],b[valid];row={'side':side,'a':na,'b':nb,'detected':len(p),'fbValid':len(a)}
            if len(a)<4:rows.append(row);continue
            with torch.no_grad():
                fa=model.adjusted_frame(make_frame(data,na,crop=False));fbf=model.adjusted_frame(make_frame(data,nb,crop=False))
                A=fa['F'].cpu().numpy();B=fbf['F'].cpu().numpy()
                mesh=(fa['mesh']+model.portrait.surface_residual).cpu().numpy()
            X=cv2.triangulatePoints(K@A[:3],K@B[:3],a.T,b.T);xyz=(X[:3]/X[3]).T
            va=xyz@A[:3,:3].T+A[:3,3];vb=xyz@B[:3,:3].T+B[:3,3]
            ua=va@K.T;ub=vb@K.T;ua=ua[:,:2]/ua[:,2:];ub=ub[:,:2]/ub[:,2:]
            repro=np.maximum(np.linalg.norm(ua-a,axis=1),np.linalg.norm(ub-b,axis=1))
            ca=-A[:3,:3].T@A[:3,3];cb=-B[:3,:3].T@B[:3,3]
            ra=xyz-ca;rb=xyz-cb;ra/=np.maximum(np.linalg.norm(ra,axis=1,keepdims=True),1e-9);rb/=np.maximum(np.linalg.norm(rb,axis=1,keepdims=True),1e-9)
            angle=np.degrees(np.arccos((ra*rb).sum(1).clip(-1,1)))
            # Local surface consistency is a check, NOT the track measurement.
            dist,near=cKDTree(mesh).query(xyz);metric=np.median(va[:,2])/K[0,0]
            good=np.isfinite(xyz).all(1)&(va[:,2]>.05)&(vb[:,2]>.05)&(repro<1.25)&(angle>.75)&(dist<.012)
            row.update(accepted=int(good.sum()),reprojectionMedian=float(np.median(repro[good])) if good.any() else None,
                angleMedian=float(np.median(angle[good])) if good.any() else None,surfaceDistancePxMedian=float(np.median(dist[good])/metric) if good.any() else None)
            rows.append(row)
            if good.sum()>=4:candidates.append((side,na,nb,a[good],b[good],xyz[good],repro[good],angle[good]))
    scores={side:sum(len(c[3]) for c in candidates if c[0]==side) for side in ('left','right')}
    side=max(scores,key=scores.get);chosen=[c for c in candidates if c[0]==side]
    report={'rows':rows,'scores':scores,'selected':side,'rule':'training-only cheek strip; FB<0.75px, reprojection<1.25px, angle>0.75deg; conditional on existing F',
        'reliable':scores[side]>=16 and len(chosen)>=3,'thresholdsFrozen':True,'developmentRGBRead':False,'surfaceNotMeasurementTruth':True}
    save_json(out/'correspondences.json',report)
    if not report['reliable']:raise ValueError('insufficient_real_local_tracks:'+str(scores))
    np.savez_compressed(out/'tracks.npz',**{f'{i}_{k}':c[j] for i,c in enumerate(chosen) for k,j in [('a',3),('b',4),('xyz',5),('reprojection',6),('angle',7)]})
    c=max(chosen,key=lambda c:len(c[3]));im=(data['rgb'][c[1]]*255).round().astype(np.uint8).copy()
    for xy in c[3]:cv2.circle(im,tuple(np.rint(xy).astype(int)),2,(60,240,160),1)
    cv2.imwrite(str(out/'training-texture-tracks.png'),cv2.cvtColor(im,cv2.COLOR_RGB2BGR))
    return side,report


def weights(state,C,K,width,height,mask,unit_scale=1.):
    """Exact per-splat accumulated alpha*T over a fixed pixel support.
    Zero dummy colour differentiates contribution, not position/appearance.
    Visibility and sorting are shared with the actual renderer.
    """
    v=torch.zeros(len(state.means),1,device=state.means.device,requires_grad=True)
    im,_,info=rasterization(state.means.detach(),state.quats.detach(),state.scales.detach(),state.opacity.detach(),v,
        C[None],K[None],width,height,packed=True,sh_degree=None,near_plane=.01*unit_scale,far_plane=1e10*unit_scale,rasterize_mode='classic')
    grad=torch.autograd.grad((im[0,...,0]*mask).sum(),v)[0][:,0]
    return grad.detach(),{k:info[k].detach() for k in ('means2d','conics','radii','gaussian_ids')}


def select_patch(model,data,names,side,out,cap=480):
    p=model.portrait;score=torch.zeros(len(p.role),device='cuda');sigmas=[];outside=0
    support_tri=set();edge_moments=torch.zeros(len(p.role),3,3,device='cuda');wide_score=torch.zeros_like(score)
    for name in names:
        f=model.adjusted_frame(make_frame(data,name,crop=False));s=model.head_state(f);mask=torch.as_tensor(patch_mask(data,name,side),device='cuda')
        if mask.sum()<16:continue
        c,info=weights(s,f['F'],f['K'],f['fullSize'][0],f['fullSize'][1],mask)
        score+=c/mask.sum();uv=info['means2d'];ids=info['gaussian_ids'].long();con=info['conics']
        matrix=torch.stack((con[:,0],con[:,1],con[:,1],con[:,2]),-1).reshape(-1,2,2);cov=torch.linalg.inv(matrix)
        sigma=torch.linalg.eigvalsh(cov).clamp_min(0).sqrt();sigmas.append(sigma[c[ids]>.5].cpu().numpy())
        wide_score[ids]+=c[ids]*(sigma[:,1]>3).float()
        gray=cv2.cvtColor(data['rgb'][name],cv2.COLOR_RGB2GRAY);gx=cv2.Sobel(gray,cv2.CV_32F,1,0);gy=cv2.Sobel(gray,cv2.CV_32F,0,1)
        pts=s.means.detach()@f['F'][:3,:3].T+f['F'][:3,3];sx=(pts[:,0]/pts[:,2]*f['K'][0,0]+f['K'][0,2]).round().long().clamp(0,mask.shape[1]-1);sy=(pts[:,1]/pts[:,2]*f['K'][1,1]+f['K'][1,2]).round().long().clamp(0,mask.shape[0]-1)
        gx=torch.tensor(gx,device='cuda')[sy,sx];gy=torch.tensor(gy,device='cuda')[sy,sx]
        lifted=(torch.stack([gx,gy,torch.zeros_like(gx)],1)@f['F'][:3,:3]).detach()
        lifted=torch.nn.functional.normalize(lifted,dim=-1);edge_moments+=lifted[:,:,None]*lifted[:,None,:]*(c*(gx.square()+gy.square()).sqrt())[:,None,None]
        xy=uv.round().long();h,w=mask.shape;inside=(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
        center_in=inside&mask[xy[:,1].clamp(0,h-1),xy[:,0].clamp(0,w-1)]
        outside+=int(((c[ids]>.5)&~center_in).sum())
    labels=model.component_origin[p.origin_index];eligible=(labels==0)&(p.role!=2)&(score>.00003)&(wide_score>.5)
    # One connected surface component, not an arbitrary top-k scattered set.
    tris=p.triangle_ids.cpu().numpy();eids=torch.where(eligible[:p.surface_count])[0].cpu().numpy()
    tri_score={int(t):float(score[torch.as_tensor(eids[tris[eids]==t],device='cuda')].sum()) for t in np.unique(tris[eids])}
    if not tri_score:raise ValueError('no_supported_surface_contributors')
    root=max(tri_score,key=tri_score.get);allowed=set(tri_score);seen={root};queue=[root]
    while queue:
        t=queue.pop(0)
        for neighbour in p.adjacency[t]:
            if int(neighbour) in allowed and int(neighbour) not in seen:seen.add(int(neighbour));queue.append(int(neighbour))
    selected=[i for i in eids if tris[i] in seen];selected=sorted(selected,key=lambda i:float(score[i]),reverse=True)[:cap]
    ids=torch.tensor(selected,device='cuda');np.save(out/'source-edge-moments.npy',edge_moments.detach().cpu().numpy());save_json(out/'patch-selection.json',{'side':side,'parents':len(ids),'connectedTriangles':sorted(seen),
        'stableUIDs':p.stable_uid[ids].cpu().tolist(),'outsideCenterContributorEvents':outside,'actualConicSigmaQuantiles':np.quantile(np.concatenate(sigmas),[.1,.5,.9],axis=0).tolist(),
        'rule':'full alpha*T contribution, compatible skin semantics, edge-connected triangle component; capped local budget',
        'maximumParents':cap,'roiIsNotSurface':True})
    return ids,seen,score


@torch.no_grad()
def photo_children(model,data,names,side,ids,bary):
    p=model.portrait;n=len(ids);colors=[];valids=[]
    for name in names:
        f=model.adjusted_frame(make_frame(data,name,crop=False));mesh=f['mesh']+p.surface_residual;tri=mesh[p.faces[ids]]
        xyz=(tri*bary[...,None]).sum(1);v=xyz@f['F'][:3,:3].T+f['F'][:3,3];uv=v@f['K'].T;uv=uv[:,:2]/uv[:,2:]
        x,y=uv[:,0].round().long(),uv[:,1].round().long();h,w=f['rgb'].shape[:2];ok=(v[:,2]>.05)&(x>=2)&(x<w-2)&(y>=2)&(y<h-2)
        x=x.clamp(0,w-1);y=y.clamp(0,h-1);m=f['masks'];ok &= m['face_core'][y,x]&~m['glasses_visible'][y,x]&~m['unknown_or_occluded'][y,x]
        # Geometric facing rejects the occluded side. Conditional visibility;
        # source-pixel support remains distinct from independent depth evidence.
        normal=torch.nn.functional.normalize(torch.linalg.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),dim=-1)
        camera=torch.linalg.inv(f['F'])[:3,3];ok &= ((camera-xyz)*normal).sum(1)>0
        colors.append(f['rgb'][y,x]);valids.append(ok)
    valid=torch.stack(valids);rgb=torch.stack(colors);rgb[~valid]=torch.nan
    return valid.sum(0)>=3,torch.nanmedian(rgb,dim=0).values,valid.sum(0)


@torch.no_grad()
def replace_patch(model,optimizer,selected,allowed,data,names,side,edge_moments=None):
    p=model.portrait;ensure_point_lineage(p);s=p.surface_count;n=len(p.role);dev=p.sh.device
    mesh=(p.reference_mesh+p.surface_residual).cpu().numpy();faces=p.faces.cpu().numpy()
    regions=np.full(len(faces),-1);regions[list(allowed)]=1;adj=mesh_adjacency(mesh,faces,regions)
    cov=p.local_state(p.reference_mesh).covariance()[selected].cpu().numpy();oldtri=p.triangle_ids[selected].cpu().numpy()
    oldb=p.embedding[selected].cpu().numpy();oldb/=oldb.sum(1,keepdims=True)
    childids=[];childb=[];childcov=[];blocked=0
    for index,t,b,V in zip(selected.cpu().numpy(),oldtri,oldb,cov):
        tri=mesh[faces[t]];normal=np.cross(tri[1]-tri[0],tri[2]-tri[0]);normal/=np.linalg.norm(normal)
        u=tri[1]-tri[0];u/=np.linalg.norm(u);v=np.cross(normal,u);T=np.stack([u,v],1)
        if edge_moments is not None and np.trace(edge_moments[index])>1e-10:
            _,ev=np.linalg.eigh(T.T@edge_moments[index]@T);u=T@ev[:,-1];v=np.cross(normal,u);T=np.stack([u,v],1)
        # Sample the full tangent covariance in a source-edge aligned chart.
        cc=T.T@V@T;L=np.linalg.cholesky(cc+np.eye(2)*1e-12);delta=T@L*.62
        N=np.outer(normal,normal);G=.60*(np.eye(3)-N)+N;Vnew=G@V@G.T
        for a,beta in [(-1,-1),(-1,1),(1,-1),(1,1)]:
            target=b@tri+a*delta[:,0]+beta*delta[:,1];bc=barycentric_of(target,tri)
            ti,bc,_,stops=walk_embeddings(mesh,faces,adj,np.array([t]),bc[None]);blocked+=stops
            childids.append(ti[0]);childb.append(bc[0]);childcov.append(Vnew)
    ids=torch.tensor(childids,device=dev);bary=torch.tensor(np.array(childb),device=dev,dtype=torch.float32)
    supported,color,count=photo_children(model,data,names,side,ids,bary);good=supported.reshape(-1,4).all(1)
    selected=selected[good];keepchild=good.repeat_interleave(4);ids=ids[keepchild];bary=bary[keepchild];color=color[keepchild];count=count[keepchild]
    if len(selected)<8:raise ValueError('insufficient_supported_patch_children')
    V=np.array(childcov)[keepchild.cpu().numpy()];evals,evecs=np.linalg.eigh(V);negative=np.linalg.det(evecs)<0;evecs[negative,:,0]*=-1
    q=Rotation.from_matrix(evecs).as_quat()[:,[3,0,1,2]];ls=.5*np.log(evals.clip(1e-12))
    stay=torch.ones(s,device=dev,dtype=torch.bool);stay[selected]=False;rest=torch.where(stay)[0];src=selected.repeat_interleave(4)
    mapping=torch.cat([rest,src,torch.arange(s,n,device=dev)]);sm=mapping[:len(rest)+len(src)];begin=len(rest);end=begin+len(src)
    retired=p.stable_uid[selected].clone();old_uid=p.stable_uid.clone();old_parent=p.parent_uid.clone()
    for key in ['embedding','normal_offset','sh','opacity_logits','log_scales','quats']:
        old=getattr(p,key);mp=sm if key in ('embedding','normal_offset') else mapping;values=old.detach()[mp].clone()
        if key=='embedding':values[begin:end]=bary
        if key=='log_scales':values[begin:end]=torch.tensor(ls,device=dev,dtype=values.dtype)
        if key=='quats':values[begin:end]=torch.tensor(q,device=dev,dtype=values.dtype)
        if key=='sh':
            # Real training colours initialize DC; no held-out RGB or skin fill.
            values[begin:end,0]=(color-.5)/C0;values[begin:end,1:]=0
        if key=='opacity_logits':
            tau=-torch.log1p(-values[begin:end].sigmoid().clamp_max(.999));values[begin:end]=torch.logit((-torch.expm1(-tau/1.7)).clamp(.001,.999))
        new=torch.nn.Parameter(values,requires_grad=old.requires_grad);setattr(p,key,new)
        for group in optimizer.param_groups:group['params']=[new if a is old else a for a in group['params']]
        states=optimizer.state.pop(old,{})
        for k,value in states.items():
            if isinstance(value,torch.Tensor) and value.shape==old.shape:
                states[k]=value[mp].clone();states[k][begin:end]=0
        optimizer.state[new]=states
    p.triangle_ids=torch.cat([p.triangle_ids[rest],ids]);p.initial_normal_offset=p.initial_normal_offset[sm].clone();p.initial_embedding=p.embedding.detach().clone();p.skin_band=p.skin_band[sm].clone()
    for key in ['role','source_index','origin_index','confidence','generation','metric_per_pixel','initial_log_scales']:
        setattr(p,key,getattr(p,key)[mapping].clone())
    p.generation[begin:end]+=1;p.initial_log_scales[begin:end]=p.log_scales[begin:end].detach()
    p.stable_uid=old_uid[mapping];p.parent_uid=old_parent[mapping];p.parent_uid[begin:end]=retired.repeat_interleave(4)
    p.stable_uid[begin:end]=torch.arange(int(p.next_uid),int(p.next_uid)+len(src),device=dev);p.next_uid+=len(src)
    assert not torch.isin(retired,p.stable_uid).any()
    return torch.arange(begin,end,device=dev),{'before':n,'after':len(p.role),'parentsRetired':len(selected),'children':len(src),'retiredUIDs':retired.cpu().tolist(),
        'childUIDs':p.stable_uid[begin:end].cpu().tolist(),'normalThicknessPreserved':True,'tangentFactor':.60,'boundaryStops':blocked,
        'validPhotoSupportMinimum':int(count.min()),'alphaRule':'optical-depth initialization only, not a compositing identity','mapping':mapping.cpu().tolist()}
