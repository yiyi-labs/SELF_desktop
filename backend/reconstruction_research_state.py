"""Recoverable state and bounded motion for isolated portrait research.

No publisher imports. Old appearance NPZs are explicit warm starts; only this
complete schema can restore optimizer, topology, sampling and random state.
"""
from __future__ import annotations
import copy
import hashlib
import random
from pathlib import Path
import numpy as np
import torch
from flame_open_model import axis_angle_matrix

SCHEMA = 'self-portrait-training-state-1'

class FrameSampler:
    def __init__(self, names, seed):
        if not names or len(set(names)) != len(names):
            raise ValueError('nonempty_unique_observation_names_required')
        self.names = list(names); self.rng = random.Random(seed)
        self.order = []; self.cursor = 0
    def next(self):
        if self.cursor == len(self.order):
            self.order = list(self.names); self.rng.shuffle(self.order); self.cursor = 0
        name = self.order[self.cursor]; self.cursor += 1
        return name
    def state_dict(self):
        return dict(names=self.names, order=self.order, cursor=self.cursor, rng=self.rng.getstate())
    def load_state_dict(self, state):
        if self.names != state['names']: raise ValueError('sampler_observations_changed')
        self.order = list(state['order']); self.cursor = state['cursor']; self.rng.setstate(state['rng'])

class BoundedHeadPose(torch.nn.Module):
    """Local F only. Fixed K/world C/scale; dev and audit never get variables."""
    def __init__(self, names, reference, device='cpu', degrees=1., translation=.0015):
        super().__init__(); self.names = list(names); self.reference = reference
        self.index = {n:i for i,n in enumerate(names)}
        self.degrees = degrees; self.translation = translation
        self.delta = torch.nn.Parameter(torch.zeros((len(names), 6), device=device))
    def forward(self, name, F):
        if name not in self.index or name == self.reference: return F
        value = torch.tanh(self.delta[self.index[name]])
        rotation = axis_angle_matrix(value[:3]*(self.degrees*np.pi/180/np.sqrt(3)))
        result = F.clone()
        result[:3,:3] = rotation@F[:3,:3]
        result[:3,3] = F[:3,3]+value[3:]*(self.translation/np.sqrt(3))
        return result
    def regularizer(self):
        return self.delta.tanh().square().mean()


def rng_state():
    n = np.random.get_state()
    return {'python':random.getstate(), 'numpy':(n[0],torch.from_numpy(n[1].astype(np.int64)),*n[2:]),
            'torch':torch.get_rng_state(), 'cuda':torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []}

def restore_rng(state):
    random.setstate(state['python']); n=state['numpy']
    np.random.set_state((n[0],n[1].cpu().numpy().astype(np.uint32),*n[2:]))
    torch.set_rng_state(state['torch'].cpu())
    if state['cuda']:
        if not torch.cuda.is_available(): raise ValueError('CUDA_RNG_requires_CUDA_resume')
        torch.cuda.set_rng_state_all([x.cpu() for x in state['cuda']])


def optimizer_bindings(module, optimizers):
    inverse={id(p):n for n,p in module.named_parameters()}
    result={}
    for key,optim in optimizers.items():
        result[key]=[[inverse[id(p)] for p in g['params']] for g in optim.param_groups]
    return result


def save_checkpoint(path, module, optimizers, samplers, *, stage, step, contract,
                    strategy=None, scheduler=None, extra=None):
    path=Path(path)
    if path.exists(): raise FileExistsError('checkpoint_must_not_overwrite')
    payload=dict(schema=SCHEMA, stage=stage, step=step, contract=contract,
        model=module.state_dict(), trainable={n:p.requires_grad for n,p in module.named_parameters()}, optimizers={k:v.state_dict() for k,v in optimizers.items()},
        bindings=optimizer_bindings(module,optimizers), samplers={k:v.state_dict() for k,v in samplers.items()},
        rng=rng_state(), strategy=strategy, scheduler=scheduler, extra=extra or {})
    torch.save(payload,path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restore_checkpoint(path, module, optimizers, samplers, *, contract, device='cpu'):
    payload=torch.load(path,map_location=device,weights_only=False) # trusted, own local checkpoint only
    if payload['schema']!=SCHEMA or payload['contract']!=contract:
        raise ValueError('checkpoint_contract_mismatch')
    current=module.state_dict()
    if current.keys()!=payload['model'].keys(): raise ValueError('checkpoint_fields_missing_or_extra')
    # Resize only declared tensors. Missing fields are NEVER initialized silently.
    params=dict(module.named_parameters()); buffers=dict(module.named_buffers())
    for name,value in payload['model'].items():
        if current[name].dtype!=value.dtype: raise ValueError('checkpoint_dtype_mismatch:'+name)
        if current[name].shape!=value.shape:
            parent_name,_,leaf=name.rpartition('.')
            parent=module.get_submodule(parent_name) if parent_name else module
            if name in params:
                setattr(parent,leaf,torch.nn.Parameter(torch.empty_like(value),requires_grad=params[name].requires_grad))
            elif name in buffers: setattr(parent,leaf,torch.empty_like(value))
            else: raise ValueError('undeclared_checkpoint_tensor:'+name)
    module.load_state_dict(payload['model'],strict=True)
    for n,p in module.named_parameters():p.requires_grad_(payload['trainable'][n])
    named=dict(module.named_parameters())
    if set(optimizers)!=set(payload['optimizers']) or set(samplers)!=set(payload['samplers']):
        raise ValueError('optimizer_or_sampler_set_mismatch')
    for key,optim in optimizers.items():
        groups=payload['bindings'][key]
        if len(groups)!=len(optim.param_groups): raise ValueError('optimizer_group_mismatch')
        for group,names in zip(optim.param_groups,groups): group['params']=[named[n] for n in names]
        optim.load_state_dict(payload['optimizers'][key])
    for key,sampler in samplers.items(): sampler.load_state_dict(payload['samplers'][key])
    restore_rng(payload['rng'])
    return payload


def validate_research_manifest(data, reference, names):
    """Input/numeric contract, explicitly NOT an E1--E5 quality approval."""
    if not names or reference not in data['worlds']: raise ValueError('missing_world_reference')
    s=float(data['scale'])
    if not np.isfinite(s) or s<=0: raise ValueError('invalid_shared_scale')
    K=np.asarray(data['K'])
    if K.shape!=(3,3) or not np.isfinite(K).all() or min(K[0,0],K[1,1])<=0:
        raise ValueError('invalid_intrinsics')
    maximum=0.
    for name in names:
        if name not in data['worlds'] or name not in data['local']: raise ValueError('world_observation_missing:'+name)
        C=np.asarray(data['worlds'][name]); F=np.asarray(data['local'][name]['F']).copy()
        for matrix in (C,F):
            if matrix.shape!=(4,4) or not np.isfinite(matrix).all(): raise ValueError('invalid_transform')
            if not np.allclose(matrix[3],[0,0,0,1],atol=1e-6): raise ValueError('invalid_homogeneous_row')
            if not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),atol=1e-4) or np.linalg.det(matrix[:3,:3])<.999:
                raise ValueError('nonrigid_observation')
        F[:3,3]*=s; H=np.linalg.solve(C,F)
        maximum=max(maximum,float(np.abs(C@H-F).max()))
    return {'researchInputsValid':True,'releaseQualityPassed':False,'C_times_H_scaled_F_max':maximum,
            'worldNames':list(names),'reference':reference,'scale':s,
            'cameraStatus':'existing_research_estimates_not_independent_calibration'}


def rigid_component_state(state, angles, translation, pivot):
    """Differentiable covariance AND SH rotation for trainable body motion.

    The existing to_world helper intentionally detaches a fixed quaternion;
    do not reuse that fixed-transform conversion for a trainable rotation.
    """
    from reconstruction_portrait_model import GaussianState,quat_product,rotate_sh1
    R=axis_angle_matrix(angles);theta=torch.linalg.vector_norm(angles)
    q=torch.cat((torch.cos(theta/2).reshape(1),.5*torch.sinc(theta/(2*torch.pi))*angles))
    return GaussianState((state.means-pivot)@R.T+pivot+translation,
        quat_product(q,state.quats),state.scales,state.opacity,rotate_sh1(state.sh,R),state.parts)


def ensure_point_lineage(portrait):
    if hasattr(portrait,'stable_uid'):return
    n=len(portrait.role);device=portrait.role.device
    portrait.register_buffer('stable_uid',torch.arange(n,device=device,dtype=torch.long))
    portrait.register_buffer('parent_uid',torch.full((n,),-1,device=device,dtype=torch.long))
    portrait.register_buffer('next_uid',torch.tensor(n,device=device,dtype=torch.long))


@torch.no_grad()
def replace_face_with_lineage(portrait,optimizer,selected,validate_children):
    ensure_point_lineage(portrait)
    selected=torch.as_tensor(selected,device=portrait.role.device,dtype=torch.long)
    old_n=len(portrait.role);old_surface=portrait.surface_count
    uid=portrait.stable_uid.clone();parent=portrait.parent_uid.clone();checked=[]
    def validate(ids,bary):
        result=validate_children(ids,bary);checked.append(result.detach().clone());return result
    result=portrait.replace_skin_parents(selected,optimizer,validate)
    count=len(selected);selected=selected[checked[0][:count]&checked[0][count:]]
    keep=torch.ones(old_surface,device=selected.device,dtype=torch.bool);keep[selected]=False
    rest=torch.where(keep)[0];mapping=torch.cat((rest,selected,selected,torch.arange(old_surface,old_n,device=selected.device)))
    start=len(rest);stop=start+2*len(selected)
    portrait.stable_uid=uid[mapping];portrait.parent_uid=parent[mapping]
    portrait.parent_uid[start:stop]=uid[selected].repeat(2)
    next_uid=int(portrait.next_uid)
    portrait.stable_uid[start:stop]=torch.arange(next_uid,next_uid+2*len(selected),device=selected.device)
    portrait.next_uid.add_(2*len(selected))
    result['retiredStableUIDs']=uid[selected].cpu().tolist()
    result['childStableUIDs']=portrait.stable_uid[start:stop].cpu().tolist()
    return result
