"""Real pixel-track check of frozen B transport vs static world projection.
Predicted source depth is conditional, so this is not motion/depth ground truth.
No new pose fitted; no training. Unknown motion is not silently identity.
"""
from pathlib import Path
import argparse,json,shutil
import numpy as np,torch,cv2
from reconstruction_complete_context import load_complete
from reconstruction_continuity_surface import physical_masks
from reconstruction_dense_contract import project,unproject,bilinear
from reconstruction_dense_surfaces import native_uv
from reconstruction_surface_handoff import move_observation_points
from reconstruction_ray_surface import sample_mask
from reconstruction_components_v3 import save_json,sha

def run(complete,depth,out):
    out=Path(out);data,plan,base,contract=load_complete(complete,out)
    names=list(base.body_motion.timestamps);names=sorted(names,key=base.body_motion.timestamps.get)
    masks=physical_masks(contract['spec']['prepared'],data,names)
    manifest=json.loads((Path(depth)/'manifest.json').read_text());rows={r['imageName']:r for r in manifest['observations'] if r['group']=='world' and r['scaleGatePassed'] and r['imageName'] in names}
    motions={n:base.body_motion.matrix(n).detach().cpu().numpy() for n in names}
    images={n:cv2.cvtColor((data['rgb'][n]*255).round().astype(np.uint8),cv2.COLOR_RGB2GRAY) for n in names}
    tracks=[];errors=[]
    # Deterministic distributed cells avoid a logo-only measured constraint.
    for source in names[:3]:
        if source not in rows:continue
        m=masks[source]['cloth'];h,w=m.shape;points=[]
        for gy in range(4):
            for gx in range(3):
                cell=np.zeros_like(m);cell[gy*h//4:(gy+1)*h//4,gx*w//3:(gx+1)*w//3]=m[gy*h//4:(gy+1)*h//4,gx*w//3:(gx+1)*w//3]
                p=cv2.goodFeaturesToTrack(images[source],12,.015,12,mask=cell.astype(np.uint8)*255,blockSize=7)
                if p is not None:points.extend(p[:,0])
        if not points:continue
        p=np.asarray(points,np.float32).reshape(-1,1,2);a=dict(np.load(Path(depth)/rows[source]['file']))
        qproc=np.c_[p[:,0],np.ones(len(p))]@a['nativeToProcessed'].T;d=bilinear(a['depth'],qproc[:,:2])
        xyz=unproject(p[:,0],d,data['K'],data['worlds'][source]);valid0=np.isfinite(xyz).all(1)&(d>0)
        observations={i:[dict(name=source,uv=p[i,0].tolist())] for i in np.flatnonzero(valid0)}
        for target in names:
            if target==source:continue
            q,ok,_=cv2.calcOpticalFlowPyrLK(images[source],images[target],p,None,winSize=(31,31),maxLevel=4)
            back,ok2,_=cv2.calcOpticalFlowPyrLK(images[target],images[source],q,None,winSize=(31,31),maxLevel=4)
            valid=valid0&(ok[:,0]>0)&(ok2[:,0]>0)&(np.linalg.norm(back[:,0]-p[:,0],axis=1)<.75)&sample_mask(masks[target]['cloth'],q[:,0])
            for i in np.flatnonzero(valid):
                x,y=p[i,0];u,v=q[i,0]
                pa=cv2.getRectSubPix(images[source],(15,15),(float(x),float(y))).astype(float)
                pb=cv2.getRectSubPix(images[target],(15,15),(float(u),float(v))).astype(float)
                pa-=pa.mean();pb-=pb.mean();ncc=(pa*pb).sum()/max(np.linalg.norm(pa)*np.linalg.norm(pb),1e-8)
                if ncc<.85:continue
                observations[i].append(dict(name=target,uv=q[i,0].tolist(),ncc=float(ncc)))
        for i,obs in observations.items():
            if len(obs)<4:continue
            record=dict(id=source+':'+str(i),source=source,sourceUV=p[i,0].tolist(),observations=obs)
            error=[]
            for o in obs[1:]:
                target=o['name'];uv,z=project(xyz[i:i+1],data['K'],data['worlds'][target]);moved=move_observation_points(xyz[i:i+1],source,target,motions)
                um,zm=project(moved,data['K'],data['worlds'][target])
                if z[0]<=0 or zm[0]<=0:continue
                error.append(dict(name=target,static=float(np.linalg.norm(uv[0]-o['uv'])),transport=float(np.linalg.norm(um[0]-o['uv']))))
            record['errors']=error;tracks.append(record);errors.extend(error)
    raw=np.array([[e['static'],e['transport']] for e in errors])
    report=dict(sourceHash=data['sourceHash'],completeCheckpointHash=contract['completeCheckpointHash'],depthManifestHash=sha(Path(depth)/'manifest.json'),
        names=names,tracks=len(tracks),observations=len(errors),realTrackRules='distributed corners, >=4 images, FB<.75 px, NCC>=.85, cloth masks',
        median= np.median(raw,0).tolist() if len(raw) else None,p90=np.quantile(raw,.9,axis=0).tolist() if len(raw) else None,
        interpretation='existing B tested against real RGB tracks but initial depth is predicted; not independent motion truth',
        trackIdentity='source-track events; cross-source physical duplicates not deduplicated',motionAccepted=False,bodyTrainingSteps=0,published=False)
    save_json(out/'tracks.json',tracks);save_json(out/'result.json',report);shutil.copyfile(__file__,out/Path(__file__).name)
    print(json.dumps(report),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('complete','depth','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.complete,a.depth,a.out)