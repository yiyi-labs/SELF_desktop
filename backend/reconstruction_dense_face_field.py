"""Conditional dense multi-window face geometry, fixed topology and original SH.
No synthetic texture, camera rewrite, identity change, or per-view warp.
"""
import numpy as np,torch
from scipy.spatial import cKDTree
from scipy.optimize import lsq_linear
from build_cross_window_surface import build_surface
from run_measured_head_surface_repair import LocalMeasuredField
from reconstruction_components_v3 import save_json
from reconstruction_portrait_pipeline import make_frame
from reconstruction_portrait_model import quaternion_matrix


def dense_face_field(base,data,plan,folders,out,geometry_mode='vector'):
    arrays,proposal=build_surface(folders,data,plan,base,out,budget=6000,part='face')
    f=base.baseline.adjusted_frame(make_frame(data,data['reference'],crop=False));head=base.baseline.head_state(f)
    ids=torch.where(base.keep_head&(head.parts==1))[0];xyz=head.means[ids].detach().cpu().numpy()
    rotation=quaternion_matrix(head.quats[ids]).detach().cpu().numpy();scales=head.scales[ids].detach().cpu().numpy()
    distance,index=cKDTree(xyz).query(arrays['means'])
    normals=rotation[np.arange(len(ids)),:,scales.argmin(1)]
    compatible=np.abs((normals[index]*arrays['normal']).sum(1))>=np.cos(np.radians(30))
    keep=(arrays['cross_window_agreement']>0)&compatible&(distance<=5*arrays['pixel'])
    source=np.flatnonzero(keep)
    if len(source)<32:raise ValueError('insufficient_cross_window_face_depth:'+str(len(source)))
    # A coarse Gaussian is not a unique physical surface sample. Multiple actual
    # measured positions within its footprint remain distinct surface anchors.
    # Initialize each on the compatible old tangent surface, not at its centre.
    chosen=source[np.argsort(arrays['uid'][source])]
    if len(chosen)>1024:chosen=chosen[np.floor(np.arange(1024)*len(chosen)/1024).astype(int)]
    measured=arrays['means'][chosen];delta=measured-xyz[index[chosen]];nn=normals[index[chosen]]
    old=measured-(delta*nn).sum(1)[:,None]*nn
    pixel=float(np.median(arrays['pixel'][chosen]));field=LocalMeasuredField(torch.tensor(old,device='cuda',dtype=torch.float32),pixel*3,min(16 if geometry_mode=='normal' else 96,len(old)))
    w=field.weights(torch.as_tensor(old,device='cuda',dtype=torch.float32))[0].detach().cpu().numpy()
    # Stable source hashes define hold-out conditional depth support before fitting.
    held=arrays['uid'][chosen]%5==0
    if held.sum()<8 or (~held).sum()<16:raise ValueError('insufficient_conditional_depth_audit')
    target=(measured-old)/float(field.maximum)
    quality=np.minimum(arrays['support'][chosen],5)/5
    A=w[~held]*quality[~held,None];b=target[~held]*quality[~held,None]
    if geometry_mode=='normal':
        # Shared normal displacement only; lateral XYZ freedom cannot absorb
        # conditional depth noise. Node normals remain the frozen prior.
        _,ni=cKDTree(old).query(field.nodes.cpu().numpy());node_normal=nn[ni]
        block=np.concatenate([A*node_normal[:,axis][None] for axis in range(3)],0)
        value=np.concatenate([b[:,axis] for axis in range(3)])
        fit=lsq_linear(np.r_[block,np.eye(A.shape[1])*.05],np.r_[value,np.zeros(A.shape[1])],bounds=(-.95,.95),max_iter=80,tol=1e-8)
        v=fit.x[:,None]*node_normal
    elif geometry_mode=='vector':
        solutions=[]
        for axis in range(3):
            fit=lsq_linear(np.r_[A,np.eye(A.shape[1])*.05],np.r_[b[:,axis],np.zeros(A.shape[1])],bounds=(-.95,.95),max_iter=80,tol=1e-8);solutions.append(fit.x)
        v=np.stack(solutions,1)
    else:raise ValueError('unknown_geometry_mode')
    initial=np.linalg.norm(measured-old,axis=1)/pixel
    final=np.linalg.norm(measured-old-w@v*float(field.maximum),axis=1)/pixel
    accepted=bool(np.quantile(final[held],.9)<=np.quantile(initial[held],.9)+.1 and np.median(final[held])<np.median(initial[held]))
    with torch.no_grad():field.delta.copy_(torch.tensor(np.arctanh(v),device='cuda',dtype=torch.float32))
    for p in field.parameters():p.requires_grad_(False)
    save_json(out/'geometry.json',dict(method='cross-window actual fused depth; bounded shared canonical surface field',
        geometryMode=geometry_mode,anchors=len(chosen),heldDepth=len(final[held]),controls=len(field.nodes),maximumPixels=3,
        initialMedianPixels=float(np.median(initial)),finalMedianPixels=float(np.median(final)),
        heldInitialP90Pixels=float(np.quantile(initial[held],.9)),heldFinalP90Pixels=float(np.quantile(final[held],.9)),
        geometryResearchGatePassed=accepted,conditionalOnRecordedF=True,independentGeometryTruth=False,
        poseFixed=True,topologyFixed=True,syntheticDetails=False))
    np.savez_compressed(out/'geometry-depth-support.npz',old=old,measured=measured,uid=arrays['uid'][chosen],head_id=ids[index[chosen]].cpu().numpy(),held=held,initialError=initial,finalError=final)
    torch.save(field.state_dict(),out/'field.pt')
    active=ids[field.weights(head.means[ids])[0].sum(1)>.01]
    return field,active,accepted,data['reference']
