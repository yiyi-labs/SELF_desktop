"""Train-only inverse-depth calibration against real static COLMAP tracks.
Shared per-window sensor/model calibration, never per-image scale or camera
rewrite. Held-out POINT3D_ID groups decide whether correction is admissible.
"""
from pathlib import Path
import argparse,json,shutil,hashlib
import numpy as np,cv2,pycolmap
from scipy.optimize import least_squares
from reconstruction_components_v3 import sha,save_json
from reconstruction_dense_contract import bilinear,project
from reconstruction_ray_surface import sample_mask


def fit_inverse_depth(predicted,measured,point_ids):
    p=np.asarray(predicted,float);m=np.asarray(measured,float);ids=np.asarray(point_ids,np.int64)
    if p.ndim!=1 or p.shape!=m.shape or p.shape!=ids.shape:raise ValueError('depth_correspondence_identity')
    if len(p)<80 or not np.isfinite(p).all() or not np.isfinite(m).all() or np.any(p<=0) or np.any(m<=0):return dict(accepted=False,reason='insufficient_real_static_depth')
    hold=np.array([int.from_bytes(hashlib.sha256(str(int(i)).encode()).digest()[:4],'little')%5==0 for i in ids])
    if hold.sum()<12 or (~hold).sum()<50:return dict(accepted=False,reason='insufficient_heldout_point_groups')
    unit=float(np.median(1/m));x=1/p/unit;y=1/m/unit
    def fun(v):return np.r_[(x[~hold]*v[0]+v[1]-y[~hold])/y[~hold],(v-[1.,0.])*.015]
    fit=least_squares(fun,[1.,0.],bounds=([.25,-.5],[4.,.5]),loss='soft_l1',f_scale=.03,max_nfev=80)
    inverse=x*fit.x[0]+fit.x[1];good=inverse>0
    after=np.full(len(p),np.inf);after[good]=1/(inverse[good]*unit)
    old=np.abs(p/m-1);new=np.abs(after/m-1)
    accepted=bool(fit.success and good.all() and np.median(new[hold])<=.03 and np.quantile(new[hold],.9)<=.08 and np.quantile(new[hold],.9)<=np.quantile(old[hold],.9)*.8)
    return dict(accepted=accepted,scale=float(fit.x[0]),shiftNormalized=float(fit.x[1]),inverseUnit=unit,
        records=len(p),uniquePoints=len(set(ids)),heldoutUniquePoints=len(set(ids[hold])),
        heldoutMedianBefore=float(np.median(old[hold])),heldoutMedianAfter=float(np.median(new[hold])),
        heldoutP90Before=float(np.quantile(old[hold],.9)),heldoutP90After=float(np.quantile(new[hold],.9)),
        nfev=fit.nfev,success=bool(fit.success),cameraChanges=0,perFrameScales=0,independentSensorTruth=False)


def run(prepared,split,depth,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);prep=Path(prepared);folder=Path(depth)
    meta=json.loads((prep/'preparation.json').read_text());raw=dict(np.load(prep/'local_geometry.npz'));plan=json.loads(Path(split).read_text());manifest=json.loads((folder/'manifest.json').read_text())
    if meta['sourceHash']!=manifest['sourceHash']:raise ValueError('depth_source_changed')
    train=set(plan['train']);forbidden=set(plan['development']+plan['audit']);K=raw['K'];C={str(n):raw['C'][i] for i,n in enumerate(raw['world_names'])}
    mapping=pycolmap.Reconstruction(str(prep.parent.parent/meta['staticMap']));groups={};records=[]
    for row in manifest['observations']:
        name=row['imageName']
        if row['group']!='world' or not row['scaleGatePassed'] or name not in train:continue
        if name in forbidden or row['role']!='train':raise ValueError('calibration_role_leak')
        a=dict(np.load(folder/row['file']));np.testing.assert_allclose(a['W2C'],C[name],atol=1e-5,rtol=0)
        lab=dict(np.load(prep/'rectified_observations'/(name+'.npz')));room=lab['room_visible']&~lab['unknown_or_occluded']
        im=next((im for im in mapping.images.values() if im.name==name),None)
        if im is None:continue
        observed=[];ids=[];measured=[];pixel=[]
        for element in im.points2D:
            if not element.has_point3D():continue
            pid=int(element.point3D_id);point=mapping.points3D[pid]
            if point.error>2.5:continue
            ray=mapping.cameras[im.camera_id].cam_from_img(element.xy);u=K@np.r_[ray,1.];uv=u[:2]/u[2]
            re,z=project(np.asarray(point.xyz)[None],K,C[name])
            if z[0]<=0 or np.linalg.norm(re[0]-uv)>3 or not sample_mask(room,uv[None])[0]:continue
            proc=(a['nativeToProcessed']@np.r_[uv,1.])[:2]
            d=bilinear(a['depth'],proc[None])[0]
            xy=np.rint(proc).astype(int);h,w=a['depth'].shape;x,y=xy
            if not (1<=x<w-1 and 1<=y<h-1) or not np.isfinite(d) or d<=0:continue
            patch=a['depth'][y-1:y+2,x-1:x+2]
            if not np.isfinite(patch).all() or np.ptp(patch)>.06*d:continue
            observed.append(float(d));measured.append(float(z[0]));ids.append(pid);pixel.append(uv.tolist())
        group=groups.setdefault(row['window'],dict(predicted=[],measured=[],ids=[]))
        group['predicted']+=observed;group['measured']+=measured;group['ids']+=ids
        records.append(dict(name=name,window=row['window'],records=len(ids),cacheFile=row['file'],cacheHash=sha(folder/row['file'])))
    result={str(k):fit_inverse_depth(v['predicted'],v['measured'],v['ids']) for k,v in groups.items()}
    report=dict(windows=result,sourceHash=meta['sourceHash'],depthManifestHash=sha(folder/'manifest.json'),preparedHash=sha(prep/'preparation.json'),splitHash=sha(split),records=records,
        meaning='real static multi-view track depths conditional on frozen SfM; grouped holdout, no RGB/dev selection',published=False)
    save_json(out/'result.json',report);np.savez_compressed(out/'source-correspondences.npz',**{str(k)+'_'+field:np.array(v[field]) for k,v in groups.items() for field in v})
    shutil.copyfile(__file__,out/Path(__file__).name);print(json.dumps(result),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','split','depth','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.prepared,a.split,a.depth,a.out)