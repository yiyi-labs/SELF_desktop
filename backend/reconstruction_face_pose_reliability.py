"""CPU local-pose proposals, independently checked by real image tracks.

Visibility from FLAME is a prior classification, never measured surface truth.
This module neither changes production preparation nor trains appearance.
"""
from dataclasses import dataclass,asdict
import cv2
import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class PoseReliabilityConfig:
    minimum_points:int=24
    front_cosine:float=.20
    rotation_bound_degrees:float=.75
    center_translation_bound_native_pixels:float=1.5
    robust_native_pixels:float=2.
    maximum_evaluations:int=60


def project(points,F,K):
    camera=np.asarray(points)@F[:3,:3].T+F[:3,3]
    pixel=camera@K.T
    return pixel[:,:2]/pixel[:,2:],camera[:,2]


def pose_delta(F,center,delta,rotation_unit,translation_unit):
    result=np.asarray(F,dtype=np.float64).copy()
    R=cv2.Rodrigues(np.asarray(delta[:3])*rotation_unit)[0]
    pivot=F[:3,:3]@center+F[:3,3]
    result[:3,:3]=R@F[:3,:3]
    result[:3,3]=R@F[:3,3]+pivot-R@pivot+np.asarray(delta[3:])*translation_unit
    return result


def bounded_pose_candidate(points,observed,F,K,fit_mask,reliability,*,config=PoseReliabilityConfig()):
    points=np.asarray(points,np.float64);observed=np.asarray(observed,np.float64)
    fitting=np.asarray(fit_mask,bool)&(np.asarray(reliability)>0)
    initial,depth=project(points,F,K)
    if not np.isfinite(points).all() or not np.isfinite(observed).all() or (depth<=0).any():
        raise ValueError('pose_reliability_nonfinite_or_nonpositive')
    if fitting.sum()<config.minimum_points:
        return np.asarray(F).copy(),{'status':'insufficient_visible_distributed_points','count':int(fitting.sum())}
    # Do not let a tiny patch or one line determine six pose variables.
    centered=observed[fitting]-observed[fitting].mean(0)
    eigen=np.linalg.eigvalsh(centered.T@centered/max(len(centered),1))
    if eigen[0]<25 or eigen[0]/eigen[1]<.025:
        return np.asarray(F).copy(),{'status':'insufficient_image_distribution','covarianceEigen':eigen.tolist()}
    center=points[fitting].mean(0)
    ru=np.radians(config.rotation_bound_degrees)/np.sqrt(3.)
    tu=float(np.median(depth[fitting])/np.mean([K[0,0],K[1,1]]))*config.center_translation_bound_native_pixels/np.sqrt(3.)
    weights=np.sqrt(np.asarray(reliability)[fitting])
    def residual(delta):
        candidate=pose_delta(F,center,delta,ru,tu)
        uv,_=project(points,candidate,K)
        # Fixed reliability from observation/prior visibility, not fitted weights.
        return ((uv[fitting]-observed[fitting])*weights[:,None]).reshape(-1)
    solved=least_squares(residual,np.zeros(6),bounds=(-1,1),loss='huber',
        f_scale=config.robust_native_pixels,max_nfev=config.maximum_evaluations,
        xtol=1e-9,ftol=1e-9,gtol=1e-9)
    candidate=pose_delta(F,center,solved.x,ru,tu)
    after,after_depth=project(points,candidate,K)
    if not np.isfinite(candidate).all() or (after_depth<=0).any():raise ValueError('pose_candidate_invalid')
    old=np.linalg.norm(initial-observed,axis=-1);new=np.linalg.norm(after-observed,axis=-1)
    return candidate,{'status':'bounded_candidate_requires_independent_texture_check',
        'config':asdict(config),'count':int(fitting.sum()),'evaluations':solved.nfev,
        'rotationDeltaDegrees':float(np.linalg.norm(solved.x[:3])*ru*180/np.pi),
        'centerTranslationDeltaModelUnits':float(np.linalg.norm(solved.x[3:])*tu),
        'translationBoundModelUnits':float(tu*np.sqrt(3.)),
        'fitMedianBefore':float(np.median(old[fitting])),'fitMedianAfter':float(np.median(new[fitting])),
        'fitP90Before':float(np.quantile(old[fitting],.9)),'fitP90After':float(np.quantile(new[fitting],.9)),
        'reservedMedianBefore':float(np.median(old[~fit_mask])),'reservedMedianAfter':float(np.median(new[~fit_mask])),
        'reservedP90Before':float(np.quantile(old[~fit_mask],.9)),'reservedP90After':float(np.quantile(new[~fit_mask],.9)),
        'deltaNormalized':solved.x.tolist(),'cameraKChanged':False,'expressionOrIdentityChanged':False,
        'appearanceUsed':False,'acceptedForTraining':False}


def triangle_landmarks(mesh,faces,landmark_faces,bary,F):
    tri=np.asarray(mesh)[np.asarray(faces)[landmark_faces]]
    point=(tri*np.asarray(bary)[...,None]).sum(1)
    normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-12)
    camera=point@F[:3,:3].T+F[:3,3]
    view=-camera/np.maximum(np.linalg.norm(camera,axis=1,keepdims=True),1e-12)
    cosine=(normal@F[:3,:3].T*view).sum(1)
    return point,cosine


def mutual_ratio_matches(a,b,ratio=.75):
    if a is None or b is None or len(a)<2 or len(b)<2:return {}
    matcher=cv2.BFMatcher(cv2.NORM_L2)
    def selected(x,y):
        return {m.queryIdx:m.trainIdx for pair in matcher.knnMatch(x,y,k=2) if len(pair)==2
            for m,n in [pair] if m.distance<ratio*n.distance}
    forward=selected(a,b);back=selected(b,a)
    return {i:j for i,j in forward.items() if back.get(j)==i}


def three_view_cycles(ab,bc,ac):
    return [(a,b,bc[b]) for a,b in sorted(ab.items()) if b in bc and ac.get(a)==bc[b]]


def native_face_features(gray,mask,sift,padding=64):
    """Allocate the detector budget locally, retaining native full-frame pixels."""
    if gray.shape!=mask.shape or gray.ndim!=2:raise ValueError('native_feature_domain_shape')
    y,x=np.where(mask)
    if not len(x):return np.zeros((0,2)),None,{'count':0,'nativeSize':list(gray.shape[::-1])}
    h,w=gray.shape;x0=max(0,int(x.min())-padding);x1=min(w,int(x.max())+padding+1)
    y0=max(0,int(y.min())-padding);y1=min(h,int(y.max())+padding+1)
    keys,descriptor=sift.detectAndCompute(gray[y0:y1,x0:x1],mask[y0:y1,x0:x1])
    points=np.array([k.pt for k in keys],np.float64).reshape(-1,2)+[x0,y0]
    return points,descriptor,{'count':len(keys),'crop':[x0,y0,x1,y1],
        'nativeSize':[w,h],'resized':False,'keypointCoordinates':'native_full_frame; crop_origin_added_once'}


def source_ray_binding(pixel,mesh,faces,F,K):
    """One source-ray anchor on the prior; not a triangulated measured point."""
    origin=-F[:3,:3].T@F[:3,3]
    direction=F[:3,:3].T@np.linalg.solve(K,np.r_[pixel,1.])
    direction/=np.linalg.norm(direction)
    tri=np.asarray(mesh)[faces];e1=tri[:,1]-tri[:,0];e2=tri[:,2]-tri[:,0]
    h=np.cross(np.broadcast_to(direction,e2.shape),e2);det=np.einsum('ij,ij->i',e1,h)
    valid=np.abs(det)>1e-10;inv=np.zeros_like(det);inv[valid]=1/det[valid]
    s=origin-tri[:,0];u=inv*np.einsum('ij,ij->i',s,h);q=np.cross(s,e1)
    v=inv*(q@direction);t=inv*np.einsum('ij,ij->i',e2,q)
    valid&=(u>=-1e-7)&(v>=-1e-7)&(u+v<=1+1e-7)&(t>0)
    if not valid.any():return None
    index=int(np.argmin(np.where(valid,t,np.inf)))
    return index,np.array([1-u[index]-v[index],u[index],v[index]])
