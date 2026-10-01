"""Observed surface envelopes for standard 3DGS, research only.

Original implementation inspired by depth-regularized 3DGS and surface
concentration. No PGSR/2DGS renderer is copied or claimed. The centre-depth
moments are a diagnostic/regularizer, NOT ray-plane intersections or depth
truth. Prior depth remains camera-conditioned evidence, never a publication
certificate. RGB supervision is independent of feature/depth availability.
"""
from pathlib import Path
import json
import cv2
import numpy as np
import torch
import torch.nn.functional as F
from gsplat import rasterization
from reconstruction_dense_contract import project, unproject, bilinear, digest
from reconstruction_dense_surfaces import native_uv
from reconstruction_portrait_model import GaussianState, quaternion_matrix, evaluate_sh1
from reconstruction_portrait_pipeline import masked_mean


def sample_mask(mask, uv):
    finite=np.isfinite(uv).all(-1);p=np.rint(np.nan_to_num(uv)).astype(np.int64)
    h,w=mask.shape;valid=finite&(p[:,0]>=0)&(p[:,0]<w)&(p[:,1]>=0)&(p[:,1]<h)
    out=np.zeros(len(p),bool);out[valid]=mask[p[valid,1],p[valid,0]]
    return out


def moment_error(q, first, second, depth):
    """Normalized E[(centre z - observed z)^2], true alpha*T weights.
    Differentiable normalization avoids rewarding uniform opacity collapse.
    Does not claim to measure within-kernel thickness or true first surfaces.
    """
    mass=q.clamp_min(1e-5);d=depth.clamp_min(1e-5)
    return (second/mass/d.square()-2*first/mass/d+1).clamp_min(0)


def draw_moments(state,C,K,width,height,unit_scale):
    centre=torch.linalg.inv(C)[:3,3]
    rgb=evaluate_sh1(state.sh,state.means-centre)
    group=F.one_hot(state.parts.long(),5).to(rgb.dtype)
    z=(state.means@C[:3,:3].T+C[:3,3])[:,2]/unit_scale
    features=torch.cat((rgb,group,group*z[:,None],group*z.square()[:,None]),1)
    im,a,info=rasterization(state.means,state.quats,state.scales,state.opacity,features,
        C[None],K[None],width,height,packed=True,sh_degree=None,render_mode='RGB',
        rasterize_mode='classic',near_plane=.01*unit_scale,far_plane=1e10*unit_scale)
    return dict(rgb=im[0,:,:,:3],q=im[0,:,:,3:8],first=im[0,:,:,8:13],
        second=im[0,:,:,13:18],alpha=a[0,:,:,0],info=info)


def transport_patch(original,reference,patch):
    """Reference-local deltas follow each component's EXISTING rigid motion.
    Fixed point order, no reclassification, no camera/pose edits. At zero
    delta state is exact (including unnormalised serialization quaternions).
    """
    R=quaternion_matrix(original.quats)@quaternion_matrix(reference.quats).transpose(-1,-2)
    delta=patch.state()
    from reconstruction_portrait_model import quat_product
    q0=reference.quats  # already normalized once by FreeComponent.state()
    inv=q0*torch.tensor([1.,-1.,-1.,-1.],device=q0.device)
    dq=quat_product(inv,delta.quats)
    rotated=quat_product(original.quats,dq)
    # Add the rotation delta to exact original avoids normalization-only drift.
    initial_rot=quat_product(original.quats,quat_product(inv,q0))
    quats=original.quats+(rotated-initial_rot)
    v=delta.sh-reference.sh
    vector=torch.stack((-v[:,3],-v[:,1],v[:,2]),1)
    moved=torch.einsum('nij,njc->nic',R,vector)
    sh=original.sh+torch.stack((v[:,0],-moved[:,1],moved[:,2],-moved[:,0]),1)
    return GaussianState(original.means+torch.einsum('nij,nj->ni',R,delta.means-reference.means),
        quats,original.scales*(delta.scales/reference.scales),
        original.opacity+(delta.opacity-reference.opacity),sh,original.parts)


def collect_observed_depth(depth_folder,data,train_names,masks,body_names,out,*,body_motion=None,body_motion_verified=False):
    """Dense pixel support, not SIFT/Delaunay coverage. Distinct train views.
    Keep unknown/unconfirmed pixels out of depth loss, never out of RGB loss.
    Fixed 3% depth consistency; no per-frame depth rescaling. Each window's
    scale was previously verified by its saved camera contract.
    Clothing requires explicitly verified same-unit motion; missing or merely
    photometric motion omits depth supervision, never the RGB observations.
    """
    folder=Path(depth_folder);spec=json.loads((folder/'manifest.json').read_text())
    if spec['sourceHash']!=data['sourceHash'] or spec['depthMeaning']!='camera_z' or spec['matrixMeaning']!='W2C':
        raise ValueError('depth_contract_mismatch')
    rows=[r for r in spec['observations'] if r['group']=='world' and r['scaleGatePassed'] and r['imageName'] in train_names]
    cache={};records=[];selected={}
    for r in rows:
        n=r['imageName']
        if r['role']!='train' or n in spec['forbidden']:raise ValueError('heldout_depth_leak')
        a=dict(np.load(folder/r['file']));np.testing.assert_allclose(a['W2C'],data['worlds'][n],rtol=0,atol=1e-5)
        np.testing.assert_allclose(a['K'],a['nativeToProcessed']@data['K'],rtol=0,atol=1e-4)
        cache[r['file']]=a
    for r in rows:
        n=r['imageName'];a=cache[r['file']];h,w=a['depth'].shape
        yy,xx=np.mgrid[:h,:w];uv=np.c_[xx.ravel(),yy.ravel()].astype(float)
        dep=a['depth'].ravel();xyz=unproject(uv,dep,a['K'],a['W2C']);nuv=native_uv(uv,a['nativeToProcessed'])
        from reconstruction_surface_handoff import observation_layers
        layers=observation_layers(n,body_names,body_motion,body_motion_verified)
        result={}
        for layer in layers:
            own=sample_mask(masks[n][layer],nuv)&np.isfinite(dep)&(dep>0)
            own &= a['confidence'].ravel()>=np.quantile(a['confidence'],.2)
            support=np.zeros(len(uv),np.int16);free=np.zeros(len(uv),np.int16);seen=set()
            for t in rows:
                tn=t['imageName']
                if t['window']!=r['window'] or tn in seen or (layer=='cloth' and tn not in body_names):continue
                seen.add(tn);b=cache[t['file']]
                projected=xyz
                if layer=='cloth':
                    if tn not in body_motion:continue
                    from reconstruction_surface_handoff import move_observation_points
                    projected=move_observation_points(xyz,n,tn,body_motion)
                puv,z=project(projected,b['K'],b['W2C'])
                d=bilinear(b['depth'],puv);cf=bilinear(b['confidence'],puv)
                valid=np.isfinite(d)&(d>0)&(z>0)&sample_mask(masks[tn][layer],native_uv(puv,b['nativeToProcessed']))
                valid &= cf>=np.quantile(b['confidence'],.2)
                support+=(valid&(abs(z-d)<=.03*d)).astype(np.int16)
                free+=(valid&(z<d-.03*d)).astype(np.int16)
            good=own&(support>=3)&(free<=1)
            # Native output sampling, exact recorded half-pixel mapping, no guessed K.
            nh,nw=data['rgb'][n].shape[:2];ny,nx=np.mgrid[:nh,:nw]
            p=np.c_[nx.ravel(),ny.ravel(),np.ones(nh*nw)]@a['nativeToProcessed'].T;p=p[:,:2]
            valid=sample_mask(good.reshape(h,w),p).reshape(nh,nw)&masks[n][layer]
            d=bilinear(a['depth'],p).reshape(nh,nw);valid&=np.isfinite(d)&(d>0)
            # A depth discontinuity is not smoothed into a new surface.
            lo=cv2.erode(a['depth'].astype(np.float32),np.ones((3,3),np.uint8));hi=cv2.dilate(a['depth'].astype(np.float32),np.ones((3,3),np.uint8))
            stable=(hi-lo)<=.06*np.maximum(a['depth'],1e-6)
            valid &= sample_mask(stable,p).reshape(nh,nw)
            result[layer]=(np.nan_to_num(d).astype(np.float32),valid)
            records.append(dict(name=n,window=r['window'],layer=layer,densePixels=int(own.sum()),supportedPixels=int(good.sum()),nativeValidPixels=int(valid.sum()),hash=digest(folder/r['file'])))
        # Prefer observation with most consensus pixels, never development RGB.
        score=sum(int(v.sum()) for _,v in result.values())
        if n not in selected or score>selected[n][0]:selected[n]=(score,result)
    priors={n:r[1] for n,r in selected.items()}
    out=Path(out);out.mkdir(exist_ok=False)
    for n,layers in priors.items():np.savez_compressed(out/(n+'.npz'),**{k+suffix:value for k,pair in layers.items() for suffix,value in zip(('_depth','_valid'),pair)})
    (out/'manifest.json').write_text(json.dumps(dict(sourceHash=data['sourceHash'],inputManifestHash=digest(folder/'manifest.json'),modelLock=spec['modelLock'],records=records,
        supervision='camera-conditioned multiview depth; not independent truth',bodyDepthMotion='verified explicit same-unit B transport' if body_motion is not None and body_motion_verified else 'unknown; omitted from depth, retained in RGB',rgbUsesAllValidObservedPixels=True),indent=2),encoding='utf-8')
    return priors,records
