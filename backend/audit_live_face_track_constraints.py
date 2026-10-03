"""CPU-only, bounded F/shared-anchor diagnostics from cached physical tracks."""
from pathlib import Path
import argparse
import json
import shutil
import cv2
import numpy as np
import scipy
import torch
from compare_live_opaque_person_runs import resolve,read_json,digest,_save_strip
from flame_open_model import FlameOpen
from reconstruction_face_pose_reliability import project,triangle_landmarks,source_ray_binding
from reconstruction_face_track_constraints import (texture_pose_candidate,shared_surface_candidate,
    triangle_basis,TrackConstraintConfig,unique_physical_tracks)


def stats(a):
    a=np.asarray(a,float).ravel()
    return {'count':len(a),'median':float(np.median(a)) if len(a) else None,
        'p90':float(np.quantile(a,.9)) if len(a) else None,'mean':float(np.mean(a)) if len(a) else None}


def audit(run,measurements,output):
    run=resolve(run);measurements=resolve(measurements);out=resolve(output)
    if out.exists():raise FileExistsError(out)
    cfg=read_json(run/'config.json');prepared=resolve(cfg['prepared']);meta=read_json(prepared/'preparation.json')
    observed=read_json(measurements/'report.json')
    if observed['sourceHash']!=meta['sourceHash']:raise ValueError('track_solve_source_mismatch')
    with np.load(prepared/'local_geometry.npz',allow_pickle=False) as a:g={k:a[k].copy() for k in a.files}
    names=g['names'].tolist();index={n:i for i,n in enumerate(names)};roles=dict(zip(names,g['roles'].tolist()))
    state=torch.load(run/'trained-state.pt',map_location='cpu',weights_only=True)
    residual=state['model']['portrait.surface_residual'].detach().numpy()
    meshes=g['meshes']+residual[None];Fs=g['F'].copy();candidate=Fs.copy();K=g['K']
    model=FlameOpen(24,12);faces=model.faces.numpy();li=model.landmark_indices.numpy()
    lf=model.landmark_faces.numpy();lb=model.barycentric.numpy();fit_marks=np.arange(len(li))%5!=0
    reference=observed['reference'];extent=float(np.ptp(meshes[index[reference]],axis=0).max())
    out.mkdir(parents=True);hashes={}
    for path in (run/'config.json',run/'trained-state.pt',prepared/'local_geometry.npz',measurements/'report.json'):
        hashes[str(path)]=digest(path)
    source=out/'algorithm-source';source.mkdir()
    for name in ('audit_live_face_track_constraints.py','reconstruction_face_track_constraints.py','reconstruction_face_pose_reliability.py'):
        p=Path(__file__).parent/name;shutil.copyfile(p,source/name);hashes[str(p)]=digest(p)
    windows=[];surface_rows=[];pose_rows={};sidecar=[]
    for wi,w in enumerate(observed['windows']):
        triple=w['names'];rawrows=[r for r in observed['tracks'] if r['window']==wi]
        rows,duplicates=unique_physical_tracks(rawrows)
        selected=[]
        for row in rows:
            bind=source_ray_binding(np.asarray(row['measured'][0]),meshes[index[triple[0]]],faces,Fs[index[triple[0]]],K)
            if bind is None:continue
            fi,bary=bind
            tri=np.stack([meshes[index[n]][faces[fi]] for n in triple])
            points=(tri*bary[None,:,None]).sum(1)
            bases=np.stack([triangle_basis(t) for t in tri]);measured=np.asarray(row['measured'])
            _,s=shared_surface_candidate(points,bases,measured,Fs[[index[n] for n in triple]],K,extent)
            s.update(window=wi,names=triple,sourceKeypoint=row['sourceKeypoint'],triangle=int(fi),bary=bary.tolist())
            surface_rows.append(s);sidecar.append((wi,fi,bary,np.asarray(s['offsetModelUnits'])))
            selected.append({'row':row,'points':points,'measured':measured,'surface':s})
        # Entire physical tracks are held out; third image also remains unused
        # by every shared-surface solve above.
        fit=np.arange(len(selected))%3!=0
        window={'names':triple,'tracks':len(selected),'descriptorTracks':len(rawrows),
            'coincidentOrientationDuplicates':duplicates,'fitTracks':int(fit.sum()),'reservedTracks':int((~fit).sum()),'pose':{}}
        for vi,n in enumerate(triple):
            pts=np.stack([r['points'][vi] for r in selected]);uv=np.stack([r['measured'][vi] for r in selected])
            newF,pr=texture_pose_candidate(pts,uv,Fs[index[n]],K,fit,fixed=n==reference)
            original=project(pts,Fs[index[n]],K)[0];new=project(pts,newF,K)[0]
            olderr=np.linalg.norm(original-uv,axis=1);newerr=np.linalg.norm(new-uv,axis=1)
            lpoints,_=triangle_landmarks(meshes[index[n]],faces,lf,lb,Fs[index[n]])
            lmold=np.linalg.norm(project(lpoints,Fs[index[n]],K)[0]-g['marks'][index[n]][li],axis=1)
            lmnew=np.linalg.norm(project(lpoints,newF,K)[0]-g['marks'][index[n]][li],axis=1)
            fullspan=np.ptp(g['marks'][index[n]][li],axis=0)
            trackspan=np.ptp(uv[fit],axis=0) if fit.any() else np.zeros(2)
            # These conservative a-priori gates require independent track
            # improvement, landmark stability and spread over a face, not one
            # tiny patch. No failed candidate is written into prepared F.
            enough=(~fit).sum()>=4 and fit.sum()>=10
            improved=enough and np.median(newerr[~fit])<=np.median(olderr[~fit])-.15 and np.quantile(newerr[~fit],.9)<=np.quantile(olderr[~fit],.9)+.25
            stable=np.quantile(lmnew[~fit_marks],.9)<=np.quantile(lmold[~fit_marks],.9)+.25 and np.median(lmnew[fit_marks])<=np.median(lmold[fit_marks])+.25
            spread=bool(np.all(trackspan/np.maximum(fullspan,1)>.25))
            accepted=bool(improved and stable and spread and roles[n]=='train' and n!=reference)
            candidate[index[n]]=newF if accepted else Fs[index[n]]
            pr.update(oldFit=stats(olderr[fit]),newFit=stats(newerr[fit]),oldReserved=stats(olderr[~fit]),newReserved=stats(newerr[~fit]),
                oldFitLandmarks=stats(lmold[fit_marks]),newFitLandmarks=stats(lmnew[fit_marks]),
                oldReservedLandmarks=stats(lmold[~fit_marks]),newReservedLandmarks=stats(lmnew[~fit_marks]),
                trackFaceExtentRatio=(trackspan/np.maximum(fullspan,1)).tolist(),acceptedForBoundedAppearanceTrial=accepted,
                gates={'enoughIndependentTracks':bool(enough),'reservedTrackImprovement':bool(improved),'landmarkGuard':bool(stable),'faceSpread':spread})
            window['pose'][n]=pr;pose_rows[n]=pr
        for name,label in [('oldErrors','before'),('newErrors','after')]:
            window['shared'+label]={part:stats([r['surface'][name][vi] for r in selected]) for vi,part in enumerate(('source','target','third'))}
        window['dataJacobianWeakModeTracks']=sum(r['surface']['observableModes']<3 for r in selected)
        # Visualize actual source structures; cyan observations, yellow old
        # shared-surface projections, magenta bounded shared-point proposals.
        views=[]
        for vi,n in enumerate(triple):
            rgb=cv2.cvtColor(cv2.imread(str(prepared/'rectified_observations'/n)),cv2.COLOR_BGR2RGB)
            for r in selected:
                olduv=project(r['points'][vi:vi+1],Fs[index[n]],K)[0][0]
                tri=meshes[index[n]][faces[r['surface']['triangle']]]
                pnew=r['points'][vi]+triangle_basis(tri)@np.asarray(r['surface']['offsetModelUnits'])
                newuv=project(pnew[None],Fs[index[n]],K)[0][0]
                for xy,color in ((r['measured'][vi],(0,255,160)),(olduv,(255,210,0)),(newuv,(255,70,230))):
                    cv2.circle(rgb,tuple(np.rint(xy).astype(int)),2,color,1)
            marks=g['marks'][index[n]][li];lo=np.maximum(np.floor(marks.min(0)-25).astype(int),0)
            hi=np.minimum(np.ceil(marks.max(0)+25).astype(int),np.array([rgb.shape[1],rgb.shape[0]]))
            crop=rgb[lo[1]:hi[1],lo[0]:hi[0]]
            canvas=np.zeros((800,650,3),np.float32);hh,ww=crop.shape[:2]
            scale=min(1.,800/hh,650/ww);crop=cv2.resize(crop,(round(ww*scale),round(hh*scale)))
            canvas[:crop.shape[0],:crop.shape[1]]=crop.astype(np.float32)/255.;views.append(canvas)
        _save_strip(out/('tracks-window-'+str(wi)+'.png'),views,triple)
        windows.append(window)
    # Exact untouched development/reference matrices, including non-window F.
    untouched=[i for i,n in enumerate(names) if roles[n]!='train' or n==reference or n not in pose_rows]
    if not np.array_equal(candidate[untouched],Fs[untouched]):raise ValueError('unselected_pose_changed')
    np.savez_compressed(out/'gated-pose-candidates.npz',names=np.asarray(names),roles=g['roles'],F_before=Fs,F_candidate=candidate,K=K,
        reference=np.asarray(reference),sourceHash=np.asarray(meta['sourceHash']))
    np.savez_compressed(out/'shared-anchor-candidates.npz',window=np.asarray([r[0] for r in sidecar]),
        triangle=np.asarray([r[1] for r in sidecar]),bary=np.stack([r[2] for r in sidecar]),offset=np.stack([r[3] for r in sidecar]))
    report={'run':str(run),'measurements':str(measurements),'sourceHash':meta['sourceHash'],'inputHashes':hashes,
        'config':TrackConstraintConfig().__dict__,'software':{'opencv':cv2.__version__,'scipy':scipy.__version__,'torch':torch.__version__},
        'modelState':'current trained shared surface = prepared per-frame mesh + checkpoint portrait.surface_residual; fixed original F/K',
        'surfaceResidualMaxModelUnits':float(np.linalg.norm(residual,axis=1).max()),'faceExtentModelUnits':extent,
        'windows':windows,'surfaceTracks':surface_rows,'acceptedPoseViews':[n for n,r in pose_rows.items() if r['acceptedForBoundedAppearanceTrial']],
        'fixedDevelopmentReferenceAndOtherViews':True,'gpuUsed':False,'zeroAppearanceTraining':True,
        'limitations':['Source-ray intersection supplies a prior anchor, not measured true depth.',
            'Shared per-track offsets diagnose surface feasibility; they are not yet a connected triangle-surface update.',
            'Third observations are independent of each geometry solve, but belong to research-used source material.',
            'No production preparation, renderer, appearance, topology or old asset is changed.']}
    for p,h in hashes.items():
        if digest(p)!=h:raise ValueError('track_audit_input_changed:'+p)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':'complete','tracks':len(surface_rows),'acceptedPoseViews':report['acceptedPoseViews'],
        'windows':[{'names':w['names'],'before':w['sharedbefore']['third'],'after':w['sharedafter']['third']} for w in windows]}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--measurements',required=True);p.add_argument('--output',required=True)
    audit(**vars(p.parse_args()))
