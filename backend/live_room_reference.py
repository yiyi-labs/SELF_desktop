"""Choose an independently constrained room reference without changing capture state.

The head/body export reference and every K/C remain fixed. Only cached, accepted
world depth images with original static-map tracks may become room-surface
references. Selection does not lower the solver's disjoint fit/held thresholds.
"""
from pathlib import Path
import argparse
import json
import time

import cv2
import numpy as np

from live_dense import read_prepared,resolve_path,physical_masks,mask_at,static_track_names,training_name_scopes
from live_dense_contract import bilinear,project,digest,write_json
from live_shared_room_surface import point_fold,independent_track_observations
from observation_domains import attach_observation_domains


def choose_reference_candidates(candidates,primary,max_candidates=2):
    """Eligibility first; measured shared context decides a bounded try order."""
    eligible=[r for r in candidates if r['eligible'] and r['reference']!=primary]
    eligible.sort(key=lambda r:(-r['sharedPrimaryTrackCount'],-r['heldTrackCount'],-r['fitTrackCount'],r['reference'],r['window']))
    selected=[];seen=set()
    for row in eligible:
        if row['reference'] in seen:continue
        selected.append(row);seen.add(row['reference'])
        if len(selected)>=min(max_candidates,2):break
    return selected


def inspect_room_references(parent_bundle,output,*,max_candidates=2):
    import pycolmap
    started=time.perf_counter();parent_path=Path(parent_bundle).resolve();parent=json.loads(parent_path.read_text())
    root=Path(parent['depthManifestPath']).parent;request=json.loads((root/'request.json').read_text())
    data=read_prepared(request['prepared']);scope=training_name_scopes(data,request.get('splitPath'),expected_split_hash=request.get('splitHash'))
    names=[n for n in scope['geometryTrain'] if n in data['world']]
    labels={n:dict(np.load(data['prepared']/'rectified_observations'/(n+'.npz'),allow_pickle=False)) for n in names}
    context=dict(labels=labels,K=data['K'],staticMap=str(resolve_path(data['metadata']['staticMap'],data['prepared'])))
    attach_observation_domains(context,data['prepared']);masks={n:physical_masks(context['labels'][n])['room'] for n in names}
    safe={n:cv2.erode(m.astype(np.uint8),np.ones((7,7),np.uint8)).astype(bool) for n,m in masks.items()}
    rec=pycolmap.Reconstruction(context['staticMap']);images={im.name:im for im in rec.images.values()}
    tracked=set(static_track_names(names,images,data['world']));tracked_points={}
    for pid,p in rec.points3D.items():
        if p.error>2 or p.track.length()<3:continue
        unique,_=independent_track_observations(rec,p,tracked,data['K'],safe)
        observations={o['imageName']:np.array(o['uv']) for o in unique}
        if len(observations)>=3:tracked_points[int(pid)]=observations
    primary=parent['reference'];primary_ids={pid for pid,views in tracked_points.items() if primary in views}
    depth=json.loads((root/'depth-manifest.json').read_text());accepted={tuple(k) for k in parent['acceptedWindows']}
    rows=[r for r in depth['observations'] if r['group']=='world' and ('world',r['window']) in accepted and r['imageName'] in names]
    candidates=[]
    for row in rows:
        n=row['imageName'];ids=[]
        p=root/row['file']
        if digest(p)!=row['depthHash']:raise ValueError('room_reference_depth_input_changed')
        a=dict(np.load(p,allow_pickle=False));np.testing.assert_allclose(a['W2C'],data['world'][n],atol=1e-7,rtol=0)
        np.testing.assert_allclose(a['K'],a['nativeToProcessed']@data['K'],atol=1e-6,rtol=0)
        if n in tracked:
            for pid,views in tracked_points.items():
                if n not in views:continue
                pixel=(a['nativeToProcessed']@np.r_[views[n],1.])[:2];z=float(bilinear(a['depth'],pixel[None])[0]);true_z=project(rec.points3D[pid].xyz[None],data['K'],data['world'][n])[1][0]
                if np.isfinite(z) and min(z,true_z)>0:ids.append(pid)
        fit=[i for i in ids if point_fold(i)!=0];held=[i for i in ids if point_fold(i)==0]
        eligible=len(fit)>=20 and len(held)>=12
        candidates.append(dict(reference=n,window=row['window'],fitTrackCount=len(fit),heldTrackCount=len(held),fitTrackIds=fit,heldTrackIds=held,
            mapTrackEvidence=n in tracked,sharedPrimaryTrackCount=len(set(ids)&primary_ids),sourceRoomPixels=int(masks[n].sum()),eligible=eligible,
            reason='eligible_for_bounded_surface_validation' if eligible else 'insufficient_independent_map_tracks',predictedDepthTruth=False))
    selected=choose_reference_candidates(candidates,primary,max_candidates)
    report=dict(kind='independent_room_reference_eligibility',sourceSha256=parent['sourceSha256'],preparedSha256=parent['preparedSha256'],
        localGeometrySha256=parent['localGeometrySha256'],parentManifestPath=str(parent_path),parentManifestSha256=digest(parent_path),
        moduleSha256=digest(__file__),primaryReference=primary,candidates=candidates,selected=selected,trainNames=names,
        thresholds=dict(fitTracks=20,heldTracks=12,staticPointError=2,minimumViews=3),KChanged=False,CChanged=False,
        exportReferenceChanged=False,solverInvoked=False,gpuUsed=False,seconds=time.perf_counter()-started,
        conclusion='References are eligible hypotheses; each still requires the unchanged held surface solve and full scene rendering. No result replaces an existing asset.')
    out=Path(output);out.mkdir(parents=True,exist_ok=False);write_json(out/'report.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--bundle',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    report=inspect_room_references(args.bundle,args.output)
    print(json.dumps(dict(selected=[{k:r[k] for k in ('reference','window','fitTrackCount','heldTrackCount','sharedPrimaryTrackCount')} for r in report['selected']],seconds=report['seconds'])))
