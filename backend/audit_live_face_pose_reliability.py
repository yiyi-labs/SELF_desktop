"""Bounded CPU measurement audit; preserves all prepared cameras and assets."""
from pathlib import Path
import argparse
import json
import cv2
import numpy as np

from compare_live_opaque_person_runs import resolve,read_json,digest,mask_hash,_save_strip
from audit_live_boundary_coverage import original_semantics
from reconstruction_live_face_domain import observed_face_domain
from flame_open_model import FlameOpen
from reconstruction_face_pose_reliability import (project,triangle_landmarks,bounded_pose_candidate,
    mutual_ratio_matches,three_view_cycles,source_ray_binding,native_face_features)


def stats(values):
    a=np.asarray(values);a=a[np.isfinite(a)]
    return {'count':int(a.size),'median':float(np.median(a)) if a.size else None,
        'p90':float(np.quantile(a,.9)) if a.size else None,'mean':float(np.mean(a)) if a.size else None}


def audit(run,output):
    run=resolve(run);out=resolve(output)
    if out.exists():raise FileExistsError(out)
    conf=read_json(run/'config.json');prepared=resolve(conf['prepared']);meta=read_json(prepared/'preparation.json')
    with np.load(prepared/'local_geometry.npz',allow_pickle=False) as a:g={k:a[k].copy() for k in a.files}
    names=g['names'].tolist();roles=dict(zip(names,g['roles'].tolist()));index={n:i for i,n in enumerate(names)}
    train=[n for n in names if roles[n]=='train'];K=g['K'];oldF=g['F'];candidate=oldF.copy()
    model=FlameOpen(24,12);faces=model.faces.numpy();lfaces=model.landmark_faces.numpy()
    lbary=model.barycentric.numpy();lindices=model.landmark_indices.numpy();fit=np.arange(len(lindices))%5!=0
    source=Path(meta['source']);timeline=read_json(source/'frame_selection.json')
    times={r['name']:r['timestampSeconds'] for r in timeline['selectedFrames']}
    if timeline['captureSha256']!=conf['sourceSha256']:raise ValueError('pose_audit_source_mismatch')
    ref=read_json(run/'portrait.view.json')['sourceFrame'];refi=index[ref]
    refcenter=-oldF[refi,:3,:3].T@oldF[refi,:3,3];refangle=np.arctan2(refcenter[0],refcenter[2])
    rows={};domain={};image_cache={};hashes={}
    for path in (run/'config.json',prepared/'preparation.json',prepared/'local_geometry.npz',source/'face_landmarks.npz',source/'frame_selection.json'):
        hashes[str(path)]=digest(path)
    with np.load(source/'face_landmarks.npz') as a:rawmarks={n:a[n].copy() for n in names}
    out.mkdir(parents=True)
    for name in names:
        i=index[name];F=oldF[i];mesh=g['meshes'][i]
        path=prepared/'rectified_observations'/(name+'.npz');hashes[str(path)]=digest(path)
        with np.load(path,allow_pickle=False) as a:old={k:a[k].copy() for k in a.files}
        classes,confidence,outside,labels=original_semantics(prepared,meta,name,K,old)
        face=observed_face_domain(classes,confidence,outside,labels)
        if mask_hash(face)!=conf['observedFaceDomain']['maskHashes'][name]:raise ValueError('pose_audit_mask_changed')
        domain[name]=face&(classes==3)&(confidence>=.7)&~labels['hair_visible']&~labels['glasses_visible']&~outside
        points,cosine=triangle_landmarks(mesh,faces,lfaces,lbary,F)
        observed=g['marks'][i][lindices];pred,depth=project(points,F,K);err=np.linalg.norm(pred-observed,axis=-1)
        rect=cv2.undistortPoints(rawmarks[name].reshape(-1,1,2),K,np.asarray(meta['sourceDistortion']),P=K).reshape(-1,2)
        remaperror=float(np.max(np.abs(rect-g['marks'][i])))
        if remaperror>1e-5:raise ValueError('pose_audit_rectified_landmark_contract')
        pix=np.rint(observed).astype(int);h,w=face.shape;inside=(pix[:,0]>=0)&(pix[:,0]<w)&(pix[:,1]>=0)&(pix[:,1]<h)
        xx=pix[:,0].clip(0,w-1);yy=pix[:,1].clip(0,h-1)
        skin=inside&domain[name][yy,xx]
        reliability=np.where(skin&(cosine>.2),confidence[yy,xx]*np.clip(cosine,0,1),0)
        if roles[name]=='train' and name!=ref:
            candidate[i],proposal=bounded_pose_candidate(points,observed,F,K,fit,reliability)
        else:proposal={'status':'reference_fixed' if name==ref else 'development_pose_unchanged','acceptedForTraining':False}
        center=-F[:3,:3].T@F[:3,3];angle=np.arctan2(center[0],center[2])-refangle
        groups={'all105':np.ones(len(err),bool),'fit84':fit,'reserved21':~fit,
            'prior_back_facing':cosine<=0,'prior_grazing':(cosine>0)&(cosine<=.2),
            'prior_front_facing':cosine>.2,'observed_confident_skin':skin,
            'skin_front_fit':skin&(cosine>.2)&fit,'not_confident_skin':~skin}
        rows[name]={'role':roles[name],'time':times[name],'relativeLocalCameraAzimuth':float(np.degrees(np.arctan2(np.sin(angle),np.cos(angle)))),
            'errorByDomain':{label:stats(err[mask]) for label,mask in groups.items()},
            'targetRectificationMaxAbsPixels':remaperror,'proposal':proposal,
            'perLandmark':{'mediapipeIds':lindices.tolist(),'errorPx':err.tolist(),'cosine':cosine.tolist(),
                'fit':fit.tolist(),'observedSkin':skin.tolist(),'reliability':reliability.tolist()}}
    eligible=[]
    for start in range(len(train)-2):
        triple=train[start:start+3]
        angles=np.asarray([rows[n]['relativeLocalCameraAzimuth'] for n in triple])
        if times[triple[-1]]-times[triple[0]]<=4.5 and np.ptp(angles)<=15:
            eligible.append(triple)
    chosen=[eligible[i] for i in np.unique(np.linspace(0,len(eligible)-1,min(6,len(eligible))).round().astype(int))] if eligible else []
    sift=cv2.SIFT_create(nfeatures=800,contrastThreshold=.006,edgeThreshold=12)
    feature={};feature_receipt={}
    for name in sorted(set(n for t in chosen for n in t)):
        path=prepared/'rectified_observations'/name;hashes[str(path)]=digest(path)
        rgb=cv2.cvtColor(cv2.imread(str(path)),cv2.COLOR_BGR2RGB);image_cache[name]=rgb
        mask=cv2.erode(domain[name].astype(np.uint8),np.ones((7,7),np.uint8))*255
        gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        keys,_=sift.detectAndCompute(gray,mask)
        points,desc,receipt=native_face_features(gray,mask,sift)
        receipt['fullCanvasMaskedDetectorCount']=len(keys)
        feature_receipt[name]=receipt;feature[name]=(points,desc)
    windows=[];tracks=[]
    for wi,triple in enumerate(chosen):
        a,b,c=triple;fa,fb,fc=[feature[n] for n in triple]
        cycles=three_view_cycles(mutual_ratio_matches(fa[1],fb[1]),mutual_ratio_matches(fb[1],fc[1]),mutual_ratio_matches(fa[1],fc[1]))
        cycles=cycles[:150];rows_window=[]
        for track_id,cycle in enumerate(cycles):
            measured=np.stack([feature[n][0][j] for n,j in zip(triple,cycle)])
            binding=source_ray_binding(measured[0],g['meshes'][index[a]],faces,oldF[index[a]],K)
            if binding is None:continue
            face_id,bary=binding;points=np.stack([(g['meshes'][index[n]][faces[face_id]]*bary[:,None]).sum(0) for n in triple])
            projected=np.stack([project(point[None],oldF[index[n]],K)[0][0] for point,n in zip(points,triple)])
            frozen=np.stack([project(points[0:1],oldF[index[n]],K)[0][0] for n in triple])
            # The old source anchor stays fixed for both candidates: source
            # motion therefore counts too, rather than reconstructing each ray.
            corrected=np.stack([project(point[None],candidate[index[n]],K)[0][0] for point,n in zip(points,triple)])
            row={'window':wi,'names':triple,'sourceKeypoint':int(cycle[0]),'triangle':int(face_id),'bary':bary.tolist(),
                'measured':measured.tolist(),'originalError':np.linalg.norm(projected-measured,axis=-1).tolist(),
                'candidateError':np.linalg.norm(corrected-measured,axis=-1).tolist(),
                'frozenExpressionMeshError':np.linalg.norm(frozen-measured,axis=-1).tolist(),
                'meshDeformationProjectedPixels':np.linalg.norm(frozen-projected,axis=-1).tolist()}
            tracks.append(row);rows_window.append(row)
        q=lambda key,pos:stats([r[key][pos] for r in rows_window])
        windows.append({'names':triple,'spanSeconds':times[c]-times[a],'cycles':len(cycles),'surfaceAnchors':len(rows_window),
            'oldSource':q('originalError',0),'newSource':q('candidateError',0),
            'oldTarget':q('originalError',1),'newTarget':q('candidateError',1),
            'oldThird':q('originalError',2),'newThird':q('candidateError',2),
            'frozenExpressionTarget':q('frozenExpressionMeshError',1),'frozenExpressionThird':q('frozenExpressionMeshError',2),
            'expressionMotionTarget':q('meshDeformationProjectedPixels',1),'expressionMotionThird':q('meshDeformationProjectedPixels',2)})
        if rows_window:
            views=[]
            for vi,name in enumerate(triple):
                img=image_cache[name].copy()
                for r in rows_window:
                    xy=np.rint(r['measured'][vi]).astype(int);cv2.circle(img,tuple(xy),2,(0,255,120),-1)
                y,x=np.where(domain[name]);views.append(img[y.min():y.max()+1,x.min():x.max()+1].astype(np.float32)/255.)
            size=(400,500);views=[cv2.resize(v,size,interpolation=cv2.INTER_AREA) for v in views]
            _save_strip(out/('window-'+str(wi)+'.png'),views,triple)
    np.savez_compressed(out/'bounded-pose-candidates.npz',names=np.asarray(names),roles=g['roles'],F_before=oldF,F_candidate=candidate,K=K,
        reference=np.asarray(ref),sourceHash=np.asarray(meta['sourceHash']))
    report={'run':str(run),'sourceHash':meta['sourceHash'],'reference':ref,'views':rows,'windows':windows,
        'tracks':tracks,'featureExtraction':feature_receipt,'inputHashes':hashes,'cameraContract':'native rectified 1080x1920; fixed full K; model-space F only',
        'textureMethod':'SIFT mutual .75 ratio plus actual direct three-view descriptor cycle; no LK/no image warp',
        'windowRule':{'maxSpanSeconds':4.5,'maxRelativeAzimuthSpread':15,'maximumWindows':6,'maximumTracksPerWindow':150},
        'zeroTraining':True,'gpuUsed':False,'acceptedForTraining':False,
        'limitations':['Landmark visibility comes from the template prior, not measured first-surface depth.',
            'The physical-track anchor intersects a prior mesh once; it is not independently triangulated geometry.',
            'Reserved landmark residuals and independent SIFT targets are not final independent audit images.',
            'Expression comparison is diagnostic, not permission to freeze genuine expression motion.',
            'Candidate F is only a sidecar proposal and is never applied to prepared or published assets.']}
    for path,expected in hashes.items():
        if digest(path)!=expected:raise ValueError('pose_audit_input_changed:'+path)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':'CPU pose and texture reliability complete','views':len(rows),'windows':len(windows),'tracks':len(tracks)}))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--output',required=True)
    audit(**vars(parser.parse_args()))
