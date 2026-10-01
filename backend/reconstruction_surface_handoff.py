"""Motion-consistent observations and finite evidence-backed room surfaces.
Research-only, standard 3DGS output. Predicted depth is support, not truth.
"""
import hashlib
import numpy as np
import cv2
from scipy.spatial.transform import Rotation
from reconstruction_dense_contract import rigid_check, project, unproject, bilinear
from reconstruction_dense_surfaces import native_uv
from reconstruction_ray_surface import sample_mask


def observation_layers(name,body_names,motions,verified):
    """Unverified photometric B never authorizes clothing depth supervision."""
    if verified and motions is None:raise ValueError('verified_motion_missing')
    return ['room']+(['cloth'] if verified and name in body_names and name in motions else [])

def move_observation_points(points, source, target, motions):
    """World at source -> canonical body -> world at target; missing is unknown."""
    if source not in motions or target not in motions:
        raise ValueError('missing_observed_body_motion')
    a=rigid_check(motions[source]);b=rigid_check(motions[target])
    if source==target:return np.asarray(points).copy()
    T=b@np.linalg.inv(a)
    return np.asarray(points)@T[:3,:3].T+T[:3,3]


def finite_plane(points, depths, *, minimum=80, tolerance=.008):
    """Robust finite-domain plane proposal, never extension beyond observations."""
    points=np.asarray(points,float);depths=np.asarray(depths,float)
    if len(points)<minimum:return None
    active=np.isfinite(points).all(1)&np.isfinite(depths)&(depths>0)
    for _ in range(4):
        if active.sum()<minimum:return None
        p=points[active];centre=np.median(p,0)
        _,singular,V=np.linalg.svd(p-centre,full_matrices=False);normal=V[-1]
        distance=np.abs((points-centre)@normal)
        active &= distance<=tolerance*depths
    if active.mean()<.85 or singular[1]/max(singular[0],1e-12)<.08:return None
    return centre,normal,active


def plane_rays(uv,K,C,centre,normal):
    """Exact ray-plane intersections; zero-based pixels and original camera z."""
    T=rigid_check(C);origin=-T[:3,:3].T@T[:3,3]
    rays=np.c_[uv,np.ones(len(uv))]@np.linalg.inv(K).T@T[:3,:3]
    denominator=rays@normal
    z=((centre-origin)@normal)/np.where(abs(denominator)>1e-8,denominator,np.nan)
    xyz=origin+rays*z[:,None]
    return xyz,z


def plane_samples(uv,K,C,centre,normal,stride=2):
    xyz,z=plane_rays(uv,K,C,centre,normal)
    xp,_=plane_rays(uv+[stride,0],K,C,centre,normal)
    yp,_=plane_rays(uv+[0,stride],K,C,centre,normal)
    a=xp-xyz;b=yp-xyz;la=np.linalg.norm(a,axis=1)
    ax=a/np.maximum(la[:,None],1e-12);n=np.broadcast_to(normal,(len(uv),3)).copy()
    by=np.cross(n,ax);by/=np.maximum(np.linalg.norm(by,axis=1)[:,None],1e-12)
    # Tangential coverage follows actual lattice, normal thickness stays local.
    lb=abs(np.einsum('ni,ni->n',b,by))
    basis=np.stack((ax,by,n),-1)
    scales=np.c_[la*.70,lb*.70,np.minimum(la,lb)*.12]
    good=np.isfinite(xyz).all(1)&(z>0)&np.isfinite(scales).all(1)&(scales.min(1)>1e-7)
    return xyz,basis,scales,good


def coherent_regions(depth,K,C,valid,*,stride=4,angle_degrees=18):
    """Connected geometry samples; no screen colour clusters mistaken for depth."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    h,w=depth.shape;y,x=np.mgrid[1:h-1:stride,1:w-1:stride]
    uv=np.c_[x.ravel(),y.ravel()].astype(float);z=depth[y,x].ravel()
    p=unproject(uv,z,K,C)
    xp=unproject(uv+[1,0],depth[y,x+1].ravel(),K,C)
    yp=unproject(uv+[0,1],depth[y+1,x].ravel(),K,C)
    n=np.cross(xp-p,yp-p);length=np.linalg.norm(n,axis=1)
    good=valid[y,x].ravel()&np.isfinite(p).all(1)&(z>0)&(length>1e-10)
    n/=np.maximum(length[:,None],1e-12);grid=np.arange(len(p)).reshape(y.shape)
    pairs=np.r_[np.c_[grid[:,:-1].ravel(),grid[:,1:].ravel()],np.c_[grid[:-1].ravel(),grid[1:].ravel()]]
    i,j=pairs.T
    same=good[i]&good[j]&(abs(z[i]-z[j])<.04*np.minimum(z[i],z[j]))
    same &= abs(np.einsum('ni,ni->n',n[i],n[j]))>np.cos(np.deg2rad(angle_degrees))
    i,j=i[same],j[same];g=coo_matrix((np.ones(len(i)*2),(np.r_[i,j],np.r_[j,i])),shape=(len(p),len(p)))
    count,label=connected_components(g,directed=False)
    return uv,p,z,good,label,grid.shape


def build_room_planes(data,masks,priors,depth_folder,train_names,out,*,budget=14000,max_regions=8):
    """Train-only observed finite planes; retain unsupported original content."""
    from pathlib import Path
    import json
    from reconstruction_dense_contract import digest,write_json
    folder=Path(depth_folder);manifest=json.loads((folder/'manifest.json').read_text())
    rows=[r for r in manifest['observations'] if r['group']=='world' and r['scaleGatePassed'] and r['imageName'] in train_names]
    cache={r['file']:dict(np.load(folder/r['file'])) for r in rows}
    proposals=[];records=[]
    for row in rows:
        name=row['imageName'];a=cache[row['file']]
        if row['role']!='train' or name in manifest['forbidden']:raise ValueError('plane_role_leak')
        h,w=a['depth'].shape;yy,xx=np.mgrid[:h,:w];uv=np.c_[xx.ravel(),yy.ravel()].astype(float)
        nv=native_uv(uv,a['nativeToProcessed'])
        valid=sample_mask(priors[name]['room'][1],nv).reshape(h,w)
        # RGB edge guards real boundaries; low texture is retained, not discarded.
        rgb=bilinear(data['rgb'][name],nv).reshape(h,w,3)
        gray=np.nan_to_num(rgb).mean(-1)
        edge=np.hypot(cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3),cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3))
        valid &= cv2.dilate((edge>.20).astype(np.uint8),np.ones((3,3),np.uint8))==0
        uv4,p,z,good,labels,shape=coherent_regions(a['depth'],a['K'],a['W2C'],valid)
        sizes=np.bincount(labels[good],minlength=len(labels))
        for label in np.argsort(sizes)[::-1][:max_regions]:
            ids=np.flatnonzero(good&(labels==label));fit=finite_plane(p[ids],z[ids])
            if fit is None:continue
            centre,normal,inliers=fit;ids=ids[inliers]
            # Domain is a union of local observed cells, not a convex hull across holes.
            domain=np.zeros((h,w),np.uint8)
            for point in uv4[ids].astype(int):
                x,y=point;domain[max(0,y-2):min(h,y+3),max(0,x-2):min(w,x+3)]=1
            domain &= valid.astype(np.uint8)
            y2,x2=np.mgrid[1:h-1:2,1:w-1:2];u=np.c_[x2.ravel(),y2.ravel()].astype(float)
            chosen=domain[y2,x2].ravel()>0;u=u[chosen]
            xyz,basis,scales,ok=plane_samples(u,a['K'],a['W2C'],centre,normal)
            observed=bilinear(a['depth'],u)
            ok &= abs(project(xyz,a['K'],a['W2C'])[1]-observed)<=.015*observed
            support=np.zeros(len(u),np.int16);free=np.zeros(len(u),np.int16);seen=set()
            for t in rows:
                tn=t['imageName']
                if t['window']!=row['window'] or tn in seen:continue
                seen.add(tn);b=cache[t['file']];q,d=project(xyz,b['K'],b['W2C'])
                measured=bilinear(b['depth'],q)
                v=(d>0)&np.isfinite(measured)&(measured>0)&sample_mask(priors[tn]['room'][1],native_uv(q,b['nativeToProcessed']))
                support+=(v&(abs(d-measured)<=.03*measured)).astype(np.int16)
                free+=(v&(d<measured-.03*measured)).astype(np.int16)
            ok &= (support>=3)&(free<=1)
            u=u[ok];xyz=xyz[ok];basis=basis[ok];scales=scales[ok]
            if len(u)<100:continue
            colour=bilinear(data['rgb'][name],native_uv(u,a['nativeToProcessed']))
            if not np.isfinite(colour).all():raise ValueError('plane_invalid_colour')
            namespace=f'room-plane:{data["sourceHash"]}:{row["window"]}:{name}:{int(label)}'
            uid=np.array([int.from_bytes(hashlib.sha256((namespace+':'+str(v.tolist())).encode()).digest()[:8],'little')&((1<<63)-1) for v in u],np.int64)
            sh=np.zeros((len(u),4,3),np.float32);sh[:,0]=(colour-.5)/.28209479177387814
            proposal=dict(means=xyz,quats=Rotation.from_matrix(basis).as_quat()[:,[3,0,1,2]],scales=scales,
                opacity=np.full(len(u),.6),sh=sh,parts=np.zeros(len(u),np.int64),uid=uid,support=support[ok],
                confidence=bilinear(a['confidence'],u),source_image=np.full(len(u),name),source_uv=native_uv(u,a['nativeToProcessed']),
                normal=basis[:,:,2],plane=np.full(len(u),len(records),np.int64))
            proposals.append(proposal);records.append(dict(name=name,window=row['window'],points=len(u),sourceSamples=len(ids),
                centre=centre.tolist(),normal=normal.tolist(),p90RelativeResidual=float(np.quantile(abs((p[ids]-centre)@normal)/z[ids],.9)),
                depthHash=digest(folder/row['file']),independentGeometryTruth=False))
    if not proposals:raise ValueError('no_multiview_finite_room_surface')
    a={k:np.concatenate([p[k] for p in proposals]) for k in proposals[0]}
    # Keep spatial/normal layers distinct. No RGB-selected favourable view.
    step=float(np.median(a['scales'][:,:2]))
    key=np.c_[np.floor(a['means']/step).astype(np.int64),np.rint(a['normal']*4).astype(np.int64)]
    order=np.lexsort((a['uid'],-a['confidence'],-a['support']));_,which=np.unique(key[order],axis=0,return_index=True);ids=order[which]
    # Only cache the full finite domain; local replacement decides a bounded subset.
    out=Path(out);out.mkdir(exist_ok=False)
    a={k:v[ids] for k,v in a.items()};np.savez_compressed(out/'surface-pool.npz',**a,source_hash=np.array(data['sourceHash']))
    write_json(out/'planes.json',dict(records=records,count=len(ids),budget=budget,geometryMeaning='multiview-supported predicted finite surfaces; not independent truth',published=False))
    return a,records


def select_room_transaction(state,pool,*,max_parents=12,budget=14000,projection_evidence=None,contribution=None):
    """Wide-kernel proposal with real finite surface support, not deletion by colour."""
    from scipy.spatial import cKDTree
    means=state.means.detach().cpu().numpy();scales=state.scales.detach().cpu().numpy()
    quats=state.quats.detach().cpu().numpy();parts=state.parts.detach().cpu().numpy()
    tree=cKDTree(pool['means']);distance,nearest=tree.query(means,k=1)
    local=pool['scales'][nearest,:2].max(1)
    candidates=np.flatnonzero((parts==0)&(scales.max(1)>8*local)&(distance<2*scales.max(1)))
    if contribution is not None:
        if len(contribution)!=len(means) or projection_evidence is None:raise ValueError('incomplete_projection_evidence')
        names=[str(e['imageName']) for e in projection_evidence]
        if len(set(names))!=len(names):raise ValueError('duplicate_projection_observation')
        candidates=np.flatnonzero((parts==0)&(contribution>.001))
        candidates=candidates[np.argsort(-contribution[candidates])]
    else:candidates=candidates[np.argsort(-scales[candidates].max(1))]
    chosen=[];covered=np.zeros(len(pool['means']),bool);records=[]
    for parent in candidates:
        R=Rotation.from_quat(quats[parent,[1,2,3,0]]).as_matrix()
        v=(pool['means']-means[parent])@R
        power=(v/np.maximum(scales[parent],1e-8)).__pow__(2).sum(1)
        if projection_evidence is None:affected=power<9
        else:
            votes=np.zeros(len(pool['means']),np.int16)
            for e in projection_evidence:
                loc=np.flatnonzero(e['gaussian_ids']==parent)
                if len(loc)!=1:continue
                xy,z=project(pool['means'],e['K'],e['C']);delta=xy-e['means2d'][loc[0]]
                a,b,c=e['conics'][loc[0]];power2=a*delta[:,0]**2+2*b*delta[:,0]*delta[:,1]+c*delta[:,1]**2
                votes+=((z>0)&(power2<9)&sample_mask(e['room'],xy)).astype(np.int16)
            affected=votes>=2
        if affected.sum()<150:continue
        # Keep a finite, bounded local transaction. No quota-driven global cleanup.
        merged=covered|affected
        if merged.sum()>budget:continue
        chosen.append(int(parent));covered=merged
        records.append(dict(parent=int(parent),supportedSamples=int(affected.sum()),initialAxes=scales[parent].tolist(),
            nearestSurfaceDistance=float(distance[parent]),proposalOnly=True,selectionMeaning='actual common alpha*T plus finite projected background support' if projection_evidence is not None else '3D covariance proximity'))
        if len(chosen)>=max_parents:break
    ids=np.flatnonzero(covered)
    if not chosen or not len(ids):raise ValueError('no_bounded_supported_room_replacement')
    selected={k:v[ids] for k,v in pool.items() if np.ndim(v)>0 and len(v)==len(pool['means'])}
    return np.array(chosen,np.int64),selected,records
