"""Prepare a bounded actual static-room MVS window, no camera rematching."""
import argparse,json,time
from pathlib import Path
import cv2,numpy as np,pycolmap
from reconstruction_surface_evidence import export_colmap,project
from reconstruction_components_v3 import save_json,sha

def run(prepared,out,reference):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);p=Path(prepared);meta=json.loads((p/'preparation.json').read_text());z=dict(np.load(p/'local_geometry.npz'));K=z['K'];C={str(n):z['C'][i] for i,n in enumerate(z['world_names'])};available=sorted(set(meta['train'])&set(C));ref=int(reference[6:10]);names=sorted(sorted(available,key=lambda n:abs(int(n[6:10])-ref))[:7]);images={};masks={}
    for n in names:
        images[n]=cv2.cvtColor(cv2.imread(str(p/'rectified_observations'/n)),cv2.COLOR_BGR2RGB);lab=dict(np.load(p/'rectified_observations'/(n+'.npz')));masks[n]=lab['room_visible']&~lab['unknown_or_occluded']
    path=Path(meta['staticMap']);path=path if path.is_absolute() else p.parent.parent/path;mapping=pycolmap.Reconstruction(str(path));points=[]
    for pid,point in mapping.points3D.items():
        if point.error>2.5:continue
        obs=[]
        for element in point.track.elements:
            im=mapping.images[element.image_id];n=im.name
            if n not in names:continue
            ray=mapping.cameras[im.camera_id].cam_from_img(im.points2D[element.point2D_idx].xy);q=K@np.r_[ray,1.];uv=q[:2]/q[2];x,y=np.rint(uv).astype(int)
            if 0<=x<1080 and 0<=y<1920 and masks[n][y,x]:obs.append({'name':n,'uv':uv.tolist(),'sigma':1.})
        if len(obs)>=3:points.append({'sourceID':int(pid),'xyz':point.xyz.tolist(),'observations':obs,'color':point.color.tolist(),'error':float(point.error)})
    contract=export_colmap(out/'colmap',images,masks,names,C,K,points);save_json(out/'contract.json',{'schema':'self.surface-window.v1','sourceHash':meta['sourceHash'],'prepared':str(p),'preparedHash':sha(p/'preparation.json'),'names':names,'cameraFrame':'world','B':{n:np.eye(4).tolist() for n in names},'contract':contract,'use':'training_only_static_room','mask':'all observed room pixels, including low texture; not SIFT support mask'});save_json(out/'tracks.json',points)
    print(json.dumps({'names':names,'points':len(points)}),flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--prepared',required=True);a.add_argument('--out',required=True);a.add_argument('--reference',required=True);s=a.parse_args();run(s.prepared,s.out,s.reference)
