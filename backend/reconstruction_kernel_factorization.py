"""Local covariance factorization with explicit inherited evidence.
The un-clipped quadrature preserves Gaussian density moments; clipping can
change those moments. This is NOT
an identity of alpha compositing, a new surface measurement or generated detail.
It provides a bounded representation trial whose image coverage must recover.
"""
import hashlib
import numpy as np
import torch
from reconstruction_portrait_model import GaussianState,quaternion_matrix
from reconstruction_components_v3 import FreeComponent

def quadrature_children(state,parent_uid,axes=(0,1),order=7,fraction=.45):
    if order<3 or not 0<fraction<1 or len(set(axes))!=len(axes):
        raise ValueError('factorization_configuration')
    nodes,weight=np.polynomial.hermite.hermgauss(order)
    nodes=nodes*np.sqrt(2*(1-fraction*fraction));weight=weight/np.sqrt(np.pi)
    mesh=np.meshgrid(*([np.arange(order)]*len(axes)),indexing='ij')
    codes=np.stack([m.reshape(-1) for m in mesh],1)
    n=len(state.means); k=len(codes); device=state.means.device
    local=torch.zeros(k,3,device=device,dtype=state.means.dtype)
    mass=torch.ones(k,device=device,dtype=state.means.dtype)
    for col,axis in enumerate(axes):
        local[:,axis]=torch.tensor(nodes[codes[:,col]],device=device,dtype=state.means.dtype)
        mass*=torch.tensor(weight[codes[:,col]],device=device,dtype=state.means.dtype)
    # Choose the largest canonical covariance axes independently for each parent.
    sorted_axes=torch.argsort(state.scales,dim=-1,descending=True)
    coordinates=torch.zeros(n,k,3,device=device)
    attenuation=torch.ones(n,3,device=device)
    for axis in axes:
        idx=sorted_axes[:,axis]
        coordinates.scatter_(2,idx[:,None,None].expand(n,k,1),local[:,axis][None,:,None].expand(n,k,1))
        attenuation.scatter_(1,idx[:,None],fraction)
    offset=coordinates*state.scales[:,None,:]
    R=quaternion_matrix(state.quats)
    means=state.means[:,None,:]+torch.einsum('nij,nkj->nki',R,offset)
    scales=state.scales*attenuation
    peak=state.opacity[:,None]*mass[None,:]/(fraction**len(axes))
    opacity=peak.clamp(.00001,.995)
    result=GaussianState(means.reshape(-1,3),
        state.quats[:,None,:].expand(n,k,4).reshape(-1,4),
        scales[:,None,:].expand(n,k,3).reshape(-1,3),
        opacity.reshape(-1),state.sh[:,None,:,:].expand(n,k,4,3).reshape(-1,4,3),
        state.parts[:,None].expand(n,k).reshape(-1))
    uid=[]
    for parent in parent_uid:
        for code in codes:
            uid.append(int.from_bytes(hashlib.sha256(('factorization:'+str(int(parent))+':'+','.join(map(str,code))).encode()).digest()[:8],'little')&((1<<63)-1))
    return result,np.asarray(uid,np.int64),dict(parentCount=n,childrenPerParent=k,
        massWeights=mass.cpu().tolist(),gridCodes=codes.tolist(),
        parentUID=np.repeat(np.asarray(parent_uid),k).tolist(),
        axesRank=list(axes),order=order,fraction=fraction,
        peakClampCount=int((peak>.995).sum()),peakLowerClampCount=int((peak<.00001).sum()),
        preservesQuadratureMomentsBeforeClamp=True,
        preservesDensityMoments=bool(((peak>=.00001)&(peak<=.995)).all()),preservesAlphaCompositing=False,
        geometryEvidence='inherited baseline covariance; NOT independent new geometry')

class LocalKernelTransaction(torch.nn.Module):
    def __init__(self,baseline,ids,children,uid):
        super().__init__();self.baseline=baseline;self.scale=baseline.scale
        self.register_buffer('parent_ids',torch.as_tensor(ids,device='cuda',dtype=torch.long))
        keep=torch.ones(len(baseline.baseline.room.state().means),device='cuda',dtype=torch.bool)
        keep[self.parent_ids]=False; self.register_buffer('keep_room',keep)
        # The only displaced positions are inherited children. Geometry is held
        # fixed first, and can never quietly move the rest of the full scene.
        bound=torch.median(children.scales.min(-1).values)*.5
        self.patch=FreeComponent(children,torch.as_tensor(uid,device='cuda'),
            torch.ones(len(uid),device='cuda'),'world',bound)
    def state(self,f):
        from reconstruction_components_v3 import pick
        from reconstruction_portrait_model import joined_state
        s=self.baseline.state(f)
        # Continuity order: retained head, retained room, retained body, patch.
        head=int(self.baseline.keep_head.sum()); oldids=torch.where(self.baseline.keep_room)[0]
        valid=~torch.isin(oldids,self.parent_ids)
        mask=torch.ones(len(s.means),device=s.means.device,dtype=torch.bool)
        mask[head:head+len(oldids)]=valid
        return joined_state(pick(s,mask),self.patch.state())
    def render(self,f):
        from reconstruction_portrait_pipeline import draw
        f=self.baseline.baseline.adjusted_frame(f);s=self.state(f);h,w=f['rgb'].shape[:2]
        return draw(s,f['C'],f['K'],w,h,unit_scale=self.scale)