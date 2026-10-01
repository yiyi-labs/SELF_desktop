"""Shared measured XYZ and independent bounded body motion; CPU stage.
Depth predictions are not required or treated as surface truth. World C stays
fixed. All fits retain a third observation and data-only depth information.
"""
import hashlib
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from scipy.sparse import lil_matrix,eye
from reconstruction_dense_contract import project,rigid_check
from reconstruction_surface_evidence import triangulate_track

def deduplicate_tracks(tracks,pixels=1.5):
    kept=[];duplicates=[]
    for t in sorted(tracks,key=lambda t:(-len(t['observations']),t['id'])):
        obs={o['name']:np.asarray(o['uv']) for o in t['observations']};hit=None
        for old in kept:
            common=[np.linalg.norm(obs[o['name']]-o['uv'])<pixels for o in old['observations'] if o['name'] in obs]
            if len(common)>=3 and sum(common)>=3 and old['region']==t['region']:hit=old['id'];break
        if hit:duplicates.append(dict(id=t['id'],sameAs=hit))
        else:kept.append(t)
    return kept,duplicates

def motion_matrices(names,timestamps,reference,raw,pivot,scale,max_rotation=3.,max_translation=.02):
    times=np.asarray([timestamps[n] for n in names],float)
    if not np.isfinite(times).all() or len(set(names))!=len(names):raise ValueError('motion_identity')
    duration=max(float(np.ptp(times)),1e-9);B={}
    for n in names:
        tau=(timestamps[n]-timestamps[reference])/duration
        R=Rotation.from_rotvec(np.asarray(raw[:3])*np.radians(max_rotation)*tau).as_matrix()
        T=np.eye(4);T[:3,:3]=R;T[:3,3]=pivot-R@pivot+np.asarray(raw[3:])*scale*max_translation*tau
        B[n]=rigid_check(T)
    return B

def quadratic_motion_matrices(names,timestamps,reference,raw,pivot,scale,max_rotation=3.,max_translation=.02):
    """Twelve shared coefficients, fixed scale/reference, no per-frame poses.
    tau and tau^2 are globally shared within the observed short window.
    The normalized basis bounds each coordinate; vector norms can be sqrt(3) larger.
    """
    raw=np.asarray(raw,float).reshape(2,6)
    times=np.asarray([timestamps[n] for n in names],float)
    if not np.isfinite(times).all() or len(set(names))!=len(names):raise ValueError('motion_identity')
    duration=max(float(np.ptp(times)),1e-9);B={}
    for n in names:
        tau=(timestamps[n]-timestamps[reference])/duration
        v=(raw[0]*tau+raw[1]*tau*tau)/2
        R=Rotation.from_rotvec(v[:3]*np.radians(max_rotation)).as_matrix()
        T=np.eye(4);T[:3,:3]=R;T[:3,3]=pivot-R@pivot+v[3:]*scale*max_translation
        B[n]=rigid_check(T)
    return B


def measured_geometry(tracks,cameras,K,timestamps,*,body=False,scale=1.,max_nfev=60,motion_model='velocity'):
    tracks,duplicates=deduplicate_tracks(tracks);names=sorted(cameras,key=lambda n:(timestamps[n],n));reference=names[len(names)//2]
    records=[];rejected=[]
    for t in tracks:
        obs=sorted([o for o in t['observations'] if o['name'] in cameras],key=lambda o:(timestamps[o['name']],o['name']))
        if len(obs)<4:rejected.append(dict(id=t['id'],reason='fewer_than_four_real_observations'));continue
        centres=np.array([-cameras[o['name']][:3,:3].T@cameras[o['name']][:3,3] for o in obs[:-1]])
        if np.linalg.norm(np.ptp(centres,axis=0))<1e-9:
            rejected.append(dict(id=t['id'],reason='no_translational_depth_evidence'));continue
        train={**t,'observations':obs[:-1]}
        try:x,quality=triangulate_track(train,cameras,K)
        except (ValueError,np.linalg.LinAlgError):rejected.append(dict(id=t['id'],reason='triangulation_numeric'));continue
        if not quality['positive'] or quality['p90Error']>12 or quality['maxAngleDegrees']<1:
            rejected.append(dict(id=t['id'],reason='initial_geometry_not_supported',quality=quality));continue
        withheld=int.from_bytes(hashlib.sha256(t['id'].encode()).digest()[:4],'little')%5==0
        records.append({**t,'observations':obs,'initial':x,'initialQuality':quality,'withheldTrack':withheld})
    if not records:return dict(records=[],rejections=rejected,duplicates=duplicates,blocked='no_triangulatable_tracks',motionAccepted=False,B={n:np.eye(4).tolist() for n in names})
    pivot=np.median([r['initial'] for r in records],axis=0);fitting=[r for r in records if not r['withheldTrack']];N=len(fitting)
    if motion_model not in ('velocity','quadratic'):raise ValueError('unknown_motion_model')
    parameter_motion=(12 if motion_model=='quadratic' else 6) if body else 0;X=np.asarray([r['initial'] for r in fitting]);obs=[(i,o) for i,r in enumerate(fitting) for o in r['observations'][:-1]]
    metric=np.median([max(project(r['initial'][None],K,cameras[r['observations'][0]['name']])[1][0],1e-6)/K[0,0] for r in fitting]) if N else scale*.001
    def bodies(v):return (quadratic_motion_matrices if motion_model=='quadratic' else motion_matrices)(names,timestamps,reference,v,pivot,scale) if body else {n:np.eye(4) for n in names}
    def datares(raw):
        B=bodies(raw[:parameter_motion]) if body else bodies(None);xx=X+raw[parameter_motion:].reshape(N,3)*metric
        return np.concatenate([(project(xx[i:i+1],K,cameras[o['name']]@B[o['name']])[0][0]-o['uv'])/o['sigma'] for i,o in obs])
    def residual(raw):
        r=datares(raw);prior=raw[parameter_motion:]/20
        return np.r_[r,raw[:parameter_motion]*.3 if body else [],prior]
    count=parameter_motion+3*N;J=lil_matrix((2*len(obs)+count,count),dtype=int)
    for j,(i,o) in enumerate(obs):
        if body:J[2*j:2*j+2,:parameter_motion]=1
        J[2*j:2*j+2,parameter_motion+3*i:parameter_motion+3*i+3]=1
    J[2*len(obs):,:]=eye(count)
    raw=np.zeros(count);bound=np.r_[np.ones(parameter_motion),np.full(3*N,20.)]
    if N>=3:
        fit=least_squares(residual,raw,jac_sparsity=J.tocsr(),bounds=(-bound,bound),loss='soft_l1',f_scale=1.,x_scale='jac',max_nfev=max_nfev)
        raw=fit.x;optimizer=dict(nfev=fit.nfev,success=bool(fit.success),cost=float(fit.cost),motionRaw=raw[:parameter_motion].tolist() if body else [],metricPerPixel=float(metric))
    else:optimizer=dict(nfev=0,success=False,reason='insufficient_fit_tracks')
    B=bodies(raw[:parameter_motion] if body else None);G={n:cameras[n]@B[n] for n in names};output=[]
    for t in records:
        fitobs=t['observations'][:-1];x,q=triangulate_track({**t,'observations':fitobs},G,K);third=t['observations'][-1]
        uv,_=project(x[None],K,G[third['name']]);err=float(np.linalg.norm(uv[0]-third['uv']))
        uv0,_=project(t['initial'][None],K,cameras[third['name']]);err0=float(np.linalg.norm(uv0[0]-third['uv']))
        def pointres(p):return np.concatenate([(project(p[None],K,G[o['name']])[0][0]-o['uv'])/o['sigma'] for o in fitobs])
        eps=max(metric*.001,1e-9);jj=np.stack([(pointres(x+np.eye(3)[k]*eps)-pointres(x-np.eye(3)[k]*eps))/(2*eps) for k in range(3)],1);sv=np.linalg.svd(jj,compute_uv=False)
        accepted=bool(q['positive'] and q['p90Error']<=2.5 and err<=3 and q['maxAngleDegrees']>=2 and sv[-1]/sv[0]>=.01)
        output.append(dict(id=t['id'],region=t['region'],observations=t['observations'],xyz=x.tolist(),initialXYZ=t['initial'].tolist(),quality=q,thirdError=err,initialThirdError=err0,dataSingularValues=sv.tolist(),accepted=accepted,withheldTrack=t['withheldTrack']))
    hold=[r for r in output if r['withheldTrack']];test=[r['thirdError'] for r in hold];old=[r['initialThirdError'] for r in hold]
    regions={r['region'] for r in output if r['accepted']};motion_ok=bool(body and len(test)>=4 and np.quantile(test,.9)<=3 and np.median(test)<=np.median(old)+.25 and len([r for r in output if r['accepted']])>=30 and any(s.startswith('upper_') for s in regions) and any(s.startswith('lower_') for s in regions))
    return dict(records=output,duplicates=duplicates,rejections=rejected,optimizer=optimizer,reference=reference,pivot=pivot.tolist(),B={n:B[n].tolist() for n in names},cameras={n:G[n].tolist() for n in names},worldC={n:cameras[n].tolist() for n in names},motionAccepted=motion_ok,withheldThirdP90=float(np.quantile(test,.9)) if test else None,withheldBeforeP90=float(np.quantile(old,.9)) if old else None,knownCamerasOverwritten=False,oneScale=True,motionModel=motion_model,geometryIsMeasuredHypothesis=True)
