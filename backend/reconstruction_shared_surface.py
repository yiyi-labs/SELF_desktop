"""Isolated shared-surface correction. No production entry or topology changes.
A track has ONE immutable triangle/barycentric anchor and multiple true pixels.
"""
import math
import numpy as np
import torch
import torch.nn.functional as F
from reconstruction_detail_controlled import DetailModel
from reconstruction_portrait_model import GaussianState, quat_product


def triangle_frames(tri):
    x=F.normalize(tri[:,1]-tri[:,0],dim=-1)
    z=F.normalize(torch.linalg.cross(x,tri[:,2]-tri[:,0]),dim=-1)
    y=torch.linalg.cross(z,x)
    return torch.stack((x,y,z),-1)


def small_rotation_quaternion(R):
    # Only bounded, near-identity surface transports use this branch.
    # Unlike the fixed world-transform converter, this retains derivatives.
    w=torch.sqrt((1+R.diagonal(dim1=-2,dim2=-1).sum(-1)).clamp_min(1e-8))*.5
    return F.normalize(torch.stack((w,(R[:,2,1]-R[:,1,2])/(4*w),
        (R[:,0,2]-R[:,2,0])/(4*w),(R[:,1,0]-R[:,0,1])/(4*w)),-1),dim=-1)


class SharedSurfaceModel(DetailModel):
    def attach_surface(self,basis,bound):
        p=self.portrait
        self.register_buffer('surface_base',p.surface_residual.detach().clone())
        self.register_buffer('surface_basis',basis)
        self.register_buffer('surface_bound',torch.as_tensor(bound,device=basis.device,dtype=basis.dtype))
        self.surface_control=torch.nn.Parameter(torch.zeros(basis.shape[1],3,device=basis.device,dtype=basis.dtype))
    def displacement(self):
        return (self.surface_basis@self.surface_control.tanh())*self.surface_bound/math.sqrt(3)
    def current_mesh(self,mesh):return mesh+self.surface_base+self.displacement()
    def head_state(self,frame):
        # Existing complete state, including offsets/glasses/hair, is preserved.
        # The fixed portrait surface_residual is represented exactly by base.
        mesh=frame['mesh'];delta=self.displacement();p=self.portrait
        state=super().head_state({**frame,'mesh':mesh+delta})
        ids=p.faces[p.triangle_ids]
        before=triangle_frames((mesh+self.surface_base)[ids])
        after=triangle_frames((mesh+self.surface_base+delta)[ids])
        R=after@before.transpose(-1,-2)
        q=quat_product(small_rotation_quaternion(R),state.quats[:p.surface_count])
        return GaussianState(state.means,torch.cat((q,state.quats[p.surface_count:])),
            state.scales,state.opacity,state.sh,state.parts)
    def project_anchors(self,mesh,transform,K,triangle,bary):
        tri=self.current_mesh(mesh)[self.portrait.faces[triangle]]
        xyz=(tri*bary[...,None]).sum(1)
        cam=xyz@transform[:3,:3].T+transform[:3,3]
        uv=cam@K.T
        return uv[:,:2]/uv[:,2:],cam[:,2]


def make_basis(mesh,faces,anchor_triangles,count=12,rings=3):
    """Bounded connected chart; no per-pair independent geometry variables."""
    allowed=set(int(v) for t in anchor_triangles for v in faces[t])
    for _ in range(rings):
        use=np.isin(faces,list(allowed)).any(1)
        allowed.update(faces[use].reshape(-1).tolist())
    vertices=np.array(sorted(allowed));coords=mesh[vertices]
    centers=[int(np.argmin(np.linalg.norm(coords-coords.mean(0),axis=1)))]
    for _ in range(min(count,len(vertices))-1):
        distance=np.min(np.linalg.norm(coords[:,None]-coords[centers][None],axis=-1),axis=1)
        centers.append(int(distance.argmax()))
    d=np.linalg.norm(coords[:,None]-coords[centers][None],axis=-1)
    spacing=np.median(np.partition(np.linalg.norm(coords[centers][:,None]-coords[centers][None],axis=-1),1,axis=1)[:,1])
    raw=np.exp(-.5*(d/max(spacing,1e-6))**2);raw/=raw.sum(1,keepdims=True)
    # Boundary taper avoids moving unobserved neighbouring components abruptly.
    edges=np.unique(np.sort(np.concatenate([faces[:,:2],faces[:,1:],faces[:,[0,2]]]),axis=1),axis=0)
    inside=np.isin(edges,vertices);boundary=edges[inside.sum(1)==1][inside[inside.sum(1)==1]]
    taper=np.ones(len(vertices))
    if len(boundary):
        edge_distance=np.min(np.linalg.norm(coords[:,None]-mesh[np.unique(boundary)][None],axis=-1),axis=1)
        taper=np.minimum(edge_distance/max(spacing*.75,1e-6),1)
    basis=np.zeros((len(mesh),len(centers)),np.float32);basis[vertices]=raw*taper[:,None]
    return basis,{'vertices':vertices.tolist(),'controls':vertices[centers].tolist(),'spacing':float(spacing),'rings':rings}

