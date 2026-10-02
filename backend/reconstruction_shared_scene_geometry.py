"""Evidence-constrained shared geometry for the complete research scene.
Original implementation; no renderer/production replacement. One displacement
field is shared across cameras. Unknown geometry stays represented in RGB.
"""
import numpy as np
import torch
from scipy.spatial import cKDTree
from reconstruction_portrait_model import GaussianState, quaternion_matrix
from reconstruction_surface_continuity import transport_covariance


class LayeredSurfaceField(torch.nn.Module):
    """Bounded material field with normal/layer guards and analytic Jacobian.
    Unlike distance-only smoothing, close parallel sheets cannot share a node
    across their normal separation. Every zero field is exactly the old state.
    """
    def __init__(self, points, normals, thickness, metric, controls=96):
        super().__init__()
        if len(points)<4 or controls<1:raise ValueError('surface_domain')
        p=points.detach();n=torch.nn.functional.normalize(normals.detach(),dim=-1)
        metric=torch.as_tensor(metric,device=p.device,dtype=p.dtype).expand(len(p)).clone()
        if not torch.isfinite(p).all() or not (metric>0).all():raise ValueError('surface_metric')
        selected=[0];distance=torch.full((len(p),),float('inf'),device=p.device)
        for _ in range(min(controls,len(p))-1):
            distance=torch.minimum(distance,(p-p[selected[-1]]).square().sum(-1))
            selected.append(int(distance.argmax()))
        ids=torch.tensor(selected,device=p.device);nodes=p[ids]
        radius=torch.cdist(p,nodes).min(1).values.quantile(.85).clamp_min(metric.median()*4)*2
        self.register_buffer('nodes',nodes);self.register_buffer('normal',n[ids])
        self.register_buffer('radius',radius)
        self.register_buffer('thickness',thickness[ids].detach().clamp_min(metric[ids]*2))
        # Native-pixel-derived limits, not coordinates of this particular face.
        self.register_buffer('bound',metric[ids]*32)
        self.delta=torch.nn.Parameter(torch.zeros_like(nodes))
    def forward(self,points,normals,thickness):
        distance=torch.cdist(points,self.nodes)
        _,idx=distance.topk(min(4,len(self.nodes)),dim=1,largest=False)
        d=points[:,None]-self.nodes[idx]
        normal=self.normal[idx]
        same=(normal*normals[:,None]).sum(-1).abs()>.90
        gap=(d*normal).sum(-1).abs()
        # Layer admission is fixed geometry, not optimized into a zero weight.
        same &= gap<2*(self.thickness[idx]+thickness[:,None])
        raw=torch.exp(-d.square().sum(-1)/(2*self.radius.square()))*same
        w=raw/raw.sum(1,keepdim=True).clamp_min(1e-20)
        v=self.delta.tanh()[idx]*self.bound[idx][...,None]
        grad=-d/self.radius.square()
        dw=w[:,:,None]*(grad-(w[:,:,None]*grad).sum(1,keepdim=True))
        offset=(w[:,:,None]*v).sum(1)
        J=torch.eye(3,device=points.device,dtype=points.dtype)[None]+torch.einsum('nki,nkj->nji',dw,v)
        return points+offset,J
    def regularizer(self):return self.delta.tanh().square().mean()


def surface_normals(state):
    R=quaternion_matrix(state.quats)
    smallest=state.scales.argmin(-1)
    n=R[torch.arange(len(R),device=R.device),:,smallest]
    return n,state.scales.min(-1).values


def polar_frame(J,chunk=512):
    # Small-matrix batched CUDA workspace grows sharply with batch length.
    # Same factorization, bounded batches; no precision/geometry approximation.
    output=[]
    for a in J.detach().split(chunk):
        u,_,v=torch.linalg.svd(a)
        fix=torch.ones((len(a),3),device=a.device,dtype=a.dtype)
        fix[:,-1]=torch.linalg.det(u@v).sign()
        output.append((u*fix[:,None,:])@v)
    return torch.cat(output)


def bounded_singular_values(J,chunk=512):
    return torch.cat([torch.linalg.svdvals(a) for a in J.split(chunk)])


def move_sh(sh,R):
    v=torch.stack((-sh[:,3],-sh[:,1],sh[:,2]),1)
    moved=torch.einsum('nij,njc->nic',R,v)
    return torch.stack((sh[:,0],-moved[:,1],moved[:,2],-moved[:,0]),1)


def replace_same_order(state,ids,patch):
    """Exact index identity and all unaffected fields, including SH/parts."""
    if len(ids)!=len(patch.means) or len(torch.unique(ids))!=len(ids):raise ValueError('replacement_order')
    result={}
    for k in GaussianState.__dataclass_fields__:
        a=getattr(state,k).clone();a[ids]=getattr(patch,k);result[k]=a
    return GaussianState(**result)


def guarded_surface_edges(points,normals,thickness,parts,metric,k=6):
    """Same owner, normal and depth sheet; no fabric/skin welding or folds."""
    p=np.asarray(points);n=np.asarray(normals);th=np.asarray(thickness);px=np.broadcast_to(metric,(len(p),))
    d,j=cKDTree(p).query(p,k=min(k,len(p)))
    i=np.repeat(np.arange(len(p)),j.shape[1]-1);j=j[:,1:].ravel();d=d[:,1:].ravel();v=p[j]-p[i]
    good=(i<j)&(parts[i]==parts[j])&(np.abs((n[i]*n[j]).sum(1))>.90)
    good &= (np.abs((v*n[i]).sum(1))<2*(th[i]+th[j]+px[i]))&(d<12*np.maximum(px[i],px[j]))
    return np.c_[i[good],j[good]].astype(np.int64)


def canonicalize_sources(points,quats,sh,source_names,motions,*,verified):
    """Observed world-at-source -> one canonical body reference, before fusion.
    Never silently consume a photometric B or identity for an unknown source.
    """
    if not verified:raise ValueError('body_motion_unverified')
    from scipy.spatial.transform import Rotation
    from reconstruction_dense_contract import rigid_check
    from reconstruction_portrait_model import rotate_sh1
    p=np.asarray(points).copy();q=np.asarray(quats).copy();colour=np.asarray(sh).copy()
    for name in sorted(set(source_names)):
        if name not in motions:raise ValueError('body_source_motion_missing:'+str(name))
        T=np.linalg.inv(rigid_check(motions[name]));ids=np.where(source_names==name)[0]
        p[ids]=p[ids]@T[:3,:3].T+T[:3,3]
        R=Rotation.from_matrix(T[:3,:3]);q[ids]=(R*Rotation.from_quat(q[ids][:,[1,2,3,0]])).as_quat()[:,[3,0,1,2]]
        colour[ids]=rotate_sh1(torch.tensor(colour[ids]),torch.tensor(T[:3,:3],dtype=torch.tensor(colour).dtype)).numpy()
    return p,q,colour