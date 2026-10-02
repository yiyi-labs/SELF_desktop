"""Native full-canvas math shared by complete-state recovery and research.

Consolidates the actual draw/frame formulas. No runner, preparation, density,
production profile or image downsampling is invoked here.
"""
import numpy as np
import torch
import torch.nn.functional as functional
from gsplat import rasterization
from reconstruction_portrait_model import evaluate_sh1


def draw(state,C,K,width,height,*,unit_scale=1.,antialiased=False,absgrad=False):
    center=torch.linalg.inv(C)[:3,3]
    rgb=evaluate_sh1(state.sh,state.means-center)
    groups=functional.one_hot(state.parts.long(),5).to(rgb.dtype)
    depth=(state.means@C[:3,:3].T+C[:3,3])[:,2]
    features=torch.cat((rgb,groups,groups*depth[:,None]),dim=1)
    image,alpha,info=rasterization(state.means,state.quats,state.scales,state.opacity,
        features,C[None],K[None],width,height,packed=True,sh_degree=None,
        render_mode='RGB+D',rasterize_mode='antialiased' if antialiased else 'classic',
        near_plane=.01*unit_scale,far_plane=1e10*unit_scale,absgrad=absgrad)
    return dict(rgb=image[0,:,:,:3],alpha=alpha[0,:,:,0],q=image[0,:,:,3:8],
        q_depth=image[0,:,:,8:13]/unit_scale,depth=image[0,:,:,-1]/unit_scale,info=info)


def masked_mean(value,mask):
    return (value*mask).sum()/mask.sum().clamp_min(1)


def make_frame(data,name,*,crop=True,half=False,device='cuda'):
    tensor=lambda x:torch.as_tensor(np.ascontiguousarray(x),device=device,dtype=torch.float32)
    rgb=data['rgb'][name];labels=data['labels'][name];K=data['K'].copy();h,w=rgb.shape[:2];rectangle=(0,0,w,h)
    if crop:
        observed=labels['face_core']|labels['face_boundary']|labels['hair_visible']|labels['glasses_visible']
        y,x=np.where(observed)
        if not len(x):raise ValueError('missing_head_observation:'+name)
        rectangle=(max(0,int(x.min())-24),max(0,int(y.min())-24),min(w,int(x.max())+25),min(h,int(y.max())+25))
        x0,y0,x1,y1=rectangle;rgb=rgb[y0:y1,x0:x1];labels={k:v[y0:y1,x0:x1] for k,v in labels.items()}
        K[0,2]-=x0;K[1,2]-=y0
    return dict(rgb=tensor(rgb),masks={k:tensor(v).bool() for k,v in labels.items()},K=tensor(K),
        F=tensor(data['local'][name]['F']),C=tensor(data['worlds'][name]) if name in data['worlds'] else None,
        mesh=tensor(data['local'][name]['mesh']),rectangle=rectangle,name=name,nativeScale=1,fullSize=(w,h),
        fullK=tensor(data['K']),requestedHalfIgnored=bool(half))


def full_frame_draw(state,C,frame,*,unit_scale=1.,antialiased=False,absgrad=False):
    w,h=frame['fullSize'];x0,y0,x1,y1=frame['rectangle'];K=frame['fullK']
    cropK=K.clone();cropK[0,2]-=x0;cropK[1,2]-=y0
    if not torch.allclose(cropK,frame['K'],atol=1e-5,rtol=0):raise ValueError('native_crop_intrinsics_changed')
    if frame['nativeScale']!=1 or frame['rgb'].shape[:2]!=(y1-y0,x1-x0):raise ValueError('native_canvas_contract')
    center=torch.linalg.inv(C)[:3,3];rgb=evaluate_sh1(state.sh,state.means-center)
    groups=functional.one_hot(state.parts.long(),5).to(rgb.dtype)
    depth=(state.means@C[:3,:3].T+C[:3,3])[:,2]
    features=torch.cat((rgb,groups,groups*depth[:,None]),1)
    image,alpha,info=rasterization(state.means,None,None,state.opacity,features,C[None],K[None],w,h,
        covars=state.covariance(),packed=True,sh_degree=None,render_mode='RGB+D',absgrad=absgrad,
        rasterize_mode='antialiased' if antialiased else 'classic',near_plane=.01*unit_scale,far_plane=1e10*unit_scale)
    info['width']=w;info['height']=h
    if info['means2d'].requires_grad:info['means2d'].retain_grad()
    full=dict(rgb=image[0,:,:,:3],alpha=alpha[0,:,:,0],q=image[0,:,:,3:8],
        q_depth=image[0,:,:,8:13]/unit_scale,depth=image[0,:,:,-1]/unit_scale)
    return {**{k:v[y0:y1,x0:x1] for k,v in full.items()},'info':info}
