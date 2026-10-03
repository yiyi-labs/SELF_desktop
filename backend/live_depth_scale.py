"""One conditional-depth scale per window, independently checked on static tracks.

Sparse points constrain metric alignment, not where background may exist.
K/C, image identities and all original depth observations remain unchanged.
"""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from live_dense import read_prepared, resolve_path, mask_at, native_uv, physical_masks, overlap_check
from live_dense_contract import bilinear, project, digest, write_json
from observation_domains import attach_observation_domains


def summarize(relative):
    a=np.asarray(relative,float)
    return dict(count=len(a),median=float(np.median(a)) if len(a) else None,p90=float(np.quantile(a,.9)) if len(a) else None)


def fit_window_scale(rows):
    """Physical POINT3D_ID splits, never splitting repeated measurements of one point."""
    ids=sorted(set(r['pointId'] for r in rows));fold={i:int(hashlib.sha256(str(i).encode()).hexdigest()[:8],16)%5 for i in ids}
    train=[r for r in rows if fold[r['pointId']]!=0];held=[r for r in rows if fold[r['pointId']]==0]
    ratios=[np.median([np.log(r['measuredDepth']/r['predictedDepth']) for r in train if r['pointId']==i]) for i in ids if fold[i]!=0]
    scale=float(np.exp(np.median(ratios))) if ratios else 1.
    before=summarize([abs(r['predictedDepth']/r['measuredDepth']-1) for r in held])
    after=summarize([abs(scale*r['predictedDepth']/r['measuredDepth']-1) for r in held])
    enough=len({r['pointId'] for r in train})>=20 and len({r['pointId'] for r in held})>=12 and len({r['imageName'] for r in held})>=3
    accepted=bool(enough and .5<=scale<=2 and after['median']<=.03 and after['p90']<=.08 and after['p90']<=before['p90']+.002)
    return dict(scale=scale,accepted=accepted,trainPointIds=sorted({r['pointId'] for r in train}),
        validationPointIds=sorted({r['pointId'] for r in held}),validationViews=sorted({r['imageName'] for r in held}),
        before=before,after=after,enoughStaticAnchors=enough,fit='median log scale, one vote per static POINT3D_ID',
        threshold=dict(heldMedianRelative=.03,heldP90Relative=.08),perFrameScale=False,cameraChanged=False)


def static_anchor_rows(data,rows,depth_root,masks,rec):
    lookup={i.name:i for i in rec.images.values()};out=[];rejections={}
    for row in rows:
        name=row['imageName'];im=lookup[name];a=dict(np.load(depth_root/row['file'],allow_pickle=False));C=data['world'][name]
        np.testing.assert_allclose(im.cam_from_world().matrix(),C[:3],atol=1e-7,rtol=0)
        safe=cv2.erode(masks[name].astype(np.uint8),np.ones((7,7),np.uint8)).astype(bool)
        candidates=[]
        for pt in im.points2D:
            if not pt.has_point3D():continue
            p=rec.points3D[pt.point3D_id]
            if p.track.length()<3 or not np.isfinite(p.error) or p.error>2:continue
            candidates.append((int(pt.point3D_id),p.xyz.copy(),float(p.error),int(p.track.length())))
        if not candidates:continue
        xyz=np.stack([p[1] for p in candidates]);uv,z=project(xyz,data['K'],C)
        processed=(np.c_[uv,np.ones(len(uv))]@a['nativeToProcessed'].T)[:,:2]
        pred=bilinear(a['depth'],processed);cf=bilinear(a['confidence'],processed)
        valid=(z>0)&mask_at(safe,uv)&np.isfinite(pred)&(pred>0)&np.isfinite(cf)&(cf>0)
        rejections[name]=dict(tracked=len(candidates),validStaticDepth=int(valid.sum()))
        for j in np.flatnonzero(valid):
            pid,xyz,error,length=candidates[j]
            out.append(dict(imageName=name,pointId=pid,sourceKind='COLMAP_STATIC_TRACK',measuredDepth=float(z[j]),predictedDepth=float(pred[j]),
                nativeUV=uv[j].tolist(),processedUV=processed[j].tolist(),trackLength=length,reprojectionError=error))
    return out,rejections


def audit_calibration(original,supplement,output):
    import pycolmap
    original=Path(original);supplement=Path(supplement);out=Path(output);out.mkdir(parents=True,exist_ok=False)
    request=json.loads((original/'request.json').read_text());data=read_prepared(request['prepared'])
    base=json.loads((original/'depth-manifest.json').read_text());near=json.loads((supplement/'depth-manifest.json').read_text())
    selected={tuple(k) for k in json.loads((original/'result.json').read_text())['acceptedWindows']}
    reference=base['reference'];refwindows={r['window'] for r in base['observations'] if r['group']=='world' and r['imageName']==reference}
    base_selected=[r for r in base['observations'] if r['group']=='world' and ('world',r['window']) in selected and r['window'] in refwindows]
    allrows=base_selected+near['observations']
    names=list(dict.fromkeys(r['imageName'] for r in allrows))
    labels={n:dict(np.load(data['prepared']/'rectified_observations'/(n+'.npz'),allow_pickle=False)) for n in names}
    domains=dict(labels=labels,K=data['K'],staticMap=str(resolve_path(data['metadata']['staticMap'],data['prepared'])))
    attach_observation_domains(domains,data['prepared']);masks={n:physical_masks(domains['labels'][n])['room'] for n in names}
    rec=pycolmap.Reconstruction(domains['staticMap']);reports=[];parameters={};reference=base['reference']
    basewindows=sorted({r['window'] for r in base_selected})
    for label,root,rows in [(f'world-{w}',original,[r for r in base_selected if r['window']==w]) for w in basewindows]+[('reference-short-window',supplement,near['observations'])]:
        anchors,rejected=static_anchor_rows(data,rows,root,masks,rec);result=fit_window_scale(anchors)
        result.update(label=label,depthRoot=str(root.resolve()),rows=rows,rejections=rejected,anchors=anchors)
        reports.append(result);parameters[label]=result
    checks=[]
    local=parameters['reference-short-window'];localrow=next(r for r in local['rows'] if r['imageName']==reference)
    localdepth=dict(np.load(supplement/localrow['file'],allow_pickle=False))
    for w in basewindows:
        label=f'world-{w}';old=parameters[label];row=next(r for r in old['rows'] if r['imageName']==reference)
        arr=dict(np.load(original/row['file'],allow_pickle=False))
        before=overlap_check(arr,localdepth,masks[reference])
        after=overlap_check({**arr,'depth':arr['depth']*old['scale']},{**localdepth,'depth':localdepth['depth']*local['scale']},masks[reference])
        checks.append(dict(worldWindow=w,before=before,after=after,independentStaticCalibrationAccepted=old['accepted'] and local['accepted']))
    final=dict(sourceHash=base['sourceHash'],reference=reference,windows=reports,crossWindow=checks,
        staticMap=domains['staticMap'],sourceHashIdentity=data['metadata']['sourceHash'],training=False,inference=False,
        note='Static reconstructed anchors estimate one scale; they are not independent sensor depth or a room existence mask.')
    write_json(out/'report.json',final)
    print(json.dumps({**final,'windows':[{k:v for k,v in r.items() if k not in ('anchors','rows','trainPointIds','validationPointIds')} for r in reports]},indent=2))
    return final
