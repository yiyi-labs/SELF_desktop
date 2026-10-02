"""Compare frozen static projections with independent native patch measurements.
A bounded contextual diagnostic for a failed body window; no camera rewrite.
"""
from pathlib import Path
import argparse,json,shutil,time
import cv2,numpy as np,pycolmap
from reconstruction_components_v3 import save_json,sha
from reconstruction_dense_contract import project
from reconstruction_ray_surface import sample_mask
from reconstruction_native_measurements import native_measurement


def run(prepared,body_result,out,maximum=64):
    start=time.perf_counter();prep=Path(prepared);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    meta=json.loads((prep/'preparation.json').read_text());body=json.loads(Path(body_result).read_text())
    if body['sourceHash']!=meta['sourceHash']:raise ValueError('context_source_changed')
    raw=dict(np.load(prep/'local_geometry.npz'));K=raw['K'];C={str(n):raw['C'][i] for i,n in enumerate(raw['world_names'])}
    roles={str(n):str(raw['roles'][i]) for i,n in enumerate(raw['names'])}
    names=body['names']
    if any(n not in C or roles[n]!='train' for n in names):raise ValueError('context_world_or_role_missing')
    mapping=pycolmap.Reconstruction(str(prep.parent.parent/meta['staticMap']))
    by_name={im.name:im for im in mapping.images.values()};measurements={};rows={};gray={}
    for n in names:
        im=by_name[n];cam=mapping.cameras[im.camera_id];lab=dict(np.load(prep/'rectified_observations'/(n+'.npz')))
        mask=lab['room_visible']&~lab['unknown_or_occluded'];gray[n]=cv2.imread(str(prep/'rectified_observations'/n),cv2.IMREAD_GRAYSCALE)
        for p in im.points2D:
            if not p.has_point3D():continue
            pid=int(p.point3D_id);point=mapping.points3D[pid]
            if point.error>2.5:continue
            ray=cam.cam_from_img(p.xy);u=K@np.r_[ray,1.];uv=u[:2]/u[2]
            if not sample_mask(mask,uv[None])[0]:continue
            predicted,z=project(np.asarray(point.xyz)[None],K,C[n])
            if z[0]<=0:continue
            measurements.setdefault(pid,{})[n]=dict(uv=uv,predicted=predicted[0])
    # Image-space stratification of actual observed static features, not manual ROI.
    candidates=[(pid,obs) for pid,obs in measurements.items() if len(obs)>=3]
    candidates.sort(key=lambda item:(tuple(np.floor(next(iter(item[1].values()))['uv']/128).astype(int)),item[0]))
    if len(candidates)>maximum:candidates=[candidates[i] for i in np.linspace(0,len(candidates)-1,maximum).round().astype(int)]
    refined={n:[] for n in names};rejected={};detail=[]
    for pid,observations in candidates:
        source=next(n for n in names if n in observations);source_uv=observations[source]['uv']
        for n in names:
            if n==source or n not in observations:continue
            o=observations[n]
            try:
                uv,checks=native_measurement(gray[source],gray[n],source_uv,o['uv'])
                refined[n].append(float(np.linalg.norm(uv-o['predicted'])))
                detail.append(dict(point3DID=pid,source=source,target=n,measured=uv.tolist(),predicted=o['predicted'].tolist(),frozenFeature=o['uv'].tolist(),**checks))
            except (ValueError,cv2.error) as e:
                reason=str(e).split('\n')[0];rejected[reason]=rejected.get(reason,0)+1
    for n in names:
        values=[float(np.linalg.norm(obs[n]['uv']-obs[n]['predicted'])) for obs in measurements.values() if n in obs]
        rows[n]=dict(staticFeatureCount=len(values),staticReprojectionMedian=float(np.median(values)) if values else None,staticReprojectionP90=float(np.quantile(values,.9)) if values else None,
            nativeRefinedCount=len(refined[n]),nativeRefinedMedian=float(np.median(refined[n])) if refined[n] else None,nativeRefinedP90=float(np.quantile(refined[n],.9)) if refined[n] else None)
    save_json(out/'result.json',dict(sourceHash=meta['sourceHash'],preparedHash=sha(prep/'preparation.json'),bodyResultHash=sha(body_result),rows=rows,rejections=rejected,physicalTrackProposals=len(candidates),nativeMeasurements=detail,
        interpretation='static feature reprojections are conditional SfM checks; native texture refinement is independent of body fit. Agreement does not prove all camera/depth truth or cloth rigidity.',cameraChanges=0,trainingSteps=0,published=False,seconds=time.perf_counter()-start))
    shutil.copyfile(__file__,out/Path(__file__).name);print(json.dumps(dict(rows=rows,rejections=rejected,seconds=time.perf_counter()-start)),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','body-result','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.prepared,a.body_result,a.out)