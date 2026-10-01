"""Native, role-checked short-window MVS input from real head-local tracks.
One bounded window; RGB untouched; no unknown world pose is fabricated.
"""
import argparse,json,shutil,time
from pathlib import Path
import cv2,numpy as np
from reconstruction_complete_contract import export_native_mvs_window
from reconstruction_components_v3 import save_json,sha

def native_object_crop(images,masks,K,points,padding=24):
    bounds=[]
    for m in masks.values():
        y,x=np.where(m)
        if not len(x):raise ValueError('empty_observed_hair_mask')
        bounds.append([x.min(),y.min(),x.max()+1,y.max()+1])
    h,w=next(iter(images.values())).shape[:2];b=np.array(bounds)
    x0=max(0,int(b[:,0].min())-padding);y0=max(0,int(b[:,1].min())-padding)
    x1=min(w,int(b[:,2].max())+padding);y1=min(h,int(b[:,3].max())+padding)
    cropK=np.array(K).copy();cropK[0,2]-=x0;cropK[1,2]-=y0
    records=[{**p,'observations':[{**o,'uv':(np.array(o['uv'])-[x0,y0]).tolist()} for o in p['observations']]} for p in points]
    return {n:im[y0:y1,x0:x1].copy() for n,im in images.items()},{n:m[y0:y1,x0:x1].copy() for n,m in masks.items()},cropK,records,[x0,y0,x1,y1]


def retriangulate_fixed_records(records,cameras,K):
    from reconstruction_surface_evidence import triangulate_track,project
    accepted=[];rejected=0
    for t in records:
        obs=t['observations'];x,q=triangulate_track(dict(t,observations=obs[:-1]),cameras,K)
        uv,z=project(x[None],cameras[obs[-1]['name']],K);third=float(np.linalg.norm(uv[0]-obs[-1]['uv']))
        if not(q['positive'] and q['p90Error']<=2.5 and q['maxAngleDegrees']>=1. and z[0]>0 and third<=3):rejected+=1;continue
        metric=max(float((x@cameras[obs[0]['name']][:3,:3].T+cameras[obs[0]['name']][:3,3])[2]/K[0,0]),1e-8)
        def residual(p):return np.concatenate([(project(p[None],cameras[o['name']],K)[0][0]-o['uv'])/o['sigma'] for o in obs[:-1]])
        eps=metric*.001;J=np.stack([(residual(x+np.eye(3)[k]*eps)-residual(x-np.eye(3)[k]*eps))/(2*eps) for k in range(3)],1);sv=np.linalg.svd(J,compute_uv=False)
        if sv[-1]/sv[0]<.01:rejected+=1;continue
        accepted.append(dict(t,xyz=x.tolist(),quality=q,thirdError=third,dataSingularValues=sv.tolist()))
    return accepted,rejected


def run(prepared,tracks,out,native_object_roi=False,include_face_anchors=False,complete=None):
    p=Path(prepared);out=Path(out);out.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    cache=json.loads(Path(tracks).read_text());meta=json.loads((p/'preparation.json').read_text());z=np.load(p/'local_geometry.npz');names0=[str(n) for n in z['names']];K=z['K']
    if cache['sourceHash']!=meta['sourceHash']:raise ValueError('source_identity_changed')
    groups=[]
    for wi,block in enumerate(cache['windows']):
        records=[t for t in cache['tracks'] if t['region']=='hair' and 'xyz' in t and t['id'].startswith(str(wi)+':')]
        groups.append((len(records),wi,records,block))
    _,wi,records,block=max(groups,key=lambda a:(a[0],-a[1]))
    hair_count=len(records)
    if include_face_anchors:records=records+[t for t in cache['tracks'] if t['region']=='face' and 'xyz' in t and t['id'].startswith(str(wi)+':')]
    names=sorted({o['name'] for t in records for o in t['observations']})
    if len(records)<24 or not 4<=len(names)<=12 or any(n not in meta['train'] for n in names):raise ValueError('insufficient_train_only_hair_geometry')
    cameras={n:z['F'][names0.index(n)] for n in names};restored=None;retriangulated_rejections=0
    if complete:
        from reconstruction_complete_context import load_complete
        from reconstruction_portrait_pipeline import make_frame
        data,plan,base,restored=load_complete(complete,out/'restored-source')
        if data['sourceHash']!=cache['sourceHash']:raise ValueError('restored_head_source_changed')
        cameras={n:base.baseline.adjusted_frame(make_frame(data,n,crop=False))['F'].cpu().numpy() for n in names}
        records,retriangulated_rejections=retriangulate_fixed_records(records,cameras,K)
        names=sorted({o['name'] for t in records for o in t['observations']});cameras={n:cameras[n] for n in names}
        hair_count=sum(t['region']=='hair' for t in records)
        if len(records)<24 or len(names)<4:raise ValueError('insufficient_restored_camera_head_geometry')
    images={};masks={};points=[]
    for n in names:
        images[n]=cv2.cvtColor(cv2.imread(str(p/'rectified_observations'/n)),cv2.COLOR_BGR2RGB);lab=dict(np.load(p/'rectified_observations'/(n+'.npz')))
        masks[n]=(lab['hair_visible']|lab['face_core']|lab['face_boundary'] if include_face_anchors else lab['hair_visible'])&~lab['unknown_or_occluded']
    for t in records:
        first=t['observations'][0];x,y=np.rint(first['uv']).astype(int);rgb=images[first['name']][y,x]
        points.append(dict(xyz=t['xyz'],observations=t['observations'],color=rgb.tolist(),error=t['quality']['medianError'],sourceID=t['id']))
    fullK=K.copy();rectangle=None
    if native_object_roi:images,masks,K,points,rectangle=native_object_crop(images,masks,K,points)
    exported=export_native_mvs_window(out/'colmap',images,masks,names,cameras,K,points,input_pixel_center='opencv_integer')
    save_json(out/'contract.json',dict(schema='self.surface-window.v1',sourceHash=cache['sourceHash'],prepared=str(p.resolve()),preparedHash=sha(p/'preparation.json'),names=names,cameraFrame='head-local',contract=exported,
        nativeK=K.tolist(),fullK=fullK.tolist(),nativeObjectRectangle=rectangle,restoredCompleteCheckpointHash=restored['completeCheckpointHash'] if restored else None,retriangulatedRejected=retriangulated_rejections,RGBResized=False,worldCUsed=False,includeFaceAnchors=include_face_anchors,hairAnchorCount=hair_count,faceAnchorCount=len(records)-hair_count,selection='most supported native training hair trajectories among fixed timestamp windows',geometryConditionalOnExistingF=True,
        rigidAssumption='short head-local visible hair; not neck or clothes',use='training_only_head' if include_face_anchors else 'training_only_hair',mask='observed head' if include_face_anchors else 'observed hair',unknownExcluded=True,sourceRGBUnchanged=True,
        stageBudget=dict(maximumMVSSeconds=360,maximumThreads=4,resolutionLevel=1,maximumImages=12),trackHash=sha(tracks),published=False))
    save_json(out/'tracks.json',points);shutil.copyfile(__file__,out/Path(__file__).name)
    print(json.dumps(dict(window=wi,names=names,tracks=len(points),seconds=time.perf_counter()-started)),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepared',required=True);p.add_argument('--tracks',required=True);p.add_argument('--out',required=True);p.add_argument('--native-object-roi',action='store_true');p.add_argument('--include-face-anchors',action='store_true');p.add_argument('--complete');a=p.parse_args();run(a.prepared,a.tracks,a.out,a.native_object_roi,a.include_face_anchors,a.complete)
