"""Bounded shared normal surface using the unchanged standard GS draw path.
FLAME is a low-frequency prior. One field is shared across real training
images. Non-skin means/scales/rotation remain exact. No covariance renderer
switch, no eigenvector/SVD gradients, no independent per-frame identity.
"""
import torch
from reconstruction_canonical_surface import CanonicalSurfaceModel,transport_field
from reconstruction_shared_surface import triangle_frames,small_rotation_quaternion
from reconstruction_detail_controlled import DetailModel
from reconstruction_portrait_model import GaussianState,joined_state,quat_product
from reconstruction_fullframe import draw_frame


def relative_surface_rotation(before,after):
    a=triangle_frames(before);b=triangle_frames(after)
    # Exactly identity at unchanged geometry, with nonzero derivatives there.
    # This transports orientation. It does NOT claim full affine shear strain.
    return torch.eye(3,device=a.device,dtype=a.dtype)[None]+(b-a)@a.transpose(-1,-2)


class PhotometricSurfaceModel(CanonicalSurfaceModel):
    def attach_canonical_field(self):
        super().attach_canonical_field();p=self.portrait;tri=self.canonical_reference[p.faces]
        normal=torch.nn.functional.normalize(torch.linalg.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),dim=-1)
        total=torch.zeros_like(self.canonical_reference)
        for k in range(3):total.index_add_(0,p.faces[:,k],normal)
        self.register_buffer('canonical_normals',torch.nn.functional.normalize(total,dim=-1))
        self.register_buffer('active_vertices',torch.zeros(len(total),device=total.device,dtype=torch.bool))
        self.register_buffer('surface_bound',p.metric_per_pixel.median()*3)
        self.surface_control=torch.nn.Parameter(torch.zeros(len(total),device=total.device))
    def field(self):
        return self.canonical_normals*(self.surface_control.tanh()*self.surface_bound*self.active_vertices)[:,None]
    def posed_delta(self,f):
        return transport_field(self.field(),self.rotations(f['mesh'],f['name']))
    def head_state(self,f):
        p=self.portrait;delta=self.posed_delta(f);original=DetailModel.head_state(self,f)
        moved=DetailModel.head_state(self,{**f,'mesh':f['mesh']+delta});ids=p.faces[p.triangle_ids]
        R=relative_surface_rotation((f['mesh']+self.surface_base)[ids],(f['mesh']+self.surface_base+delta)[ids])
        rq=small_rotation_quaternion(R);q=quat_product(rq,original.quats[:p.surface_count])
        skin=self.component_origin[p.origin_index[:p.surface_count]]==0
        means=torch.cat((torch.where(skin[:,None],moved.means[:p.surface_count],original.means[:p.surface_count]),original.means[p.surface_count:]))
        quats=torch.cat((torch.where(skin[:,None],q,original.quats[:p.surface_count]),original.quats[p.surface_count:]))
        # Local Gaussian extents stay in the existing trainable standard scales.
        # Surface geometry transports orientation only; no hidden second stretch.
        return GaussianState(means,quats,original.scales,original.opacity,original.sh,original.parts)
    def render(self,frame,stage):
        f=self.adjusted_frame(frame);s=self.head_state(f);C=f['F'];unit=1.
        if stage!='T0':
            if f['C'] is None:raise ValueError('no_measured_world_C')
            s=s.to_world(f['C'],f['F'],self.scale);C=f['C'];unit=self.scale
            if stage!='T1':s=joined_state(s,self.room.state(),self.body_state(f['name']))
        return draw_frame(s,C,f,unit_scale=unit)
