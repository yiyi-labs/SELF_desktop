"""Bounded static 2D--3D localization for real near-time capture windows.

The existing map, intrinsics and registered poses never move. New cameras
come only from masked SIFT correspondences to that map, with withheld point
identities used for validation. A failed query contributes no camera matrix.
"""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import time
import cv2
import numpy as np
import pycolmap


def _hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def immutable_map_hash(model):
    h=hashlib.sha256()
    for i,c in sorted(model.cameras.items()):
        h.update(str((i,c.model_name,c.width,c.height)).encode());h.update(np.asarray(c.params).tobytes())
    for i,im in sorted(model.images.items()):
        if im.has_pose:h.update(str((i,im.name)).encode());h.update(np.asarray(im.cam_from_world().matrix()).tobytes())
    for i,p in sorted(model.points3D.items()):h.update(str(i).encode());h.update(np.asarray(p.xyz).tobytes())
    return h.hexdigest()


def track_split(point_ids):
    """One physical map point cannot appear in both fit and validation."""
    ids=np.asarray(point_ids,dtype=np.int64)
    if len(np.unique(ids))!=len(ids):raise ValueError('registration_duplicate_physical_track')
    held=np.array([int(hashlib.sha256(str(int(i)).encode()).hexdigest()[:8],16)%5==0 for i in ids])
    return ~held,held


def projection_quality(points,observed,pose,camera):
    cam=points@pose[:3,:3].T+pose[:3,3]
    pixel=camera.img_from_cam(cam,False)
    error=np.linalg.norm(pixel-observed,axis=1)
    normalized=observed/np.array([camera.width,camera.height])
    cells=np.floor(normalized*4).astype(int).clip(0,3)
    hull=cv2.convexHull(normalized.astype(np.float32)) if len(normalized)>=3 else None
    return {'count':len(points),'positiveDepthFraction':float(np.mean(cam[:,2]>.001)),
        'medianPx':float(np.median(error)),'p90Px':float(np.quantile(error,.9)),
        'gridCells4x4':len(np.unique(cells,axis=0)),
        'imageHullFraction':float(cv2.contourArea(hull)) if hull is not None else 0.}


def quality_accepted(fit,held,inliers):
    return (fit['count']>=24 and held['count']>=8 and inliers>=20 and inliers/fit['count']>=.4
        and held['positiveDepthFraction']>=.98 and held['medianPx']<=2.5 and held['p90Px']<=6.
        and held['gridCells4x4']>=4 and held['imageHullFraction']>=.02)


def propose_windows(names,registered,development,marks,times,source,max_anchors=2,neighbours=4):
    names=sorted(n for n in names if n in times);position={n:i for i,n in enumerate(names)}
    eligible=[n for n in registered if n in position and n not in development]
    scores={};sharp={}
    for n in eligible:
        m=np.asarray(marks[n]);scores[n]=float(np.linalg.norm(m[234]-m[454])/max(np.linalg.norm(m[10]-m[152]),1.))
        image=cv2.imread(str(source/'frames'/n),cv2.IMREAD_GRAYSCALE)
        xy0=np.floor(m.min(0)).astype(int);xy1=np.ceil(m.max(0)).astype(int)
        x0,y0=np.maximum(xy0,0);x1,y1=np.minimum(xy1,[image.shape[1],image.shape[0]])
        face=image[y0:y1,x0:x1]
        sharp[n]=float(cv2.Laplacian(face,cv2.CV_32F).var()) if face.size else 0.
    if not eligible:return []
    floor=float(np.quantile(list(sharp.values()),.25));chosen=[]
    for n in sorted(eligible,key=lambda n:(-scores[n],n)):
        if sharp[n]<floor or any(abs(times[n]-times[r['anchor']])<=3.5 for r in chosen):continue
        at=position[n];near=[m for m in names[max(0,at-neighbours):at+neighbours+1]
                            if abs(times[m]-times[n])<=1.75 and m not in development]
        chosen.append({'anchor':n,'names':near,'frontalScore':scores[n],'faceSharpness':sharp[n],
            'existingRegisteredTraining':[m for m in near if m in registered]})
        if len(chosen)>=max_anchors:break
    return chosen


def existing_static_window(model,registered,development,times):
    """Skip rescue only with measured baseline, not just a frame count.

    Local F is not fitted yet. Scene depth is used for this early numerical
    screen; choose_capture_reference subsequently applies its unchanged
    head-distance/body contract after fitting. No static-depth value is
    presented as a head-distance measurement.
    """
    eligible=sorted(n for n in registered if n not in development and n in times)
    for name in eligible:
        near=sorted((n for n in eligible if abs(times[n]-times[name])<=1.75),
                    key=lambda n:(abs(times[n]-times[name]),n))[:8]
        if len(near)<3:continue
        centers=[];depths=[]
        for n in near:
            im=registered[n];C=np.asarray(im.cam_from_world().matrix());centers.append(-C[:3,:3].T@C[:3,3])
            ids={int(p.point3D_id) for p in im.points2D if p.has_point3D()}
            if ids:
                xyz=np.stack([model.points3D[i].xyz for i in ids]);z=(xyz@C[:3,:3].T+C[:3,3])[:,2]
                depths.extend(z[z>1e-6].tolist())
        if not depths:continue
        centers=np.stack(centers);baseline=float(np.linalg.norm(centers[:,None]-centers[None,:],axis=-1).max())
        depth=float(np.median(depths));ratio=baseline/depth
        if baseline>1e-7 and ratio>=.005:
            return {'anchor':name,'imageNames':near,'cameraBaselineWorld':baseline,
                    'medianStaticPointDepthWorld':depth,'baselineToStaticDepth':ratio,
                    'requiresLaterLocalHeadReferenceCheck':True}
    return None


def extend_static_short_windows(source,base_database,model,selected_names,out,*,development_names=None):
    """Return verified extra world cameras; never mutate the fixed map."""
    started=time.perf_counter();source=Path(source);out=Path(out);out.mkdir(exist_ok=False)
    before=immutable_map_hash(model);camera=next(iter(model.cameras.values()))
    original_camera=np.asarray(camera.params).copy()
    manifest=json.loads((source/'frame_selection.json').read_text())
    if manifest.get('captureSha256')!=_hash(source/'capture.mp4'):raise ValueError('registration_capture_hash_mismatch')
    times={r['name']:float(r['timestampSeconds']) for r in manifest['selectedFrames']
           if r.get('timestampSeconds') is not None and np.isfinite(r['timestampSeconds'])}
    with np.load(source/'face_landmarks.npz') as marks:
        available=list(marks.files);registered={im.name:im for im in model.images.values() if im.has_pose}
        dev=set(development_names if development_names is not None else selected_names[3::5])
        windows=propose_windows(available,registered,dev,marks,times,source)
    report={'sourceSha256':manifest['captureSha256'],'method':'fixed_map_masked_sift_2d3d_withheld_track_validation',
        'pycolmapVersion':pycolmap.__version__,'mapBeforeSha256':before,'windows':windows,
        'developmentNames':sorted(dev),'cameraRefinement':False,'mapBundleAdjustment':False,
        'thresholds':{'maxAnchors':2,'heldMedianPx':2.5,'heldP90Px':6.,'minHeldGridCells':4,
            'minHeldHullFraction':.02,'minPositiveDepth':.98,'minFitTracks':24,'minHeldTracks':8},'queries':[]}
    # A valid existing near-time window needs no rescue. Actual baseline and
    # local F/scene-scale checks remain in choose_capture_reference later.
    existing=existing_static_window(model,registered,dev,times)
    if existing is not None:
        report['status']='existing_registered_short_window';report['existingWindow']=existing;extra={}
    else:
        queries=sorted({n for r in windows for n in r['names'] if n not in registered})
        database=out/'localization.db';shutil.copyfile(base_database,database)
        if queries:
            reader=pycolmap.ImageReaderOptions(mask_path=source/'static_feature_masks',existing_camera_id=camera.camera_id)
            extract=pycolmap.FeatureExtractionOptions(num_threads=6,max_image_size=1600);extract.sift.max_num_features=4500
            pycolmap.extract_features(database,source/'frames',image_names=queries,
                camera_mode=pycolmap.CameraMode.SINGLE,reader_options=reader,
                extraction_options=extract,device=pycolmap.Device.cpu)
            anchors=[n for n in registered if n in times and n not in dev]
            matching={q:sorted(anchors,key=lambda n:(abs(times[n]-times[q]),n))[:6] for q in queries}
            pairs=out/'pairs.txt';pairs.write_text(''.join(f'{q} {a}\n' for q in queries for a in matching[q]))
            pycolmap.match_image_pairs(database,matching_options=pycolmap.FeatureMatchingOptions(num_threads=6),
                pairing_options=pycolmap.ImportedPairingOptions(match_list_path=str(pairs)),device=pycolmap.Device.cpu)
        extra={}
        with pycolmap.Database.open(database) as db:
            images={im.name:im for im in db.read_all_images()}
            for query in queries:
                q=images[query];keypoints=db.read_keypoints(q.image_id)[:,:2].astype(np.float64)
                votes=defaultdict(Counter);map_sources=defaultdict(set)
                for anchor in matching[query]:
                    a=registered[anchor];matches=np.asarray(db.read_two_view_geometry(q.image_id,a.image_id).inlier_matches)
                    for qi,ai in matches:
                        feature=a.points2D[int(ai)]
                        if not feature.has_point3D():continue
                        pid=int(feature.point3D_id);p=model.points3D[pid]
                        if len(p.track.elements)<3:continue
                        votes[int(qi)][pid]+=1;map_sources[(int(qi),pid)].add(anchor)
                unique={};ambiguous=set()
                mask=cv2.imread(str(source/'static_feature_masks'/(query+'.png')),cv2.IMREAD_GRAYSCALE)
                for qi,counts in votes.items():
                    if len(counts)!=1:continue
                    pid=next(iter(counts));x,y=np.rint(keypoints[qi]).astype(int)
                    if x<0 or y<0 or x>=mask.shape[1] or y>=mask.shape[0] or mask[y,x]<128:continue
                    if pid in unique:ambiguous.add(pid)
                    else:unique[pid]=qi
                for pid in ambiguous:unique.pop(pid,None)
                pids=np.array(sorted(unique),dtype=np.int64)
                row={'name':query,'correspondences':len(pids),'ambiguousTracksExcluded':len(ambiguous),
                    'mapAnchorNames':matching[query],'status':'insufficient_unique_static_tracks'}
                report['queries'].append(row)
                if len(pids)<40:continue
                uv=np.array([keypoints[unique[int(i)]] for i in pids]);xyz=np.array([model.points3D[int(i)].xyz for i in pids])
                fit,held=track_split(pids)
                if fit.sum()<24 or held.sum()<8:continue
                estimation=pycolmap.AbsolutePoseEstimationOptions(estimate_focal_length=False)
                estimation.ransac.max_error=4.;estimation.ransac.random_seed=42;estimation.ransac.max_num_trials=5000
                refinement=pycolmap.AbsolutePoseRefinementOptions(refine_focal_length=False,refine_extra_params=False)
                result=pycolmap.estimate_and_refine_absolute_pose(uv[fit],xyz[fit],camera,estimation,refinement)
                if result is None:row['status']='pnp_failed';continue
                C=np.eye(4);C[:3]=result['cam_from_world'].matrix()
                train_q=projection_quality(xyz[fit],uv[fit],C,camera);held_q=projection_quality(xyz[held],uv[held],C,camera)
                accepted=quality_accepted(train_q,held_q,int(result['num_inliers']))
                row.update(status='accepted_fixed_map_localization' if accepted else 'withheld_validation_failed',
                    fit=train_q,held=held_q,inliers=int(result['num_inliers']),
                    fitPoint3DIDs=pids[fit].tolist(),heldPoint3DIDs=pids[held].tolist())
                if accepted:extra[query]=C
                np.savez_compressed(out/(query+'.correspondences.npz'),point3D_ids=pids,uv=uv,xyz=xyz,
                    fit=fit,held=held,pose=C,accepted=np.asarray(accepted))
        report['status']='bounded_localization_complete'
    if immutable_map_hash(model)!=before or not np.array_equal(camera.params,original_camera):
        raise ValueError('registration_modified_fixed_map_or_intrinsics')
    report.update(mapAfterSha256=immutable_map_hash(model),accepted=list(extra),seconds=time.perf_counter()-started,
                  sourceDatabaseSha256=_hash(base_database),fixedMapUnchanged=True)
    np.savez_compressed(out/'world-additions.npz',names=np.asarray(list(extra)),
                        C=np.stack(list(extra.values())) if extra else np.empty((0,4,4)))
    (out/'report.json').write_text(json.dumps(report,indent=2));return extra,report
