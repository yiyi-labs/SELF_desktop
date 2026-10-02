"""Body-motion admission from physical tracks before static triangulation.
An initial static residual is not a valid rejection for a moving person.
Fixed cameras, scale and reference; shared X and bounded time-basis motion.
Existing frozen source data only. Failed motion never enables depth transport.
"""
from pathlib import Path
import argparse,json,time,shutil,hashlib
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import cKDTree
from scipy.sparse import lil_matrix,eye
from reconstruction_dense_contract import project,unproject,bilinear
from reconstruction_motion_geometry import motion_matrices
from reconstruction_components_v3 import save_json,sha


def dedup_measured(tracks,threshold=1.5):
    kept=[];duplicates=[]
    for t in sorted(tracks,key=lambda t:(-len(t['observations']),t['id'])):
        obs={o['name']:np.asarray(o['uv']) for o in t['observations']};hit=None
        for old in kept:
            shared=[np.linalg.norm(obs[o['name']]-o['uv'])<threshold for o in old['observations'] if o['name'] in obs]
            if sum(shared)>=3:hit=old['id'];break
        if hit is None:kept.append(t)
        else:duplicates.append(dict(id=t['id'],sameAs=hit))
    return kept,duplicates


def geometry_training_pool(raw,plan,world_names):
    """Unused prepared training observations can measure geometry, never holdouts.
    A colour minibatch list is not the complete eligible measurement domain.
    """
    held=set(plan['development'])|set(plan['audit'])
    original_train={str(n) for i,n in enumerate(raw['names']) if str(raw['roles'][i])=='train'}
    return (original_train&set(world_names))-held


def solve_body_tracks(tracks,C,K,timestamps,reference,scale,initial,*,max_nfev=80,motion_basis="velocity",rotation_bound=4.,xyz_bound_fraction=.05):
    """No pre-fit static reprojection gate. Real image measurements are fixed.
    Conditional source depth initializes X; it is a prior, not geometric truth.
    A third observation and entire track groups stay outside the motion fit.
    """
    from reconstruction_dense_contract import rigid_check
    if reference not in C or not np.isfinite(scale) or scale<=0:raise ValueError('body_reference_or_scale')
    if not 0<rotation_bound<=8:raise ValueError('finite_body_rotation_bound')
    if not .01<=xyz_bound_fraction<=.15:raise ValueError('finite_body_seed_uncertainty')
    if set(C)!=set(timestamps) or not np.isfinite(list(timestamps.values())).all() or np.ptp(list(timestamps.values()))<=0:raise ValueError('body_timestamps')
    K=np.asarray(K,float)
    if K.shape!=(3,3) or not np.isfinite(K).all() or K[0,0]<=0 or K[1,1]<=0:raise ValueError('body_intrinsics')
    for matrix in C.values():rigid_check(matrix)
    names=sorted(C,key=lambda n:timestamps[n]);tracks,dup=dedup_measured(tracks)
    records=[]
    for t in tracks:
        obs=sorted([o for o in t['observations'] if o['name'] in C],key=lambda o:timestamps[o['name']])
        if len(obs)<4 or t['id'] not in initial:continue
        x=np.asarray(initial[t['id']],float)
        if not np.isfinite(x).all():continue
        withheld=int.from_bytes(hashlib.sha256(t['id'].encode()).digest()[:4],'little')%5==0
        records.append({**t,'observations':obs,'x0':x,'withheld':withheld})
    if len(records)<12:return dict(blocked='insufficient_distinct_measured_tracks',count=len(records),duplicates=dup,motionAccepted=False)
    fit=[r for r in records if not r['withheld']];N=len(fit);x0=np.array([r['x0'] for r in fit]);pivot=np.median(x0,0)
    z=np.array([project(r['x0'][None],K,C[reference])[1][0] for r in fit]);metric=z/K[0,0]
    if np.any(metric<=0):raise ValueError('body_seed_positive_depth')
    bounds=np.maximum(z*xyz_bound_fraction,metric*8)
    obs=[(i,o) for i,r in enumerate(fit) for o in r['observations'][:-1]]
    if motion_basis not in ('velocity','acceleration','two-node','temporal-knots'):raise ValueError('motion_basis')
    motion_dim=6 if motion_basis=='velocity' else 18 if motion_basis=='temporal-knots' else 12
    all_y=np.array([project(r['x0'][None],K,C[reference])[0][0,1] for r in records]);lo,hi=np.quantile(all_y,[.2,.8])
    if hi<=lo:raise ValueError('body_spatial_support')
    for r,y in zip(records,all_y):
        t=float(np.clip((y-lo)/(hi-lo),0,1));r['upperWeight']=1-t*t*(3-2*t)
    def camera_for(b,name,r):
        matrix=b[name]
        if motion_basis=='two-node':matrix=matrix[0]*r['upperWeight']+matrix[1]*(1-r['upperWeight'])
        return C[name]@matrix
    def bodies(raw):
        if motion_basis=='temporal-knots':
            from scipy.spatial.transform import Rotation
            # Four shared time knots, first coefficient fixed to remove the
            # constant-pose gauge. No per-frame scale, point or image warp.
            knots=np.linspace(min(timestamps.values()),max(timestamps.values()),4)
            values=np.vstack([np.zeros(6),raw[:18].reshape(3,6)])
            vref=np.array([np.interp(timestamps[reference],knots,values[:,k]) for k in range(6)])
            result={}
            for name in names:
                v=.5*(np.array([np.interp(timestamps[name],knots,values[:,k]) for k in range(6)])-vref)
                R=Rotation.from_rotvec(v[:3]*np.radians(rotation_bound)).as_matrix();T=np.eye(4)
                T[:3,:3]=R;T[:3,3]=pivot-R@pivot+v[3:]*scale*.025;result[name]=T
            return result
        if motion_basis=='two-node':
            nodes=[motion_matrices(names,timestamps,reference,raw[k*6:(k+1)*6],pivot,scale,max_rotation=rotation_bound,max_translation=.025) for k in range(2)]
            return {n:np.stack([nodes[0][n],nodes[1][n]]) for n in names}
        if motion_basis=='velocity':return motion_matrices(names,timestamps,reference,raw[:6],pivot,scale,max_rotation=rotation_bound,max_translation=.025)
        from scipy.spatial.transform import Rotation
        result={};duration=max(timestamps.values())-min(timestamps.values())
        coefficients=raw[:12].reshape(2,6)
        for name in names:
            tau=(timestamps[name]-timestamps[reference])/duration
            v=coefficients[0]*tau+.5*coefficients[1]*tau*tau
            R=Rotation.from_rotvec(v[:3]*np.radians(rotation_bound)).as_matrix();T=np.eye(4)
            T[:3,:3]=R;T[:3,3]=pivot-R@pivot+v[3:]*scale*.025;result[name]=T
        return result
    def datares(raw):
        b=bodies(raw);x=x0+raw[motion_dim:].reshape(N,3)*bounds[:,None]
        return np.concatenate([(project(x[i:i+1],K,camera_for(b,o['name'],fit[i]))[0][0]-o['uv'])/o.get('sigma',.75) for i,o in obs])
    def residual(raw):
        coupling=(raw[:6]-raw[6:12])*.5 if motion_basis=='two-node' else np.diff(np.vstack([np.zeros(6),raw[:18].reshape(3,6)]),n=2,axis=0).ravel()*.5 if motion_basis=='temporal-knots' else []
        return np.r_[datares(raw),raw[:motion_dim]*.3,raw[motion_dim:]*.2,coupling]
    coupling_size=6 if motion_basis=='two-node' else 12 if motion_basis=='temporal-knots' else 0
    cols=motion_dim+N*3;J=lil_matrix((2*len(obs)+cols+coupling_size,cols),dtype=int)
    for row,(i,o) in enumerate(obs):J[row*2:row*2+2,:motion_dim]=1;J[row*2:row*2+2,motion_dim+i*3:motion_dim+3+i*3]=1
    J[2*len(obs):2*len(obs)+cols,:]=eye(cols)
    if coupling_size:J[-coupling_size:,:motion_dim]=1
    result=least_squares(residual,np.zeros(cols),jac_sparsity=J.tocsr(),bounds=(-np.ones(cols),np.ones(cols)),loss='soft_l1',f_scale=1.,max_nfev=max_nfev,x_scale='jac',ftol=1e-5,xtol=1e-5,gtol=1e-5)
    B=bodies(result.x);output=[];old_err=[];new_err=[];hold=[];fit_errors=[];motion_information=np.zeros((motion_dim,motion_dim))
    for r in records:
        x=r['x0'];z=project(x[None],K,C[reference])[1][0];bound=max(z*xyz_bound_fraction,z/K[0,0]*8)
        measurements=r['observations'][:-1]
        def fun(v):
            xx=x+v*bound
            return np.r_[np.concatenate([(project(xx[None],K,camera_for(B,o['name'],r))[0][0]-o['uv'])/o.get('sigma',.75) for o in measurements]),v*.2]
        # All points including withheld tracks use only fitting observations;
        # their last image never participates in motion or shared-X fitting.
        fitx=least_squares(fun,np.zeros(3),bounds=(-np.ones(3),np.ones(3)),loss='soft_l1',max_nfev=30)
        xx=x+fitx.x*bound;errors=[];before=[];rays=[];positive=True
        for o in r['observations']:
            uv0,z0=project(x[None],K,C[o['name']]);uv,z1=project(xx[None],K,camera_for(B,o['name'],r))
            positive &= bool(np.isfinite(uv).all() and z1[0]>0)
            errors.append(float(np.linalg.norm(uv[0]-o['uv'])));before.append(float(np.linalg.norm(uv0[0]-o['uv'])))
            centre=np.linalg.inv(camera_for(B,o['name'],r))[:3,3];d=xx-centre;rays.append(d/np.linalg.norm(d))
        eps=max(z/K[0,0]*.001,1e-9)
        def pfun(p):return np.concatenate([(project(p[None],K,camera_for(B,o['name'],r))[0][0]-o['uv'])/o.get('sigma',.75) for o in measurements])
        jj=np.stack([(pfun(xx+np.eye(3)[k]*eps)-pfun(xx-np.eye(3)[k]*eps))/(2*eps) for k in range(3)],1);sv=np.linalg.svd(jj,compute_uv=False)
        angle=float(np.degrees(np.arccos(np.clip((np.asarray(rays)@np.asarray(rays).T).min(),-1,1))))
        # Data-only Schur information eliminates each shared point's nuisance XYZ.
        # Priors and regularization must not manufacture observed body motion.
        if not r['withheld']:
            eps_motion=1e-4;pose_columns=[]
            for k in range(motion_dim):
                direction=np.zeros_like(result.x);direction[k]=eps_motion
                bp=bodies(result.x+direction);bm=bodies(result.x-direction)
                a=np.concatenate([(project(xx[None],K,camera_for(bp,o['name'],r))[0][0]-o['uv'])/o.get('sigma',.75) for o in measurements])
                b=np.concatenate([(project(xx[None],K,camera_for(bm,o['name'],r))[0][0]-o['uv'])/o.get('sigma',.75) for o in measurements])
                pose_columns.append((a-b)/(2*eps_motion))
            jm=np.stack(pose_columns,1);projected=jm-jj@(np.linalg.pinv(jj)@jm)
            motion_information+=projected.T@projected
        accepted=bool(positive and np.quantile(errors[:-1],.9)<=2.5 and errors[-1]<=3 and angle>=2 and sv[-1]/sv[0]>=.01)
        output.append(dict(id=r['id'],region=r.get('region','cloth'),names=[o['name'] for o in r['observations']],xyz=xx.tolist(),upperWeight=r['upperWeight'],initialXYZ=x.tolist(),normalizedSeedOffset=fitx.x.tolist(),seedBoundWorld=bound,errors=errors,before=before,withheld=r['withheld'],accepted=accepted,dataSingularValues=sv.tolist(),angleDegrees=angle))
        old_err.extend(before);new_err.extend(errors);fit_errors.extend(errors[:-1])
        if r['withheld']:hold.append(errors[-1])
    valid=[r for r in output if r['accepted']];regions={r['region'] for r in valid}
    eigen=np.linalg.eigvalsh(motion_information).clip(0);singular=np.sqrt(eigen)
    observed=bool(singular[-1]>0 and singular[0]/singular[-1]>=1e-3)
    gate=bool(observed and result.success and len(valid)>=30 and len(hold)>=4 and np.quantile(hold,.9)<=3 and any(r.startswith('upper_') for r in regions) and any(r.startswith('lower_') for r in regions))
    return dict(records=output,duplicates=dup,names=names,reference=reference,B={n:B[n].tolist() for n in names} if motion_basis!='two-node' else {},
        nodeTransforms={n:B[n].tolist() for n in names} if motion_basis=='two-node' else {},
        fieldBinding='fixed canonical material weights, shared across images; not per-view image warp',
        count=len(records),accepted=len(valid),motionDataSingularValues=singular.tolist(),motionDataCondition=float(singular[0]/singular[-1]) if singular[-1]>0 else 0.,
        motionDataObservable=observed,motionRotationBoundDegrees=rotation_bound,xyzBoundFraction=xyz_bound_fraction,acceptedDepthPriorsAsTruth=False,nfev=result.nfev,success=bool(result.success),motionBasis=motion_basis,velocity=result.x[:motion_dim].tolist(),
        medianBefore=float(np.median(old_err)),medianAfter=float(np.median(new_err)),p90Before=float(np.quantile(old_err,.9)),p90After=float(np.quantile(new_err,.9)),
        withheldThirdP90=float(np.quantile(hold,.9)) if hold else None,motionAccepted=gate,
        initialStaticErrorUsedForAdmission=False,sourceDepth='conditional prediction, not truth',fixed='C,K,scale,reference; no per-frame scale or free pose',published=False)


def run(prepared,complete,tracks,depth,out,motion_basis="velocity",rotation_bound=4.,xyz_bound_fraction=.05):
    import torch
    clock=time.perf_counter();out=Path(out);out.mkdir(parents=True,exist_ok=False);prep=Path(prepared);root=Path(depth)
    meta=json.loads((prep/'preparation.json').read_text());raw=dict(np.load(prep/'local_geometry.npz'));K=raw['K'];C={str(n):raw['C'][i] for i,n in enumerate(raw['world_names'])}
    ck=torch.load(Path(complete)/'candidate-final.pt',map_location='cpu',weights_only=False);body=ck['extra']['meta']
    if ck['contract']['sourceHash']!=meta['sourceHash']:raise ValueError('body_checkpoint_source_changed')
    measurements=json.loads(Path(tracks).read_text());manifest=json.loads((root/'manifest.json').read_text())
    if measurements['sourceHash']!=meta['sourceHash'] or manifest['sourceHash']!=meta['sourceHash']:raise ValueError('body_measurement_source_changed')
    plan_path=Path(ck['contract']['spec']['observations']);plan=json.loads(plan_path.read_text())
    current_train=geometry_training_pool(raw,plan,C)
    identity=json.loads((prep.parent.parent/meta['source']/'frame_manifest.audit.json').read_text())
    if identity['captureSha256']!=meta['sourceHash']:raise ValueError('body_timestamp_source_changed')
    timestamps={r['name']:r['timestampSeconds'] for r in identity['frames']}
    depth_names={r['imageName'] for r in manifest['observations'] if r['group']=='world' and r['scaleGatePassed']}
    # Pick a measured, short training window; never reuse names only because
    # a previous photometric B happened to use them. No image ID is a time.
    choices=[]
    for window in measurements['windows']:
        ns=[n for n in window if n in current_train]
        if len(ns)<4:continue
        usable=sum((t.get('region')=='cloth' or t.get('region','').startswith(('upper_','lower_'))) and len([o for o in t['observations'] if o['name'] in ns])>=4 and any(o['name'] in depth_names for o in t['observations'] if o['name'] in ns) for t in measurements['tracks'])
        choices.append((usable,ns))
    if not choices:raise ValueError('no_measured_body_window')
    _,names=max(choices,key=lambda r:r[0]);ts={n:timestamps[n] for n in names}
    middle=np.median(list(ts.values()));reference=min(set(names)&depth_names,key=lambda n:abs(ts[n]-middle))
    rows={r['imageName']:r for r in manifest['observations'] if r['group']=='world' and r['scaleGatePassed'] and r['imageName'] in names}
    cache={n:dict(np.load(root/r['file'])) for n,r in rows.items()};candidate=[];initial={}
    for t in measurements['tracks']:
        if t.get('region')!='cloth' and not t.get('region','').startswith(('upper_','lower_')):continue
        obs=[o for o in t['observations'] if o['name'] in names]
        if len(obs)<4:continue
        source=next((o for o in obs if o['name']==reference),next((o for o in obs if o['name'] in cache),obs[0]));n=source['name']
        if n not in cache:continue
        a=cache[n];uv=np.asarray(source['uv'],float);proc=(a['nativeToProcessed']@np.r_[uv,1.])[:2];z=bilinear(a['depth'],proc[None])[0]
        if not np.isfinite(z) or z<=0:continue
        x=unproject(uv[None],np.array([z]),K,C[n])[0]
        lab=dict(np.load(prep/'rectified_observations'/(n+'.npz')));yvals,xvals=np.where(lab['neck_cloth_visible']);left,right=np.quantile(xvals,[.33,.67]);upper=np.quantile(yvals,.4)
        region=('upper_' if uv[1]<=upper else 'lower_')+('left' if uv[0]<left else 'right' if uv[0]>right else 'middle')
        candidate.append(dict(t,region=region,observations=obs));initial[t['id']]=x
    save_json(out/'input-contract.json',dict(sourceHash=meta['sourceHash'],K=K.tolist(),worldC={n:C[n].tolist() for n in names},timestamps=ts,reference=reference,scale=float(raw['scale']),
        trainRoleHash=sha(plan_path),auxiliaryGeometryTrain=[n for n in names if n not in plan['train']],colourTrainingSplitUnchanged=True,depthSources={n:dict(file=r['file'],window=r['window'],hash=sha(root/r['file'])) for n,r in rows.items()},
        motionBasis=motion_basis,rotationBoundDegrees=rotation_bound,xyzBoundFraction=xyz_bound_fraction,maxNfev=80,published=False))
    np.savez_compressed(out/'initial-points.npz',trackIDs=np.asarray(list(initial)),xyz=np.asarray(list(initial.values())))
    save_json(out/'native-measurements.json',dict(sourceHash=meta['sourceHash'],tracks=candidate))
    shutil.copyfile(__file__,out/Path(__file__).name)
    result=solve_body_tracks(candidate,{n:C[n] for n in names},K,ts,reference,float(raw['scale']),initial,motion_basis=motion_basis,rotation_bound=rotation_bound,xyz_bound_fraction=xyz_bound_fraction)
    result.update(sourceHash=meta['sourceHash'],inputHashes={str(p):sha(p) for p in (Path(tracks),Path(complete)/'candidate-final.pt',root/'manifest.json')},seconds=time.perf_counter()-clock)
    save_json(out/'result.json',result);shutil.copyfile(__file__,out/Path(__file__).name)
    save_json(out/'admission.json',dict(candidateRecords=len(candidate),uniqueAfterDedup=result.get('count'),reference=reference,sourceDepthIsTruth=False,failedResultTransportEnabled=False))
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','B','nodeTransforms','duplicates','inputHashes')}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','complete','tracks','depth','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--motion-basis',choices=['velocity','acceleration','two-node','temporal-knots'],default='velocity');p.add_argument('--rotation-bound',type=float,default=4.);p.add_argument('--xyz-bound-fraction',type=float,default=.05);a=p.parse_args();run(a.prepared,a.complete,a.tracks,a.depth,a.out,a.motion_basis,a.rotation_bound,a.xyz_bound_fraction)