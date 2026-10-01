"""Finite continuous surface corrections for the existing complete SELF scene.
No production, device, camera-estimation or publisher imports. A motion gradient
is transported as a covariance; a smooth RGB blend is never a skin connection.
"""
import numpy as np
import torch
from reconstruction_portrait_model import GaussianState, quaternion_matrix


def matrix_quaternion(matrix):
    """Stable branch selection, differentiable within the selected chart."""
    r=matrix
    a=torch.stack((1+r[:,0,0]+r[:,1,1]+r[:,2,2],
        1+r[:,0,0]-r[:,1,1]-r[:,2,2],1-r[:,0,0]+r[:,1,1]-r[:,2,2],
        1-r[:,0,0]-r[:,1,1]+r[:,2,2]),1).clamp_min(1e-12).sqrt()
    values=torch.stack((torch.stack((a[:,0]**2,r[:,2,1]-r[:,1,2],r[:,0,2]-r[:,2,0],r[:,1,0]-r[:,0,1]),1),
        torch.stack((r[:,2,1]-r[:,1,2],a[:,1]**2,r[:,0,1]+r[:,1,0],r[:,0,2]+r[:,2,0]),1),
        torch.stack((r[:,0,2]-r[:,2,0],r[:,0,1]+r[:,1,0],a[:,2]**2,r[:,1,2]+r[:,2,1]),1),
        torch.stack((r[:,1,0]-r[:,0,1],r[:,0,2]+r[:,2,0],r[:,1,2]+r[:,2,1],a[:,3]**2),1)),1)
    values=values/(2*a[:,:,None]);ix=a.argmax(1)
    return torch.nn.functional.normalize(values[torch.arange(len(r),device=r.device),ix],dim=1)


def transport_covariance(state,jacobian,means,rotation):
    """Exact J Sigma J^T and rigid direction transport, standard SH1/PLY output.
    Geometry solves freeze covariance directions; eigenvector charts are not
    used as unconstrained trainable rotations. Centres and eigenvalues retain
    gradients. Direction colour follows the supplied polar/rigid frame only.
    """
    covariance=jacobian@state.covariance()@jacobian.transpose(-1,-2)
    eigenvalues,basis=torch.linalg.eigh(covariance)
    # A quaternion only represents a proper orientation. Flipping an eigenaxis
    # changes neither covariance nor the scalar colour coefficients.
    basis=basis.clone();basis[:,:,0]*=torch.where(torch.linalg.det(basis)<0,-1.,1.)[:,None]
    quat=matrix_quaternion(basis.detach())
    vector=torch.stack((-state.sh[:,3],-state.sh[:,1],state.sh[:,2]),1)
    moved=torch.einsum('nij,njc->nic',rotation,vector)
    sh=torch.stack((state.sh[:,0],-moved[:,1],moved[:,2],-moved[:,0]),1)
    return GaussianState(means,quat,eigenvalues.clamp_min(1e-16).sqrt(),state.opacity,sh,state.parts)


def projected_transition_gradient(points,C,K,top,bottom,neck):
    """Analytic derivative of the fixed canonical-reference screen-y field."""
    cam=points@C[:3,:3].T+C[:3,3];q=cam@K.T
    if bottom<=top or torch.any(cam[:,2]<=0):raise ValueError('invalid_transition_reference')
    y=q[:,1]/q[:,2]
    numerator=K[1]@C[:3,:3];denominator=K[2]@C[:3,:3]
    dy=numerator[None]/q[:,2,None]-q[:,1,None]*denominator[None]/q[:,2,None].square()
    u=((y-top)/(bottom-top)).clamp(0,1)
    dw=(-6*u+6*u.square())[:,None]*dy/(bottom-top)
    dw=torch.where(neck[:,None],dw,torch.zeros_like(dw))
    return dw


def continuous_motion(state,H,B,weight,gradient,*,field_jacobian=None):
    """Full local derivative of the two-node head/body position map.
    The per-centre weight stays the restored reference field. Its derivative
    describes footprint deformation, not a new guessed skeleton or pose.
    """
    from reconstruction_continuity_surface import blend_rigid_state
    rigid=blend_rigid_state(state,H,B,weight)
    eye=torch.eye(3,device=state.means.device,dtype=state.means.dtype)
    head=state.means@H[:3,:3].T+H[:3,3];body=state.means@B[:3,:3].T+B[:3,3]
    J=weight[:,None,None]*H[:3,:3]+(1-weight[:,None,None])*B[:3,:3]
    if field_jacobian is not None:J=J@field_jacobian
    # The weights and their derivative are tied to canonical material points.
    # Their outer-product term is NOT differentiated through the field again.
    J=J+(head-body)[:,:,None]*gradient[:,None,:]
    # Polar frame is evaluated without colour fitting or an unstable SVD
    # gradient at repeated singular values. This stage fixes H/B.
    U,_,V=torch.linalg.svd(J.detach());fix=eye[None].repeat(len(J),1,1)
    fix[:,2,2]=torch.where(torch.linalg.det(U@V)<0,-1.,1.)
    R=U@fix@V
    result=transport_covariance(state,J,rigid.means,R)
    return result,J


class SharedDisplacementField(torch.nn.Module):
    """One bounded canonical field shared by every view; no per-view warp."""
    def __init__(self,points,maximum,controls=24):
        super().__init__()
        if len(points)<3 or maximum<=0:raise ValueError('surface_field_domain')
        p=points.detach();indices=[0];distance=torch.full((len(p),),float('inf'),device=p.device)
        for _ in range(min(controls,len(p))-1):
            distance=torch.minimum(distance,(p-p[indices[-1]]).square().sum(-1));indices.append(int(distance.argmax()))
        nodes=p[indices];radius=torch.quantile(torch.cdist(p,nodes).min(1).values,.9).clamp_min(maximum)*2
        self.register_buffer('nodes',nodes);self.register_buffer('radius',radius)
        self.register_buffer('maximum',torch.tensor(float(maximum),device=p.device))
        self.delta=torch.nn.Parameter(torch.zeros_like(nodes))
    def forward(self,points):
        d=points[:,None]-self.nodes[None];raw=torch.exp(-d.square().sum(-1)/(2*self.radius.square()))
        weights=raw/raw.sum(-1,keepdim=True).clamp_min(1e-20)
        derivative=-d/self.radius.square()
        dw=weights[:,:,None]*(derivative-(weights[:,:,None]*derivative).sum(1,keepdim=True))
        displacement=self.delta.tanh()*self.maximum
        offset=weights@displacement
        J=torch.eye(3,device=points.device)[None]+torch.einsum('nki,kj->nji',dw,displacement)
        return points+offset,J
    def regularizer(self):
        return self.delta.tanh().square().mean()


def select_skin_contacts(neck,head,K,C,*,maximum_pixels=8.):
    """Finite same-skin proximity constraints, not independent geometry truth.
    Both positive depth and native projected distance are checked. No collar.
    """
    from scipy.spatial import cKDTree
    from reconstruction_dense_contract import project
    distance,ix=cKDTree(head).query(neck)
    a,z=project(neck,K,C);b,bz=project(head[ix],K,C)
    metric=z/K[0,0]
    good=(z>0)&(bz>0)&np.isfinite(metric)&(distance<=maximum_pixels*metric)&(np.linalg.norm(a-b,axis=1)<=maximum_pixels)
    return np.flatnonzero(good),ix[good],dict(count=int(good.sum()),
        nearestDistancePixels=np.quantile(distance/np.maximum(metric,1e-12),[.1,.5,.9]).tolist(),
        maximumPixels=maximum_pixels,measuredTruth=False,skinClothWeld=False)
