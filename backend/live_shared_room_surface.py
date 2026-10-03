"""Bounded CPU shared-room surface correction; camera/colour/point count untouched.

A low-dimensional inverse-depth residual defines ONE reference surface in world
coordinates. All original static track observations constrain that same surface.
Conditional depth is a soft prior, not a hard background-existence mask.
"""
import hashlib
import json
import shutil
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix

from live_dense import read_prepared, resolve_path, mask_at, native_uv, physical_masks,training_name_scopes,static_track_names
from live_dense_contract import bilinear, project, unproject, digest, write_json
from observation_domains import attach_observation_domains


class SharedRoomEvidenceUnavailable(ValueError):
    """Only explicitly inadequate geometric evidence may retain the input bundle."""


def basis_weights(uv,width,height,cols,rows):
    q=np.asarray(uv,float)*[(cols-1)/(width-1),(rows-1)/(height-1)]
    q=np.clip(q,[0,0],[cols-1-1e-9,rows-1-1e-9]);ij=np.floor(q).astype(int);f=q-ij
    a=ij[:,1]*cols+ij[:,0]
    ids=np.c_[a,a+1,a+cols,a+cols+1]
    w=np.c_[(1-f[:,0])*(1-f[:,1]),f[:,0]*(1-f[:,1]),(1-f[:,0])*f[:,1],f[:,0]*f[:,1]]
    return ids,w


def shared_points(values,uv,initial_depth,K,C,shape,size):
    ids,w=basis_weights(uv,*size,*shape);delta=(values[ids]*w).sum(1)
    return unproject(uv,initial_depth*np.exp(-delta),K,C)


def point_fold(pid):
    return int(hashlib.sha256(str(pid).encode()).hexdigest()[:8],16)%5


def distinct_image_observations(observations,*,same_pixel_tolerance=1e-6):
    """One physical track has one vote per image; conflicting pixels are unknown."""
    by_name={}
    for observation in observations:by_name.setdefault(observation['imageName'],[]).append(observation)
    kept=[];ambiguous=[];duplicates=0
    for name,items in by_name.items():
        uv=np.asarray([o['uv'] for o in items],float)
        if len(items)>1 and np.max(np.linalg.norm(uv-uv[0],axis=1))>same_pixel_tolerance:
            ambiguous.append(name);continue
        kept.append(items[0]);duplicates+=len(items)-1
    return kept,dict(duplicateSamePixelObservations=duplicates,ambiguousImageNames=ambiguous)


def independent_track_observations(rec,point,names,K,safe_masks):
    observations=[]
    for element in point.track.elements:
        im=rec.images[element.image_id]
        if im.name not in names:continue
        ray=rec.cameras[im.camera_id].cam_from_img(im.points2D[element.point2D_idx].xy)
        q=K@np.r_[ray,1.];uv=q[:2]/q[2]
        if not mask_at(safe_masks[im.name],uv[None])[0]:continue
        observations.append(dict(imageName=im.name,uv=uv.tolist()))
    return distinct_image_observations(observations)


def stats(a):
    a=np.asarray(a,float)
    return dict(count=len(a),median=float(np.median(a)) if len(a) else None,p90=float(np.quantile(a,.9)) if len(a) else None)


def replacement_budget_indices(retained_count,fresh,budget):
    """Protect every out-of-scope original point; budget only the new surface."""
    from live_dense import select_budget
    if retained_count>budget:raise ValueError('shared_surface_budget_cannot_preserve_original_content')
    capacity=budget-retained_count
    new_indices=select_budget(fresh,capacity) if capacity and len(fresh['means']) else np.empty(0,dtype=np.int64)
    return np.r_[np.arange(retained_count,dtype=np.int64),retained_count+new_indices]


def run_shared_surface(prepared,dense,output,*,window=None,reference=None,max_evaluations=40,proposed_window_receipt=None):
    import pycolmap
    start=time.perf_counter();data=read_prepared(prepared);dense=Path(dense);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((dense/'depth-manifest.json').read_text());reference=reference or manifest['reference']
    selected=json.loads((dense/'result.json').read_text())['acceptedWindows']
    possible=[w for group,w in selected if group=='world' and any(r['group']=='world' and r['window']==w and r['imageName']==reference for r in manifest['observations'])]
    recovery=None
    if proposed_window_receipt is not None:
        from live_room_window_recovery import verify_window_proposal
        recovery=verify_window_proposal(proposed_window_receipt,data,dense,reference,window)
    if not possible and recovery is None:raise SharedRoomEvidenceUnavailable('shared_surface_no_accepted_reference_world_window')
    if window is None:window=min(possible)
    if window not in possible and recovery is None:raise ValueError('shared_surface_window_not_accepted')
    rows=[r for r in manifest['observations'] if r['group']=='world' and r['window']==window]
    if reference not in [r['imageName'] for r in rows]:raise SharedRoomEvidenceUnavailable('shared_surface_reference_missing')
    views={r['imageName']:dict(np.load(dense/r['file'],allow_pickle=False)) for r in rows};ref=views[reference]
    names=list(views);request=json.loads((dense/'request.json').read_text())
    if request.get('splitPath') and not request.get('splitHash'):raise ValueError('dense_split_lock_missing')
    scope=training_name_scopes(data,request.get('splitPath'),expected_split_hash=request.get('splitHash'))
    measured_names=[n for n in scope['geometryTrain'] if n in data['world']]
    labels={n:dict(np.load(data['prepared']/'rectified_observations'/(n+'.npz'),allow_pickle=False)) for n in measured_names}
    domains=dict(labels=labels,K=data['K'],staticMap=str(resolve_path(data['metadata']['staticMap'],data['prepared'])))
    attach_observation_domains(domains,data['prepared']);masks={n:physical_masks(domains['labels'][n])['room'] for n in measured_names}
    safe_masks={n:cv2.erode(mask.astype(np.uint8),np.ones((7,7),np.uint8)).astype(bool) for n,mask in masks.items()}
    rgb={n:cv2.imread(str(data['prepared']/'rectified_observations'/n)).astype(np.float32)/255 for n in names}
    rec=pycolmap.Reconstruction(domains['staticMap']);lookup={im.name:im for im in rec.images.values()}
    track_names=set(static_track_names(measured_names,lookup,data['world']))
    if reference not in track_names:
        raise SharedRoomEvidenceUnavailable('shared_surface_reference_has_no_independent_map_tracks')
    h,w=ref['depth'].shape;cols,gridrows=12,20;parameters=cols*gridrows
    # Actual tracked source pixels, not projected template or DA3 correspondences.
    tracks=[];seen_point_ids=set();identity_audit=[];duplicate_source_ids=[]
    for sourcept in lookup[reference].points2D:
        if not sourcept.has_point3D():continue
        pid=int(sourcept.point3D_id);p=rec.points3D[pid]
        if pid in seen_point_ids:duplicate_source_ids.append(pid);continue
        seen_point_ids.add(pid)
        if p.error>2 or p.track.length()<3:continue
        observations,audit=independent_track_observations(rec,p,track_names,data['K'],safe_masks)
        if audit['duplicateSamePixelObservations'] or audit['ambiguousImageNames']:identity_audit.append(dict(pointId=pid,**audit))
        if len(observations)<3 or reference not in [o['imageName'] for o in observations]:continue
        source=np.array(next(o['uv'] for o in observations if o['imageName']==reference))
        processed=(ref['nativeToProcessed']@np.r_[source,1.])[:2]
        initial=float(bilinear(ref['depth'],processed[None])[0]);truez=float(project(p.xyz[None],data['K'],data['world'][reference])[1][0])
        if not np.isfinite(initial) or min(initial,truez)<=0:continue
        tracks.append(dict(pointId=pid,referenceNativeUV=source.tolist(),referenceProcessedUV=processed.tolist(),
            initialDepth=initial,staticAnchorDepth=truez,observations=observations,role='validation' if point_fold(pid)==0 else 'fit'))
    if len([t for t in tracks if t['role']=='fit'])<20 or len([t for t in tracks if t['role']=='validation'])<12:
        write_json(out/'input-failure.json',dict(reason='shared_surface_insufficient_independent_tracks',tracks=tracks,solverInvoked=False,
            trackIdentityAudit=identity_audit,duplicateSourcePointIds=duplicate_source_ids))
        raise SharedRoomEvidenceUnavailable('shared_surface_insufficient_independent_tracks')
    train=[t for t in tracks if t['role']=='fit'];train_uv=np.array([t['referenceProcessedUV'] for t in train]);train_z=np.array([t['initialDepth'] for t in train])
    train_ids,train_w=basis_weights(train_uv,w,h,cols,gridrows)
    track_rows=[]
    for i,t in enumerate(train):
        for o in t['observations']:
            if o['imageName']!=reference:track_rows.append((i,o['imageName'],np.array(o['uv'])))
    # Full observed room grid: weak texture stays in the domain. Unknown and
    # moving foreground do not become evidence merely because depth exists.
    yy,xx=np.mgrid[4:h-4:12,4:w-4:12];uv=np.c_[xx.ravel(),yy.ravel()].astype(float)
    source_ok=mask_at(masks[reference],native_uv(uv,ref['nativeToProcessed']))
    uv=uv[source_ok];z=bilinear(ref['depth'],uv);ok=np.isfinite(z)&(z>0);uv=uv[ok];z=z[ok]
    ids,weights=basis_weights(uv,w,h,cols,gridrows);x0=unproject(uv,z,ref['K'],ref['W2C'])
    prior_records=[]
    for n,a in views.items():
        if n==reference:continue
        q,depth=project(x0,a['K'],a['W2C']);target=bilinear(a['depth'],q)
        plausible=(depth>0)&np.isfinite(target)&(target>0)&mask_at(masks[n],native_uv(q,a['nativeToProcessed']))
        plausible&=(depth<=target*1.2)&(depth>=target*.8)
        good=np.flatnonzero(plausible)
        if len(good):prior_records.append((n,good))
    # Smooth the bounded residual, not a fabricated global plane. Native image
    # edges stop propagation; no single SIFT seed is expanded into a wall.
    gray=cv2.cvtColor(rgb[reference],cv2.COLOR_BGR2GRAY);edges=cv2.Canny((gray*255).astype(np.uint8),40,100)
    links=[]
    for y in range(gridrows):
        for x in range(cols):
            for nx,ny in ((x+1,y),(x,y+1)):
                if nx>=cols or ny>=gridrows:continue
                a=np.array([x/(cols-1)*(w-1),y/(gridrows-1)*(h-1)]);b=np.array([nx/(cols-1)*(w-1),ny/(gridrows-1)*(h-1)])
                strip=np.linspace(a,b,12);native=native_uv(strip,ref['nativeToProcessed'])
                if not mask_at(masks[reference],native).all():continue
                crossed=bilinear(edges.astype(float),native)
                weight=.1 if np.nanmax(crossed)>64 else 1.
                links.append((y*cols+x,ny*cols+nx,weight))
    def evaluate(values):
        tz=train_z*np.exp(-(values[train_ids]*train_w).sum(1));X=unproject(train_uv,tz,ref['K'],ref['W2C'])
        track=[]
        for i,n,target in track_rows:
            q,_=project(X[i:i+1],data['K'],data['world'][n]);track.extend((q[0]-target)/(1.0*np.sqrt(len(track_rows))))
        # Shared reference surface points are projected into every target;
        # there is no independent per-view shape or image warp variable.
        sz=z*np.exp(-(values[ids]*weights).sum(1));S=unproject(uv,sz,ref['K'],ref['W2C']);soft=[]
        total=max(1,sum(len(indices) for n,indices in prior_records))
        for n,indices in prior_records:
            a=views[n];q,zz=project(S[indices],a['K'],a['W2C']);observed=bilinear(a['depth'],q)
            valid=np.isfinite(observed)&(observed>0)&(zz>0)&mask_at(masks[n],native_uv(q,a['nativeToProcessed']))
            residual=np.zeros(len(indices));residual[valid]=np.log(zz[valid]/observed[valid])/.12
            soft.extend(.15*residual/np.sqrt(total))
        smooth=[.15*weight*(values[a]-values[b])/.04/np.sqrt(max(1,len(links))) for a,b,weight in links]
        return np.r_[track,soft,.03*values/.1/np.sqrt(parameters),smooth]
    length=len(evaluate(np.zeros(parameters)));sparsity=lil_matrix((length,parameters),dtype=np.int8);offset=0
    for i,n,target in track_rows:
        sparsity[offset:offset+2,train_ids[i]]=1;offset+=2
    for n,indices in prior_records:
        for i in indices:sparsity[offset,ids[i]]=1;offset+=1
    for i in range(parameters):sparsity[offset,i]=1;offset+=1
    for a,b,weight in links:sparsity[offset,[a,b]]=1;offset+=1
    fit=least_squares(evaluate,np.zeros(parameters),jac_sparsity=sparsity.tocsr(),bounds=(-.15,.15),
        max_nfev=max_evaluations,loss='soft_l1',f_scale=.1,ftol=1e-6,xtol=1e-6,gtol=1e-6)
    def measure(values,role):
        rr=[];depth=[]
        for t in tracks:
            if t['role']!=role:continue
            q=np.array(t['referenceProcessedUV'])[None];X=shared_points(values,q,np.array([t['initialDepth']]),ref['K'],ref['W2C'],(cols,gridrows),(w,h))
            depth.append(abs(project(X,ref['K'],ref['W2C'])[1][0]/t['staticAnchorDepth']-1))
            for o in t['observations']:
                if o['imageName']==reference:continue
                p,_=project(X,data['K'],data['world'][o['imageName']]);rr.append(np.linalg.norm(p[0]-o['uv']))
        return dict(reprojectionPx=stats(rr),relativeDepth=stats(depth))
    before={r:measure(np.zeros(parameters),r) for r in ('fit','validation')};after={r:measure(fit.x,r) for r in ('fit','validation')}
    all_y,all_x=np.mgrid[:h,:w];pixels=np.c_[all_x.ravel(),all_y.ravel()];bid,bw=basis_weights(pixels,w,h,cols,gridrows)
    delta=(fit.x[bid]*bw).sum(1).reshape(h,w);corrected=ref['depth']*np.exp(-delta)
    np.savez_compressed(out/'shared-surface.npz',referenceDepthBefore=ref['depth'],referenceDepthAfter=corrected,delta=delta,
        controls=fit.x,K=ref['K'],W2C=ref['W2C'],nativeToProcessed=ref['nativeToProcessed'],sourceHash=manifest['sourceHash'])
    # Pixel support is unchanged. Geometry uncertainty is recorded, not used to
    # delete low-texture RGB or declare a complete model.
    mask=mask_at(masks[reference],native_uv(pixels,ref['nativeToProcessed'])).reshape(h,w)
    colour=cv2.applyColorMap(np.uint8(np.clip((delta+.15)/.3*255,0,255)),cv2.COLORMAP_TURBO);colour[~mask]=0
    cv2.imwrite(str(out/'bounded-inverse-depth-delta.png'),colour)
    accepted=bool(after['validation']['relativeDepth']['median']<=.03 and after['validation']['relativeDepth']['p90']<=.08
        and after['validation']['reprojectionPx']['p90']<=before['validation']['reprojectionPx']['p90'])
    report=dict(sourceHash=manifest['sourceHash'],reference=reference,window=window,config=dict(grid=[cols,gridrows],maxEvaluations=max_evaluations,
        logInverseDepthBound=.15,depthSoftPriorSigma=.12,depthSoftPriorWeight=.15,KChanged=False,CChanged=False,oneSharedSurface=True),
        before=before,after=after,accepted=accepted,nfev=fit.nfev,cost=float(fit.cost),success=bool(fit.success),solverStatus=fit.message,
        seconds=time.perf_counter()-start,tracks=tracks,trackIdentityAudit=identity_audit,duplicateSourcePointIds=duplicate_source_ids,
        shapeIdentity='one reference-coordinate surface projected into all target cameras',
        evidenceBoundary='Track geometry constrains low-frequency corrections; unanchored weak-texture detail remains a conditional hypothesis.',
        photometricTraining=False,GPU=False,depthIsTruth=False,sourceCodeHash=digest(__file__))
    if recovery is not None:report['windowRecoveryProposal']=recovery
    write_json(out/'report.json',report);print(json.dumps({k:v for k,v in report.items() if k!='tracks'},indent=2));return report


def export_shared_room_initialization(solved,parent_bundle,output,budget=30000,*,completion_reference=None,existing_additions=(),candidate_filter=None):
    """Typed conditional surface transaction; no fake three-depth-vote labels."""
    from scipy.spatial import cKDTree
    from scipy.spatial.transform import Rotation
    from live_dense import surface_samples,support_samples,select_budget,C0
    solved=Path(solved);parent_path=Path(parent_bundle).resolve();parent=json.loads(parent_path.read_text())
    for component in parent['components'].values():
        for key in ('path','surfaceCorrectionReceipt'):
            if component.get(key) and not Path(component[key]).is_absolute():
                component[key]=str((parent_path.parent/component[key]).resolve())
    if not Path(parent['depthManifestPath']).is_absolute():
        parent['depthManifestPath']=str((parent_path.parent/parent['depthManifestPath']).resolve())
    report=json.loads((solved/'report.json').read_text());surface=dict(np.load(solved/'shared-surface.npz',allow_pickle=False))
    root=Path(parent['depthManifestPath']).parent;request=json.loads((root/'request.json').read_text());data=read_prepared(request['prepared'])
    if report['sourceHash']!=parent['sourceSha256'] or str(surface['sourceHash'])!=parent['sourceSha256']:raise ValueError('shared_surface_source_changed')
    reference=report['reference'];np.testing.assert_allclose(surface['W2C'],data['world'][reference],atol=1e-7,rtol=0)
    np.testing.assert_allclose(surface['K'],surface['nativeToProcessed']@data['K'],atol=1e-6,rtol=0)
    validation=report['after']['validation'];before=report['before']['validation']
    fit_ids=[t['pointId'] for t in report['tracks'] if t['role']=='fit'];held_ids=[t['pointId'] for t in report['tracks'] if t['role']=='validation']
    qualified=bool(report['accepted'] and report['config']['oneSharedSurface'] and not report['config']['KChanged'] and not report['config']['CChanged']
        and len(fit_ids)>=20 and len(held_ids)>=12 and not(set(fit_ids)&set(held_ids))
        and validation['relativeDepth']['median']<=.03 and validation['relativeDepth']['p90']<=.08
        and validation['reprojectionPx']['p90']<=before['reprojectionPx']['p90'])
    if not qualified:raise ValueError('shared_surface_validation_not_qualified')
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    if request.get('splitPath') and not request.get('splitHash'):raise ValueError('dense_split_lock_missing')
    scope=training_name_scopes(data,request.get('splitPath'),expected_split_hash=request.get('splitHash'))
    names=[n for n in scope['geometryTrain'] if n in data['world']]
    labels={n:dict(np.load(data['prepared']/'rectified_observations'/(n+'.npz'),allow_pickle=False)) for n in names}
    domains=dict(labels=labels,K=data['K'],staticMap=str(resolve_path(data['metadata']['staticMap'],data['prepared'])))
    attach_observation_domains(domains,data['prepared']);masks={n:physical_masks(domains['labels'][n])['room'] for n in names}
    uv,xyz,basis,scales,good=surface_samples(surface['referenceDepthAfter'],surface['K'],surface['W2C'])
    native=native_uv(uv,surface['nativeToProcessed']);good&=mask_at(masks[reference],native)
    # An auxiliary surface may fill any actually observed room region, not
    # just pixels hidden by the person in one display reference. The source
    # room mask, independent track validation, multiview filters and final
    # compatible-surface deduplication still apply to every new sample.
    source_rgb=cv2.cvtColor(cv2.imread(str(data['prepared']/'rectified_observations'/reference)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
    colours=bilinear(source_rgb,native);good&=np.isfinite(colours).all(1)
    indices=np.flatnonzero(good);xyz=xyz[indices];uv=uv[indices];native=native[indices];scales=scales[indices];basis=basis[indices];colours=colours[indices]
    if not len(indices):raise SharedRoomEvidenceUnavailable('shared_surface_no_observed_room_candidates')
    depth_manifest=json.loads((root/'depth-manifest.json').read_text())
    targets=[(r,dict(np.load(root/r['file'],allow_pickle=False))) for r in depth_manifest['observations'] if r['group']=='world' and r['window']==report['window']]
    depth_votes,free,occluded=support_samples(xyz,targets,masks,confidence_gate=False)
    image_support=np.zeros(len(xyz),np.int16);colour_support=np.zeros(len(xyz),np.int16)
    observed_names=[]
    for n in names:
        q,z=project(xyz,data['K'],data['world'][n]);static=(z>0)&mask_at(masks[n],q)
        image_support+=static
        rgb=cv2.cvtColor(cv2.imread(str(data['prepared']/'rectified_observations'/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        observed=bilinear(cv2.GaussianBlur(rgb,(3,3),0),q)
        agree=static&np.isfinite(observed).all(1)&(np.mean(np.abs(observed-colours),1)<=.12)
        colour_support+=agree
        if agree.any():observed_names.append(n)
    # Same depth threshold and free-space rule. The extra class is explicit:
    # same shared conditional surface corroborated by static source pixels;
    # static RGB overlap is NOT claimed to establish geometric visibility.
    strict=(depth_votes>=3)&(free<=1)
    soft=(depth_votes<3)&(image_support>=3)&(colour_support>=3)&(free<=1)
    keep=np.flatnonzero(strict|soft)
    if not len(keep):raise SharedRoomEvidenceUnavailable('shared_surface_no_supported_room_candidates')
    xy=xyz[keep];pixel=uv[keep];native=native[keep];colours=colours[keep]
    trainuv=np.array([t['referenceProcessedUV'] for t in report['tracks'] if t['role']=='fit'])
    distance=cKDTree(trainuv).query(pixel)[0]
    confidence=np.clip(.15+.65*np.exp(-distance/24),.15,.8)
    kinds=np.where(depth_votes[keep]>=3,'depth_consistent_shared_surface','conditional_shared_surface')
    surface_hash=digest(solved/'shared-surface.npz')
    uid=np.array([int.from_bytes(hashlib.sha256(f'SHARED:{parent["sourceSha256"]}:{surface_hash}:{int(i)}'.encode()).digest()[:8],'little')&((1<<63)-1) for i in indices[keep]],np.int64)
    sh=np.zeros((len(keep),4,3),np.float32);sh[:,0]=(colours-.5)/C0
    fresh=dict(means=xy,scales=scales[keep],quats=Rotation.from_matrix(basis[keep]).as_quat()[:,[3,0,1,2]],
        opacity=np.full(len(keep),.6),sh=sh,normal=basis[keep,:,2],parts=np.zeros(len(keep),np.int16),uid=uid,
        layer=np.full(len(keep),'room'),source_image=np.full(len(keep),reference),source_uv=native,
        source_window=np.full(len(keep),report['window'],np.int16),support=depth_votes[keep],confidence=confidence,
        raw_confidence=np.ones(len(keep)),weighted_support=depth_votes[keep]*confidence,
        static_image_support=image_support[keep],colour_support=colour_support[keep],depth_free=free[keep],depth_occluded=occluded[keep],
        evidence_type=kinds,anchor_distance_processed_px=distance,correction_type=np.full(len(keep),'shared_world_inverse_depth'),
        source_original_index=indices[keep].astype(np.int64))
    if candidate_filter is not None:
        fresh=candidate_filter(fresh)
        if not len(fresh['means']):raise SharedRoomEvidenceUnavailable('shared_surface_no_candidates_after_local_compatibility')
    if completion_reference is not None:
        from live_room_completion import export_addition
        return export_addition(fresh,solved,parent_path,out,budget,data,report,fit_ids,held_ids,existing_additions)
    old=dict(np.load(parent['components']['room']['path'],allow_pickle=False));oldn=len(old['means'])
    olduv,oldz=project(old['means'],surface['K'],surface['W2C']);expected=bilinear(surface['referenceDepthAfter'],olduv)
    region=np.zeros(surface['referenceDepthAfter'].shape,np.uint8)
    p=np.rint(pixel).astype(int);region[p[:,1],p[:,0]]=1;region=cv2.dilate(region,np.ones((3,3),np.uint8))
    replace=(oldz>0)&mask_at(region>0,olduv)&np.isfinite(expected)&(np.abs(oldz-expected)<=.15*expected)
    retained=np.flatnonzero(~replace)
    fallback=dict(static_image_support=old['support'],colour_support=old['support'],depth_free=np.zeros(oldn,np.int16),depth_occluded=np.zeros(oldn,np.int16),
        evidence_type=np.full(oldn,'original_depth_consistent'),anchor_distance_processed_px=np.full(oldn,-1.),
        correction_type=np.full(oldn,'unchanged_original'),source_original_index=np.arange(oldn,dtype=np.int64))
    combined={k:np.concatenate((old.get(k,fallback.get(k))[retained],v)) for k,v in fresh.items()}
    chosen=replacement_budget_indices(len(retained),fresh,budget);combined={k:v[chosen] for k,v in combined.items()}
    asset=out/'room-surface.npz';np.savez_compressed(asset,**combined,source_hash=np.asarray(parent['sourceSha256']),coordinate_frame=np.asarray('world'),
        referenceName=np.asarray(parent['reference']),surfaceReferenceName=np.asarray(reference))
    receipt=dict(schemaVersion=1,kind='shared-static-track-surface-correction',qualified=qualified,
        sourceSha256=parent['sourceSha256'],preparedSha256=digest(data['prepared']/'preparation.json'),localGeometrySha256=digest(data['prepared']/'local_geometry.npz'),
        nativeK=data['K'].tolist(),referenceName=reference,referenceC=data['world'][reference].tolist(),
        solverReportPath=str((solved/'report.json').resolve()),solverReportSha256=digest(solved/'report.json'),
        surfacePath=str((solved/'shared-surface.npz').resolve()),surfaceSha256=digest(solved/'shared-surface.npz'),
        trainTrackIds=fit_ids,validationTrackIds=held_ids,before=report['before'],after=report['after'],
        config=report['config'],originalDepthThreshold=.03,originalFreeMaximum=1,
        originalRoomCount=oldn,retiredInCorrectedRange=int(replace.sum()),retainedOutsideRange=len(retained),
        newSurfaceCount=len(keep),strictDepthCount=int(strict.sum()),conditionalCount=int(soft.sum()),finalCount=len(chosen),
        finalRetainedOutsideRange=len(retained),finalNewSurfaceCount=int(len(chosen)-len(retained)),
        budgetPolicy='all original out-of-scope points retained; only new surface sampled within remaining budget',
        replacementScope='observed reference room pixels with proposed footprint and same depth layer within 15%; other room retained',
        conditionalBoundary='Static-mask and original-colour agreement do not prove visibility or measured depth. Unanchored surface remains conditional.',
        originalRoomAssetHash=parent['components']['room']['sha256'],roomAssetHash=digest(asset),inference=False,training=False)
    write_json(out/'surface-correction-receipt.json',receipt)
    row={**parent['components']['room'],'path':str(asset),'sha256':digest(asset),'count':len(chosen),
        'referenceName':parent['reference'],'surfaceReferenceName':reference,
        'trainNames':names,'validTrainNames':names,'typedSupport':True,
        'surfaceCorrectionReceipt':str(out/'surface-correction-receipt.json'),'surfaceCorrectionReceiptSha256':digest(out/'surface-correction-receipt.json'),
        'supportMeaning':'support remains strict depth votes; static_image_support and evidence_type identify conditional surface evidence separately',
        'physicalGeometryVerified':False}
    final={**parent,'components':{**parent['components'],'room':row},'manifestPath':str(out/'result.json'),
        'parentManifestPath':str(parent_path.resolve()),'parentManifestHash':digest(parent_path),'published':False}
    write_json(out/'result.json',final);print(json.dumps({k:v for k,v in receipt.items() if k not in ('trainTrackIds','validationTrackIds','nativeK','referenceC','before','after')},indent=2))
    return final


def apply_shared_room_correction(parent_bundle,output,*,max_evaluations=40,budget=None,replay_receipt=None,complete_observed=False,reference_fallback=True):
    """Optional, bounded live stage. Evidence failures preserve the original model.

    Programming, I/O and changed-input contract errors deliberately propagate.
    This stage qualifies a conditional initialization, never final visual quality.
    """
    parent_path=Path(parent_bundle).resolve();parent=json.loads(parent_path.read_text())
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'algorithm-source';snapshot.mkdir();source_hashes={}
    for name in ('live_shared_room_surface.py','live_room_reference.py','live_dense.py',
                 'live_dense_contract.py','observation_domains.py'):
        path=Path(__file__).with_name(name);shutil.copyfile(path,snapshot/name);source_hashes[name]=digest(snapshot/name)
    # Retaining a relative component reference must not reinterpret it relative
    # to the new output directory. Preserve identities and resolve their base.
    for component in parent['components'].values():
        for key in ('path','surfaceCorrectionReceipt'):
            if component.get(key) and not Path(component[key]).is_absolute():
                component[key]=str((parent_path.parent/component[key]).resolve())
        if component.get('path') and digest(component['path'])!=component['sha256']:
            raise ValueError('shared_stage_component_changed')
        if component.get('surfaceCorrectionReceipt') and digest(component['surfaceCorrectionReceipt'])!=component['surfaceCorrectionReceiptSha256']:
            raise ValueError('shared_stage_receipt_changed')
    depth_path=Path(parent['depthManifestPath'])
    if not depth_path.is_absolute():depth_path=(parent_path.parent/depth_path).resolve()
    parent['depthManifestPath']=str(depth_path)
    if digest(depth_path)!=parent['depthManifestHash']:raise ValueError('shared_stage_depth_manifest_changed')
    root=depth_path.parent;request=json.loads((root/'request.json').read_text())
    prepared=Path(request['prepared'])
    if not prepared.is_absolute():prepared=(root/prepared).resolve()
    if request['sourceHash']!=parent['sourceSha256']:raise ValueError('shared_stage_source_changed')
    for file,key in (('preparation.json','preparedSha256'),('local_geometry.npz','localGeometrySha256')):
        if digest(prepared/file)!=parent[key]:raise ValueError('shared_stage_prepared_changed:'+file)
    report=None;reason=None;replay=None;selected_solve=out/'solve';reference_attempts=[];reference_selection=None
    if not parent['components'].get('room',{}).get('count',0):
        reason='shared_surface_room_initialization_missing'
    elif replay_receipt is not None:
        # Replaying frozen geometry is distinct from solving a new capture.
        # An accepted receipt must bind the source, prepared state and both
        # solver outputs. Merely passing an arbitrary old surface is forbidden.
        receipt_path=Path(replay_receipt).resolve();receipt=json.loads(receipt_path.read_text())
        if not receipt['qualified'] or receipt['kind']!='shared-static-track-surface-correction':
            raise ValueError('shared_stage_replay_not_qualified')
        for key in ('sourceSha256','preparedSha256','localGeometrySha256'):
            if receipt[key]!=parent[key]:raise ValueError('shared_stage_replay_identity_changed:'+key)
        solve=out/'solve';solve.mkdir()
        for path_key,hash_key,filename in (('solverReportPath','solverReportSha256','report.json'),
                                          ('surfacePath','surfaceSha256','shared-surface.npz')):
            old=Path(receipt[path_key])
            if not old.is_absolute():old=(receipt_path.parent/old).resolve()
            if digest(old)!=receipt[hash_key]:raise ValueError('shared_stage_replay_output_changed:'+filename)
            shutil.copyfile(old,solve/filename)
        original_source=Path(receipt['solverReportPath']).parent/'algorithm-source'
        if original_source.is_dir():shutil.copytree(original_source,solve/'algorithm-source')
        report=json.loads((solve/'report.json').read_text())
        if not report['accepted']:raise ValueError('shared_stage_replay_report_not_accepted')
        replay=dict(receiptPath=str(receipt_path),receiptSha256=digest(receipt_path),solverInvoked=False,
                    solverReportSha256=receipt['solverReportSha256'],surfaceSha256=receipt['surfaceSha256'])
        write_json(out/'replayed-geometry.json',replay)
    else:
        try:
            report=run_shared_surface(prepared,root,selected_solve,max_evaluations=max_evaluations)
        except SharedRoomEvidenceUnavailable as error:
            reason=str(error)
        if report is not None and not report['accepted']:reason='shared_surface_validation_not_qualified'
        # The portrait/body reference is not an arbitrary constraint on a
        # static room solve. Try only bounded, independently eligible cached
        # room observations; never change the exported person reference.
        allowed_reasons={'shared_surface_insufficient_independent_tracks','shared_surface_reference_has_no_independent_map_tracks',
            'shared_surface_no_accepted_reference_world_window','shared_surface_validation_not_qualified'}
        if reference_fallback and reason in allowed_reasons:
            from live_room_reference import inspect_room_references
            reference_attempts.append(dict(reference=parent['reference'],reason=reason,solvePath=str(selected_solve)))
            reference_selection=inspect_room_references(parent_path,out/'reference-selection',max_candidates=2)
            for number,candidate in enumerate(reference_selection['selected']):
                trial=out/f'reference-attempt-{number+1}';trial.mkdir()
                try:
                    alternative=run_shared_surface(prepared,root,trial/'solve',reference=candidate['reference'],window=candidate['window'],max_evaluations=max_evaluations)
                    accepted=bool(alternative['accepted'])
                    reference_attempts.append(dict(reference=candidate['reference'],window=candidate['window'],
                        status='qualified' if accepted else 'validation_failed',solvePath=str(trial/'solve')))
                    if accepted:
                        report=alternative;selected_solve=trial/'solve';reason=None;break
                except SharedRoomEvidenceUnavailable as error:
                    reference_attempts.append(dict(reference=candidate['reference'],window=candidate['window'],status='evidence_unavailable',reason=str(error),solvePath=str(trial/'solve')))
            write_json(out/'reference-attempts.json',dict(exportReference=parent['reference'],attempts=reference_attempts,
                selectionPath=str(out/'reference-selection/report.json'),selectionSha256=digest(out/'reference-selection/report.json'),
                fitMinimum=20,heldMinimum=12,thresholdsChanged=False,cameraChanged=False))
    if reason is None:
        try:
            final=export_shared_room_initialization(selected_solve,parent_path,out/'initialization',
                budget=budget if budget is not None else int(parent['components']['room']['count']))
        except SharedRoomEvidenceUnavailable as error:
            reason=str(error)
    if reason is not None:
        report_path=selected_solve/'report.json'
        receipt=dict(schemaVersion=1,kind='shared-static-track-surface-correction',qualified=False,
            status='original_bundle_retained',reason=reason,sourceSha256=parent['sourceSha256'],
            parentManifestPath=str(parent_path),parentManifestHash=digest(parent_path),
            preparedSha256=parent['preparedSha256'],localGeometrySha256=parent['localGeometrySha256'],
            solvePerformed=report is not None,sourceHashes=source_hashes,
            solverReportPath=str(report_path) if report_path.is_file() else None,
            solverReportSha256=digest(report_path) if report_path.is_file() else None,
            referenceAttempts=reference_attempts,visualQualityPassed=False,assetsChanged=False,published=False)
        write_json(out/'not-applied-receipt.json',receipt)
        final={**parent,'manifestPath':str(out/'result.json'),
            'parentManifestPath':str(parent_path),'parentManifestHash':digest(parent_path),
            'sharedRoomCorrection':{'status':'not_applied','reason':reason,
                'receiptPath':str(out/'not-applied-receipt.json'),'receiptSha256':digest(out/'not-applied-receipt.json')},'published':False}
        write_json(out/'result.json',final);return final
    final['sharedRoomCorrection']=dict(status='conditional_initialization_applied',visualQualityPassed=False,
        sourceHashes=source_hashes,solverReportPath=str(selected_solve/'report.json'),solverReportSha256=digest(selected_solve/'report.json'),
        exportReference=parent.get('reference'),surfaceReference=report.get('reference'),referenceAttempts=reference_attempts)
    if replay is not None:final['sharedRoomCorrection']['replayedGeometry']=replay
    # The returned manifest always names the actual terminal bundle, rather
    # than leaving callers pointing to the pre-correction initialization.
    final['manifestPath']=str((out/'initialization/result.json').resolve())
    write_json(final['manifestPath'],final)
    if complete_observed:
        from live_room_completion import complete_observed_room
        final=complete_observed_room(final['manifestPath'],out/'observed-room-completion')
    return final
