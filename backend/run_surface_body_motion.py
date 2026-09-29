"""Bounded upper-body rigid-velocity fit and pinned MVS preparation.
Six motion variables for the whole short interval, NOT a free pose per frame.
Reference body transform is identity; world camera calibration is unchanged.
"""
import argparse,json,time
from pathlib import Path
import cv2,numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from scipy.sparse import lil_matrix
from reconstruction_surface_evidence import measured_tracks,triangulate_track,export_colmap,project
from reconstruction_components_v3 import save_json,sha


def run(prepared,selection,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);start=time.perf_counter();prep=Path(prepared);z=dict(np.load(prep/'local_geometry.npz'));meta=json.loads((prep/'preparation.json').read_text());rows=json.loads(Path(selection).read_text())
    choice=max(rows,key=lambda r:r['tracking']['tracks']/(1+r['allTrackMedianError']));names=choice['names'];K=z['K'];C={str(n):z['C'][i] for i,n in enumerate(z['world_names'])};images={};masks={}
    for n in names:
        images[n]=cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB);lab=dict(np.load(prep/'rectified_observations'/(n+'.npz')));masks[n]=lab['neck_cloth_visible']&~lab['unknown_or_occluded'];chin=z['marks'][list(z['names']).index(n),152,1];chin*=1920 if chin<=1.5 else 1;masks[n][:int(chin)]=False
    tracks,stats=measured_tracks(images,masks,names,max_corners=600);reverse,rstats=measured_tracks(images,masks,list(reversed(names)),max_corners=600);stats['reverse']=rstats;stats['crossSeedDuplicates']=0
    for t in reverse:
        duplicate=False
        for existing in tracks:
            common={o['name']:np.array(o['uv']) for o in existing['observations']};hits=[np.linalg.norm(np.array(o['uv'])-common[o['name']])<1.5 for o in t['observations'] if o['name'] in common]
            if sum(hits)>=2:duplicate=True;break
        if duplicate:stats['crossSeedDuplicates']+=1
        else:tracks.append(t)
    records=[]
    for t in tracks:
        x,r=triangulate_track(t,C,K)
        if r['positive'] and r['p90Error']<12 and r['maxAngleDegrees']>1:records.append({**t,'initial':x,'before':r})
    if len(records)<40:save_json(out/'result.json',{'blocked':'too_few_bounded_motion_tracks','n':len(records)});return
    center=np.median([t['initial'] for t in records],axis=0);unit=float(z['scale']);times=np.array([int(n[6:10]) for n in names],float);times=(times-times[len(names)//2])/max(np.ptp(times),1.);tau=dict(zip(names,times));N=len(records);fit=[i for i in range(N) if i%5!=0];pos={i:j for j,i in enumerate(fit)};X0=np.array([records[i]['initial'] for i in fit]);obs=[(i,o) for i in fit for o in records[i]['observations'][:-1]]
    def bodies(v):
        result={}
        for n in names:
            R=Rotation.from_rotvec(v[:3]*np.radians(3)*tau[n]).as_matrix();B=np.eye(4);B[:3,:3]=R;B[:3,3]=center-R@center+v[3:]*unit*.02*tau[n];result[n]=B
        return result
    def fun(raw):
        Bs=bodies(raw[:6]);xs=X0+raw[6:].reshape(-1,3)*unit*.02
        err=[(project(xs[pos[i]][None],C[o['name']]@Bs[o['name']],K)[0][0]-o['uv'])/o['sigma'] for i,o in obs]
        return np.r_[np.asarray(err).reshape(-1),raw[:6]*.4,raw[6:]*.12]
    count=6+3*len(fit);J=lil_matrix((len(obs)*2+count,count),dtype=int)
    for j,(i,o) in enumerate(obs):J[j*2:j*2+2,:6]=1;J[j*2:j*2+2,6+pos[i]*3:9+pos[i]*3]=1
    J[len(obs)*2:,:]=__import__('scipy').sparse.eye(count)
    x=np.zeros(count);before=fun(x);res=least_squares(fun,x,bounds=(-np.ones(count),np.ones(count)),jac_sparsity=J.tocsr(),loss='soft_l1',f_scale=1.,x_scale='jac',max_nfev=80,ftol=1e-5,xtol=1e-5)
    B=bodies(res.x[:6]);cameras={n:C[n]@B[n] for n in names};points=[];audit=[]
    for i,t in enumerate(records):
        # Independent triangulation evaluates whole held-out tracks. Fit tracks
        # also retain the last-view measurement as a third-view check.
        train={**t,'observations':t['observations'][:-1]}
        x,r=triangulate_track(train,cameras,K);last=t['observations'][-1];uv,_=project(x[None],cameras[last['name']],K);third=float(np.linalg.norm(uv[0]-last['uv']))
        audit.append({'id':t['id'],'use':'withheld_track' if i%5==0 else 'fit','before':t['before'],'after':r,'thirdError':third})
        if r['positive'] and r['p90Error']<=2.5 and third<=3 and r['maxAngleDegrees']>=1:
            source=t['observations'][0];u,v=np.rint(source['uv']).astype(int);points.append({**t,'xyz':x.tolist(),'color':images[source['name']][v,u].tolist(),'error':r['medianError']});points[-1].pop('initial')
    save_json(out/'observations.json',audit);save_json(out/'optimizer.json',{'algorithm':'scipy-trf-sparse-soft-l1','nfev':res.nfev,'cost':res.cost,'success':res.success,'velocityRaw':res.x[:6].tolist(),'reference':names[len(names)//2],'bounds':'3deg/interval and .02*scene_scale/interval; fixed K,C,scale','source':stats})
    # No check claims world-to-body gauge is independently metrically measured.
    enough=len(points)>=60;report={'names':names,'count':len(points),'geometryAccepted':enough,'scaleMotionAmbiguity':'bounded by known world cameras, fixed reference and small velocity prior; not independent absolute body scale calibration','seconds':time.perf_counter()-start,'publish':False}
    if len(points)>=3: # Diagnostic MVS is allowed even when the quality gate fails.
        contract=export_colmap(out/'colmap',images,masks,names,cameras,K,points)
        save_json(out/'contract.json',{'schema':'self.surface-window.v1','sourceHash':meta['sourceHash'],'prepared':str(prep),'preparedHash':sha(prep/'preparation.json'),'names':names,'B':{n:B[n].tolist() for n in names},'worldC':{n:C[n].tolist() for n in names},'contract':contract,'use':'training_depth_with_third_view_checks','quality':'bounded_research_candidate_not_release','motionQualityAccepted':enough})
        save_json(out/'tracks.json',points)
    save_json(out/'result.json',report);print(json.dumps(report),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepared',required=True);p.add_argument('--selection',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.prepared,a.selection,a.out)


