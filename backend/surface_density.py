"""Bounded tangent splits with complete Adam/source/UID synchronization.

Derived points share their parent's evidence; splitting is extra capacity,
not a new measurement. No global shrink, opacity reset, or scene pruning.
"""
import copy
import math
import numpy as np
import torch
from portrait_model import quaternion_matrix


def _optimizers(value):
    return value if isinstance(value, (tuple, list)) else (value,)


@torch.no_grad()
def split_surface_parameters(scene, optimizer, selected):
    p=scene.environment
    selected=torch.as_tensor(selected,device=p["means"].device,dtype=torch.long)
    n=len(p["means"])
    if not len(selected) or len(selected.unique())!=len(selected):
        raise ValueError("unique_nonempty_surface_parents")
    if (selected<0).any() or (selected>=n).any():
        raise ValueError("surface_parent_outside_range")
    rest=torch.arange(n,device=selected.device)
    rest=rest[~torch.isin(rest,selected)]
    mapping=torch.cat((rest,selected,selected))
    child_start=len(rest)
    scales=p["scales"][selected].exp()
    axes=scales[:,:2].argmax(1)
    R=quaternion_matrix(p["quats"][selected])
    direction=R[torch.arange(len(selected),device=selected.device),:,axes]
    offsets=direction*scales.gather(1,axes[:,None])*.45
    updates={k:v.detach()[mapping].clone() for k,v in p.items()}
    updates["means"][child_start:child_start+len(selected)]-=offsets
    updates["means"][child_start+len(selected):]+=offsets
    for begin in (child_start,child_start+len(selected)):
        updates["scales"][begin+torch.arange(len(selected),device=selected.device),axes]+=math.log(.70)
    alpha=p["opacities"][selected].sigmoid()
    updates["opacities"][child_start:]=torch.logit((1-torch.sqrt(1-alpha)).repeat(2).clamp(1e-6,1-1e-6))
    # Every optimizer that aliases these environment parameters (the shared
    # room clock and the body clock) must follow the mutation together.
    for current in _optimizers(optimizer):
        for group in current.param_groups:
            name=group["name"]
            old=p[name]
            old_state=current.state.pop(old,{})
            new=torch.nn.Parameter(updates[name],requires_grad=old.requires_grad)
            p[name]=new
            group["params"]=[new]
            state={}
            for key,value in old_state.items():
                if torch.is_tensor(value) and value.shape==old.shape:
                    state[key]=value[mapping].clone()
                    state[key][child_start:]=0
                else:
                    state[key]=copy.deepcopy(value)
            current.state[new]=state
    scene.environment_parts=scene.environment_parts[mapping].clone()
    old_initial_means=scene.environment_initial_means
    scene.environment_initial_means=old_initial_means[mapping].clone()
    scene.environment_initial_means[child_start:]=updates["means"][child_start:]
    # Retained points keep their original priors, not the trained location.
    old_initial_scales=scene.environment_initial_scales
    scene.environment_initial_scales=old_initial_scales[mapping].clone()
    scene.environment_initial_scales[child_start:]=updates["scales"][child_start:]
    old_ids=scene.environment_uid
    max_uid=int(old_ids.max())+1
    scene.environment_uid=torch.cat((old_ids[rest],torch.arange(max_uid,max_uid+2*len(selected),device=selected.device)))
    scene.environment_parent_uid=torch.cat((scene.environment_parent_uid[rest],old_ids[selected].repeat(2)))
    scene.environment_generation=scene.environment_generation[mapping].clone()
    scene.environment_generation[child_start:]+=1
    host=mapping.cpu().numpy()
    scene.environment_sources={k:v[host].copy() for k,v in scene.environment_sources.items()}
    layers=getattr(scene,'environment_layers',None)
    if layers is not None:
        # Children inherit their parent's declared surface layer identity.
        scene.environment_layers=layers[host]
    return {"before":n,"after":len(mapping),"parentsRetired":len(selected),"children":2*len(selected),
            "sameEvidenceReused":True,"coverageIdentityNotAssumed":True}


def select_surface_parents(scene, info, max_parents=384, parts=(0, 4)):
    ids=info.get("gaussian_ids")
    radius=info.get("radii")
    means2d=info.get("means2d")
    if ids is None or means2d is None or means2d.grad is None:
        return torch.empty(0,dtype=torch.long,device=scene.environment_parts.device)
    # The rasterizer renders the entire head followed by the environment.
    offset=len(scene.portrait.role)
    valid=ids>=offset
    local=ids[valid]-offset
    if not len(local):
        return local
    radius=radius[valid].reshape(len(local),-1).amax(-1)
    grad=means2d.grad[valid].norm(dim=-1)
    scale=scene.environment["scales"].detach()[local].exp()
    thin=scale[:,2]<.30*scale[:,:2].amin(1)
    # Room and garment/body surfaces both grow detail; the head stays with the
    # portrait's own validated split transaction.
    eligible=torch.isin(scene.environment_parts[local],
        torch.as_tensor(parts,device=scene.environment_parts.device))&thin&(radius>4)&(grad>0)&(scene.environment_generation[local]<2)
    selected=local[eligible]
    scores=grad[eligible]*radius[eligible]
    if not len(selected):
        return selected
    order=torch.argsort(scores,descending=True)[:max_parents]
    return selected[order].unique()


@torch.no_grad()
def prune_environment(scene, optimizer, opacity_threshold=.01, minimum_keep=.7):
    """Remove permanently invisible environment splats, bounded and recorded.

    A prune that would erase more than the allowed fraction is skipped: this
    is cleanup of dead capacity, never a way to thin a healthy surface.
    """
    p=scene.environment
    opacity=p["opacities"].detach().sigmoid()
    keep=opacity>opacity_threshold
    n=len(keep)
    removed=int((~keep).sum().item())
    if removed==0:
        return {"before":n,"after":n,"removed":0,"threshold":opacity_threshold}
    if float(keep.float().mean().item())<minimum_keep:
        return {"before":n,"after":n,"removed":0,"threshold":opacity_threshold,
                "skipped":"prune_would_remove_too_much"}
    keep_idx=torch.flatnonzero(keep)
    updates={k:v.detach()[keep_idx].clone() for k,v in p.items()}
    for current in _optimizers(optimizer):
        for group in current.param_groups:
            name=group["name"]
            old=p[name]
            old_state=current.state.pop(old,{})
            new=torch.nn.Parameter(updates[name],requires_grad=old.requires_grad)
            p[name]=new
            group["params"]=[new]
            state={}
            for key,value in old_state.items():
                if torch.is_tensor(value) and value.shape==old.shape:
                    state[key]=value[keep_idx].clone()
                else:
                    state[key]=copy.deepcopy(value)
            current.state[new]=state
    scene.environment_parts=scene.environment_parts[keep_idx].clone()
    scene.environment_initial_means=scene.environment_initial_means[keep_idx].clone()
    scene.environment_initial_scales=scene.environment_initial_scales[keep_idx].clone()
    scene.environment_uid=scene.environment_uid[keep_idx].clone()
    scene.environment_parent_uid=scene.environment_parent_uid[keep_idx].clone()
    scene.environment_generation=scene.environment_generation[keep_idx].clone()
    scene.environment_sources={k:v[keep_idx.cpu().numpy()] for k,v in scene.environment_sources.items()}
    layers=getattr(scene,'environment_layers',None)
    if layers is not None:
        scene.environment_layers=layers[keep_idx.cpu().numpy()]
    return {"before":n,"after":int(len(keep_idx)),"removed":removed,
            "threshold":opacity_threshold}
