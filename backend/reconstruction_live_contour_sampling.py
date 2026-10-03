"""One-sided, same-surface derivatives at observed depth discontinuities.

Research helper: no depth extrapolation, mask dilation or opacity changes.
Identical centre grid/depth and forward derivatives on regular interiors.
"""
import numpy as np
from reconstruction_live_dense_contract import unproject


def surface_samples(depth, K, T, *, ownership=None, stride=2):
    depth=np.asarray(depth);h,w=depth.shape
    if ownership is None:ownership=np.ones_like(depth,dtype=bool)
    ownership=np.asarray(ownership,dtype=bool)
    if ownership.shape!=depth.shape or stride<1:raise ValueError('contour_sampling_contract')
    yy,xx=np.mgrid[1:h-1:stride,1:w-1:stride];yy=yy.ravel();xx=xx.ravel()
    uv=np.c_[xx,yy].astype(float);z=depth[yy,xx]
    xyz=unproject(uv,z,K,T)
    centre=ownership[yy,xx]&np.isfinite(z)&(z>0)&np.isfinite(xyz).all(1)
    vectors=[];valids=[];fallback=[]
    for axis in (0,1):
        dx,dy=(1,0) if axis==0 else (0,1)
        zp=depth[yy+dy,xx+dx];zm=depth[yy-dy,xx-dx]
        positive=centre&ownership[yy+dy,xx+dx]&np.isfinite(zp)&(zp>0)&(np.abs(zp-z)<.03*z)
        negative=centre&ownership[yy-dy,xx-dx]&np.isfinite(zm)&(zm>0)&(np.abs(zm-z)<.03*z)
        use_negative=~positive&negative
        forward=unproject(uv+[dx,dy],zp,K,T)-xyz
        backward=xyz-unproject(uv-[dx,dy],zm,K,T)
        vectors.append(np.where(use_negative[:,None],backward,forward))
        valids.append(positive|negative);fallback.append(use_negative)
    a,b=vectors
    normal=np.cross(a,b);norm=np.linalg.norm(normal,axis=1)
    sa=np.linalg.norm(a,axis=1);sb=np.linalg.norm(b,axis=1)
    good=centre&valids[0]&valids[1]&(norm>1e-12)&(sa>0)&(sb>0)
    normal=normal/np.maximum(norm[:,None],1e-12);tangent=a/np.maximum(sa[:,None],1e-12)
    basis=np.stack((tangent,np.cross(normal,tangent),normal),-1)
    scales=np.stack((sa,sb,np.minimum(sa,sb)*.25),1)*stride*.75
    return uv,xyz,basis,scales,good,dict(
        fallbackX=fallback[0],fallbackY=fallback[1],centreValid=centre,
        directionValidX=valids[0],directionValidY=valids[1])
