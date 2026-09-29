"""Finite multi-view garment patch, honest fallback after dense tool failure.
Continuous triangles are hypotheses supported by >=3 common measured views.
No extrapolation, no claim to complete clothing, no head-motion binding.
"""
import argparse,json,math
from pathlib import Path
import cv2,numpy as np
from scipy.spatial import Delaunay
from scipy.spatial.transform import Rotation
from reconstruction_surface_evidence import project
from reconstruction_components_v3 import save_json


def run(window,out):
    window=Path(window);out=Path(out);out.mkdir(parents=True,exist_ok=False);contract=json.loads((window/'contract.json').read_text());pts=json.loads((window/'tracks.json').read_text());names=contract['names'];K=np.array(contract['contract']['K']);C={n:np.array(v) for n,v in contract['contract']['cameras'].items()};prep=Path(contract['prepared']);images={n:cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255 for n in names};labels={n:dict(np.load(prep/'rectified_observations'/(n+'.npz'))) for n in names};masks={n:labels[n]['neck_cloth_visible']&~labels[n]['unknown_or_occluded'] for n in names}
    counts={n:sum(any(o['name']==n for o in p['observations']) for p in pts) for n in names};ref=max(names,key=lambda n:counts[n]);ids=[i for i,p in enumerate(pts) if any(o['name']==ref for o in p['observations'])];uv=np.array([next(o['uv'] for o in pts[i]['observations'] if o['name']==ref) for i in ids]);xyz=np.array([p['xyz'] for p in pts]);triangles=[];samples=[];scales=[];quats=[];colors=[];source=[];barylist=[];support=[]
    for localtri in Delaunay(uv).simplices:
        tri=np.array(ids)[localtri];V=xyz[tri];screen=uv[localtri];common=set(names)
        for i in tri:common&={o['name'] for o in pts[i]['observations']}
        if len(common)<3:continue
        sides=np.linalg.norm(screen[[1,2,0]]-screen,axis=1);normal=np.cross(V[1]-V[0],V[2]-V[0]);area=np.linalg.norm(normal)
        if area<1e-8 or max(sides)>100:continue
        normal/=area;X=(V[1]-V[0]);X/=np.linalg.norm(X);Y=np.cross(normal,X);R=np.stack([X,Y,normal],1);q=Rotation.from_matrix(R).as_quat()[[3,0,1,2]]
        div=max(2,int(np.ceil(max(sides)/3.)));tid=len(triangles);triangles.append({'vertices':tri.tolist(),'commonViews':sorted(common),'divisions':div,'source':'triangulated cloth tracks; interpolated surface not independent dense measurement'})
        for a in range(div+1):
            for b in range(div+1-a):
                bar=np.array([a,b,div-a-b],float)/div;P=bar@V;observed=[];metric=[]
                for n in sorted(common):
                    pixels,z=project(P[None],C[n],K);x,y=np.rint(pixels[0]).astype(int)
                    if z[0]>0 and 1<=x<1079 and 1<=y<1919 and masks[n][y-1:y+2,x-1:x+2].all():observed.append(np.median(images[n][y-1:y+2,x-1:x+2],axis=(0,1)));metric.append(z[0]/K[0,0])
                if len(observed)<3 or np.max(np.std(observed,axis=0))>.12:continue
                mm=float(np.median(metric));samples.append(P);scales.append([mm*2.,mm*2.,mm*.2]);quats.append(q);colors.append(np.median(observed,axis=0));source.append(tid);barylist.append(bar);support.append(len(observed))
    if not samples:save_json(out/'result.json',{'blocked':'no_three_view_compatible_surface_patch','triangles':len(triangles)});return
    # Remove duplicate shared-edge barycentric positions, keeping explicit source.
    samples=np.array(samples);_,keep=np.unique(np.round(samples,8),axis=0,return_index=True);keep=np.sort(keep)
    np.savez_compressed(out/'surface.npz',means=samples[keep],scales=np.array(scales)[keep],quats=np.array(quats)[keep],rgb=np.array(colors)[keep],triangle=np.array(source)[keep],bary=np.array(barylist)[keep],support=np.array(support)[keep],sourceVertices=xyz,point_uid=np.arange(len(keep)),parent_uid=np.full(len(keep),-1))
    save_json(out/'triangles.json',triangles);save_json(out/'observations.json',contract)
    region={}
    panels=[]
    for n in names:
        mask=np.zeros((1920,1080),np.uint8)
        for tri in triangles:
            pixels,z=project(xyz[tri['vertices']],C[n],K)
            if np.all(z>0):cv2.fillConvexPoly(mask,np.rint(pixels).astype(np.int32),1)
        mask=mask.astype(bool)&masks[n];region[n]=mask
        im=(images[n]*255).round().astype(np.uint8);edges=cv2.Canny(mask.astype(np.uint8)*255,100,200)>0;im[edges]=[70,200,170];panels.append(cv2.resize(im,(270,480)))
    np.savez_compressed(out/'regions.npz',**region);cv2.imwrite(str(out/'supported-patch.png'),cv2.cvtColor(np.concatenate(panels,1),cv2.COLOR_RGB2BGR))
    save_json(out/'result.json',{'triangles':len(triangles),'gaussians':len(keep),'regionPixels':{n:int(m.sum()) for n,m in region.items()},'motionQualityAccepted':contract.get('motionQualityAccepted',False),'reconstruction':'finite multi-view track surface hypothesis; OpenMVS did not produce depth','published':False})
    print(json.dumps({'triangles':len(triangles),'points':len(keep),'reference':ref}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--window',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.window,a.out)
