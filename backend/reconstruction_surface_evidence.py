"""Reusable measured-track and short-window surface stages; research only.
No production configuration, publisher or device imports. Observation masks
exclude unknown pixels; they never overwrite source RGB or certify depth.
"""
from pathlib import Path
import json, time
import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def project(x, C, K):
    p=np.asarray(x)@C[:3,:3].T+C[:3,3]
    q=p@K.T
    return q[...,:2]/q[...,2:3],p[...,2]


def measured_tracks(images, masks, names, *, max_corners=400, refine=True):
    """Source SubPix + direct/serial flow cycle + symmetric real-patch ECC.
    Tracking weights depend only on measured texture/FB/cycle, never on model
    residual. All retained observations use ONE physical track identity.
    """
    g={n:cv2.cvtColor(images[n],cv2.COLOR_RGB2GRAY) for n in names}
    first=names[0];er=cv2.erode(masks[first].astype(np.uint8),np.ones((19,19),np.uint8))
    seed=cv2.goodFeaturesToTrack(g[first],max_corners,.008,5,mask=er*255,blockSize=5)
    if seed is None:return [],{'seeds':0}
    cv2.cornerSubPix(g[first],seed,(3,3),(-1,-1),(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.01))
    n=len(seed);records=[[{'name':first,'uv':p.tolist(),'sigma':.5,'fb':0.,'cycle':0.,'correlation':1.}] for p in seed[:,0]]
    alive=np.ones(n,bool);prev=seed.copy();rejections={k:0 for k in ['boundary','flow','cycle','patch']}
    for a,b in zip(names[:-1],names[1:]):
        cur,ok,_=cv2.calcOpticalFlowPyrLK(g[a],g[b],prev,None,winSize=(31,31),maxLevel=3)
        back,ok2,_=cv2.calcOpticalFlowPyrLK(g[b],g[a],cur,None,winSize=(31,31),maxLevel=3)
        direct,ok3,_=cv2.calcOpticalFlowPyrLK(g[first],g[b],seed,None,winSize=(31,31),maxLevel=3)
        fb=np.linalg.norm(back[:,0]-prev[:,0],axis=1);cycle=np.linalg.norm(cur[:,0]-direct[:,0],axis=1)
        h,w=g[b].shape
        for i in np.where(alive)[0]:
            p=cur[i,0];x,y=np.rint(p).astype(int)
            if not(16<x<w-17 and 16<y<h-17 and masks[b][y,x]):alive[i]=False;rejections['boundary']+=1;continue
            if not(ok[i,0] and ok2[i,0] and ok3[i,0]) or fb[i]>1.:alive[i]=False;rejections['flow']+=1;continue
            if cycle[i]>1.2:alive[i]=False;rejections['cycle']+=1;continue
            correlation=1.;refined=p.copy();refine_fb=0.
            if refine:
                src=cv2.getRectSubPix(g[first],(25,25),tuple(seed[i,0])).astype(np.float32)/255
                dst=cv2.getRectSubPix(g[b],(25,25),tuple(p)).astype(np.float32)/255
                if src.std()<.012 or dst.std()<.012:alive[i]=False;rejections['patch']+=1;continue
                try:
                    warp=np.eye(2,3,dtype=np.float32)
                    correlation,warp=cv2.findTransformECC(src,dst,warp,cv2.MOTION_TRANSLATION,(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,30,1e-4),None,3)
                    _,inv=cv2.findTransformECC(dst,src,np.eye(2,3,dtype=np.float32),cv2.MOTION_TRANSLATION,(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,30,1e-4),None,3)
                    delta=warp[:,2];refine_fb=float(np.linalg.norm(delta+inv[:,2]));refined=p+delta
                    if correlation<.85 or np.linalg.norm(delta)>2.5 or refine_fb>.5:raise ValueError('ambiguous_patch')
                except (cv2.error,ValueError):alive[i]=False;rejections['patch']+=1;continue
            sigma=float(np.clip(.35+fb[i]+cycle[i]*.35+refine_fb,.4,1.5))
            records[i].append({'name':b,'uv':refined.tolist(),'rawUV':p.tolist(),'sigma':sigma,'fb':float(fb[i]),'cycle':float(cycle[i]),'correlation':float(correlation)})
        prev=cur
    tracks=[{'id':f'{first}:{i}','observations':obs} for i,obs in enumerate(records) if len(obs)>=3]
    return tracks,{'seeds':len(seed),'tracks':len(tracks),'rejections':rejections,'measurement':'SubPix + serial/direct cycle + symmetric patch ECC' if refine else 'SubPix + serial/direct cycle'}


def triangulate_track(track,cameras,K):
    obs=track['observations'];A=[]
    for o in obs:
        P=K@cameras[o['name']][:3];u,v=o['uv'];A.extend([u*P[2]-P[0],v*P[2]-P[1]])
    _,_,V=np.linalg.svd(np.asarray(A));x=V[-1,:3]/V[-1,3]
    def fun(p):return np.concatenate([(project(p[None],cameras[o['name']],K)[0][0]-o['uv'])/o['sigma'] for o in obs])
    result=least_squares(fun,x,loss='soft_l1',f_scale=1.,max_nfev=30)
    x=result.x;errors=[];rays=[];positive=True
    for o in obs:
        uv,z=project(x[None],cameras[o['name']],K);errors.append(float(np.linalg.norm(uv[0]-o['uv'])));positive&=z[0]>0
        center=np.linalg.inv(cameras[o['name']])[:3,3];ray=x-center;rays.append(ray/np.linalg.norm(ray))
    dots=np.clip(np.asarray(rays)@np.asarray(rays).T,-1,1);angle=float(np.degrees(np.arccos(dots.min())))
    return x,{'errors':errors,'maxAngleDegrees':angle,'positive':bool(positive),'medianError':float(np.median(errors)),'p90Error':float(np.quantile(errors,.9))}


def export_colmap(out,images,masks,names,cameras,K,points,*,mask_suffix='.mask.png'):
    """Undistorted PINHOLE text contract; native pixels; world-to-local-camera.
    points contains shared XYZ and REAL observed image coordinates, not image ID
    cast to a frame index. Same scale is retained; no automatic normalization.
    """
    out=Path(out);(out/'images').mkdir(parents=True,exist_ok=False);(out/'sparse').mkdir()
    h,w=images[names[0]].shape[:2]
    (out/'sparse/cameras.txt').write_text(f'1 PINHOLE {w} {h} {K[0,0]:.12g} {K[1,1]:.12g} {K[0,2]:.12g} {K[1,2]:.12g}\n')
    observations={n:[] for n in names};pointlines=[]
    for pi,p in enumerate(points,1):
        items=[]
        for o in p['observations']:
            n=o['name']
            if n not in observations:continue
            items.extend([names.index(n)+1,len(observations[n])]);observations[n].append((*o['uv'],pi))
        rgb=p['color'];pointlines.append(' '.join(map(str,[pi,*p['xyz'],*rgb,p['error'],*items])))
    lines=[]
    for ii,n in enumerate(names,1):
        C=cameras[n];q=Rotation.from_matrix(C[:3,:3]).as_quat()[[3,0,1,2]]
        lines.append(' '.join(map(str,[ii,*q,*C[:3,3],1,n])))
        lines.append(' '.join(' '.join(map(str,o)) for o in observations[n]))
        cv2.imwrite(str(out/'images'/n),cv2.cvtColor(images[n],cv2.COLOR_RGB2BGR))
        # OpenMVS expects basename without final extension, verified source.
        cv2.imwrite(str(out/'images'/(Path(n).stem+mask_suffix)),masks[n].astype(np.uint8)*255)
    (out/'sparse/images.txt').write_text('\n'.join(lines)+'\n');(out/'sparse/points3D.txt').write_text('\n'.join(pointlines)+'\n')
    return {'width':w,'height':h,'K':K.tolist(),'cameras':{n:cameras[n].tolist() for n in names},'imageIDs':dict(zip(names,range(1,len(names)+1))),'points':len(points),'RGBMaskApplied':False,'pixelCenter':'original_opencv_colmap_integer_centres','scaleChanged':False}
