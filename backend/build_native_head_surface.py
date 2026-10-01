"""Native actual-MVS hair proposal in verified head-local coordinates.
Physical fused points are conditional on the fixed local F; no generated hair.
"""
from pathlib import Path
import json,hashlib,shutil,argparse
import cv2,numpy as np,torch
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from reconstruction_components_v3 import sha,save_json
from reconstruction_mvs_contract import read_mvs_cloud
from reconstruction_room_surface_repair import validate_imported_native_intrinsics
from reconstruction_dense_contract import project
from reconstruction_portrait_pipeline import make_frame
from reconstruction_complete_context import load_complete


def supported_region(folder,data,plan,base,min_views=3):
    folder=Path(folder);meta=json.loads((folder/'contract.json').read_text());names=meta['names']
    if meta['sourceHash']!=data['sourceHash'] or meta['cameraFrame']!='head-local':raise ValueError('head_surface_source_or_frame_changed')
    if set(names)&set(plan['development']+plan['audit']) or any(data['local'][n]['role']!='train' for n in names):raise ValueError('head_MVS_role_leak')
    validate_imported_native_intrinsics(folder,meta,meta['nativeK'])
    np.testing.assert_allclose(meta['fullK'],data['K'],rtol=0,atol=1e-6)
    cameras={n:base.baseline.adjusted_frame(make_frame(data,n,crop=False))['F'].cpu().numpy() for n in names}
    for n in names:np.testing.assert_allclose(meta['contract']['cameras'][n],cameras[n],rtol=0,atol=1e-6)
    cloud=read_mvs_cloud(folder/'dense.ply');xyz=cloud['xyz'];norm=np.linalg.norm(cloud['normal'],axis=1)
    finite=np.isfinite(xyz).all(1)&np.isfinite(cloud['normal']).all(1)&(norm>.8)
    views=np.zeros((len(names),len(xyz)),bool);col=np.zeros((len(xyz),3));count=np.zeros(len(xyz),int);source=np.full(len(xyz),'',dtype='U64');sourceUV=np.zeros((len(xyz),2));uvs={}
    for vi,n in enumerate(names):
        uv,z=project(xyz,data['K'],cameras[n]);uvs[n]=uv;h,w=data['rgb'][n].shape[:2];xy=np.rint(np.nan_to_num(uv)).astype(int)
        inside=finite&(z>0)&(xy[:,0]>1)&(xy[:,0]<w-2)&(xy[:,1]>1)&(xy[:,1]<h-2)&np.array([vi in v for v in cloud['views']])
        lab=data['labels'][n];mask=cv2.erode((lab['hair_visible']&~lab['unknown_or_occluded']).astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)
        clipped=xy.clip([0,0],[w-1,h-1]);inside&=mask[clipped[:,1],clipped[:,0]];ii=np.flatnonzero(inside)
        if not len(ii):continue
        rgb=np.array([np.median(data['rgb'][n][y-1:y+2,x-1:x+2],axis=(0,1)) for x,y in xy[ii]])
        first=count[ii]==0;source[ii[first]]=n;sourceUV[ii[first]]=uv[ii[first]];col[ii]+=rgb;count[ii]+=1;views[vi,ii]=True
    ii=np.flatnonzero(count>=min_views)
    if len(ii)<32:raise ValueError('insufficient_actual_hair_surface:'+str(len(ii)))
    f=base.baseline.adjusted_frame(make_frame(data,data['reference'],crop=False));head=base.baseline.head_state(f);old=torch.where(base.keep_head&(head.parts==2))[0];parent_support=np.zeros(len(old),int)
    for vi,n in enumerate(names):
        ids=ii[views[vi,ii]]
        if not len(ids):continue
        posed=base.baseline.head_state(base.baseline.adjusted_frame(make_frame(data,n,crop=False)));uv,z=project(posed.means[old].cpu().numpy(),data['K'],cameras[n]);distance=cKDTree(uvs[n][ids]).query(uv)[0]
        parent_support+=(distance<=4)&(z>0)
    retired=old[parent_support>=min_views].cpu().numpy()
    if len(retired)<8:raise ValueError('no_finite_hair_parent_surface_overlap:'+str(len(retired)))
    # Source-linked finite sampling; density spacing is recomputed after budget.
    digest=sha(folder/'dense.ply');uid=np.array([int.from_bytes(hashlib.sha256(f'HEAD-MVS:{digest}:{i}'.encode()).digest()[:8],'little')&((1<<63)-1) for i in ii],np.int64)
    if len(ii)>4000:
        order=np.argsort(uid);selected=order[np.rint(np.linspace(0,len(order)-1,4000)).astype(int)];ii=ii[selected];uid=uid[selected]
    points=xyz[ii];normal=cloud['normal'][ii]/norm[ii,None];nn=np.median(cKDTree(points).query(points,k=min(5,len(points)))[0][:,1:],1)
    ref=names[len(names)//2];_,z=project(points,data['K'],cameras[ref]);pixel=z/data['K'][0,0]
    if np.any(pixel<=0):raise ValueError('invalid_head_surface_depth')
    axis=np.tile([1.,0,0],(len(points),1));axis[abs(normal[:,0])>.8]=[0,1,0];u=np.cross(axis,normal);u/=np.linalg.norm(u,axis=1,keepdims=True);v=np.cross(normal,u)
    q=Rotation.from_matrix(np.stack((u,v,normal),-1)).as_quat()[:,[3,0,1,2]];tangent=np.clip(nn*.7,pixel*.8,pixel*3.);scales=np.c_[tangent,tangent,np.minimum(tangent*.25,pixel*.6)]
    sh=np.zeros((len(points),4,3));sh[:,0]=(col[ii]/count[ii,None]-.5)/.28209479177387814
    arrays=dict(means=points,quats=q,scales=scales,opacity=np.full(len(points),.6),sh=sh,parts=np.full(len(points),2,np.int64),uid=uid,support=count[ii],source_index=ii,source_image=source[ii],source_uv=sourceUV[ii],normal=normal,source_hash=np.array(data['sourceHash']))
    proposal=dict(names=names,rawPoints=len(xyz),hairSupported=int((count>=min_views).sum()),selected=len(points),minViews=min_views,retiredHead=retired.tolist(),retiredUID=base.baseline.portrait.stable_uid[torch.as_tensor(retired,device='cuda')].cpu().tolist(),remainingHair=int(len(old)-len(retired)),
        cloudHash=digest,cameraFrame='head-local',nativePixelContractChecked=True,colour='native original hair-valid 3x3 median over actual fused views',unknownHairKept=True,oldPointProposal='centre within 4 native pixels of measured hair in at least 3 actual fused supporting observations; not visibility truth',
        geometryConditionalOnF=True,completeHairValidated=False,published=False)
    return arrays,retired,proposal

def run(complete,mvs,out):
    out=Path(out);data,plan,base,contract=load_complete(complete,out);a,ids,record=supported_region(mvs,data,plan,base)
    np.savez_compressed(out/'surface.npz',**a);save_json(out/'proposal.json',record);shutil.copyfile(__file__,out/'algorithm-source'/Path(__file__).name);print(json.dumps({k:record[k] for k in ['rawPoints','hairSupported','selected','remainingHair']}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--mvs',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.complete,a.mvs,a.out)
