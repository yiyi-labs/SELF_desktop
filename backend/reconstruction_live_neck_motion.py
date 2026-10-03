"""Transport observed neck skin between the head and a quasistatic body.

No samples, colours or opacity are created. Cloth and every non-neck component
remain exactly unchanged. The body transform is explicitly identity: this is
a short-window quasistatic hypothesis, not measured general body motion.
The full spatial Jacobian transports covariance; SH follows its polar frame.
"""
import numpy as np
import torch
from reconstruction_portrait_model import (GaussianState, quaternion_matrix,
                                           scaled_head_transform)


class TransportedGaussianState(GaussianState):
    """Rendering uses exact covariance gradients; factors are export values.

    A caller combining components must concatenate their covariance() tensors,
    not refactor these tensors or discard them with a plain joined_state call.
    """
    def __init__(self,means,quats,scales,opacity,sh,parts,covariance):
        super().__init__(means,quats,scales,opacity,sh,parts)
        self.transported_covariance=covariance

    def covariance(self):
        return self.transported_covariance


def joined_covariant(*states):
    """Join standard export fields and retain every exact covariance graph."""
    if not states:raise ValueError('neck_empty_scene_join')
    fields={key:torch.cat([getattr(state,key) for state in states])
            for key in GaussianState.__dataclass_fields__}
    return TransportedGaussianState(**fields,
        covariance=torch.cat([state.covariance() for state in states]))


def _rigid(value, label):
    if value.shape != (4, 4) or not torch.isfinite(value).all():
        raise ValueError('neck_invalid_transform:'+label)
    eye=torch.eye(3,device=value.device,dtype=value.dtype)
    if not torch.allclose(value[3],value.new_tensor([0,0,0,1]),atol=1e-6,rtol=0) or \
       not torch.allclose(value[:3,:3].T@value[:3,:3],eye,atol=2e-5,rtol=0) or \
       not torch.allclose(torch.det(value[:3,:3]),value.new_tensor(1),atol=2e-5,rtol=0):
        raise ValueError('neck_nonrigid_transform:'+label)


def _matrix_quaternion(r):
    """Stable proper-basis conversion; no ambiguous eigenvector gradients."""
    a=torch.stack((1+r[:,0,0]+r[:,1,1]+r[:,2,2],
        1+r[:,0,0]-r[:,1,1]-r[:,2,2],1-r[:,0,0]+r[:,1,1]-r[:,2,2],
        1-r[:,0,0]-r[:,1,1]+r[:,2,2]),1).clamp_min(1e-12).sqrt()
    candidates=torch.stack((
        torch.stack((a[:,0]**2,r[:,2,1]-r[:,1,2],r[:,0,2]-r[:,2,0],r[:,1,0]-r[:,0,1]),1),
        torch.stack((r[:,2,1]-r[:,1,2],a[:,1]**2,r[:,0,1]+r[:,1,0],r[:,0,2]+r[:,2,0]),1),
        torch.stack((r[:,0,2]-r[:,2,0],r[:,0,1]+r[:,1,0],a[:,2]**2,r[:,1,2]+r[:,2,1]),1),
        torch.stack((r[:,1,0]-r[:,0,1],r[:,0,2]+r[:,2,0],r[:,1,2]+r[:,2,1],a[:,3]**2),1)),1)
    candidates=candidates/(2*a[:,:,None])
    q=candidates[torch.arange(len(r),device=r.device),a.argmax(1)]
    return torch.nn.functional.normalize(q,dim=-1)


class NeckBinding(torch.nn.Module):
    def __init__(self, means, neck, C, F, scene_scale):
        super().__init__()
        if means.ndim!=2 or means.shape[1]!=3 or not torch.isfinite(means).all():
            raise ValueError('neck_invalid_reference_points')
        if neck.shape!=(len(means),):raise ValueError('neck_layer_count')
        _rigid(C,'C');_rigid(F,'F')
        if not np.isfinite(scene_scale) or scene_scale<=0:raise ValueError('neck_scene_scale')
        self.register_buffer('reference_C',C.detach().clone())
        self.register_buffer('reference_F',F.detach().clone())
        self.register_buffer('scene_scale',means.new_tensor(scene_scale))
        self.register_buffer('inverse_head_reference',torch.linalg.inv(
            scaled_head_transform(C,F,float(scene_scale))).detach())
        self.register_buffer('neck',neck.detach().clone())
        weight=means.new_zeros(len(means));gradient=torch.zeros_like(means)
        camera=means@C[:3,:3].T+C[:3,3]
        if neck.any() and (camera[neck,2]<=0).any():
            raise ValueError('neck_reference_nonpositive_depth')
        # Intrinsic fy/cy cancel in this normalized interval. No image-space
        # content is invented, and the field is fixed to reference material.
        if int(neck.sum())>=2:
            y=camera[neck,1]/camera[neck,2]
            top,bottom=y.min(),y.max();span=bottom-top
            if float(span)>1e-8:
                u=((y-top)/span).clamp(0,1)
                weight[neck]=1-u*u*(3-2*u)
                dy=C[1,:3][None]/camera[neck,2,None]-\
                    camera[neck,1,None]*C[2,:3][None]/camera[neck,2,None].square()
                gradient[neck]=(-6*u+6*u.square())[:,None]*dy/span
        self.register_buffer('weight',weight.detach())
        self.register_buffer('gradient',gradient.detach())

    def relative_head(self,C,F):
        _rigid(C,'C');_rigid(F,'F')
        if torch.equal(C,self.reference_C) and torch.equal(F,self.reference_F):
            return torch.eye(4,device=C.device,dtype=C.dtype)
        return scaled_head_transform(C,F,float(self.scene_scale)) @ self.inverse_head_reference

    def transforms(self,state,C,F):
        """Centres and full deformation Jacobian, with no alpha/colour loss."""
        if len(state.means)!=len(self.weight):raise ValueError('neck_topology_changed')
        H=self.relative_head(C,F);R=H[:3,:3]
        eye=torch.eye(3,device=R.device,dtype=R.dtype)
        head=state.means@R.T+H[:3,3];delta=head-state.means
        moved=state.means+self.weight[:,None]*delta
        J=eye[None]+self.weight[:,None,None]*(R-eye)[None]+delta[:,:,None]*self.gradient[:,None,:]
        return moved,J

    def deform(self,state,C,F):
        if len(state.means)!=len(self.weight):raise ValueError('neck_topology_changed')
        # Exact reference identity includes quaternions/SH, not only centres.
        if torch.equal(C,self.reference_C) and torch.equal(F,self.reference_F):return state
        active=self.neck & (self.weight>0)
        if not active.any():return state
        moved,J=self.transforms(state,C,F);J=J[active]
        if not torch.isfinite(J).all() or torch.any(torch.linalg.det(J)<=0):
            raise ValueError('neck_transition_fold_requires_motion_evidence')
        source_covariance=state.covariance()
        sigma=J@source_covariance[active]@J.transpose(-1,-2)
        # Factors are a numeric PLY/export representation. Rendering receives
        # sigma itself below, so repeated eigenvalues never erase gradients or
        # introduce eigenvector-gradient instability during image training.
        eigenvalues,basis=torch.linalg.eigh(sigma.detach())
        if torch.any(eigenvalues<=0):raise ValueError('neck_nonpositive_covariance')
        basis=basis.detach().clone()
        basis[:,:,0]*=torch.where(torch.linalg.det(basis)<0,-1.,1.)[:,None]
        q=_matrix_quaternion(basis)
        # Polar rotation transports the one directional field. It is not an
        # average of differently rotated SH and is never a colour correction.
        U,_,Vh=torch.linalg.svd(J.detach());R=U@Vh
        sh=state.sh[active];vector=torch.stack((-sh[:,3],-sh[:,1],sh[:,2]),1)
        v=torch.einsum('nij,njc->nic',R,vector)
        transported=torch.stack((sh[:,0],-v[:,1],v[:,2],-v[:,0]),1)
        means=state.means.clone();means[active]=moved[active]
        scales=state.scales.clone();scales[active]=eigenvalues.sqrt()
        quats=state.quats.clone();quats[active]=q
        colour=state.sh.clone();colour[active]=transported
        covariance=source_covariance.clone();covariance[active]=sigma
        return TransportedGaussianState(means,quats,scales,state.opacity,colour,state.parts,covariance)

    def receipt(self):
        return {'neckPoints':int(self.neck.sum()),'activePoints':int((self.weight>0).sum()),
                'bodyMotion':'quasistatic_identity_short_window_not_measured',
                'geometryCreated':False,'clothFollowsHead':False,
                'referenceIdentity':True,'covariance':'full_J_Sigma_J_transpose',
                'weights':'fixed_reference_observed_neck_only'}


def build_neck_binding(means,layers,reference_C,reference_F,scene_scale):
    if not torch.is_tensor(means):means=torch.as_tensor(means,dtype=torch.float32)
    if not means.is_floating_point():raise ValueError('neck_float_points_required')
    labels=np.asarray(layers)
    if labels.shape!=(len(means),):raise ValueError('neck_layer_count')
    neck=torch.as_tensor(labels=='neck_skin',device=means.device)
    C=torch.as_tensor(reference_C,device=means.device,dtype=means.dtype)
    F=torch.as_tensor(reference_F,device=means.device,dtype=means.dtype)
    return NeckBinding(means,neck,C,F,scene_scale)
