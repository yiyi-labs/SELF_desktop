"""Observed physical layers and a bounded head/body transition, research only.

No production, transport or viewer imports. Labels are rectified using recorded
distortion; body skin is never inferred from RGB colour. Motion is one bounded
short-window hypothesis, not an independently measured skeleton.
"""
from pathlib import Path
import json
import cv2
import numpy as np
import torch
from reconstruction_portrait_model import (GaussianState, quaternion_matrix,
    quat_product, rotate_sh1, scaled_head_transform)
from reconstruction_research_state import rigid_component_state


def neck_region(body_skin, face):
    """Associate observed skin with the lower face, excluding hands/arms.

    Selfie class 2 means *all* body skin, not neck. A face-relative association
    band selects existing pixels only; it never fills unknown pixels, fabric,
    or a gap between head and body. No image coordinates or person IDs are used.
    """
    body_skin=np.asarray(body_skin,bool);face=np.asarray(face,bool)
    if body_skin.shape!=face.shape:raise ValueError('semantic_canvas_mismatch')
    ys,xs=np.where(face)
    if not len(xs):return np.zeros_like(body_skin)
    left,right=int(xs.min()),int(xs.max());bottom=int(ys.max())
    fw=max(right-left+1,1);fh=max(bottom-int(ys.min())+1,1)
    h,w=face.shape;association=np.zeros_like(face)
    # The central neck/chest opening, with a small allowance for segmentation
    # gaps under the jaw. Distant exposed arm skin stays a separate body part.
    x0=max(0,left-int(.15*fw));x1=min(w,right+int(.15*fw)+1)
    y0=max(0,bottom-int(.10*fh));y1=min(h,bottom+int(.75*fh)+1)
    association[y0:y1,x0:x1]=True
    count,labels=cv2.connectedComponents((body_skin&association).astype(np.uint8),8)
    contact=np.zeros_like(face);contact[max(0,bottom-int(.10*fh)):min(h,bottom+max(3,int(.18*fh))+1),x0:x1]=True
    ids=np.unique(labels[contact&body_skin]);ids=ids[ids!=0]
    return np.isin(labels,ids)&body_skin if len(ids) else np.zeros_like(body_skin)


def physical_masks(prepared, data, names):
    prep=Path(prepared)
    audit=json.loads((prep/'pose-and-scale-audit.json').read_text())
    distortion=np.asarray(audit['sourceRadialDistortion'],float)
    result={}
    for name in names:
        h,w=data['rgb'][name].shape[:2]
        x,y=cv2.initUndistortRectifyMap(data['K'],distortion,None,data['K'],(w,h),cv2.CV_32FC1)
        raw=cv2.imread(str(prep/'component_masks/labels'/(name+'.png')),cv2.IMREAD_GRAYSCALE)
        if raw is None or raw.shape!=(h,w):raise ValueError('missing_original_semantics:'+name)
        confidence=np.load(prep/'component_masks/confidence'/(name+'.npz'))['confidence'].astype(np.float32)
        classes=cv2.remap(raw,x,y,cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=255)
        certainty=cv2.remap(confidence,x,y,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
        old=data['labels'][name];valid=(certainty>=.70)&~old['unknown_or_occluded']
        # Existing selfie-multiclass model: 2=body skin, 4=clothes. Face oval
        # exclusions remain authoritative. No shirt/skin boundary is welded.
        body_skin=valid&(classes==2)&old['neck_cloth_visible']
        face=(old['face_core']|old['face_boundary'])&~old['glasses_visible']&~old['unknown_or_occluded']
        neck=neck_region(body_skin,face)
        result[name]={'neck':neck,'other_body_skin':body_skin&~neck,
            'cloth':valid&(classes==4)&old['neck_cloth_visible'],
            'hair':old['hair_visible']&~old['unknown_or_occluded'],
            'room':old['room_visible']&~old['unknown_or_occluded'],
            'face':face}
        if np.any(result[name]['neck']&result[name]['cloth']):raise ValueError('physical_layer_overlap')
    return result


def smooth_transition(coordinate, top, bottom):
    """Fixed canonical scalar coordinate, upper=head, lower=body.
    This blends *motion*, never RGB or alpha. No per-view reclassification.
    """
    if not np.isfinite([top,bottom]).all() or bottom<=top:raise ValueError('invalid_transition_domain')
    u=((coordinate-top)/(bottom-top)).clamp(0,1)
    return 1-u*u*(3-2*u)


def blend_rigid_state(state, head_transform, body_transform, weight):
    """Continuous two-node rigid motion with quaternion/SH direction transport.

    Local covariance uses blended orientation and unchanged axis lengths.
    This deliberately does not claim a full affine-strain neck model. At both
    ends the complete rigid result is exact. Reference identity is exact.
    """
    from reconstruction_portrait_model import rotation_quaternion
    if weight.shape!=(len(state.means),) or not torch.isfinite(weight).all():raise ValueError('transition_weights')
    if torch.any((weight<0)|(weight>1)):raise ValueError('transition_weight_range')
    H,B=head_transform,body_transform
    xh=state.means@H[:3,:3].T+H[:3,3];xb=state.means@B[:3,:3].T+B[:3,3]
    from reconstruction_shared_surface import small_rotation_quaternion
    qh=small_rotation_quaternion(H[:3,:3][None])[0] if H.requires_grad else rotation_quaternion(H[:3,:3])
    qb=small_rotation_quaternion(B[:3,:3][None])[0] if B.requires_grad else rotation_quaternion(B[:3,:3])
    # Trainable body rotations are bounded near identity and retain gradients.
    # Sign alignment avoids a quaternion antipodal discontinuity.
    qb=qb*torch.where((qh*qb).sum()<0,-1.,1.)
    q=torch.nn.functional.normalize(weight[:,None]*qh+(1-weight[:,None])*qb,dim=-1)
    # Direction coefficients must follow the SAME per-point rigid orientation
    # as covariance. Averaging coefficients from two rotations would damp SH
    # at intermediate weights rather than transport one directional field.
    R=quaternion_matrix(q);vector=torch.stack((-state.sh[:,3],-state.sh[:,1],state.sh[:,2]),1)
    moved=torch.einsum('nij,njc->nic',R,vector)
    colour=torch.stack((state.sh[:,0],-moved[:,1],moved[:,2],-moved[:,0]),1)
    return GaussianState(weight[:,None]*xh+(1-weight[:,None])*xb,
        quat_product(q,state.quats),state.scales,state.opacity,colour,state.parts)


class ShortWindowBodyMotion(torch.nn.Module):
    """Six shared velocity parameters. Fixed scale/reference and no free poses.
    Out-of-window observations are never silently extrapolated.
    """
    def __init__(self,timestamps,reference,pivot,scale,device='cuda'):
        super().__init__();self.timestamps=dict(timestamps);self.reference=reference
        if reference not in timestamps or len(timestamps)<3:raise ValueError('motion_reference_observations')
        self.duration=max(timestamps.values())-min(timestamps.values())
        if self.duration<=0:raise ValueError('zero_motion_duration')
        self.scale=float(scale);self.register_buffer('pivot',torch.as_tensor(pivot,device=device,dtype=torch.float32))
        self.velocity=torch.nn.Parameter(torch.zeros(6,device=device))
    def state(self,state,name):
        if name not in self.timestamps:raise ValueError('motion_outside_observed_window:'+name)
        tau=(self.timestamps[name]-self.timestamps[self.reference])/self.duration
        v=self.velocity.tanh()*tau
        return rigid_component_state(state,v[:3]*(np.pi/180/np.sqrt(3)),v[3:]*(.005*self.scale/np.sqrt(3)),self.pivot)
    def matrix(self,name):
        from flame_open_model import axis_angle_matrix
        if name not in self.timestamps:raise ValueError('motion_outside_observed_window:'+name)
        tau=(self.timestamps[name]-self.timestamps[self.reference])/self.duration
        v=self.velocity.tanh()*tau;R=axis_angle_matrix(v[:3]*(np.pi/180/np.sqrt(3)))
        T=torch.eye(4,device=R.device,dtype=R.dtype);T[:3,:3]=R
        T[:3,3]=self.pivot-R@self.pivot+v[3:]*(.005*self.scale/np.sqrt(3))
        return T
    def regularizer(self):return self.velocity.tanh().square().mean()


def spatial_neighbours(means,quats,scales,parts):
    """Same physical surface only; no skin/cloth or different depth bridges."""
    from scipy.spatial import cKDTree
    means=np.asarray(means);n=len(means)
    if n<2:return np.empty((0,2),np.int64)
    dist,ix=cKDTree(means).query(means,k=min(n,5))
    i=np.repeat(np.arange(n),ix.shape[1]-1);j=ix[:,1:].reshape(-1);distance=dist[:,1:].reshape(-1)
    extent=np.max(scales[:,:2],axis=1)
    keep=(parts[i]==parts[j])&(distance<=4*np.maximum(extent[i],extent[j]))&(i<j)
    return np.c_[i[keep],j[keep]].astype(np.int64)
