"""Capture-local dense initialization, with pinned DA3 depth-only proposals.

This module preserves SELF's cameras, native RGB, units and standard Gaussian
contract. DA3 predicts conditional geometry, never final appearance or verified
body motion. Inference runs in its fixed small environment, outside gsplat's
training process. It cannot read or publish an old person's checkpoint.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from live_dense_contract import (
    align_camera_scale, bilinear, complete_parameter_aliases, digest,
    normalize_cameras, project, resized_camera, rigid_check, unproject,
    write_json,
)

CODE_COMMIT = '3d835ec1a5802d64a8b8b15f817a1ab54809bfe4'
MODEL_COMMIT = 'f4a6c9b3c95e41c82048423d3493a81ec3fa810e'
WEIGHT_HASH = 'e01067dc1659613083d9145a9a2547ccdbe6ccbbf83c4fe7b3e8a4e2bdae78b5'
C0 = .28209479177387814


def resolve_path(value, prepared):
    p = Path(value)
    return p.resolve() if p.is_absolute() else (Path(prepared).parent.parent/p).resolve()


def verify_tool_source_lock(root):
    """Source paths are relative to root/source; a present lock is mandatory evidence."""
    root=Path(root)
    path=root/'source-lock.json'
    if not path.is_file():
        return None
    lock=json.loads(path.read_text())
    files=lock.get('files')
    if lock.get('codeCommit')!=CODE_COMMIT:
        raise ValueError('dense_tool_source_version_changed')
    if not isinstance(files,dict) or not files:
        raise ValueError('dense_tool_source_lock_empty')
    source=(root/'source').resolve()
    repo='Depth-Anything-3-'+CODE_COMMIT
    for name,expected in files.items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or relative.parts[0]!=repo:
            raise ValueError('dense_tool_source_path_invalid:'+name)
        actual=(source/relative).resolve()
        if not actual.is_relative_to(source) or not actual.is_file():
            raise ValueError('dense_tool_source_missing:'+name)
        if not isinstance(expected,str) or digest(actual)!=expected:
            raise ValueError('dense_tool_source_changed:'+name)
    # Extra executable source can shadow a pinned module even if all locked
    # files still match. Ignore only Python's runtime bytecode caches.
    actual_python={p.relative_to(source).as_posix() for p in (source/repo).rglob('*.py')}
    if not actual_python or not actual_python<=set(files):
        raise ValueError('dense_tool_unlocked_python_source')
    return dict(path=str(path.resolve()),sha256=digest(path),verifiedFiles=len(files),codeCommit=CODE_COMMIT)


def fixed_tool(tool_root=None):
    # The live route is self-contained in this project. A retired research
    # checkout must not silently supply code or weights after a Git change.
    candidates = [Path(tool_root)] if tool_root else [
        Path(__file__).parent/'.sources/tools/da3-3d835ec']
    for root in candidates:
        if (root/'weights-lock.json').is_file():
            lock = json.loads((root/'weights-lock.json').read_text())
            if (lock['codeCommit'], lock['modelCommit']) != (CODE_COMMIT, MODEL_COMMIT):
                raise ValueError('dense_tool_version_changed')
            for row in lock['files']:
                if digest(root/'model'/row['name']) != row['sha256']:
                    raise ValueError('dense_tool_weight_changed:'+row['name'])
            if digest(root/'model/model.safetensors') != WEIGHT_HASH:
                raise ValueError('dense_tool_weight_identity')
            verify_tool_source_lock(root)
            source = root/'source'/('Depth-Anything-3-'+CODE_COMMIT)/'src'
            if not source.is_dir() or not (root/'venv/bin/python').exists():
                raise ValueError('dense_tool_environment_missing')
            return root.resolve(), source, lock
    raise ValueError('pinned_DA3_BASE_tool_missing')


def static_track_names(names,lookup,world):
    """PnP observations remain usable images but never invent map track IDs."""
    available=[]
    for n in names:
        if n not in lookup or not lookup[n].has_pose:
            continue
        np.testing.assert_allclose(lookup[n].cam_from_world().matrix(),world[n][:3],atol=1e-7,rtol=0)
        available.append(n)
    return available


def validate_world_observation_sources(prepared,meta,world):
    import pycolmap
    from capture_registration import immutable_map_hash,quality_accepted
    prepared=Path(prepared)
    model=pycolmap.Reconstruction(str(resolve_path(meta['staticMap'],prepared)))
    lookup={im.name:im for im in model.images.values()}
    tracked=static_track_names(list(world),lookup,world)
    extra=set(world)-set(tracked)
    if not extra:
        return dict(mapTrackNames=tracked,localizedImageNames=[])
    root=prepared/'short-window-registration'
    report_path=root/'report.json'
    addition_path=root/'world-additions.npz'
    if not report_path.is_file() or not addition_path.is_file():
        raise ValueError('dense_extra_world_camera_evidence_missing')
    report=json.loads(report_path.read_text())
    current=immutable_map_hash(model)
    if report.get('sourceSha256')!=meta['sourceHash'] or report.get('fixedMapUnchanged') is not True:
        raise ValueError('dense_extra_world_camera_source_or_map_changed')
    if report['mapBeforeSha256']!=current or report['mapAfterSha256']!=current or report.get('cameraRefinement') is not False or report.get('mapBundleAdjustment') is not False:
        raise ValueError('dense_extra_world_camera_gauge_changed')
    archive=dict(np.load(addition_path,allow_pickle=False))
    names=list(map(str,archive['names']))
    if len(set(names))!=len(names) or archive['C'].shape!=(len(names),4,4):
        raise ValueError('dense_extra_world_camera_identity')
    additions=dict(zip(names,archive['C']))
    queries={r['name']:r for r in report['queries']}
    if set(names)!=set(report['accepted']) or not extra<=set(names):
        raise ValueError('dense_extra_world_camera_unaccepted')
    for n in sorted(extra):
        row=queries[n]
        if row['status']!='accepted_fixed_map_localization' or not quality_accepted(row['fit'],row['held'],row['inliers']):
            raise ValueError('dense_extra_world_camera_validation_failed:'+n)
        if set(row['fitPoint3DIDs'])&set(row['heldPoint3DIDs']):
            raise ValueError('dense_extra_world_camera_track_leak')
        np.testing.assert_allclose(rigid_check(additions[n]),world[n],atol=1e-7,rtol=0)
        evidence=dict(np.load(root/(n+'.correspondences.npz'),allow_pickle=False))
        if not bool(evidence['accepted']):
            raise ValueError('dense_extra_world_camera_point_evidence_rejected:'+n)
        np.testing.assert_allclose(evidence['pose'],world[n],atol=1e-7,rtol=0)
        for role in ('fit','held'):
            if set(map(int,evidence['point3D_ids'][evidence[role]]))!=set(row[role+'Point3DIDs']):
                raise ValueError('dense_extra_world_camera_point_identity:'+n)
    return dict(mapTrackNames=tracked,localizedImageNames=sorted(extra),
        registrationReportSha256=digest(report_path),registrationCamerasSha256=digest(addition_path))


def read_prepared(prepared):
    p = Path(prepared).resolve()
    meta = json.loads((p/'preparation.json').read_text())
    source = resolve_path(meta['source'], p)
    if digest(source/'capture.mp4') != meta['sourceHash']:
        raise ValueError('dense_capture_changed')
    g = dict(np.load(p/'local_geometry.npz', allow_pickle=False))
    names = list(map(str, g['names']))
    if len(names) != len(set(names)):
        raise ValueError('dense_duplicate_image_identity')
    K = np.asarray(g['K'], float)
    if K.shape != (3, 3) or not np.isfinite(K).all() or min(K[0, 0], K[1, 1]) <= 0:
        raise ValueError('dense_intrinsic_contract')
    local = {n:rigid_check(g['F'][i]) for i,n in enumerate(names)}
    world = {str(n):rigid_check(g['C'][i]) for i,n in enumerate(g['world_names'])}
    world_sources=validate_world_observation_sources(p,meta,world)
    train = [n for i,n in enumerate(names) if str(g['roles'][i]) == 'train']
    forbidden = set(meta.get('development', [])) | set(meta.get('audit', []))
    train = [n for n in train if n not in forbidden]
    manifest = source/'frame_selection.json'
    if not manifest.is_file():
        manifest = source/'frame_manifest.audit.json'
    record = json.loads(manifest.read_text())
    if record['captureSha256'] != meta['sourceHash']:
        raise ValueError('dense_timestamp_capture_changed')
    rows = {r['name']:r for r in record.get('selectedFrames', record.get('frames', []))}
    if any(n not in rows or rows[n].get('timestampSeconds') is None for n in train):
        raise ValueError('dense_verified_timestamp_missing')
    train.sort(key=lambda n:(rows[n]['timestampSeconds'], rows[n]['sourceIndexZeroBased']))
    return dict(prepared=p, metadata=meta, source=source, geometry=g, K=K,
        local=local, world=world, train=train, forbidden=sorted(forbidden), frameRows=rows,worldObservationSources=world_sources)


def selected_names(names, limit, reference):
    if reference not in names:
        raise ValueError('dense_reference_not_training')
    ids = np.unique(np.rint(np.linspace(0, len(names)-1, min(len(names), limit))).astype(int))
    result = {names[i] for i in ids}
    result.add(reference)
    return [n for n in names if n in result]


def training_name_scopes(data,split=None,*,expected_split_hash=None):
    """Native roles always apply; an optional study split can only narrow them."""
    forbidden=set(data.get('forbidden',[]))
    colour=set(data['train'])
    split_hash=None
    if split is not None:
        split_hash=digest(split)
        if expected_split_hash is not None and split_hash!=expected_split_hash:
            raise ValueError('dense_request_split_changed')
        plan=json.loads(Path(split).read_text())
        extra=set(plan.get('development',[]))|set(plan.get('audit',[]))
        if set(plan['train'])&extra:
            raise ValueError('dense_split_roles_overlap')
        forbidden|=extra
        colour&=set(plan['train'])
    geometry=[n for n in data['train'] if n not in forbidden]
    return dict(geometryTrain=geometry,colourTrain=[n for n in geometry if n in colour],
        forbidden=sorted(forbidden),splitHash=split_hash,
        method='prepared_train_roles_then_optional_narrowing; no validation image colours')


def plan_dense_windows(data,reference,*,max_views=24,batch_size=8,split=None):
    """Pure planning used by live inference and CPU route verification alike."""
    scope=training_name_scopes(data,split)
    names=selected_names(scope['colourTrain'],max_views,reference)
    times={n:float(data['frameRows'][n]['timestampSeconds']) for n in scope['geometryTrain']}
    world=[n for n in names if n in data['world']]
    if reference not in world:
        raise ValueError('dense_reference_missing_world_camera')
    world_windows=windows(world,batch_size,reference,times)
    body_names=[n for n in scope['geometryTrain'] if n in data['world']]
    body_windows=windows(body_names,batch_size,reference,times,body=True)
    head_windows=windows(names,batch_size,reference,times)
    names=list(dict.fromkeys(n for blocks in (world_windows,head_windows,body_windows) for block in blocks for n in block))
    return dict(names=names,windows={'world':world_windows,'head-local':head_windows,'body-world':body_windows},
        observationPolicy=scope,bodyWindowStatus='reference_containing_actual_train_window' if body_windows else 'insufficient_near_time_training_views')


def choose_reference(data):
    """The unchanged SELF frontal-width rule, within real world train views."""
    names=[n for n in data['train'] if n in data['worlds']]
    if not names:
        raise ValueError('dense_reference_world_train_missing')
    return max(names,key=lambda n:np.linalg.norm(data['local'][n]['marks'][234]-data['local'][n]['marks'][454]) /
        max(np.linalg.norm(data['local'][n]['marks'][10]-data['local'][n]['marks'][152]),1))


def windows(names, batch, reference, timestamps, *, body=False):
    if batch < 3:
        raise ValueError('dense_window_requires_three_views')
    if body:
        # Reference must be inside the actually observed short window. Unknown
        # torso motion outside this window is not silently extrapolated.
        ref = timestamps[reference]
        near = sorted(names, key=lambda n:abs(timestamps[n]-ref))[:batch]
        near = [n for n in names if n in near and abs(timestamps[n]-ref) <= 1.75]
        return [near] if len(near) >= 3 and reference in near else []
    return [names[i:i+batch] for i in range(0, len(names), max(1, batch-2)) if len(names[i:i+batch]) >= 3]


def continuous_world_windows(names, batch, reference, timestamps, cameras, max_views=24):
    """Finite time-contiguous static-camera windows, separate from RGB minibatches.

    Reference first, then cover the remaining acquisition interval. A large
    unregistered time gap is never filled by skipping across it inside a batch.
    Camera centres must contain a real nonzero baseline; no pose is synthesized.
    """
    if reference not in names:
        raise ValueError('dense_world_reference_missing')
    names=sorted(names,key=lambda n:timestamps[n])
    budget=max(1,int(np.ceil(max_views/batch)))
    gaps=np.diff([timestamps[n] for n in names])
    positive=gaps[gaps>0]
    gap_limit=max(1.,min(3.,6*float(np.median(positive)))) if len(positive) else 1.
    segments=[]
    chunk=[]
    for n in names:
        if chunk and timestamps[n]-timestamps[chunk[-1]]>gap_limit:
            segments.append(chunk)
            chunk=[]
        chunk.append(n)
    if chunk:
        segments.append(chunk)
    windows_out=[]
    covered=set()
    centres=[reference]
    while len(windows_out)<budget:
        if not centres:
            remaining=[n for n in names if n not in covered]
            if not remaining:
                break
            seen=[timestamps[n] for win in windows_out for n in win]
            centres=[max(remaining,key=lambda n:min(abs(timestamps[n]-t) for t in seen))]
        centre=centres.pop(0)
        segment=next(s for s in segments if centre in s)
        near=sorted(segment,key=lambda n:abs(timestamps[n]-timestamps[centre]))[:batch]
        near=[n for n in segment if n in near and abs(timestamps[n]-timestamps[centre])<=6.]
        covered.update(near or [centre])
        if len(near)<3:
            continue
        cc=np.stack([-cameras[n][:3,:3].T@cameras[n][:3,3] for n in near])
        if np.max(np.linalg.norm(cc-cc[0],axis=1))<1e-7:
            continue
        if near not in windows_out:
            windows_out.append(near)
    return windows_out


def native_uv(uv, A):
    q = np.c_[uv, np.ones(len(uv))]@np.linalg.inv(A).T
    return q[:, :2]/q[:, 2:]


def mask_at(mask, uv):
    h,w = mask.shape
    xy = np.rint(np.nan_to_num(uv)).astype(np.int64)
    good = np.isfinite(uv).all(1)&(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
    xy = xy.clip([0,0],[w-1,h-1])
    return good&mask[xy[:,1],xy[:,0]]


def flame_depth_anchor(depth, conf, names, group, data, K, A, labels):
    """Re-anchor a person-window depth scale to the fitted FLAME head.

    DA3 recovers depth only up to scale and its own extrinsics are the only
    metric anchor the extrinsic alignment can use. On person close-ups with
    little static background that anchor degenerates: measured on job
    bdc65c2e the body component landed 3-4x too far from its own source
    cameras while the alignment gate still passed. The per-frame FLAME fit
    (metric, landmark-validated) is an independent anchor: project its mesh
    into the window canvas and compare z against DA3 depth on face/neck
    pixels. A window that cannot be anchored is rejected (its depth is not
    trustworthy), never published at an arbitrary scale.
    """
    geometry=data['geometry']
    gnames=[str(n) for n in geometry['names']]
    scale=float(geometry['scale'])
    true_z=[]
    da3_z=[]
    for i,n in enumerate(names):
        if n not in gnames:
            continue
        gi=gnames.index(n)
        mesh=np.asarray(geometry['meshes'][gi],dtype=np.float64)
        F=np.asarray(geometry['F'][gi],dtype=np.float64)
        if group=='head-local':
            cam=mesh@F[:3,:3].T+F[:3,3]
        else:
            world=data['world'].get(n)
            if world is None:
                continue
            C=np.asarray(world,dtype=np.float64)
            # Same chain as portrait_model.scaled_head_transform/to_world.
            target=F.copy()
            target[:3,3]=target[:3,3]*scale
            H=np.linalg.solve(C,target)
            world_pts=mesh@H[:3,:3].T*scale+H[:3,3]
            cam=world_pts@C[:3,:3].T+C[:3,3]
        front=cam[:,2]>.05
        Kn=np.asarray(geometry['K'],dtype=np.float64)
        zn=np.maximum(cam[:,2],1e-9)
        native=np.c_[Kn[0,0]*cam[:,0]/zn+Kn[0,2],Kn[1,1]*cam[:,1]/zn+Kn[1,2]]
        lab=labels.get(n)
        if lab is None:
            continue
        face=lab['face_core']|lab['face_boundary']
        if 'observed_body_skin' in lab:
            face=face|lab['observed_body_skin']
        good=front&mask_at(face,native)
        if not good.any():
            continue
        q=np.c_[native[good],np.ones(int(good.sum()))]@np.asarray(A,dtype=np.float64).T
        pu=q[:,0]/np.maximum(q[:,2],1e-9); pv=q[:,1]/np.maximum(q[:,2],1e-9)
        h,w=depth[i].shape
        inside=np.isfinite(pu)&np.isfinite(pv)&(pu>=0)&(pu<w)&(pv>=0)&(pv<h)
        if not inside.any():
            continue
        d=depth[i]
        samples=d[pv[inside].astype(int),pu[inside].astype(int)]
        valid=np.isfinite(samples)&(samples>0)&(conf[i][pv[inside].astype(int),pu[inside].astype(int)]>0)
        true_z.append(cam[good][inside][valid,2])
        da3_z.append(samples[valid])
    receipt={'method':'flame_fit_face_neck_pixels','group':group}
    if not true_z:
        receipt.update(anchored=False,samples=0,reason='no_flame_pixels')
        return receipt
    t=np.concatenate(true_z); s=np.concatenate(da3_z)
    ratios=t/s
    factor=float(np.median(ratios))
    spread=float(np.median(np.abs(ratios-factor))/max(factor,1e-9))
    receipt.update(samples=int(len(ratios)),factor=round(factor,6),
        ratioSpread=round(spread,4))
    anchored=len(ratios)>=120 and spread<.35 and .05<factor<20.
    receipt['anchored']=bool(anchored)
    if not anchored:
        receipt['reason']=('too_few_samples' if len(ratios)<120 else
                           'inconsistent_ratio' if spread>=.35 else 'factor_out_of_bounds')
    return receipt


def physical_masks(labels):
    # Separate SfM safety masks from observed appearance. Existing confidence
    # masks are kept; low texture is never a reason to omit a room pixel.
    skin=labels.get('observed_body_skin',np.zeros_like(labels['room_visible'])).astype(bool)
    face=labels['face_core']|labels['face_boundary']
    ys,xs=np.where(face)
    neck=np.zeros_like(skin)
    if len(xs):
        h,w=skin.shape
        left,right,bottom=int(xs.min()),int(xs.max()),int(ys.max())
        fw=right-left+1
        fh=bottom-int(ys.min())+1
        x0=max(0,left-int(.15*fw))
        x1=min(w,right+int(.15*fw)+1)
        region=np.zeros_like(skin)
        region[max(0,bottom-int(.10*fh)):min(h,bottom+int(.75*fh)+1),x0:x1]=True
        _,connected=cv2.connectedComponents((skin&region).astype(np.uint8),8)
        contact=np.zeros_like(skin)
        contact[max(0,bottom-int(.10*fh)):min(h,bottom+max(3,int(.18*fh))+1),x0:x1]=True
        ids=np.unique(connected[contact&skin])
        ids=ids[ids!=0]
        neck=np.isin(connected,ids)&skin
    return dict(room=labels.get('observed_room', labels['room_visible']).astype(bool),
        body=labels.get('observed_neck_cloth', labels['neck_cloth_visible']).astype(bool),
        neck=neck,other_body_skin=skin&~neck,
        hair=(labels['hair_visible']&~labels['unknown_or_occluded']).astype(bool))


def surface_samples(depth, K, T, stride=2):
    h,w = depth.shape
    yy,xx = np.mgrid[1:h-1:stride,1:w-1:stride]
    uv = np.c_[xx.ravel(),yy.ravel()].astype(float)
    z = depth[yy,xx].ravel()
    x = unproject(uv,z,K,T)
    a = unproject(uv+[1,0],depth[yy,xx+1].ravel(),K,T)-x
    b = unproject(uv+[0,1],depth[yy+1,xx].ravel(),K,T)-x
    normal = np.cross(a,b)
    norm = np.linalg.norm(normal,axis=1)
    sa = np.linalg.norm(a,axis=1)
    sb = np.linalg.norm(b,axis=1)
    good = np.isfinite(x).all(1)&(z>0)&(norm>1e-12)&(sa>0)&(sb>0)
    good &= (np.abs(depth[yy,xx+1].ravel()-z)<.03*z)&(np.abs(depth[yy+1,xx].ravel()-z)<.03*z)
    normal /= np.maximum(norm[:,None],1e-12)
    a /= np.maximum(sa[:,None],1e-12)
    basis = np.stack((a,np.cross(normal,a),normal),-1)
    scales = np.stack((sa,sb,np.minimum(sa,sb)*.25),1)*stride*.75
    return uv,x,basis,scales,good


def confidence_weight(values, reference):
    """Positive reliability weight, never a low-texture existence threshold."""
    valid=np.asarray(reference)[np.isfinite(reference)&(np.asarray(reference)>0)]
    scale=float(np.quantile(valid,.9)) if len(valid) else 1.
    return np.where(np.isfinite(values)&(values>0),np.clip(values/max(scale,1e-12),.05,1.),0.)


def support_samples(xyz, targets, masks, *, confidence_gate=True, return_weights=False):
    support = np.zeros(len(xyz),np.int16)
    free = support.copy()
    occluded = support.copy()
    weighted=np.zeros(len(xyz),np.float32)
    used = set()
    for row,a in targets:
        n = row['imageName']
        if n in used:
            continue
        used.add(n)
        uv,z = project(xyz,a['K'],a['W2C'])
        depth = bilinear(a['depth'],uv)
        cf = bilinear(a['confidence'],uv)
        h,w = a['depth'].shape
        valid = (z>0)&(uv[:,0]>=0)&(uv[:,0]<w-1)&(uv[:,1]>=0)&(uv[:,1]<h-1)
        valid &= np.isfinite(depth)&(depth>0)&np.isfinite(cf)&(cf>0)
        if confidence_gate:
            valid &= cf>=np.quantile(a['confidence'],.2)
        valid &= mask_at(masks[n],native_uv(uv,a['nativeToProcessed']))
        compatible=valid&(np.abs(z-depth)<=.03*depth)
        support += compatible.astype(np.int16)
        weighted+=compatible*confidence_weight(cf,a['confidence'])
        free += (valid&(z<depth-.03*depth)).astype(np.int16)
        occluded += (valid&(z>depth+.03*depth)).astype(np.int16)
    return (support,free,occluded,weighted) if return_weights else (support,free,occluded)


def overlap_check(a, b, native_mask):
    """Same original image, independent inference windows, original pixel domain."""
    h,w = a['depth'].shape
    yy,xx = np.mgrid[0:h:4,0:w:4]
    uv = np.c_[xx.ravel(),yy.ravel()]
    nuv = native_uv(uv,a['nativeToProcessed'])
    buv = (np.c_[nuv,np.ones(len(nuv))]@b['nativeToProcessed'].T)[:,:2]
    za = a['depth'][yy,xx].ravel()
    zb = bilinear(b['depth'],buv)
    good = mask_at(native_mask,nuv)&np.isfinite(za)&np.isfinite(zb)&(za>0)&(zb>0)
    if good.sum()<64:
        return dict(accepted=False,samples=int(good.sum()),reason='insufficient_shared_visible_depth')
    relative = np.abs(za[good]/zb[good]-1)
    return dict(accepted=bool(np.median(relative)<=.04 and np.quantile(relative,.9)<=.10),
        samples=int(good.sum()),medianRelative=float(np.median(relative)),p90Relative=float(np.quantile(relative,.9)))


def select_budget(arr, budget):
    """Distributed representatives preserve source XYZ and physical-layer identity."""
    if budget < 1:
        raise ValueError('dense_positive_budget')
    pitch = max(float(np.median(arr['scales'][:,:2]))*.7,1e-10)
    cell = np.floor(arr['means']/pitch).astype(np.int64)
    _,layer=np.unique(arr['layer'],return_inverse=True)
    key = np.c_[layer,cell]
    order = np.lexsort((arr['uid'],-arr['confidence'],-arr['support']))
    _,first = np.unique(key[order],axis=0,return_index=True)
    keep = order[first]
    if len(keep)>budget:
        ordering = np.lexsort((arr['uid'][keep],cell[keep,2],cell[keep,1],cell[keep,0],layer[keep]))
        keep = keep[ordering[np.floor(np.arange(budget)*len(keep)/budget).astype(int)]]
    return keep


def validate_request(request, data):
    """Reject substituted cameras, validation RGB or unrecorded body windows."""
    if data['metadata']['sourceHash'] != request['sourceHash']:
        raise ValueError('dense_request_source_changed')
    for name, key in (('preparation.json','preparedSha256'),('local_geometry.npz','localGeometrySha256')):
        if request.get(key) != digest(data['prepared']/name):
            raise ValueError('dense_request_geometry_changed:'+name)
    allowed=set(data['train'])
    colour_allowed=allowed.copy()
    if request.get('splitPath'):
        path=Path(request['splitPath'])
        if digest(path)!=request['splitHash']:
            raise ValueError('dense_request_split_changed')
        plan=json.loads(path.read_text())
        forbidden=set(plan.get('development',[]))|set(plan.get('audit',[]))
        allowed-=forbidden
        colour_allowed=allowed&set(plan['train'])
    if len(request['names'])!=len(set(request['names'])) or not set(request['names'])<=allowed:
        raise ValueError('dense_request_training_role_leak')
    used=set()
    for group,blocks in request['windows'].items():
        if group not in ('world','head-local','body-world'):
            raise ValueError('dense_request_unknown_coordinate_frame')
        for names in blocks:
            if len(names)<3 or len(names)!=len(set(names)) or not set(names)<=set(request['names']):
                raise ValueError('dense_request_window_identity')
            if group=='head-local' and not set(names)<=colour_allowed:
                raise ValueError('dense_request_colour_role_leak')
            if group!='head-local' and not set(names)<=set(data['world']):
                raise ValueError('dense_request_world_camera_missing')
            if group=='body-world':
                ref=request['reference']
                if ref not in names:
                    raise ValueError('dense_request_body_reference_missing')
                t=float(data['frameRows'][ref]['timestampSeconds'])
                if any(abs(float(data['frameRows'][n]['timestampSeconds'])-t)>1.75 for n in names):
                    raise ValueError('dense_request_body_time_extrapolation')
            used.update(names)
    if used!=set(request['names']):
        raise ValueError('dense_request_unused_image')


def dense_hair_motion(data,reference):
    from live_hair_motion import prepared_hair_motion
    return prepared_hair_motion(data['prepared'],data['metadata'],data['geometry'],reference)


def dense_camera(data,name,group,hair_motion):
    if group!='head-local':
        return data['world'][name]
    D=hair_motion.transforms[hair_motion.names.index(name)].numpy()
    return data['local'][name]@D


def infer_request(request_path):
    import torch
    from safetensors.torch import load_file
    request = json.loads(Path(request_path).read_text())
    p = Path(request['prepared'])
    out = Path(request['output'])
    data = read_prepared(p)
    tool, source, lock = fixed_tool(request['tool'])
    validate_request(request,data)
    from live_hair_motion import verify_motion_receipt
    hair_motion=None
    if request['windows'].get('head-local'):
        hair_motion=dense_hair_motion(data,request['reference'])
        verify_motion_receipt(request.get('hairMotion'),hair_motion)
    sys.path.insert(0,str(source))
    from depth_anything_3.cfg import create_object,load_config
    from depth_anything_3.utils.io.input_processor import InputProcessor
    net = create_object(load_config('depth_anything_3.configs.da3-base'))
    loaded = {k[len('model.'):]:v for k,v in load_file(tool/'model/model.safetensors').items() if k.startswith('model.')}
    loaded, aliases = complete_parameter_aliases(net.state_dict(keep_vars=True),loaded)
    net.load_state_dict(loaded,strict=True)
    del loaded
    net = net.cuda().eval()
    processor = InputProcessor()
    torch.cuda.reset_peak_memory_stats()
    start=time.perf_counter()
    cache = p/'rectified_observations'
    rgb={}
    labels={}
    for n in request['names']:
        im=cv2.imread(str(cache/n))
        if im is None:
            raise ValueError('dense_image_missing:'+n)
        rgb[n]=cv2.cvtColor(im,cv2.COLOR_BGR2RGB)
        labels[n]=dict(np.load(cache/(n+'.npz'),allow_pickle=False))
        if im.shape[:2]!=rgb[request['names'][0]].shape[:2]:
            raise ValueError('dense_native_canvas_changed:'+n)
        if labels[n]['face_core'].shape!=im.shape[:2]:
            raise ValueError('dense_native_mask_canvas_changed:'+n)
    rows=[]
    batches=[]
    for group,blocks in request['windows'].items():
        for wi,names in enumerate(blocks):
            h,w=rgb[names[0]].shape[:2]
            rectangle=[0,0,w,h]
            if group=='head-local':
                union=np.logical_or.reduce([labels[n]['face_core']|labels[n]['face_boundary']|labels[n]['hair_visible']|labels[n]['glasses_visible'] for n in names])
                yy,xx=np.where(union)
                if not len(xx):
                    raise ValueError('dense_head_crop_missing')
                pad=max(12,int(.1*max(np.ptp(xx),np.ptp(yy))))
                rectangle=[max(0,int(xx.min())-pad),max(0,int(yy.min())-pad),min(w,int(xx.max())+pad+1),min(h,int(yy.max())+pad+1)]
            x0,y0,x1,y1=rectangle
            rw,rh=x1-x0,y1-y0
            resolution=request['resolution']
            size=(max(14,round(rw/max(rw,rh)*resolution/14)*14),max(14,round(rh/max(rw,rh)*resolution/14)*14))
            K,A=resized_camera(data['K'],rectangle,(w,h),size)
            ims=[cv2.resize(rgb[n][y0:y1,x0:x1],size,interpolation=cv2.INTER_AREA) for n in names]
            expected=np.stack([dense_camera(data,n,group,hair_motion) for n in names])
            normalized,radius=normalize_cameras(expected)
            images,_,_=processor(ims,None,None,resolution,'upper_bound_resize',num_workers=1)
            if list(images.shape[-2:]) != [size[1],size[0]]:
                raise ValueError('dense_unexpected_image_resize')
            with torch.inference_mode(),torch.autocast('cuda',dtype=torch.bfloat16):
                pred=net(images[None].cuda(),torch.tensor(normalized,dtype=torch.float32,device='cuda')[None],
                    torch.tensor(np.repeat(K[None],len(names),0),dtype=torch.float32,device='cuda')[None],infer_gs=False,ref_view_strategy='first')
            depth=pred['depth'][0].float().cpu().numpy()
            conf=pred['depth_conf'][0].float().cpu().numpy()
            if depth.ndim==4:
                depth=depth[...,0]
            if conf.ndim==4:
                conf=conf[...,0]
            proposed=pred['extrinsics'][0].float().cpu().numpy()
            if proposed.shape[-2:]==(3,4):
                proposed=np.concatenate((proposed,np.tile([[[0,0,0,1]]],(len(names),1,1))),1)
            scale,alignment=align_camera_scale(proposed,expected)
            depth*=scale
            # Person close-up windows have little static background, so DA3's
            # own extrinsics—the only metric anchor the alignment above can
            # use—degenerate there (measured 3-4x depth overscale on job
            # bdc65c2e while the RMS gate still passed). The FLAME fit is an
            # independent metric anchor; a window that cannot be anchored is
            # rejected instead of published at an arbitrary scale.
            anchor=None
            if group in ('body-world','head-local'):
                anchor=flame_depth_anchor(depth,conf,names,group,data,K,A,labels)
                if anchor['anchored']:
                    depth*=anchor['factor']
                valid=bool(anchor['anchored'])
            else:
                valid=alignment['cameraCentreRmsRelative']<=.25
            batch=dict(group=group,window=wi,names=names,alignment=alignment,scaleGatePassed=valid,inputRadius=radius)
            if anchor is not None:
                batch['flameDepthAnchor']=anchor
            batches.append(batch)
            folder=out/'depth'/f'{group}-{wi}'
            folder.mkdir(parents=True)
            for i,n in enumerate(names):
                f=folder/(n+'.npz')
                np.savez_compressed(f,depth=depth[i],confidence=conf[i],K=K,W2C=expected[i],nativeToProcessed=A,
                    sourceHash=np.asarray(request['sourceHash']),imageName=np.asarray(n))
                rows.append(dict(imageName=n,group=group,window=wi,file=str(f.relative_to(out)),scaleGatePassed=valid,
                    role='train',imageHash=digest(cache/n),sourceHash=request['sourceHash'],timestampSeconds=data['frameRows'][n]['timestampSeconds'],
                    nativeSize=[w,h],processedSize=list(size),rectangle=rectangle,depthHash=digest(f)))
            del pred,images
            torch.cuda.empty_cache()
            print('DENSE_WINDOW',group,wi,len(names),valid,flush=True)
    write_json(out/'depth-manifest.json',dict(schema=1,sourceHash=request['sourceHash'],preparedHash=digest(p/'preparation.json'),
        coordinateUnits={'world':'static_COLMAP_world','body-world':'static_COLMAP_world','head-local':'FLAME_head_local'},
        headToWorldScale=float(data['geometry']['scale']),K=data['K'].tolist(),reference=request['reference'],
        observations=rows,batches=batches,aliases=aliases,toolLock=lock,modelIsConditionalGeometry=True,
        hairMotion=request.get('hairMotion'),
        camerasOverwritten=False,inferGS=False,seconds=time.perf_counter()-start,
        allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576))


def build_components(prepared, output, budgets, *, depth_root=None, components=None):
    data=read_prepared(prepared)
    out=Path(output)
    depth_root=Path(depth_root) if depth_root else out
    manifest=json.loads((depth_root/'depth-manifest.json').read_text())
    if manifest['sourceHash']!=data['metadata']['sourceHash']:
        raise ValueError('dense_surface_source_changed')
    request=json.loads((depth_root/'request.json').read_text())
    if request.get('splitPath') and not request.get('splitHash'):
        raise ValueError('dense_split_lock_missing')
    scope=training_name_scopes(data,request.get('splitPath'),expected_split_hash=request.get('splitHash'))
    rows=manifest['observations']
    groups={}
    cache={}
    masks={}
    rgb={}
    rejected=[]
    if components is not None:
        group_for={'room':'world','body':'body-world','hair':'head-local'}
        rows=[r for r in rows if r['group'] in {group_for[c] for c in components}]
    hair_motion=None
    if any(r['group']=='head-local' for r in rows):
        from live_hair_motion import verify_motion_receipt
        hair_motion=dense_hair_motion(data,manifest['reference'])
        verify_motion_receipt(manifest.get('hairMotion'),hair_motion)
    from observation_domains import attach_observation_domains
    original_labels={n:dict(np.load(data['prepared']/'rectified_observations'/(n+'.npz'),allow_pickle=False))
        for n in dict.fromkeys(r['imageName'] for r in rows)}
    domain_data=dict(labels=original_labels,K=data['K'],staticMap=str(resolve_path(data['metadata']['staticMap'],prepared)))
    attach_observation_domains(domain_data,prepared)
    for row in rows:
        n=row['imageName']
        if n not in scope['geometryTrain'] or row['role']!='train':
            raise ValueError('dense_training_role_leak')
        if row['group']=='head-local' and n not in scope['colourTrain']:
            raise ValueError('dense_colour_role_leak')
        if row['sourceHash']!=manifest['sourceHash']:
            raise ValueError('dense_row_source_changed')
        im=data['prepared']/'rectified_observations'/n
        if digest(im)!=row['imageHash'] or digest(depth_root/row['file'])!=row['depthHash']:
            raise ValueError('dense_input_changed')
        a=dict(np.load(depth_root/row['file'],allow_pickle=False))
        expected=dense_camera(data,n,row['group'],hair_motion)
        np.testing.assert_allclose(a['W2C'],expected,atol=1e-6,rtol=0)
        np.testing.assert_allclose(a['K'],a['nativeToProcessed']@data['K'],atol=1e-6,rtol=0)
        if str(a['imageName'])!=n or str(a['sourceHash'])!=manifest['sourceHash']:
            raise ValueError('dense_npz_identity')
        cache[row['file']]=a
        if n not in rgb:
            rgb[n]=cv2.cvtColor(cv2.imread(str(im)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
            masks[n]=physical_masks(domain_data['labels'][n])
        if row['scaleGatePassed']:
            groups.setdefault((row['group'],row['window']),[]).append((row,a))
    # Reject incompatible overlapping windows; never average inconsistent XYZ.
    conflicts=set()
    overlaps=[]
    for group in ('world','head-local'):
        keys=sorted(k for k in groups if k[0]==group)
        for i,ka in enumerate(keys):
            for kb in keys[i+1:]:
                aa={r['imageName']:a for r,a in groups[ka]}
                bb={r['imageName']:a for r,a in groups[kb]}
                for n in sorted(set(aa)&set(bb)):
                    check=overlap_check(aa[n],bb[n],masks[n]['room' if group=='world' else 'hair'])
                    overlaps.append(dict(group=group,windows=[ka[1],kb[1]],imageName=n,**check))
                    if not check['accepted']:
                        conflicts.add((ka,kb))
    # A component uses pairwise non-conflicting windows. Reference wins ties;
    # no-overlap pairs remain geometrically unverified, not claimed consistent.
    accepted_keys=set()
    for group in ('world','head-local','body-world'):
        keys=sorted((k for k in groups if k[0]==group),key=lambda k:(not any(r['imageName']==manifest['reference'] for r,a in groups[k]),k[1]))
        chosen=[]
        for key in keys:
            if any((min(key,old),max(key,old)) in conflicts for old in chosen):
                continue
            chosen.append(key)
        accepted_keys.update(chosen)
    result={}
    counts=[]
    for component,group,part in [('room','world',0),('hair','head-local',2),('body','body-world',4)]:
        if components is not None and component not in components:
            continue
        pieces=[]
        names=[]
        for key,targets in groups.items():
            if key[0]!=group or key not in accepted_keys:
                continue
            names.extend(r['imageName'] for r,a in targets)
            valid_masks={r['imageName']:masks[r['imageName']][component] for r,a in targets}
            for row,a in targets:
                uv,xyz,basis,scales,good=surface_samples(a['depth'],a['K'],a['W2C'])
                native=native_uv(uv,a['nativeToProcessed'])
                cf=bilinear(a['confidence'],uv)
                good&=mask_at(valid_masks[row['imageName']],native)&np.isfinite(cf)&(cf>0)
                # Background colour/texture confidence is not proof that a
                # visible wall is absent. Keep true mask/depth/visibility gates.
                if component!='room':
                    good&=cf>=np.quantile(a['confidence'],.2)
                proposed=np.flatnonzero(good)
                if not len(proposed):
                    continue
                support,free,occluded,weighted=support_samples(xyz[proposed],targets,valid_masks,
                    confidence_gate=component!='room',return_weights=True)
                chosen=(support>=3)&(free<=1)
                ids=proposed[chosen]
                counts.append(dict(component=component,window=key[1],name=row['imageName'],proposed=len(proposed),accepted=len(ids),freeRejected=int((free>1).sum())))
                if not len(ids):
                    continue
                colours=bilinear(rgb[row['imageName']],native[ids])
                finite=np.isfinite(colours).all(1)
                ids=ids[finite]
                colours=colours[finite]
                uid=np.array([int.from_bytes(hashlib.sha256(f'{manifest["sourceHash"]}:{group}:{key[1]}:{row["imageName"]}:{i}'.encode()).digest()[:8],'little')&((1<<63)-1) for i in ids],np.int64)
                layer=np.full(len(ids),component,dtype='U20')
                if component=='body':
                    layer[:]='cloth'
                    layer[mask_at(masks[row['imageName']]['other_body_skin'],native[ids])]='other_body_skin'
                    layer[mask_at(masks[row['imageName']]['neck'],native[ids])]='neck_skin'
                sh=np.zeros((len(ids),4,3),np.float32)
                sh[:,0]=(colours-.5)/C0
                pieces.append(dict(means=xyz[ids],quats=Rotation.from_matrix(basis[ids]).as_quat()[:,[3,0,1,2]],
                    scales=scales[ids],normal=basis[ids,:,2],opacity=np.full(len(ids),.6),sh=sh,parts=np.full(len(ids),part,np.int16),
                    uid=uid,layer=layer,source_image=np.full(len(ids),row['imageName']),source_uv=native[ids],
                    source_window=np.full(len(ids),key[1],np.int16),support=support[chosen][finite],
                    confidence=(.5*(confidence_weight(cf[ids],a['confidence'])+weighted[chosen][finite]/support[chosen][finite])) if component=='room' else cf[ids],
                    raw_confidence=cf[ids],weighted_support=weighted[chosen][finite]))
        if not pieces:
            result[component]=dict(status='no_three_view_consistent_depth_surface',count=0)
            continue
        arr={k:np.concatenate([p[k] for p in pieces]) for k in pieces[0]}
        before=len(arr['means'])
        keep=select_budget(arr,budgets[component])
        arr={k:v[keep] for k,v in arr.items()}
        coords='head-local' if component=='hair' else 'world'
        path=out/(component+'-surface.npz')
        np.savez_compressed(path,**arr,source_hash=np.asarray(manifest['sourceHash']),
            coordinate_frame=np.asarray(coords),referenceName=np.asarray(manifest['reference']))
        result[component]=dict(status='conditional_surface_initialized',path=str(path.resolve()),sha256=digest(path),count=len(keep),beforeBudget=before,
            coordinateFrame=coords,referenceName=manifest['reference'],
            trainNames=list(dict.fromkeys(names)),validTrainNames=list(dict.fromkeys(names)),motionStatus='short-window-unverified' if component=='body' else 'head-F' if component=='hair' else 'static-C',
            physicalGeometryVerified=False,normalSource='camera-conditioned_depth_local_derivatives',
            confidencePolicy='positive_reliability_weight_no_quantile_existence_veto' if component=='room' else 'original_positive_confidence_quintile',
            scaleMeaning='tangent native ray spacing, thin normal extent; never sparse KNN radius')
        if component=='hair':
            result[component].update(hairMotion=manifest.get('hairMotion'),
                motionStatus=hair_motion.receipt()['status'],
                hairDepthManifestPath=str((depth_root/'depth-manifest.json').resolve()),
                hairDepthManifestHash=digest(depth_root/'depth-manifest.json'))
    final=dict(schemaVersion=1,sourceSha256=manifest['sourceHash'],sourceHash=manifest['sourceHash'],reference=manifest['reference'],headToWorldScale=manifest['headToWorldScale'],
        preparedSha256=digest(data['prepared']/'preparation.json'),localGeometrySha256=digest(data['prepared']/'local_geometry.npz'),K=data['K'].tolist(),
        manifestPath=str((out/'result.json').resolve()),
        components=result,counts=counts,windowComparisons=overlaps,acceptedWindows=[list(k) for k in sorted(accepted_keys)],
        observationPolicy=scope,
        depthManifestPath=str((depth_root/'depth-manifest.json').resolve()),depthManifestHash=digest(depth_root/'depth-manifest.json'),
        privateDepthRetained=True,generatedColour=False,predictedDepthIsTruth=False,published=False)
    write_json(out/'result.json',final)
    return final


def rebuild_room_confidence(parent_bundle, output):
    """Same frozen depth and budget, room-only confidence interpretation change."""
    parent_path=Path(parent_bundle)
    parent=json.loads(parent_path.read_text())
    depth_root=Path(parent['depthManifestPath']).parent
    request=json.loads((depth_root/'request.json').read_text())
    out=Path(output)
    out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'algorithm-source'
    snapshot.mkdir()
    for n in ('live_dense.py','live_dense_contract.py','observation_domains.py'):
        shutil.copyfile(Path(__file__).with_name(n),snapshot/n)
    result=build_components(request['prepared'],out,{'room':parent['components']['room']['count']},
        depth_root=depth_root,components={'room'})
    merged={**parent,'components':{**parent['components'],'room':result['components']['room']},
        'parentManifestPath':str(parent_path.resolve()),'parentManifestHash':digest(parent_path),
        'roomRevisionManifestPath':str((out/'result.json').resolve()),'roomRevisionManifestHash':digest(out/'result.json'),
        'manifestPath':str((out/'merged-result.json').resolve()),'newDepthInference':False,'training':False}
    write_json(out/'merged-result.json',merged)
    return merged


def augment_prepared(prepared, output, *, reference, tool_root=None, max_views=24,
                     batch_size=8, process_res=504, room_budget=30000,
                     hair_budget=8000, body_budget=16000, inference_timeout=480, split=None,
                     shared_room_surface=False):
    """Create new-capture geometry once; returns standard Gaussian source files.

    Call before creating the CUDA training scene. Body proposals are valid only
    within their recorded reference-containing window until separate B evidence
    establishes transport. The caller must not use old checkpoints as fallback.
    """
    data=read_prepared(prepared)
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    print(json.dumps(dict(stage='surface',completedStages=0,totalStages=3)),flush=True)
    snapshot=out/'algorithm-source'
    snapshot.mkdir()
    source_hashes={}
    for name in ('live_dense.py','live_dense_contract.py','observation_domains.py',
                 'live_hair_motion.py','flame_open_model.py','portrait_model.py'):
        path=Path(__file__).with_name(name)
        shutil.copyfile(path,snapshot/name)
        source_hashes[name]=digest(snapshot/name)
    tool,_,lock=fixed_tool(tool_root)
    plan=plan_dense_windows(data,reference,max_views=max_views,batch_size=batch_size,split=split)
    # Locally continuous windows are proposals, not an automatic replacement:
    # the finite experiment failed independent static-anchor and overlap checks.
    # Keep the established window path until a corrected local surface passes
    # those checks; infer_reference_world exposes the reusable diagnostic stage.
    # Body requires close native training observations, not only globally sparse
    # depth views. Add a bounded reference-local set without using heldout RGB.
    from live_hair_motion import write_motion_contract
    motion=write_motion_contract(dense_hair_motion(data,reference),out)
    request=dict(prepared=str(data['prepared']),output=str(out),tool=str(tool),sourceHash=data['metadata']['sourceHash'],reference=reference,
        hairMotion=motion,
        sharedRoomSurfaceRequested=bool(shared_room_surface),
        preparedSha256=digest(data['prepared']/'preparation.json'),localGeometrySha256=digest(data['prepared']/'local_geometry.npz'),
        names=plan['names'],resolution=process_res,windows=plan['windows'],
        observationPolicy=plan['observationPolicy'],bodyWindowStatus=plan['bodyWindowStatus'],
        role='original_train_only',splitPath=str(Path(split).resolve()) if split else None,
        splitHash=digest(split) if split else None,
        license='DA3 BASE code and weights Apache-2.0',modelLock=lock,actualSourceHashes=source_hashes)
    write_json(out/'request.json',request)
    command=[str(tool/'venv/bin/python'),'-B',str(Path(__file__).resolve()),'--infer',str(out/'request.json')]
    start=time.perf_counter()
    with (out/'inference.log').open('x',encoding='utf-8') as log:
        subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT,timeout=inference_timeout)
    print(json.dumps(dict(stage='surface',completedStages=2,totalStages=3)),flush=True)
    final=build_components(prepared,out,dict(room=room_budget,hair=hair_budget,body=body_budget))
    final['seconds']=time.perf_counter()-start
    write_json(out/'result.json',final)
    if shared_room_surface:
        from live_shared_room_surface import apply_shared_room_correction
        final=apply_shared_room_correction(out/'result.json',out/'shared-room-surface',budget=room_budget,complete_observed=True)
        final['densePreparationSeconds']=time.perf_counter()-start
        write_json(final['manifestPath'],final)
    print(json.dumps(dict(stage='surface',completedStages=3,totalStages=3)),flush=True)
    return final


def append_hair_prepared(parent_manifest,output,*,timeout=600):
    """Reinfer only head batches in the corrected joint-1 frame.

    Room/body assets, their depth manifest and all receipts remain byte-for-byte
    referenced. This does not copy any old F-root hair depth into the new batch.
    """
    parent_path=Path(parent_manifest).resolve()
    parent=json.loads(parent_path.read_text())
    depth_path=Path(parent['depthManifestPath'])
    if not depth_path.is_absolute():
        depth_path=parent_path.parent/depth_path
    if digest(depth_path)!=parent['depthManifestHash']:
        raise ValueError('hair_refresh_parent_depth_changed')
    request=json.loads((depth_path.parent/'request.json').read_text())
    data=read_prepared(request['prepared'])
    for key,value in (('sourceSha256',data['metadata']['sourceHash']),
                      ('preparedSha256',digest(data['prepared']/'preparation.json')),
                      ('localGeometrySha256',digest(data['prepared']/'local_geometry.npz'))):
        if parent[key]!=value:
            raise ValueError('hair_refresh_parent_identity:'+key)
    blocks=request['windows'].get('head-local')
    if not blocks:
        raise ValueError('hair_refresh_missing_original_training_batches')
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    from live_hair_motion import write_motion_contract
    motion=write_motion_contract(dense_hair_motion(data,parent['reference']),out)
    if motion['status']=='explicit_legacy_root_local':
        raise ValueError('hair_refresh_requires_recorded_joint_fit')
    snapshot=out/'algorithm-source'
    snapshot.mkdir()
    hashes={}
    for name in ('live_dense.py','live_dense_contract.py',
                 'live_hair_motion.py','flame_open_model.py','portrait_model.py'):
        path=Path(__file__).with_name(name)
        shutil.copyfile(path,snapshot/name)
        hashes[name]=digest(path)
    request={**request,'output':str(out),'reference':parent['reference'],
             'names':list(dict.fromkeys(n for b in blocks for n in b)),
             'windows':{'head-local':blocks},'hairMotion':motion,'actualSourceHashes':hashes,
             'parentManifestPath':str(parent_path),'parentManifestHash':digest(parent_path),
             'oldHairDepthReused':False,'roomBodyParametersChanged':False}
    write_json(out/'request.json',request)
    with (out/'inference.log').open('x',encoding='utf-8') as log:
        subprocess.run([str(Path(request['tool'])/'venv/bin/python'),'-B',str(Path(__file__).resolve()),'--infer',str(out/'request.json')],
            check=True,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
    hair=build_components(request['prepared'],out,dict(hair=8000),components=['hair'])
    if not hair['components'].get('hair',{}).get('count'):
        raise ValueError('hair_refresh_no_supported_surface')
    merged=json.loads(parent_path.read_text())
    for row in merged['components'].values():
        if row.get('path') and not Path(row['path']).is_absolute():
            row['path']=str((parent_path.parent/row['path']).resolve())
    merged['components']['hair']=hair['components']['hair']
    merged.update(parentManifestPath=str(parent_path),parentManifestHash=digest(parent_path),
        auxiliaryHairManifestPath=str(out/'result.json'),auxiliaryHairManifestHash=digest(out/'result.json'),
        manifestPath=str(out/'merged-result.json'),oldHairDepthReused=False,roomBodyParametersChanged=False)
    write_json(out/'merged-result.json',merged)
    return merged


def append_body_prepared(parent, output, *, split, timeout=180):
    """One additional reference-local body batch; parent outputs never change.

    Original geometric training observations may supplement a smaller colour
    minibatch, with all development/audit identities excluded explicitly.
    """
    parent=Path(parent).resolve()
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    request=json.loads((parent/'request.json').read_text())
    data=read_prepared(request['prepared'])
    plan=json.loads(Path(split).read_text())
    forbidden=set(plan.get('development',[]))|set(plan.get('audit',[]))
    allowed=[n for n in data['train'] if n not in forbidden and n in data['world']]
    times={n:float(data['frameRows'][n]['timestampSeconds']) for n in allowed}
    block=windows(allowed,8,request['reference'],times,body=True)
    if not block:
        raise ValueError('dense_auxiliary_body_window_unavailable')
    snapshot=out/'algorithm-source'
    snapshot.mkdir()
    hashes={}
    for n in ('live_dense.py','live_dense_contract.py','observation_domains.py'):
        p=Path(__file__).with_name(n)
        shutil.copyfile(p,snapshot/n)
        hashes[n]=digest(snapshot/n)
    request={**request,'output':str(out),'names':block[0],'windows':{'body-world':block},
        'preparedSha256':digest(data['prepared']/'preparation.json'),'localGeometrySha256':digest(data['prepared']/'local_geometry.npz'),
        'actualSourceHashes':hashes,'auxiliaryGeometryTrain':[n for n in block[0] if n not in plan['train']],
        'originalColourTrainUnchanged':True,'splitHash':digest(split)}
    write_json(out/'request.json',request)
    with (out/'inference.log').open('x',encoding='utf-8') as log:
        subprocess.run([str(Path(request['tool'])/'venv/bin/python'),'-B',str(Path(__file__).resolve()),'--infer',str(out/'request.json')],
            check=True,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
    body=build_components(request['prepared'],out,dict(room=30000,hair=8000,body=16000))
    first=parent/'handoff-result.json'
    if not first.is_file():
        first=parent/'result.json'
    merged=json.loads(first.read_text())
    merged['components']['body']=body['components']['body']
    merged.update(parentManifestPath=str(first),parentManifestHash=digest(first),auxiliaryBodyManifestPath=str(out/'result.json'),
        auxiliaryBodyManifestHash=digest(out/'result.json'),auxiliaryGeometryTrain=request['auxiliaryGeometryTrain'],
        manifestPath=str(out/'merged-result.json'))
    write_json(out/'merged-result.json',merged)
    return merged


def infer_reference_world(parent, output, *, split, timeout=180):
    """Finite one-window diagnostic using the same generic live selection rule."""
    parent=Path(parent)
    request=json.loads((parent/'request.json').read_text())
    data=read_prepared(request['prepared'])
    plan=json.loads(Path(split).read_text())
    forbidden=set(plan.get('development',[]))|set(plan.get('audit',[]))
    allowed=[n for n in data['train'] if n not in forbidden and n in data['world']]
    times={n:float(data['frameRows'][n]['timestampSeconds']) for n in allowed}
    blocks=continuous_world_windows(allowed,8,request['reference'],times,data['world'],8)
    if len(blocks)!=1:
        raise ValueError('dense_reference_world_unavailable')
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'algorithm-source'
    snapshot.mkdir()
    hashes={}
    for n in ('live_dense.py','live_dense_contract.py','observation_domains.py'):
        shutil.copyfile(Path(__file__).with_name(n),snapshot/n)
        hashes[n]=digest(snapshot/n)
    request={**request,'output':str(out),'names':blocks[0],'windows':{'world':blocks},'actualSourceHashes':hashes,
        'preparedSha256':digest(data['prepared']/'preparation.json'),'localGeometrySha256':digest(data['prepared']/'local_geometry.npz'),
        'splitPath':str(Path(split).resolve()),'splitHash':digest(split),'auxiliaryGeometryTrain':[n for n in blocks[0] if n not in plan['train']]}
    write_json(out/'request.json',request)
    with (out/'inference.log').open('x',encoding='utf-8') as log:
        subprocess.run([str(Path(request['tool'])/'venv/bin/python'),'-B',str(Path(__file__).resolve()),'--infer',str(out/'request.json')],
            check=True,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
    return str(out)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--infer')
    parser.add_argument('--prepared')
    parser.add_argument('--output')
    parser.add_argument('--reference')
    parser.add_argument('--tool')
    parser.add_argument('--split')
    args=parser.parse_args()
    if args.infer:
        infer_request(args.infer)
    else:
        augment_prepared(args.prepared,args.output,reference=args.reference,tool_root=args.tool,split=args.split)
