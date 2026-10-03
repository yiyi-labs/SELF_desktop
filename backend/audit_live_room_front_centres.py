"""Finite CPU audit of room centres against recorded, conditional head depth.

This writes evidence only. It never removes points, retrains or rasterizes.
No centre result can exclude Gaussian footprint interference or unobserved yaw.
"""
from pathlib import Path
import argparse
import hashlib
import json
import time
import cv2
import numpy as np
import torch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(run, output):
    from reconstruction_live_dense import (read_prepared, project, bilinear,
        mask_at, dense_hair_motion, dense_camera)
    from reconstruction_live_hair_motion import verify_motion_receipt
    from audit_live_boundary_coverage import original_semantics
    run=Path(run).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    started=time.perf_counter();config_path=run/'config.json'
    cfg=json.loads(config_path.read_text());prepared=Path(cfg['prepared']).resolve()
    data=read_prepared(prepared);bundle=cfg['denseSurfaces']
    if bundle['sourceHash']!=cfg['sourceSha256']:raise ValueError('source_contract')
    for name,key in [('preparation.json','preparedSha256'),('local_geometry.npz','localGeometrySha256')]:
        if sha(prepared/name)!=bundle[key]:raise ValueError('prepared_contract:'+name)
    dm=Path(bundle['components']['hair']['hairDepthManifestPath'])
    if sha(dm)!=bundle['components']['hair']['hairDepthManifestHash']:raise ValueError('depth_manifest_changed')
    manifest=json.loads(dm.read_text());rows=manifest['observations']
    if manifest['sourceHash']!=bundle['sourceHash'] or manifest['reference']!=bundle['reference']:
        raise ValueError('head_depth_identity')
    scale=float(data['geometry']['scale'])
    if scale<=0 or abs(scale-float(manifest['headToWorldScale']))>1e-10:
        raise ValueError('head_depth_units')
    np.testing.assert_allclose(data['K'],manifest['K'],atol=1e-8,rtol=0)
    motion=dense_hair_motion(data,bundle['reference'])
    verify_motion_receipt(manifest['hairMotion'],motion)
    accepted={w for group,w in bundle['acceptedWindows'] if group=='head-local'}
    checkpoint=run/'T3-state.pt'
    frozen=torch.load(checkpoint,map_location='cpu',weights_only=False)
    if frozen['sourceSha256']!=cfg['sourceSha256']:raise ValueError('checkpoint_source')
    state=frozen['model'];part=state['environment_parts'].numpy()==0
    xyz=state['environment.means'].numpy()[part]
    counts={margin:np.zeros(len(xyz),np.int16) for margin in (.03,.08,.12)}
    detail=[];depth_inputs=[]
    names=sorted(set(r['imageName'] for r in rows if r['group']=='head-local'
        and r['window'] in accepted and r['imageName'] in data['train'] and r['imageName'] in data['world']))
    for name in names:
        path=prepared/'rectified_observations'/(name+'.npz')
        existing=dict(np.load(path,allow_pickle=False))
        classes,certainty,outside,labels=original_semantics(prepared,data['metadata'],name,data['K'],existing)
        core=cv2.erode(((classes==3)&(certainty>=.85)&~outside&labels['face_core']&~labels['glasses_visible']).astype(np.uint8),np.ones((9,9),np.uint8)).astype(bool)
        uv,z=project(xyz,data['K'],data['world'][name]);z_head=z/scale
        eligible=mask_at(core,uv);pred=[];valid=[]
        for row in rows:
            if row['group']!='head-local' or row['window'] not in accepted or row['imageName']!=name:continue
            depth_path=dm.parent/row['file']
            if sha(depth_path)!=row['depthHash']:raise ValueError('depth_file_changed')
            arrays=dict(np.load(depth_path,allow_pickle=False))
            camera=dense_camera(data,name,'head-local',motion)
            np.testing.assert_allclose(arrays['W2C'],camera,atol=1e-6,rtol=0)
            A=arrays['nativeToProcessed']
            np.testing.assert_allclose(arrays['K'],A@data['K'],atol=1e-4,rtol=0)
            coords=(np.c_[uv,np.ones(len(uv))]@A.T)[:,:2]
            depth=bilinear(arrays['depth'],coords);confidence=bilinear(arrays['confidence'],coords)
            h,w=arrays['depth'].shape
            good=(coords[:,0]>=0)&(coords[:,0]<w-1)&(coords[:,1]>=0)&(coords[:,1]<h-1)
            good&=np.isfinite(depth)&(depth>0)&np.isfinite(confidence)&(confidence>=np.quantile(arrays['confidence'],.2))
            pred.append(depth);valid.append(good)
            depth_inputs.append(dict(path=str(depth_path.resolve()),sha256=row['depthHash'],imageName=name,window=row['window']))
        pred=np.stack(pred);valid=np.stack(valid);middle=np.median(pred,axis=0)
        spread=np.ptp(pred,axis=0)/np.maximum(middle,1e-10)
        good=eligible&valid.all(0)&(spread<=.10)&(z_head>0)
        result=dict(imageName=name,skinPixels=int(core.sum()),roomCentersInSkin=int(eligible.sum()),
            eligibleCenters=int(good.sum()),headWindows=len(pred),sourceMaskHash=sha(path),
            diagnosticSkinHash=hashlib.sha256(np.packbits(core).tobytes()).hexdigest(),frontCounts={})
        for margin,votes in counts.items():
            front=good&(z_head<middle*(1-margin));votes+=front.astype(np.int16)
            result['frontCounts'][str(margin)]=int(front.sum())
        if good.any():result['relativeDepthQuantiles']=dict(zip(('min','p10','median','p90','max'),map(float,np.quantile(z_head[good]/middle[good],[0,.1,.5,.9,1]))))
        detail.append(result)
    report=dict(schemaVersion=1,kind='conditional_room_centre_front_audit',run=str(run),
        sourceSha256=cfg['sourceSha256'],configSha256=sha(config_path),checkpoint=str(checkpoint),checkpointSha256=sha(checkpoint),
        preparedSha256=sha(prepared/'preparation.json'),localGeometrySha256=sha(prepared/'local_geometry.npz'),
        depthManifest=str(dm),depthManifestSha256=sha(dm),auditCodeSha256=sha(__file__),
        K=data['K'].tolist(),reference=bundle['reference'],headToWorldScale=scale,
        hairMotion=motion.receipt(),verifiedCameraMeaning='F_hair=F_root@D_ref_to_frame; source camera optical Z has same units after z_world/headToWorldScale',
        depthCameraAndProcessedKVerified=True,roomCount=len(xyz),trainViews=names,byFrame=detail,depthInputs=depth_inputs,
        uniqueRoomCenterFront={str(m):dict(any=int((v>0).sum()),atLeast3=int((v>=3).sum()),maxViews=int(v.max())) for m,v in counts.items()},
        filterContract=dict(semanticClass=3,semanticConfidence=.85,excludeGlasses=True,erodePixels=9,
            depthConfidence='existing hair support quantile 0.2',sameImageSpreadMax=.10,depthMargins=[.03,.08,.12]),
        limitations=['DA3 depth is a conditional hypothesis, not measured skin first-surface truth.',
            'An accepted window may have no cross-window connecting observations; acceptance is not complete registration proof.',
            'This checks centres only, not covariance intersection, exact sorted contribution or side-yaw visibility.',
            'Zero centre violations does not prove absence of foreground haze or licence stronger opacity.',
            'Erosion/margins are diagnostic support only; no production filter or source selection changed.'],
        gpuUsed=False,parametersChanged=False,newSourceImagesSaved=False,seconds=time.perf_counter()-started)
    output.mkdir(parents=True)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    text=f'''# Current room-centre front check (CPU only)

Run: `{run}`. Source SHA: `{report['sourceSha256']}`.
Checkpoint SHA: `{report['checkpointSha256']}`.

{len(xyz)} room points; {len(names)} actual training views. At all three
diagnostic front margins (3%, 8%, 12%), zero room centres satisfy the
high-confidence inner-skin foreground condition. This does **not** justify
deleting room points or exclude off-centre Gaussian footprint interference.
No GPU, point removal, image export or model changes were performed.

Native K, crop transform, recorded head-local `F_root @ D`, and world/head
scale were checked. A world point camera-Z is divided by {scale:.12g}
before comparing with the same source-image head depth. The first surface
is still DA3-predicted, not independently measured.

The existing initializer evaluates free-space votes only inside the same
component's mask. T3 preserves initial person contribution and limits movement,
but does not recheck final Gaussian footprint/ray intersections. Thus this is
a real constraint gap, **not proof that this capture contains erroneous
room centres in front of skin**. The current evidence is insufficient for a
cross-semantic pruning or arbitrary geometric push-back fix.

The separate strict-skin-context selection retains actual head-only/full-scene
contribution comparison. Its reference view had zero added-environment
attenuation pixels; other views did not. That older experiment cannot replace
the current room-density final footprint test. Freeze geometry and classify
the actual sorted contributions before selecting any finite geometry update.

Reproduce (backend working directory):

```text
/opt/self-reconstruction/venv/bin/python -B audit_live_room_front_centres.py --run {run} --output <new-independent-directory>
```

All input hashes and per-view counts are in `report.json`; no new private
source image was saved. Hair/glasses and the rejected 367-point hair-prune
candidate were not modified.
'''
    (output/'summary.md').write_text(text,encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();result=audit(args.run,args.output)
    print(json.dumps({k:result[k] for k in ('roomCount','trainViews','uniqueRoomCenterFront','seconds')},indent=2))
