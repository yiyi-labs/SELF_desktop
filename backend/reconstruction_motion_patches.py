"""Image-backed finite component surfaces; no synthetic texture or extrapolation."""
from pathlib import Path
import json,hashlib
import numpy as np,cv2
from scipy.spatial import Delaunay
from scipy.spatial.transform import Rotation
from reconstruction_dense_contract import project,bilinear,write_json

def coverage_budget(arr,cameras,K,labels,budget,part,tile=12):
    """Balance projected sampling cells, preserving overlap before random detail.
    It is a sampler, NOT proof of rendered alpha or surface correctness.
    """
    if len(arr['means'])<=budget:return np.arange(len(arr['means']))
    keys=[]
    for n,T in cameras.items():
        uv,z=project(arr['means'],K,T);h,w=labels[n].shape;xy=np.rint(uv).astype(int);valid=(z>0)&(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h);xy=xy.clip([0,0],[w-1,h-1]);valid&=labels[n][xy[:,1],xy[:,0]]
        cells=np.floor(uv/tile).astype(np.int64);keys.append((n,cells,valid))
    counts={};pointkeys=[]
    for i in range(len(arr['means'])):
        kk=[(n,int(c[i,0]),int(c[i,1])) for n,c,v in keys if v[i]];pointkeys.append(kk)
        for k in kk:counts[k]=counts.get(k,0)+1
    score=np.array([sum(1/counts[k] for k in kk) for kk in pointkeys]);order=np.lexsort((arr['uid'],-arr['confidence'],-score));selected=[];chosen=set();covered={}
    # First pass is a deterministic balanced support layer; second keeps overlap.
    for quota in (1,2):
        for i in order:
            if int(i) in chosen:continue
            if any(covered.get(k,0)<quota for k in pointkeys[i]):
                selected.append(int(i));chosen.add(int(i))
                for k in pointkeys[i]:covered[k]=covered.get(k,0)+1
                if len(selected)==budget:return np.asarray(selected)
    chosen=set(selected)
    selected.extend(int(i) for i in order if i not in chosen)
    return np.asarray(selected[:budget])

def build_track_patch(prepared,geometry,out,component,budget=10000):
    prep=Path(prepared);out=Path(out);out.mkdir(parents=True,exist_ok=False);names=list(geometry['cameras']);K=np.load(prep/'local_geometry.npz')['K'];G={n:np.asarray(v) for n,v in geometry['cameras'].items()}
    key='hair_visible' if component=='hair' else 'neck_cloth_visible';part=2 if component=='hair' else 4
    ims={n:cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB).astype(float)/255 for n in names};labs={n:dict(np.load(prep/'rectified_observations'/(n+'.npz'))) for n in names};masks={n:labs[n][key]&~labs[n]['unknown_or_occluded'] for n in names}
    points=[r for r in geometry['records'] if r['accepted'] and (r['region']=='hair' if part==2 else r['region'].startswith(('upper_','lower_')))];worldC=geometry.get('worldC',geometry['cameras'])
    if len(points)<6:write_json(out/'result.json',dict(blocked='fewer_than_six_supported_component_tracks',tracks=len(points),component=component,published=False));return None
    count={n:sum(any(o['name']==n for o in p['observations']) for p in points) for n in names};ref=max(count,key=count.get);indices=[i for i,p in enumerate(points) if any(o['name']==ref for o in p['observations'])];uv=np.array([next(o['uv'] for o in points[i]['observations'] if o['name']==ref) for i in indices]);xyz=np.array([r['xyz'] for r in points]);triangles=[];result=[];regions={n:np.zeros(masks[n].shape,np.uint8) for n in names}
    if len(uv)<4:write_json(out/'result.json',dict(blocked='insufficient_common_reference',tracks=len(uv)));return None
    for local in Delaunay(uv).simplices:
        ids=np.asarray(indices)[local];V=xyz[ids];screen=uv[local];common=set(names)
        for i in ids:common&={o['name'] for o in points[i]['observations']}
        if len(common)<3:continue
        sides=np.linalg.norm(screen[[1,2,0]]-screen,axis=1);normal=np.cross(V[1]-V[0],V[2]-V[0]);norm=np.linalg.norm(normal)
        if norm<1e-10 or max(sides)>80 or max(sides)>4*max(min(sides),1):continue
        normal/=norm;a=V[1]-V[0];a/=np.linalg.norm(a);b=np.cross(normal,a);q=Rotation.from_matrix(np.stack((a,b,normal),1)).as_quat()[[3,0,1,2]]
        # No cross-boundary triangle: all training projections need valid interior.
        allowed=[]
        for n in sorted(common):
            pu,z=project(V,K,G[n]);probe=np.vstack([pu,pu.mean(0),(pu+pu[[1,2,0]])*.5]);xy=np.rint(probe).astype(int);h,w=masks[n].shape
            if np.all(z>0) and np.all((xy[:,0]>=2)&(xy[:,0]<w-2)&(xy[:,1]>=2)&(xy[:,1]<h-2)) and masks[n][xy[:,1],xy[:,0]].all():allowed.append(n)
        if len(allowed)<3:continue
        tid=len(triangles);div=max(2,min(30,int(np.ceil(max(sides)/3))));triangles.append(dict(ids=[points[i]['id'] for i in ids],vertices=V.tolist(),views=allowed,divisions=div))
        for i in range(div+1):
            for j in range(div+1-i):
                bary=np.array([i,j,div-i-j],float)/div;P=bary@V;colors=[];scales=[];src=[]
                for n in allowed:
                    p,z=project(P[None],K,G[n]);x,y=np.rint(p[0]).astype(int);h,w=masks[n].shape
                    if z[0]>0 and 1<x<w-2 and 1<y<h-2 and masks[n][y-1:y+2,x-1:x+2].all():colors.append(np.median(ims[n][y-1:y+2,x-1:x+2],axis=(0,1)));scales.append(z[0]/K[0,0]);src.append((n,p[0]))
                if len(colors)<3 or np.max(np.std(colors,axis=0))>.12:continue
                mm=float(np.median(scales));uid=int.from_bytes(hashlib.sha256((component+':'+':'.join(sorted(triangles[-1]['ids']))+':'+str(np.round(bary,8).tolist())).encode()).digest()[:8],'little')&((1<<63)-1)
                result.append(dict(means=P,quats=q,scales=[mm*2,mm*2,mm*.25],opacity=.6,sh=np.array([(np.median(colors,axis=0)-.5)/.28209479177387814,[0,0,0],[0,0,0],[0,0,0]]),parts=part,uid=uid,confidence=1/(max(points[k]['quality']['p90Error'] for k in ids)+.1),support=len(colors),source_image=src[0][0],source_uv=src[0][1],triangle=tid,bary=bary))
        for n in allowed:
            pu,z=project(V,K,G[n]);cv2.fillConvexPoly(regions[n],np.rint(pu).astype(np.int32),1)
    if not result:write_json(out/'result.json',dict(blocked='no_visible_continuous_surface',triangles=len(triangles)));return None
    arr={k:np.asarray([r[k] for r in result]) for k in result[0]};_,ids=np.unique(np.round(arr['means'],8),axis=0,return_index=True);arr={k:v[ids] for k,v in arr.items()};before=len(ids);keep=coverage_budget(arr,G,K,masks,budget,part);arr={k:v[keep] for k,v in arr.items()}
    np.savez_compressed(out/'surface.npz',**arr);np.savez_compressed(out/'regions.npz',**{n:v.astype(bool)&masks[n] for n,v in regions.items()});write_json(out/'triangles.json',triangles)
    obs=dict(sourceHash=geometry['sourceHash'],names=names,K=K.tolist(),cameras=geometry['cameras'],worldC=worldC,B=geometry.get('B'),component=component,reference=geometry['reference'],motionAccepted=geometry['motionAccepted'],surfaceMeaning='interpolated hypothesis supported by measured shared XYZ, not dense truth')
    write_json(out/'observations.json',obs);write_json(out/'result.json',dict(points=len(keep),beforeBudget=before,tracks=len(points),triangles=len(triangles),component=component,regionPixels={n:int((v.astype(bool)&masks[n]).sum()) for n,v in regions.items()},published=False));return arr
