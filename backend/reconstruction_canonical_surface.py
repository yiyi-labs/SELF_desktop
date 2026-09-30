"""Canonical surface transport shared by measurement and actual rendering.
Research adapter only; preserves the complete zero-field baseline and topology.
"""
import torch
from reconstruction_shared_surface import SharedSurfaceModel, triangle_frames
from reconstruction_detail_controlled import DetailModel
from reconstruction_portrait_model import GaussianState, quaternion_matrix


def vertex_rotations(reference, observed, faces):
    """Area-weighted local charts, orthogonalized per vertex; no global pose twice."""
    a=reference[faces]; b=observed[faces]
    cross=torch.linalg.cross(a[:,1]-a[:,0],a[:,2]-a[:,0])
    weight=torch.linalg.vector_norm(cross,dim=-1)
    if bool((weight<=1e-12).any()):
        raise ValueError("degenerate_reference_triangle")
    r=triangle_frames(b)@triangle_frames(a).transpose(-1,-2)
    total=torch.zeros((len(reference),3,3),device=a.device,dtype=a.dtype)
    mass=torch.zeros(len(reference),device=a.device,dtype=a.dtype)
    for k in range(3):
        total.index_add_(0,faces[:,k],r*weight[:,None,None])
        mass.index_add_(0,faces[:,k],weight)
    if bool((mass<=0).any()):
        raise ValueError("unbound_reference_vertex")
    u,_,vh=torch.linalg.svd(total/mass[:,None,None])
    sign=torch.ones((len(reference),3),device=a.device,dtype=a.dtype)
    sign[:,-1]=torch.linalg.det(u@vh).sign()
    return (u*sign[:,None,:])@vh


def transport_field(field, rotations):
    return torch.einsum("vij,vj->vi",rotations,field)


def triangle_jacobians(before, after):
    """Tangential strain plus unit-normal transport; preserves normal thickness."""
    def chart(t):
        x=t[:,1]-t[:,0]; y=t[:,2]-t[:,0]
        n=torch.nn.functional.normalize(torch.linalg.cross(x,y),dim=-1)
        return torch.stack((x,y,n),-1)
    a=chart(before); b=chart(after)
    if bool((torch.linalg.det(a).abs()<1e-12).any()):
        raise ValueError("degenerate_surface_jacobian")
    return b@torch.linalg.inv(a)


def matrix_quaternion(matrix):
    """General proper rotation -> wxyz; sign-invariant covariance contract."""
    m=matrix; diag=m.diagonal(dim1=-2,dim2=-1)
    vals=torch.stack((1+diag.sum(-1),1+diag[:,0]-diag[:,1]-diag[:,2],
                     1-diag[:,0]+diag[:,1]-diag[:,2],
                     1-diag[:,0]-diag[:,1]+diag[:,2]),-1).clamp_min(0).sqrt()
    candidates=torch.stack((
        torch.stack((vals[:,0].square(),m[:,2,1]-m[:,1,2],m[:,0,2]-m[:,2,0],m[:,1,0]-m[:,0,1]),-1),
        torch.stack((m[:,2,1]-m[:,1,2],vals[:,1].square(),m[:,1,0]+m[:,0,1],m[:,0,2]+m[:,2,0]),-1),
        torch.stack((m[:,0,2]-m[:,2,0],m[:,1,0]+m[:,0,1],vals[:,2].square(),m[:,2,1]+m[:,1,2]),-1),
        torch.stack((m[:,1,0]-m[:,0,1],m[:,2,0]+m[:,0,2],m[:,2,1]+m[:,1,2],vals[:,3].square()),-1)),1)
    candidates=candidates/(2*vals.clamp_min(.1)[...,None])
    q=candidates[torch.arange(len(m),device=m.device),vals.argmax(-1)]
    return torch.nn.functional.normalize(q,dim=-1)


@torch.no_grad()
def transport_covariance(quats, scales, jacobian):
    # Factor A A^T without treating a changed tangent basis as pure rotation.
    factor=jacobian@quaternion_matrix(quats)@torch.diag_embed(scales)
    u,s,_=torch.linalg.svd(factor)
    sign=torch.ones_like(s);sign[:,-1]=torch.linalg.det(u).sign()
    u=u*sign[:,None,:]
    return matrix_quaternion(u),s


class CanonicalSurfaceModel(SharedSurfaceModel):
    def attach_canonical_field(self):
        self.register_buffer("surface_base",self.portrait.surface_residual.detach().clone())
        self.register_buffer("canonical_reference",self.portrait.reference_mesh.detach().clone()+self.surface_base)
        self.register_buffer("canonical_field",torch.zeros_like(self.surface_base))
        self._transport_cache={}

    def displacement(self):
        return self.canonical_field

    def rotations(self, mesh, name=None):
        # Cache only fixed observation meshes. Geometry is the separately stored field.
        key=name
        if key is None:
            return vertex_rotations(self.canonical_reference,mesh+self.surface_base,self.portrait.faces).detach()
        if key not in self._transport_cache:
            self._transport_cache[key]=vertex_rotations(self.canonical_reference,
                mesh+self.surface_base,self.portrait.faces).detach()
        return self._transport_cache[key]

    def posed_displacement(self, mesh):
        return transport_field(self.canonical_field,self.rotations(mesh))

    def current_mesh(self,mesh):
        return mesh+self.surface_base+self.posed_displacement(mesh)

    def head_state(self,frame):
        mesh=frame["mesh"];p=self.portrait
        if not bool(self.canonical_field.count_nonzero()):return DetailModel.head_state(self,frame)
        delta=transport_field(self.canonical_field,self.rotations(mesh,frame["name"]))
        s=DetailModel.head_state(self,{**frame,"mesh":mesh+delta})
        if not bool(self.canonical_field.count_nonzero()):
            return s
        ids=p.faces[p.triangle_ids]
        J=triangle_jacobians((mesh+self.surface_base)[ids],
                            (mesh+self.surface_base+delta)[ids])
        # Independently represented glasses are not stretched into the skin.
        label=self.component_origin[p.origin_index[:p.surface_count]]
        J=torch.where((label==2)[:,None,None],torch.eye(3,device=J.device,dtype=J.dtype),J)
        q,sc=transport_covariance(s.quats[:p.surface_count],s.scales[:p.surface_count],J)
        return GaussianState(s.means,torch.cat((q,s.quats[p.surface_count:])),
            torch.cat((sc,s.scales[p.surface_count:])),s.opacity,s.sh,s.parts)

    def render(self,frame,stage):
        if not bool(self.canonical_field.count_nonzero()):
            return DetailModel.render(self,frame,stage)
        from reconstruction_fullframe import canvas,slice_render
        from reconstruction_portrait_model import joined_state,scaled_head_transform
        f=self.adjusted_frame(frame);p=self.portrait;mesh=f["mesh"]
        delta=transport_field(self.canonical_field,self.rotations(mesh,f["name"]))
        s=DetailModel.head_state(self,{**f,"mesh":mesh+delta})
        cov=s.covariance();ids=p.faces[p.triangle_ids]
        J=triangle_jacobians((mesh+self.surface_base)[ids],(mesh+self.surface_base+delta)[ids])
        fine=self.component_origin[p.origin_index[:p.surface_count]]
        J=torch.where((fine==2)[:,None,None],torch.eye(3,device=J.device,dtype=J.dtype),J)
        cov=torch.cat((J@cov[:p.surface_count]@J.transpose(-1,-2),cov[p.surface_count:]))
        C=f["F"];scale=1.
        if stage!="T0":
            if f["C"] is None:raise ValueError("missing_measured_world_camera")
            H=scaled_head_transform(f["C"],f["F"],self.scale)
            R=H[:3,:3];cov=R[None]@cov@R.T[None]*self.scale**2
            s=s.to_world(f["C"],f["F"],self.scale);C=f["C"];scale=self.scale
            if stage!="T1":
                room=self.room.state();body=self.body_state(f["name"])
                s=joined_state(s,room,body);cov=torch.cat((cov,room.covariance(),body.covariance()))
        width,height,rect,K=canvas(f)
        return slice_render(draw_covariance(s,cov,C,K,width,height,unit_scale=scale),rect)


def draw_covariance(state,covars,C,K,width,height,*,unit_scale=1.,antialiased=False):
    """Same locked renderer/color contract; native covariance autograd, no SVD."""
    from gsplat.rendering import rasterization
    from reconstruction_portrait_model import evaluate_sh1
    center=torch.linalg.inv(C)[:3,3]
    rgb=evaluate_sh1(state.sh,state.means-center)
    groups=torch.nn.functional.one_hot(state.parts.long(),5).to(rgb.dtype)
    depth=(state.means@C[:3,:3].T+C[:3,3])[:,2]
    features=torch.cat((rgb,groups,groups*depth[:,None]),1)
    image,alpha,info=rasterization(state.means,None,None,state.opacity,features,C[None],K[None],
        width,height,covars=covars,packed=True,sh_degree=None,render_mode="RGB+D",
        rasterize_mode="antialiased" if antialiased else "classic",
        near_plane=.01*unit_scale,far_plane=1e10*unit_scale)
    info["width"]=width;info["height"]=height
    return dict(rgb=image[0,:,:,:3],alpha=alpha[0,:,:,0],q=image[0,:,:,3:8],
        q_depth=image[0,:,:,8:13]/unit_scale,depth=image[0,:,:,-1]/unit_scale,info=info)
