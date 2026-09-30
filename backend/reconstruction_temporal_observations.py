"""Generic timestamp/ROI contracts for continuous source-video proposals.
No frame-number slicing, world-camera requirement, or synthetic masks/poses.
"""
import numpy as np,cv2


def select_windows(rows, maximum_seconds=3.5, maximum_anchor_gap=.8, limit=2):
    ordered=sorted(rows,key=lambda r:(r["timestampSeconds"],r["name"]))
    if len({r["name"] for r in ordered})!=len(ordered):
        raise ValueError("duplicate_image_name")
    chains=[]
    for r in ordered:
        if not chains or r["timestampSeconds"]-chains[-1][-1]["timestampSeconds"]>maximum_anchor_gap:
            chains.append([])
        chains[-1].append(r)
    candidates=[]
    for chain in chains:
        for i in range(len(chain)):
            block=[r for r in chain[i:] if r["timestampSeconds"]-chain[i]["timestampSeconds"]<=maximum_seconds]
            if len(block)<4:continue
            # Scores are training-image measurements, never dev/audit RGB.
            quality=np.median([r["sharpness"] for r in block])
            coverage=min(r["coverage"] for r in block)
            views=np.array([r["cameraCenter"] for r in block])
            parallax=np.linalg.norm(views-views[0],axis=1).max()
            score=float(np.log1p(quality)*np.sqrt(coverage)*(1+min(parallax,1)))
            candidates.append((score,block))
    result=[]
    for _,block in sorted(candidates,key=lambda x:(-x[0],x[1][0]["timestampSeconds"])):
        names={r["name"] for r in block}
        if any(len(names&{r["name"] for r in old})/min(len(names),len(old))>.5 for old in result):
            continue
        result.append(block)
        if len(result)==limit:break
    return result


def source_indices(times, anchors, hz=12., max_frames=64):
    times=np.asarray(times,float)
    if times.ndim!=1 or not len(times) or not np.isfinite(times).all() or np.any(np.diff(times)<=0):
        raise ValueError("strict_source_timestamps_required")
    if not anchors or hz<=0 or max_frames<1:raise ValueError("invalid_temporal_budget")
    exact=[int(a["sourceIndexZeroBased"]) for a in anchors]
    if any(i!=a["sourceIndexZeroBased"] or not 0<=i<len(times) or not np.isfinite(a["timestampSeconds"]) for i,a in zip(exact,anchors)):
        raise ValueError("source_index_or_timestamp_invalid")
    if len(set(exact))!=len(exact):raise ValueError("duplicate_source_anchor")
    if any(abs(times[i]-a["timestampSeconds"])>.002 for i,a in zip(exact,anchors)):
        raise ValueError("source_timestamp_join_mismatch")
    lo,hi=min(exact),max(exact)
    target=np.arange(times[lo],times[hi]+.5/hz,1/hz)
    idx=np.clip(np.searchsorted(times,target),lo,hi)
    idx=np.unique(np.r_[idx,exact])
    if len(idx)>max_frames:
        # Keep every measured anchor; thin proposal-only intermediate frames.
        extras=np.setdiff1d(idx,exact);budget=max_frames-len(exact)
        if budget<0:raise ValueError("anchor_count_exceeds_budget")
        idx=np.unique(np.r_[exact,extras[np.linspace(0,len(extras)-1,budget).round().astype(int)] if budget else []])
    return idx


def crop_transform(image,rectangle,canvas_size=(512,384)):
    x0,y0,x1,y1=map(int,rectangle);h,w=image.shape[:2]
    if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError("invalid_roi")
    cw,ch=canvas_size;crop=image[y0:y1,x0:x1];ratio=min(cw/(x1-x0),ch/(y1-y0))
    nw,nh=round((x1-x0)*ratio),round((y1-y0)*ratio)
    ox,oy=(cw-nw)//2,(ch-nh)//2
    out=np.zeros((ch,cw,3),image.dtype)
    out[oy:oy+nh,ox:ox+nw]=cv2.resize(crop,(nw,nh),interpolation=cv2.INTER_AREA)
    return out,dict(sx=nw/(x1-x0),sy=nh/(y1-y0),ox=ox,oy=oy,x0=x0,y0=y0)


def pixels(p,m,inverse=False):
    p=np.asarray(p);s=np.array([m["sx"],m["sy"]]);o=np.array([m["ox"],m["oy"]]);a=np.array([m["x0"],m["y0"]])
    return (p-o+.5)/s-.5+a if inverse else (p-a+.5)*s-.5+o


def affine_center_delta(warp, shape):
    """ECC transforms patch coordinates, not offsets about the patch centre."""
    h,w=shape[:2];center=np.array([(w-1)/2.,(h-1)/2.])
    return np.asarray(warp)[:,:2]@center+np.asarray(warp)[:,2]-center


def bounded_native_affine(source,target):
    if source.shape!=target.shape:raise ValueError("native_patch_shape_mismatch")
    if min(source.std(),target.std())<.010:raise ValueError("insufficient_native_texture")
    criterion=(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,30,1e-4)
    c,w=cv2.findTransformECC(source,target,np.eye(2,3,dtype=np.float32),cv2.MOTION_AFFINE,criterion,None,3)
    d,b=cv2.findTransformECC(target,source,np.eye(2,3,dtype=np.float32),cv2.MOTION_AFFINE,criterion,None,3)
    s=np.linalg.svd(w[:,:2],compute_uv=False)
    a=np.eye(3);a[:2]=w;back=np.eye(3);back[:2]=b;cycle=back@a
    delta=affine_center_delta(w,source.shape)
    cycle_delta=affine_center_delta(cycle[:2],source.shape)
    if min(c,d)<.78 or np.linalg.norm(delta)>3 or min(s)<.7 or max(s)>1.4 or np.linalg.det(w[:,:2])<.5:
        raise ValueError("ambiguous_native_affine")
    if np.linalg.norm(cycle_delta)>1 or np.linalg.norm(cycle[:2,:2]-np.eye(2))>.15:
        raise ValueError("native_affine_cycle")
    return w,float(min(c,d)),float(np.linalg.norm(cycle_delta))
