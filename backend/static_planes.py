"""Finite, measured-track-supported static planes, without a room backplate.

Each domain stays inside its distributed measured inliers' projected hull.
The plane is a geometric hypothesis, verified against training observations;
it is not a measured dense wall. No per-video cabinet or frame constants.
"""
import cv2
import numpy as np
from scipy.spatial import ConvexHull,QhullError,cKDTree


def fit_plane_groups(points, scale, *, min_inliers=24, max_planes=8):
    xyz=np.asarray(points,np.float64)
    remaining=np.arange(len(xyz))
    groups=[]
    rng=np.random.default_rng(82)
    tolerance=.0025*scale
    for _ in range(max_planes):
        if len(remaining)<min_inliers:
            break
        X=xyz[remaining]
        best=np.empty(0,int)
        for trial in range(320):
            v=X[rng.choice(len(X),3,replace=False)]
            normal=np.cross(v[1]-v[0],v[2]-v[0])
            length=np.linalg.norm(normal)
            if length<1e-8:
                continue
            normal/=length
            inliers=np.flatnonzero(np.abs((X-v[0])@normal)<tolerance)
            if len(inliers)>len(best):
                best=inliers
        if len(best)<min_inliers:
            break
        for repeat in range(3):
            center=X[best].mean(0)
            _,singular,V=np.linalg.svd(X[best]-center,full_matrices=False)
            if singular[1]<singular[0]*.12:
                break
            normal=V[-1]
            best=np.flatnonzero(np.abs((X-center)@normal)<tolerance)
        if len(best)<min_inliers or singular[1]<singular[0]*.12:
            break
        groups.append({"indices":remaining[best],"center":center,"normal":normal,
                       "basis":V[:2],"residualP90":float(np.quantile(np.abs((X[best]-center)@normal),.9)),
                       "tolerance":tolerance})
        remaining=np.setdiff1d(remaining,remaining[best])
    return groups


def finite_plane_support(room, views, masks, rgbs, scale, *, budget=10000, stride=10,
                         plane_groups=None, grow_observed=True):
    anchors=room["source_kind"]==0
    xyz=room["xyz"][anchors]
    ids=room["source_id"][anchors]
    groups=fit_plane_groups(xyz,scale) if plane_groups is None else plane_groups
    rows=[]
    colors=[]
    normals=[]
    parents=[]
    support=[]
    plane_ids=[]
    seen=set()
    report=[]
    names=list(views)
    safe={n:cv2.erode(masks[n].astype(np.uint8),np.ones((3,3),np.uint8))>0 for n in names}
    blurred={n:cv2.GaussianBlur(rgbs[n],(3,3),0) for n in names}
    for plane_index,group in enumerate(groups):
        ix=group["indices"]
        X=xyz[ix]
        center=group["center"]
        normal=group["normal"]
        basis=group["basis"]
        try:
            hull=ConvexHull((X-center)@basis.T)
        except QhullError:
            continue
        polygon_world=X[hull.vertices]
        accepted=0
        tested=0
        quota=max(1,budget//max(1,len(groups)))
        for name in names:
            C,K=views[name]
            cam=polygon_world@C[:3,:3].T+C[:3,3]
            if (cam[:,2]<=.01).any():
                continue
            uv=cam@K.T
            uv=uv[:,:2]/uv[:,2:]
            h,w=masks[name].shape
            region=np.zeros((h,w),np.uint8)
            cv2.fillConvexPoly(region,np.rint(uv).astype(np.int32),1)
            # Distributed plane tracks anchor depth. A bounded observed
            # low-texture component may extend beyond their sparse hull.
            # Stop at real image edges/semantics; never grow an infinite wall.
            if grow_observed:
                image=(rgbs[name]*255).clip(0,255).astype(np.uint8)
                edges=cv2.Canny(cv2.cvtColor(image,cv2.COLOR_RGB2GRAY),50,100)>0
                barrier=cv2.dilate(edges.astype(np.uint8),np.ones((3,3),np.uint8))>0
                static=safe[name]&~barrier
                _,labels=cv2.connectedComponents(static.astype(np.uint8),connectivity=4)
                seed_labels=np.unique(labels[(region>0)&static])
                seed_labels=seed_labels[seed_labels>0]
                expanded=np.isin(labels,seed_labels)
                distance=cv2.distanceTransform((region==0).astype(np.uint8),cv2.DIST_L2,3)
                expanded&=distance<=min(h,w)*.12
                region|=expanded.astype(np.uint8)
            # Only the intersection of an evidenced domain and real room
            # observations is sampled. We never fill unknown silhouettes.
            region&=safe[name].astype(np.uint8)
            yy,xx=np.mgrid[stride//2:h:stride,stride//2:w:stride]
            pixels=np.stack((xx.ravel(),yy.ravel()),1)
            pixels=pixels[region[pixels[:,1],pixels[:,0]]>0]
            if not len(pixels):
                continue
            invR=C[:3,:3].T
            origin=-invR@C[:3,3]
            rays=np.column_stack((pixels,np.ones(len(pixels))))@np.linalg.inv(K).T@invR.T
            denom=rays@normal
            numerator=(center-origin)@normal
            z=np.divide(numerator,denom,out=np.full(len(denom),np.nan),where=np.abs(denom)>1e-8)
            points=origin+rays*z[:,None]
            valid=np.isfinite(points).all(1)&(z>.01)
            points=points[valid]
            pixels=pixels[valid]
            if not len(points):
                continue
            tested+=len(points)
            source=blurred[name][pixels[:,1],pixels[:,0]]
            votes=np.zeros(len(points),np.int16)
            conflicts=np.zeros(len(points),np.int16)
            sum_color=np.zeros_like(source)
            for other in names:
                O,OK=views[other]
                pc=points@O[:3,:3].T+O[:3,3]
                projected=pc@OK.T
                u,v=np.rint(projected[:,:2]/np.maximum(projected[:,2:],1e-8)).astype(int).T
                mh,mw=masks[other].shape
                inside=(pc[:,2]>.01)&(u>=2)&(v>=2)&(u<mw-2)&(v<mh-2)
                iu=u.clip(0,mw-1)
                iv=v.clip(0,mh-1)
                inside&=safe[other][iv,iu]
                color=blurred[other][iv,iu]
                agree=np.abs(color-source).mean(1)<.10
                votes+=inside&agree
                conflicts+=inside&~agree
                sum_color+=color*(inside&agree)[:,None]
            valid=np.flatnonzero((votes>=3)&(conflicts<=1))
            nearest=cKDTree(X).query(points[valid],k=3)[1] if len(valid) else []
            for j,local_parents in zip(valid,nearest):
                # Plane-local spatial cell identity is independent of view.
                coord=(points[j]-center)@basis.T
                identity=(plane_index,*np.rint(coord/(.003*scale)).astype(np.int64))
                if identity in seen:
                    continue
                seen.add(identity)
                rows.append(points[j])
                colors.append(sum_color[j]/votes[j])
                normals.append(normal)
                parents.append(ids[ix[np.asarray(local_parents)]])
                support.append(votes[j])
                plane_ids.append(plane_index)
                accepted+=1
                if len(rows)>=budget or accepted>=quota:
                    break
            if len(rows)>=budget or accepted>=quota:
                break
        report.append({"plane":plane_index,"inlierTracks":len(ix),"residualP90":group["residualP90"],
                       "tolerance":group["tolerance"],"tested":tested,"accepted":accepted,
                       "domain":"distributed_plane_tracks_plus_bounded_observed_edge_components" if grow_observed else "measured_plane_inlier_hull_only",
                       "independentDenseTruth":False})
        if len(rows)>=budget:
            break
    if not rows:
        return None,{"planes":report,"status":"no_supported_finite_plane_samples"}
    return {"xyz":np.asarray(rows,np.float32),"rgb":np.asarray(colors,np.float32),
        "surface_normal":np.asarray(normals,np.float32),"triangle_sources":np.asarray(parents,np.int64),
        "plane_id":np.asarray(plane_ids,np.int16),"support":np.asarray(support,np.int16),
        "source_kind":np.full(len(rows),7,np.uint8),
        "source_id":np.arange(len(rows),dtype=np.int64)+int(room["source_id"].max())+1,
        "sample_bary":np.full((len(rows),3),np.nan)}, {"planes":report,"total":len(rows),
        "status":"finite_plane_hypotheses_need_appearance_and_occlusion_validation"}
