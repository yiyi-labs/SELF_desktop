"""Recover the complete head/body/room state without a sparse reinitialization.

The formulas below consolidate the existing SharedSurfaceModel, ContinuityStage,
FreeComponent and bounded pose implementation. They do not change their motion,
SH, topology or renderer semantics. Recovery is not a quality approval.
"""
from pathlib import Path
import json
import math
import numpy as np
import cv2
import torch
import torch.nn.functional as F
from flame_open_model import FlameOpen, axis_angle_matrix
from reconstruction_checkpoint import load_checkpoint, file_sha256, restore_tensors
from reconstruction_portrait_model import (LocalPortraitModel, GaussianState,
    joined_state, scaled_head_transform, quaternion_matrix, quat_product,
    rotate_sh1, rotation_quaternion)
from reconstruction_render_contract import make_frame, full_frame_draw, draw


def pick(state, index):
    return GaussianState(**{k:getattr(state,k)[index] for k in GaussianState.__dataclass_fields__})


def triangle_frames(tri):
    x=F.normalize(tri[:,1]-tri[:,0],dim=-1)
    z=F.normalize(torch.linalg.cross(x,tri[:,2]-tri[:,0]),dim=-1)
    y=torch.linalg.cross(z,x)
    return torch.stack((x,y,z),-1)


def small_rotation_quaternion(R):
    w=torch.sqrt((1+R.diagonal(dim1=-2,dim2=-1).sum(-1)).clamp_min(1e-8))*.5
    return F.normalize(torch.stack((w,(R[:,2,1]-R[:,1,2])/(4*w),
        (R[:,0,2]-R[:,2,0])/(4*w),(R[:,1,0]-R[:,0,1])/(4*w)),-1),dim=-1)


class BoundedPose(torch.nn.Module):
    def __init__(self,names,reference,device,degrees=1.,translation=.0015):
        super().__init__();self.names=list(names);self.reference=reference
        self.index={n:i for i,n in enumerate(names)}
        self.degrees=degrees;self.translation=translation
        self.delta=torch.nn.Parameter(torch.zeros((len(names),6),device=device))
    def forward(self,name,transform):
        if name not in self.index or name==self.reference:return transform
        value=self.delta[self.index[name]].tanh()
        R=axis_angle_matrix(value[:3]*(self.degrees*np.pi/180/np.sqrt(3)))
        result=transform.clone();result[:3,:3]=R@transform[:3,:3]
        result[:3,3]=transform[:3,3]+value[3:]*(self.translation/np.sqrt(3))
        return result


class FreeComponent(torch.nn.Module):
    def __init__(self,state,source_ids,support,coordinate_frame,max_offset):
        super().__init__();self.coordinate_frame=coordinate_frame
        for name,value in dict(base=state.means,parts=state.parts,source_ids=source_ids,
                support=support,initial_scales=state.scales).items():
            self.register_buffer(name,torch.as_tensor(value,device=state.means.device).detach().clone())
        self.register_buffer('max_offset',torch.as_tensor(max_offset,device=state.means.device,dtype=state.means.dtype))
        self.offset=torch.nn.Parameter(torch.zeros_like(state.means))
        self.log_scales=torch.nn.Parameter(state.scales.log().detach().clone())
        self.quats=torch.nn.Parameter(state.quats.detach().clone())
        self.opacity=torch.nn.Parameter(torch.logit(state.opacity.detach().clamp(.001,.999)))
        self.sh=torch.nn.Parameter(state.sh.detach().clone())
    def state(self):
        return GaussianState(self.base+self.offset.tanh()*self.max_offset,
            F.normalize(self.quats,dim=-1),self.log_scales.exp(),self.opacity.sigmoid(),self.sh,self.parts)


class StaticRoom(torch.nn.Module):
    def __init__(self,values,metadata):
        super().__init__();self.params=torch.nn.ParameterDict({
            k:torch.nn.Parameter(values[k].detach().clone()) for k in ('means','scales','quats','opacities','sh')})
        self.metadata=metadata
    def state(self):
        p=self.params
        return GaussianState(p['means'],F.normalize(p['quats'],dim=-1),p['scales'].exp(),
            p['opacities'].sigmoid(),p['sh'],torch.zeros(len(p['means']),device=p['means'].device,dtype=torch.long))


def rigid_state(state,angles,translation,pivot):
    R=axis_angle_matrix(angles);theta=torch.linalg.vector_norm(angles)
    q=torch.cat((torch.cos(theta/2).reshape(1),.5*torch.sinc(theta/(2*torch.pi))*angles))
    return GaussianState((state.means-pivot)@R.T+pivot+translation,quat_product(q,state.quats),
        state.scales,state.opacity,rotate_sh1(state.sh,R),state.parts)


class CompletePortraitBase(torch.nn.Module):
    def __init__(self,data,plan,saved,extra,device):
        super().__init__();self.scale=data['scale'];self.reference=data['reference']
        prior=data['prior'];faces=data['geometry'].faces.numpy();z=[]
        for name,row in data['local'].items():
            if row['role']!='train':continue
            tri=row['mesh'][faces[prior['surface_ids']]]
            xyz=np.concatenate(((tri*prior['surface_bary'][:,:,None]).sum(1),prior['hair_local_points']))
            cam=xyz@row['F'][:3,:3].T+row['F'][:3,3]
            z.append(np.where(cam[:,2]>.05,cam[:,2]/data['K'][0,0],np.nan))
        self.portrait=LocalPortraitModel(prior,faces,data['local'][self.reference]['mesh'],
            native_metric_per_pixel=np.nanmedian(np.stack(z),axis=0),device=device)
        n=len(self.portrait.role)
        self.portrait.register_buffer('stable_uid',torch.arange(n,device=device))
        self.portrait.register_buffer('parent_uid',torch.full((n,),-1,device=device,dtype=torch.long))
        self.portrait.register_buffer('next_uid',torch.tensor(n,device=device))
        self.pose=BoundedPose(plan['train'],self.reference,device)
        self.body_pose=BoundedPose(data['train'],self.reference,device,2.,.01*self.scale)
        self.room=StaticRoom({k:saved['room.params.'+k] for k in ('means','scales','quats','opacities','sh')},extra['roomMetadata'])
        self.body=torch.nn.ParameterDict({k:torch.nn.Parameter(saved['body.'+k].clone())
            for k in ('means','scales','quats','opacities','sh')})
        self.body_sources=extra['bodySources']
        for key in ('body_initial_means','body_initial_scales','component_origin',
                    'component_votes_initial','glass_metric_origin','surface_base','measured_surface_field'):
            self.register_buffer(key,saved[key].clone())
        self.glasses_local=torch.nn.Parameter(saved['glasses_local'].clone())
    def adjusted_frame(self,frame):return {**frame,'F':self.pose(frame['name'],frame['F'])}
    def head_state(self,frame):
        p=self.portrait;mesh=frame['mesh'];delta=self.measured_surface_field
        state=p.local_state(mesh+delta);fine=self.component_origin[p.origin_index];glass=fine==2
        offset=self.glasses_local[p.origin_index].tanh()*self.glass_metric_origin[p.origin_index,None]*3/math.sqrt(3)
        parts=torch.ones_like(fine);parts[fine==1]=2;parts[glass]=3;parts[fine==3]=4
        ids=p.faces[p.triangle_ids]
        before=triangle_frames((mesh+self.surface_base)[ids])
        after=triangle_frames((mesh+self.surface_base+delta)[ids])
        q=quat_product(small_rotation_quaternion(after@before.transpose(-1,-2)),state.quats[:p.surface_count])
        return GaussianState(state.means+offset*glass[:,None],
            torch.cat((q,state.quats[p.surface_count:])),state.scales,state.opacity,state.sh,parts)
    def body_state(self,name):
        p=self.body
        state=GaussianState(p['means'],F.normalize(p['quats'],dim=-1),p['scales'].exp(),
            p['opacities'].sigmoid(),p['sh'],torch.full((len(p['means']),),4,device=p['means'].device,dtype=torch.long))
        if not len(p['means']):return state
        raw=self.body_pose.delta[self.body_pose.index[name]].tanh() if name in self.body_pose.index and name!=self.reference else torch.zeros(6,device=p['means'].device)
        return rigid_state(state,raw[:3]*(2*np.pi/180/np.sqrt(3)),
            raw[3:]*(.01*self.scale/np.sqrt(3)),self.body_initial_means.median(0).values)


def smooth_transition(coordinate,top,bottom):
    if not np.isfinite([top,bottom]).all() or bottom<=top:raise ValueError('transition_domain')
    u=((coordinate-top)/(bottom-top)).clamp(0,1)
    return 1-u*u*(3-2*u)


def blend_rigid_state(state,H,B,weight):
    xh=state.means@H[:3,:3].T+H[:3,3];xb=state.means@B[:3,:3].T+B[:3,3]
    qh=small_rotation_quaternion(H[:3,:3][None])[0] if H.requires_grad else rotation_quaternion(H[:3,:3])
    qb=small_rotation_quaternion(B[:3,:3][None])[0] if B.requires_grad else rotation_quaternion(B[:3,:3])
    qb=qb*torch.where((qh*qb).sum()<0,-1.,1.)
    q=F.normalize(weight[:,None]*qh+(1-weight[:,None])*qb,dim=-1)
    R=quaternion_matrix(q);v=torch.stack((-state.sh[:,3],-state.sh[:,1],state.sh[:,2]),1)
    moved=torch.einsum('nij,njc->nic',R,v)
    colour=torch.stack((state.sh[:,0],-moved[:,1],moved[:,2],-moved[:,0]),1)
    return GaussianState(weight[:,None]*xh+(1-weight[:,None])*xb,
        quat_product(q,state.quats),state.scales,state.opacity,colour,state.parts)


class ShortWindowBodyMotion(torch.nn.Module):
    def __init__(self,timestamps,reference,pivot,scale):
        super().__init__();self.timestamps=dict(timestamps);self.reference=reference;self.scale=float(scale)
        self.duration=max(timestamps.values())-min(timestamps.values())
        if reference not in timestamps or self.duration<=0:raise ValueError('motion_contract')
        self.register_buffer('pivot',pivot.detach().clone())
        self.velocity=torch.nn.Parameter(torch.zeros(6,device=pivot.device))
    def matrix(self,name):
        if name not in self.timestamps:raise ValueError('motion_outside_observed_window')
        tau=(self.timestamps[name]-self.timestamps[self.reference])/self.duration;v=self.velocity.tanh()*tau
        R=axis_angle_matrix(v[:3]*(np.pi/180/np.sqrt(3)))
        T=torch.eye(4,device=R.device,dtype=R.dtype);T[:3,:3]=R
        T[:3,3]=self.pivot-R@self.pivot+v[3:]*(.005*self.scale/np.sqrt(3))
        return T


class CompleteSceneModel(torch.nn.Module):
    def __init__(self,data,plan,checkpoint,device='cuda'):
        super().__init__();extra=checkpoint['extra'];saved=checkpoint['model']
        root='baseline.';base_saved={k[len(root):]:v for k,v in saved.items() if k.startswith(root)}
        self.baseline=CompletePortraitBase(data,plan,base_saved,extra,device);self.scale=self.baseline.scale
        meta=extra['meta'];a=extra['arrays'];self.component=meta['component'];self.motion_mode=extra['config']['motionMode']
        tensor=lambda value,dtype=torch.float32:torch.as_tensor(value,device=device,dtype=dtype)
        state=GaussianState(*(tensor(a[k],torch.long if k=='parts' else torch.float32) for k in GaussianState.__dataclass_fields__))
        self.patch=FreeComponent(state,tensor(a['uid'],torch.long),tensor(a['support']),meta['coordinateGroup'],torch.median(state.scales[:,:2])*1.5)
        for key in ('edges','is_neck','keep_head','keep_room','keep_body'):
            self.register_buffer(key,saved[key].clone())
        self.body_motion=None
        if self.component=='body':
            names=meta['names'];ref=names[len(names)//2]
            self.body_motion=ShortWindowBodyMotion(meta['timestamps'],ref,saved['body_motion.pivot'],self.scale)
            for key in ('inverse_head_reference','neck_weight'):self.register_buffer(key,saved[key].clone())
        restore_tensors(self,saved)
        for value in self.parameters():value.requires_grad_(False)
    def patch_state(self,frame):
        s=self.patch.state()
        if self.component!='body' or self.motion_mode=='static':return s
        H=scaled_head_transform(frame['C'],frame['F'],self.scale)@self.inverse_head_reference
        # Preserve the original UNKNOWN out-of-window diagnostic, not a solved motion.
        B=self.body_motion.matrix(frame['name']) if frame['name'] in self.body_motion.timestamps else torch.eye(4,device=s.means.device)
        return blend_rigid_state(s,H,B,self.neck_weight)
    def state(self,frame,local=False):
        head=pick(self.baseline.head_state(frame),self.keep_head)
        if self.component=='hair':head=joined_state(head,self.patch.state())
        if local:return head
        if frame['C'] is None:raise ValueError('no_world_observation')
        states=[head.to_world(frame['C'],frame['F'],self.scale),pick(self.baseline.room.state(),self.keep_room),
                pick(self.baseline.body_state(frame['name']),self.keep_body)]
        if self.component!='hair':states.append(self.patch_state(frame))
        return joined_state(*states)
    def render(self,frame,stage='T2',*,explicit_covariance=False):
        frame=self.baseline.adjusted_frame(frame);local=stage=='T0'
        state=self.state(frame,local);C=frame['F'] if local else frame['C'];scale=1. if local else self.scale
        if explicit_covariance:return full_frame_draw(state,C,frame,unit_scale=scale)
        # Preserve the recorded complete asset's quaternion/scale projection.
        # It also projects/sorts/composites the FULL native canvas before ROI.
        w,h=frame['fullSize'];x0,y0,x1,y1=frame['rectangle']
        crop_k=frame['fullK'].clone();crop_k[0,2]-=x0;crop_k[1,2]-=y0
        if frame['nativeScale']!=1 or frame['rgb'].shape[:2]!=(y1-y0,x1-x0):raise ValueError('native_canvas_contract')
        if not torch.allclose(crop_k,frame['K'],atol=1e-5,rtol=0):raise ValueError('native_crop_intrinsics_changed')
        result=draw(state,C,frame['fullK'],w,h,unit_scale=scale)
        result['info']['width']=w;result['info']['height']=h
        if result['info']['means2d'].requires_grad:result['info']['means2d'].retain_grad()
        return {k:(v[y0:y1,x0:x1] if k!='info' else v) for k,v in result.items()}


def load_complete_data(prepared):
    """Consume the recorded original images/F/C/K, without rerunning preparation."""
    prepared=Path(prepared).resolve();metadata=json.loads((prepared/'preparation.json').read_text())
    root=prepared.parent.parent
    resolve=lambda value:Path(value) if Path(value).is_absolute() else (root/value).resolve()
    source=resolve(metadata['source']);appearance=resolve(metadata['appearance'])
    if file_sha256(source/'capture.mp4')!=metadata['sourceHash'] or file_sha256(appearance)!=metadata['appearanceHash']:
        raise ValueError('complete_input_hash_changed')
    raw=dict(np.load(prepared/'local_geometry.npz'));names=[str(n) for n in raw['names']]
    if len(names)!=len(set(names)):raise ValueError('duplicate_observation_names')
    local={n:dict(mesh=raw['meshes'][i],F=raw['F'][i],role=str(raw['roles'][i]),marks=raw['marks'][i]) for i,n in enumerate(names)}
    rgb={}
    for name in names:
        image=cv2.imread(str(prepared/'rectified_observations'/name))
        if image is None:raise ValueError('missing_original_rectified_image:'+name)
        rgb[name]=cv2.cvtColor(image,cv2.COLOR_BGR2RGB).astype(np.float32)/255
    reference=max(metadata['train'],key=lambda n:np.linalg.norm(local[n]['marks'][234]-local[n]['marks'][454])/
                  max(np.linalg.norm(local[n]['marks'][10]-local[n]['marks'][152]),1))
    return {**metadata,'source':source,'appearance':str(appearance),'staticMap':str(resolve(metadata['staticMap'])),
        'reference':reference,'geometry':FlameOpen(24,12),'prior':dict(np.load(appearance)),
        'local':local,'worlds':{str(n):raw['C'][i] for i,n in enumerate(raw['world_names'])},'rgb':rgb,
        'labels':{n:dict(np.load(prepared/'rectified_observations'/(n+'.npz'))) for n in names},
        'K':raw['K'],'scale':float(raw['scale']),'room':dict(np.load(prepared/'static_surface_seeds.npz'))}


def load_complete(manifest=None,device='cuda'):
    manifest=Path(manifest or Path(__file__).with_name('reconstruction_baseline.json'))
    lock=json.loads(manifest.read_text());root=manifest.parent
    resolve=lambda value:Path(value) if Path(value).is_absolute() else (root/value).resolve()
    for name,row in lock['files'].items():
        if file_sha256(resolve(row['path']))!=row['sha256']:raise ValueError('baseline_file_changed:'+name)
    prepared=resolve(lock['prepared']);data=load_complete_data(prepared)
    ck=load_checkpoint(resolve(lock['files']['checkpoint']['path']),expected_hash=lock['files']['checkpoint']['sha256'],device=device)
    if data['sourceHash']!=lock['sourceHash'] or ck['contract']['sourceHash']!=lock['sourceHash']:
        raise ValueError('complete_source_changed')
    if str(ck['extra']['arrays']['source_hash'])!=data['sourceHash']:raise ValueError('component_source_changed')
    plan=json.loads(resolve(lock['files']['observations']['path']).read_text())
    model=CompleteSceneModel(data,plan,ck,device)
    if model.baseline.pose.delta.shape!=(len(plan['train']),6) or model.baseline.body_pose.delta.shape!=(len(data['train']),6):
        raise ValueError('pose_index_contract_changed')
    reference=lock['reference'];frame=model.baseline.adjusted_frame(make_frame(data,reference,crop=False,device=device))
    state=model.state(frame)
    if len(state.means)!=lock['pointCount']:raise ValueError('complete_point_count_changed')
    for value in state.__dict__.values():
        if not torch.isfinite(value).all():raise ValueError('complete_state_nonfinite')
    return data,plan,model,lock,ck
