"""CPU-only footprint/fold/measurement attribution of an archived local phase.

Point-centre masks and projected covariance are diagnostic proxies, not actual
front alpha attribution. No cameras, masks, parameters or image pixels change.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from audit_live_scene_display import sha, local_path, save_json
from reconstruction_portrait_model import quaternion_matrix
from reconstruction_components_v2 import rectified_data
from flame_open_model import EMBEDDING


def quant(values):
    a=np.asarray(values)
    return np.quantile(a,[.5,.9,.99,1.]).tolist() if a.size else None


def projected(state, mesh, F, K):
    prefix='portrait.'
    ids=state[prefix+'faces'][state[prefix+'triangle_ids']]
    tri=(mesh+state[prefix+'surface_residual'])[ids]
    cross=torch.linalg.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    normal=torch.nn.functional.normalize(cross,dim=-1)
    bary=state[prefix+'embedding'];bary=bary/bary.sum(1,keepdim=True).clamp_min(1e-8)
    xyz=(tri*bary[...,None]).sum(1)+normal*state[prefix+'normal_offset'][:,None]
    cam=xyz@F[:3,:3].T+F[:3,3];p=cam@K.T;uv=p[:,:2]/p[:,2:]
    n=len(ids);R=quaternion_matrix(state[prefix+'quats'][:n]);s=state[prefix+'log_scales'][:n].exp().clamp(.00045,.018)
    covariance=(R*s[:,None,:].square())@R.transpose(-1,-2)
    J=cam.new_zeros((n,2,3));z=cam[:,2]
    J[:,0,0]=K[0,0]/z;J[:,1,1]=K[1,1]/z
    J[:,0,2]=-K[0,0]*cam[:,0]/z.square();J[:,1,2]=-K[1,1]*cam[:,1]/z.square()
    S=J@F[:3,:3]@covariance@F[:3,:3].T@J.transpose(-1,-2)+torch.eye(2)[None]*.3
    return uv.numpy(),torch.linalg.eigvalsh(S).clamp_min(0).sqrt().numpy(),normal.numpy(),cross.norm(dim=-1).numpy()


def edge_measure(source,predicted,mask):
    source=cv2.cvtColor((source.clip(0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2GRAY)
    predicted=cv2.cvtColor((predicted.clip(0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2GRAY)
    valid=cv2.erode(mask.astype(np.uint8),np.ones((7,7),np.uint8)).astype(bool)
    a=(cv2.Canny(source,50,100)>0)&valid;b=(cv2.Canny(predicted,50,100)>0)&valid
    da=cv2.distanceTransform((~a).astype(np.uint8),cv2.DIST_L2,5)
    db=cv2.distanceTransform((~b).astype(np.uint8),cv2.DIST_L2,5)
    return dict(sourceEdges=int(a.sum()),renderEdges=int(b.sum()),
        renderedEdgeDistanceToSourceQ50Q90Q99Max=quant(da[b]),
        sourceEdgeDistanceToRenderedQ50Q90Q99Max=quant(db[a]),
        fractionRenderedEdgesWithin2px=float((da[b]<=2).mean()) if b.any() else None,
        sourceEdgeRecallWithin2px=float((db[a]<=2).mean()) if a.any() else None,
        sourceLaplacianStd=float(cv2.Laplacian(source,cv2.CV_32F)[valid].std()),
        renderLaplacianStd=float(cv2.Laplacian(predicted,cv2.CV_32F)[valid].std()))


def run(run,prepared,out):
    run,prepared,out=map(local_path,(run,prepared,out));out.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(2)
    checkpoints=[run/'local-init.pt',run/'local-state.pt']
    states=[torch.load(p,map_location='cpu',weights_only=True)['model'] for p in checkpoints]
    data=np.load(prepared/'local_geometry.npz',allow_pickle=False)
    meta=json.loads((prepared/'preparation.json').read_text())
    fit=json.loads((prepared/'pose-and-scale-audit.json').read_text())
    distortion=np.asarray(meta.get('sourceDistortion',fit.get('sourceRadialDistortion')))
    names=[p.name[:-4] for p in sorted((run/'full-final').glob('*.npz'))]
    images,masks=rectified_data(local_path(meta['source']),local_path(meta['masks']),names,data['K'],distortion)
    embedding=np.load(EMBEDDING,allow_pickle=False)
    print('embedding keys',embedding.files,flush=True)
    faces=states[0]['portrait.faces'].numpy()
    # Official named embedding; original detector measurements are not a dense
    # texture-track oracle, especially around glasses and visible contours.
    lm_faces=embedding['lmk_face_idx'];lm_bary=embedding['lmk_b_coords'];lm_indices=embedding['landmark_indices']
    rows=[];panels=[]
    for name in names:
        at=list(data['names']).index(name);mesh=torch.from_numpy(data['meshes'][at]);F=torch.from_numpy(data['F'][at]);K=torch.from_numpy(data['K']).float()
        roi=masks[name]['face_core']|masks[name]['face_boundary'];h,w=roi.shape
        row=dict(name=name,role=str(data['roles'][at]),stages={})
        current=[]
        for index,(label,state) in enumerate(zip(('initial','final'),states)):
            uv,sigma,normal,area=projected(state,mesh,F,K)
            xy=np.rint(uv).astype(int);inside=(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
            xy[:,0]=xy[:,0].clip(0,w-1);xy[:,1]=xy[:,1].clip(0,h-1)
            onface=inside&roi[xy[:,1],xy[:,0]]
            points=mesh.numpy()+state['portrait.surface_residual'].numpy()
            marks=(points[faces[lm_faces]]*lm_bary[...,None]).sum(1)
            p=(marks@F[:3,:3].numpy().T+F[:3,3].numpy())@K.numpy().T;prediction=p[:,:2]/p[:,2:]
            err=np.linalg.norm(prediction-data['marks'][at][lm_indices],axis=1)
            source=np.load(run/('full-initial' if label=='initial' else 'full-final')/(name+'.npz'),allow_pickle=False)
            row['stages'][label]=dict(faceCenteredPointCount=int(onface.sum()),
                projectedMajorOneSigmaPixels=quant(sigma[onface,1]),projectedMinorOneSigmaPixels=quant(sigma[onface,0]),
                landmarkErrorPixels=quant(err),landmarkCount=len(err),
                imageEdges=edge_measure(images[name],source['rgb'],roi))
            current.append(source['rgb'])
        final=states[-1];ids=final['portrait.faces'][final['portrait.triangle_ids']]
        before=(mesh+states[0]['portrait.surface_residual'])[ids];after=(mesh+final['portrait.surface_residual'])[ids]
        nc=lambda t:torch.linalg.cross(t[:,1]-t[:,0],t[:,2]-t[:,0])
        a,b=nc(before),nc(after);ratio=(b.norm(dim=-1)/a.norm(dim=-1).clamp_min(1e-12)).numpy()
        dot=(torch.nn.functional.normalize(a,dim=-1)*torch.nn.functional.normalize(b,dim=-1)).sum(1).numpy()
        flipped=dot<0;collapsed=ratio<.2
        # Use final projection domain and real face mask; this is centre count.
        row['surface']=dict(normalFlippedAll=int(flipped.sum()),normalFlippedFaceCenters=int((flipped&onface).sum()),
            areaBelow20PercentAll=int(collapsed.sum()),areaBelow20PercentFaceCenters=int((collapsed&onface).sum()),
            faceAreaRatioQ50Q90Q99Max=quant(ratio[onface]))
        yy,xx=np.where(roi);box=(max(0,xx.min()-8),max(0,yy.min()-8),min(w,xx.max()+9),min(h,yy.max()+9));x0,y0,x1,y1=box
        strip=np.concatenate([im[y0:y1,x0:x1] for im in [images[name],*current]],1)
        cv2.imwrite(str(out/(name+'-source-initial-final.png')),cv2.cvtColor((strip.clip(0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        save_json(out/(name+'.json'),row);rows.append(row)
    result=dict(sourceHash=meta['sourceHash'],checkpointHashes=[sha(p) for p in checkpoints],rows=rows,
        notes=['projected covariance sigma is not a measured image PSF or radius','face centre masks do not measure actual alpha contribution',
               'MediaPipe embedding residual is not independent dense texture correspondence','fixed six existing native observations; no new fitted F or thresholds',
               'no GPU, optimizer, asset modification, or publication'])
    save_json(out/'report.json',result);print(json.dumps(rows,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('run','prepared','out'):parser.add_argument('--'+key,required=True)
    run(**vars(parser.parse_args()))
