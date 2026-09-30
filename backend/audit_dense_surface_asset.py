"""Frozen same-PLY contract, visibility and orbit. Not device release approval."""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch,cv2
from scipy.spatial.transform import Rotation
from reconstruction_dense_contract import digest,write_json
from reconstruction_joint_visibility import load_recorded_ply
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import draw
from audit_portrait_priority_handoff import camera_looking_at

@torch.no_grad()
def run(folder,out):
    folder=Path(folder);out=Path(out);out.mkdir(exist_ok=False)
    shutil.copyfile(__file__,out/Path(__file__).name)
    asset=folder/'candidate-research-only.ply';side=dict(np.load(folder/'candidate-identities.npz'));result=json.loads((folder/'result.json').read_text());spec=json.loads((folder/'spec.json').read_text());raw=dict(np.load(Path(spec['prepared'])/'local_geometry.npz'))
    identity=digest(asset)
    if str(side['asset_sha256'])!=identity:raise ValueError('asset_identity_mismatch')
    if len(side['component'])!=len(side['point_id']) or not np.array_equal(side['point_id'],np.arange(len(side['point_id']))):raise ValueError('exact_index_contract')
    keys=np.c_[side['source_namespace'],side['source_uid']]
    if len(np.unique(keys,axis=0))!=len(keys):raise ValueError('duplicate_uid_namespace')
    ref=result['reference'];li={str(n):i for i,n in enumerate(raw['names'])};wi={str(n):i for i,n in enumerate(raw['world_names'])}
    C=torch.tensor(raw['C'][wi[ref]],device='cuda',dtype=torch.float32);K=torch.tensor(raw['K'],device='cuda',dtype=torch.float32)
    z=load_recorded_ply(asset,max(1,int((side['source_namespace']==0).sum())))
    state=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],torch.tensor(side['component'],device='cuda',dtype=torch.long))
    h,w=cv2.imread(str(Path(spec['prepared'])/'rectified_observations'/ref)).shape[:2];scale=float(raw['scale'])
    original=draw(state,C,K,w,h,unit_scale=scale)
    rgba={k:original[k].cpu().numpy() for k in ('rgb','alpha','q')};np.savez_compressed(out/'gsplat-reference.npz',**rgba)
    cv2.imwrite(str(out/'gsplat-reference.png'),cv2.cvtColor((original['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    conservation=float((original['q'].sum(-1)-original['alpha']).abs().max())
    inv=torch.linalg.inv(C).cpu().numpy();eye=inv[:3,3];forward=inv[:3,2];up=-inv[:3,1]
    conf={'assets':[{'label':'candidate','ply':str(asset),'hash':identity}], 'K':K.cpu().tolist(),'C':C.cpu().tolist(),'width':w,'height':h,'near':.01*scale,'far':1e10*scale,'camera':eye.tolist(),'target':(eye+forward).tolist(),'up':up.tolist(),'reference':ref,'sourceHash':result['sourceHash'],'published':False}
    write_json(out/'display.json',conf)
    # Reference head origin in world; pivot and orbit axis use the SAME recorded
    # reference H, not an asset AABB that room/outliers can pull away from face.
    F=raw['F'][li[ref]].copy();F[:3,3]*=scale;H=np.linalg.solve(raw['C'][wi[ref]],F);pivot=H[:3,3];axis=H[:3,1];axis=axis/np.linalg.norm(axis)
    yaw=np.r_[np.linspace(0,-60,31),np.linspace(-60,60,61)[1:],np.linspace(60,0,31)[1:]]
    video=cv2.VideoWriter(str(out/'frozen-ply-orbit.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),20,(540,960));views=[];start=time.perf_counter()
    for i,degrees in enumerate(yaw):
        R=Rotation.from_rotvec(axis*np.radians(degrees)).as_matrix();moved=(eye-pivot)@R.T+pivot;look=(eye+forward-pivot)@R.T+pivot
        camera=camera_looking_at(moved,look,R@up)
        r=draw(state,torch.tensor(camera,device='cuda',dtype=torch.float32),K,w,h,unit_scale=scale)
        img=cv2.cvtColor((r['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR)
        video.write(cv2.resize(img,(540,960),interpolation=cv2.INTER_AREA))
        if i in (0,30,60,90,120):cv2.imwrite(str(out/f'orbit-{i:03d}.png'),img)
        views.append({'index':i,'viewerRelativeYawDegrees':float(degrees),'C':camera.tolist(),'assetHash':identity})
    video.release();write_json(out/'orbit.json',{'frames':views,'renderedSize':[w,h],'encodedSize':[540,960],'renderer':'gsplat1.5.3_not_PlayCanvas_or_Harmony','yawIsViewerRelativeNotMeasuredHeadAngle':True,'sourceHash':result['sourceHash']})
    write_json(out/'result.json',{'assetHash':identity,'pointCount':len(state.means),'UIDNamespaceUnique':True,'componentCounts':{str(p):int((side['component']==p).sum()) for p in np.unique(side['component'])},'qConservationMax':conservation,'orbitSeconds':time.perf_counter()-start,'releaseQualityPassed':False,'published':False,'sourceHash':result['sourceHash']})
    print('FROZEN_ASSET_DRAWN',identity,conservation,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.folder,a.out)