"""Depth-only research interchange. No network, viewer, worker or publisher imports."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
import numpy as np
import cv2

SCHEMA = "self-dense-observation-1"
def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()
def write_json(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding="utf-8")
def rigid_check(T):
    T=np.asarray(T,dtype=np.float64)
    if T.shape!=(4,4) or not np.isfinite(T).all():raise ValueError("invalid_transform")
    if not np.allclose(T[3],[0,0,0,1],atol=1e-6):raise ValueError("invalid_homogeneous_row")
    if not np.allclose(T[:3,:3].T@T[:3,:3],np.eye(3),atol=2e-4) or np.linalg.det(T[:3,:3])<.999:
        raise ValueError("nonrigid_camera")
    return T
def resized_camera(K, rectangle, native_size, processed_size):
    """Zero-based pixel centres, OpenCV half-pixel resize; crop BEFORE resize."""
    x0,y0,x1,y1=rectangle; nw,nh=native_size; w,h=processed_size
    if not(0<=x0<x1<=nw and 0<=y0<y1<=nh):raise ValueError("invalid_crop")
    sx,sy=w/(x1-x0),h/(y1-y0)
    A=np.array([[sx,0,sx*(.5-x0)-.5],[0,sy,sy*(.5-y0)-.5],[0,0,1.]])
    return A@K,A
def unproject(uv,z,K,W2C):
    uv=np.asarray(uv); z=np.asarray(z); T=rigid_check(W2C)
    ray=np.c_[uv,np.ones(len(uv))]@np.linalg.inv(K).T
    camera=ray*z[:,None]; return (camera-T[:3,3])@T[:3,:3]
def project(xyz,K,W2C):
    T=rigid_check(W2C); cam=xyz@T[:3,:3].T+T[:3,3]
    q=cam@K.T; return q[:,:2]/q[:,2:],cam[:,2]
def camera_centres(extrinsics):
    return np.stack([-rigid_check(T)[:3,:3].T@T[:3,3] for T in extrinsics])
def normalize_cameras(extrinsics):
    ex=np.asarray(extrinsics).copy()
    for T in ex:rigid_check(T)
    ex=ex@np.linalg.inv(ex[0]); radius=np.median(np.linalg.norm(camera_centres(ex),axis=1))
    radius=max(float(radius),.1); ex[:,:3,3]/=radius
    return ex,radius
def align_camera_scale(predicted,known):
    """ONE similarity for a window, no per-frame scale or synthesized pose."""
    a=camera_centres(predicted);b=camera_centres(known)
    ac=a-a.mean(0);bc=b-b.mean(0);energy=np.sum(ac*ac)
    if energy<1e-9:raise ValueError("unobservable_scale")
    U,s,Vh=np.linalg.svd(bc.T@ac);fix=np.eye(3);fix[-1,-1]=np.sign(np.linalg.det(U@Vh))
    R=U@fix@Vh;scale=float(np.trace(np.diag(s)@fix)/energy)
    if not np.isfinite(scale) or scale<=0:raise ValueError("invalid_depth_scale")
    t=b.mean(0)-scale*R@a.mean(0); residual=np.linalg.norm(scale*a@R.T+t-b,axis=1)
    baseline=max(float(np.sqrt(np.mean(np.sum(bc*bc,axis=1)))),1e-9)
    return scale,{"scale":scale,"rotation":R.tolist(),"translation":t.tolist(),
                  "cameraCentreRmsRelative":float(np.sqrt(np.mean(residual**2))/baseline),
                  "inputBaseline":baseline,"perFrameScale":False}
def bilinear(array,uv):
    # cv2.remap output dimensions are signed-short; dense point lists may
    # exceed 32767 rows. Chunk the requests, NOT the source image or geometry.
    q=np.asarray(uv,dtype=np.float32);array=np.asarray(array,dtype=np.float32)
    if not len(q):return np.empty((0,)+array.shape[2:],np.float32)
    return np.concatenate([cv2.remap(array,r[:,0,None],r[:,1,None],cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,borderValue=np.nan)[:,0] for r in
        (q[i:i+16000] for i in range(0,len(q),16000))],axis=0)
def classify_depth(candidate_z, observed_z, relative_tolerance=.03):
    """Occlusion is UNKNOWN, never independent visible contradiction."""
    candidate_z=np.asarray(candidate_z);observed_z=np.asarray(observed_z)
    out=np.full(candidate_z.shape,0,np.int8) # 0 unknown
    valid=np.isfinite(candidate_z)&np.isfinite(observed_z)&(candidate_z>0)&(observed_z>0)
    tol=relative_tolerance*observed_z
    out[valid & (np.abs(candidate_z-observed_z)<=tol)]=1 # compatible proposal
    out[valid & (candidate_z<observed_z-tol)]=-1 # candidate in observed free space
    out[valid & (candidate_z>observed_z+tol)]=2 # nearer observed surface; occluded
    return out
def validate_manifest(spec):
    if spec["schema"]!=SCHEMA:raise ValueError("depth_schema_mismatch")
    if spec["colour"]!="original_srgb_rgb":raise ValueError("colour_mismatch")
    if spec["depthMeaning"]!="camera_z" or spec["matrixMeaning"]!="W2C":
        raise ValueError("coordinate_contract_mismatch")
    names=[r["imageName"] for r in spec["observations"]]
    if len(names)!=len(set(names)):raise ValueError("duplicate_image_identity")
    for r in spec["observations"]:
        if r["role"]!="train":raise ValueError("heldout_in_depth_proposal")
        if r["sourceHash"]!=spec["sourceHash"]:raise ValueError("source_mismatch")
        rigid_check(r["W2C"])
        if not r.get("imageHash") or r["sourceIndexZeroBased"]<0:raise ValueError("missing_source_identity")
    return True

def complete_parameter_aliases(required,loaded):
    """Allow serialization aliases ONLY for the same Parameter object."""
    result=dict(loaded);aliases=[]
    for key,param in required.items():
        if key in result:continue
        same=[other for other,value in required.items() if value is param and other in result]
        if not same:raise ValueError('missing_independent_weight:'+key)
        result[key]=result[same[0]];aliases.append({'key':key,'sameParameterAs':same[0]})
    return result,aliases
def validate_surface_source(meta, arrays, expected_source_hash):
    """A shared source hash is necessary, not a geometry quality approval."""
    if not expected_source_hash or meta.get('sourceHash') != expected_source_hash:
        raise ValueError('surface_source_mismatch')
    for label,arr in arrays.items():
        if 'source_hash' not in arr or str(arr['source_hash']) != expected_source_hash:
            raise ValueError('surface_array_source_mismatch:'+label)
        required=('means','quats','scales','opacity','sh','parts','uid','support','confidence','source_image','source_uv')
        if any(k not in arr for k in required):
            raise ValueError('surface_fields_missing:'+label)
        n=len(arr['means'])
        if any(len(arr[k]) != n for k in required):
            raise ValueError('surface_field_length_mismatch:'+label)
        if len(np.unique(arr['uid'])) != n:
            raise ValueError('surface_uid_collision:'+label)
        if any(not np.isfinite(arr[k]).all() for k in ('means','quats','scales','opacity','sh','confidence')):
            raise ValueError('surface_nonfinite:'+label)
        if np.any(arr['scales']<=0) or np.any(arr['opacity']<=0) or np.any(arr['opacity']>1):
            raise ValueError('surface_invalid_scale_or_alpha:'+label)
    return True