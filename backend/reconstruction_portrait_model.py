"""Reusable photo-driven portrait, with FLAME as a movable soft prior.

No production publisher imports this module until E1--E5 accept a candidate.
The import adapter preserves the entire existing head, including its known
bad hair initialization, so T0/T1 cannot hide a change of point set. New hair
geometry is a separate, explicitly recorded replacement, never a silent fix.
Triangle walking is implemented here; no SplattingAvatar code is copied.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as functional

from appearance_direction_contract import C0, C1


def quat_product(a, b):
    aw, ax, ay, az = a.unbind(-1)
    bw, bx, by, bz = b.unbind(-1)
    return torch.stack((aw*bw-ax*bx-ay*by-az*bz, aw*bx+ax*bw+ay*bz-az*by,
                        aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw), -1)


def quaternion_matrix(q):
    q = functional.normalize(q, dim=-1)
    w, x, y, z = q.unbind(-1)
    return torch.stack((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w),
                        2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w),
                        2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)), -1).reshape(-1, 3, 3)


def rotation_quaternion(R):
    # Only an externally fixed rigid transform uses the CPU conversion.
    from scipy.spatial.transform import Rotation
    xyzw = Rotation.from_matrix(R.detach().cpu().double().numpy()).as_quat()
    return torch.as_tensor(xyzw[[3, 0, 1, 2]].copy(), device=R.device, dtype=R.dtype)


def rotate_sh1(coeff, R):
    vector = torch.stack((-coeff[:, 3], -coeff[:, 1], coeff[:, 2]), 1)
    moved = torch.einsum("ij,njc->nic", R, vector)
    return torch.stack((coeff[:, 0], -moved[:, 1], moved[:, 2], -moved[:, 0]), 1)


def evaluate_sh1(coeff, rays):
    direction = functional.normalize(rays, dim=-1)
    basis = torch.stack((torch.full_like(direction[:, 0], C0),
                         -C1*direction[:, 1], C1*direction[:, 2],
                         -C1*direction[:, 0]), 1)
    return (torch.einsum("ni,nic->nc", basis, coeff)+.5).clamp_min(0)


def scaled_head_transform(C, F, scale):
    """H maps *scaled* head coordinates into the world: C H = [R_F,s t_F]."""
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("one_positive_scene_scale_required")
    target = F.clone()
    target[:3, 3] = target[:3, 3]*scale
    return torch.linalg.solve(C, target)


@dataclass
class GaussianState:
    means: torch.Tensor
    quats: torch.Tensor
    scales: torch.Tensor
    opacity: torch.Tensor
    sh: torch.Tensor
    parts: torch.Tensor

    def covariance(self):
        R = quaternion_matrix(self.quats)
        return (R*self.scales[:, None, :].square()) @ R.transpose(-1, -2)

    def to_world(self, C, F, scale):
        H = scaled_head_transform(C, F, scale)
        R, t = H[:3, :3], H[:3, 3]
        return GaussianState(self.means @ R.T*scale+t,
                             quat_product(rotation_quaternion(R), self.quats),
                             self.scales*scale, self.opacity, rotate_sh1(self.sh, R), self.parts)


def joined_state(*states):
    return GaussianState(**{key: torch.cat([getattr(s, key) for s in states])
                            for key in GaussianState.__dataclass_fields__})


def mesh_adjacency(vertices, faces, regions=None):
    """Edge adjacency only; no Euclidean jumps across lips/nose surfaces.

    Manifold edges, compatible surface regions and moderate normal angles
    are required. An open/non-manifold edge or a semantic barrier stops a walk.
    """
    triangles = vertices[faces]
    n = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    edges = {}
    for i, tri in enumerate(faces):
        for opposite in range(3):
            edge = tuple(sorted(np.delete(tri, opposite).tolist()))
            edges.setdefault(edge, []).append((i, opposite))
    neighbours = np.full((len(faces), 3), -1, np.int64)
    for entries in edges.values():
        if len(entries) != 2:
            continue
        (a, ae), (b, be) = entries
        if np.dot(n[a], n[b]) < .25 or (regions is not None and regions[a] != regions[b]):
            continue
        neighbours[a, ae], neighbours[b, be] = b, a
    return neighbours


def barycentric_of(point, triangle):
    basis = np.stack((triangle[1]-triangle[0], triangle[2]-triangle[0]), 1)
    uv = np.linalg.lstsq(basis, point-triangle[0], rcond=None)[0]
    return np.array([1-uv.sum(), uv[0], uv[1]])


def walk_embeddings(vertices, faces, neighbours, ids, bary, max_hops=8):
    """Transport a tangent displacement through connected triangle edges.

    Hinge rotation unfolds the displacement into the next triangle. At a
    barrier the point is projected onto its current edge; it is not rebound
    to a nearby unrelated triangle. Returns rows whose optimizer chart changed.
    """
    ids, bary = ids.copy(), bary.copy()
    changed = np.zeros(len(ids), bool)
    blocked = 0
    for row in np.flatnonzero(bary.min(1) < -1e-7):
        for _ in range(max_hops):
            edge = int(np.argmin(bary[row]))
            if bary[row, edge] >= -1e-7:
                break
            current = int(ids[row]); nxt = int(neighbours[current, edge])
            if nxt < 0:
                blocked += 1
                bary[row] = np.maximum(bary[row], 0)
                bary[row] /= bary[row].sum()
                changed[row] = True
                break
            old, new = vertices[faces[current]], vertices[faces[nxt]]
            edge_vertices = np.delete(old, edge, axis=0)
            origin, end = edge_vertices
            axis = (end-origin)/max(np.linalg.norm(end-origin), 1e-12)
            old_n = np.cross(old[1]-old[0], old[2]-old[0]); old_n /= max(np.linalg.norm(old_n), 1e-12)
            new_n = np.cross(new[1]-new[0], new[2]-new[0]); new_n /= max(np.linalg.norm(new_n), 1e-12)
            angle = np.arctan2(np.dot(axis, np.cross(old_n, new_n)), np.dot(old_n, new_n))
            p = bary[row] @ old-origin
            p = p*np.cos(angle)+np.cross(axis, p)*np.sin(angle)+axis*np.dot(axis, p)*(1-np.cos(angle))
            bary[row] = barycentric_of(p+origin, new)
            ids[row] = nxt; changed[row] = True
        if bary[row].min() < 0:
            bary[row] = bary[row].clip(0)
            bary[row] /= max(bary[row].sum(), 1e-12)
            blocked += 1
    return ids, bary, changed, blocked


class LocalPortraitModel(torch.nn.Module):
    """A single identity/surface field and movable Gaussian embeddings.

    Per-frame F, expressions and meshes come from explicit observations. K
    and scene scale are not trainable. All displacement limits used by the
    soft prior are inferred from native pixel scale, not universal millimetres.
    """
    def __init__(self, prior, faces, reference_mesh, *, native_metric_per_pixel=None,
                 surface_regions=None, device="cpu"):
        super().__init__()
        if str(prior["color_mode"]) != "head-local-sh1":
            raise ValueError("exact_head_local_SH1_required")
        role = np.asarray(prior["role"])
        surface = len(prior["surface_ids"])
        if not np.array_equal(np.flatnonzero(role != 2), np.arange(surface)):
            raise ValueError("surface_prefix_contract_invalid")
        n = len(role); self.source_hash = str(prior["source_sha256"])
        self.model_hash = str(prior["model_sha256"])
        tensor = lambda x, dtype=torch.float32: torch.as_tensor(x, dtype=dtype, device=device)
        self.register_buffer("faces", tensor(faces, torch.long))
        self.register_buffer("triangle_ids", tensor(prior["surface_ids"], torch.long))
        self.register_buffer("role", tensor(role, torch.long))
        self.register_buffer("source_index", tensor(prior["source_index"], torch.long))
        self.register_buffer("origin_index", tensor(prior["origin_index"], torch.long))
        self.register_buffer("confidence", tensor(prior["source_confidence"]))
        self.register_buffer("generation", torch.zeros(n, dtype=torch.long, device=device))
        self.register_buffer("reference_mesh", tensor(reference_mesh))
        self.register_buffer("hair_base", tensor(prior["hair_local_points"]))
        old = np.tanh(prior["local_offsets"])
        offset = old[:surface, 0]*np.where(role[:surface] == 0, .006, .012)
        self.normal_offset = torch.nn.Parameter(tensor(offset))
        self.register_buffer("initial_normal_offset", tensor(offset.copy()))
        self.hair_delta = torch.nn.Parameter(tensor(old[surface:]*.018))
        self.register_buffer("initial_hair_delta", self.hair_delta.detach().clone())
        self.embedding = torch.nn.Parameter(tensor(prior["surface_bary"]))
        self.register_buffer("initial_embedding", self.embedding.detach().clone())
        self.constraint_mode = "soft"
        self.surface_residual = torch.nn.Parameter(torch.zeros_like(self.reference_mesh))
        self.log_scales = torch.nn.Parameter(tensor(prior["log_scales"]))
        self.quats = torch.nn.Parameter(tensor(prior["local_quats"]))
        self.opacity_logits = torch.nn.Parameter(tensor(prior["opacity_logits"]))
        self.sh = torch.nn.Parameter(tensor(prior["sh_coeff"]))
        self.register_buffer("initial_log_scales", self.log_scales.detach().clone())
        if native_metric_per_pixel is None:
            raise ValueError("observation_derived_native_pixel_scale_required")
        px = np.broadcast_to(native_metric_per_pixel, (n,)).copy()
        if not np.isfinite(px).all() or (px <= 0).any():
            raise ValueError("native_pixel_scale_invalid")
        self.register_buffer("metric_per_pixel", tensor(px))
        self.register_buffer("skin_band", tensor(role[:surface] == 0, torch.bool))
        self.adjacency = mesh_adjacency(reference_mesh, faces, surface_regions)
        edge = np.unique(np.sort(np.concatenate((faces[:, :2], faces[:, 1:], faces[:, [0, 2]])), axis=1), axis=0)
        self.register_buffer("edges", tensor(edge, torch.long))

    @property
    def surface_count(self):
        return len(self.triangle_ids)

    def surface(self, observed_mesh):
        # Same learned identity residual in every expression/observation.
        mesh = observed_mesh+self.surface_residual
        tri = mesh[self.faces[self.triangle_ids]]
        bary = self.embedding/self.embedding.sum(-1, keepdim=True).clamp_min(1e-8)
        normals = functional.normalize(torch.linalg.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]), dim=-1)
        point = (tri*bary[..., None]).sum(1)
        if self.constraint_mode == "strong":
            base = (tri*self.initial_embedding[..., None]).sum(1)
            # Controlled reconstruction of v2's 3.5 mm / .35 tangent prior,
            # at the SAME imported P. This is not a rerun of all v2 choices.
            delta = .0035*torch.tanh((point-base)/.0035)
            point = base+.35*(delta-(delta*normals).sum(1,keepdim=True)*normals)
        return point, normals

    def local_state(self, observed_mesh):
        surface, normals = self.surface(observed_mesh)
        offset = self.normal_offset
        if self.constraint_mode == "strong":
            offset = self.initial_normal_offset+.0035*torch.tanh((offset-self.initial_normal_offset)/.0035)
        means = torch.cat((surface+normals*offset[:, None], self.hair_base+self.hair_delta))
        # Preserve the imported trainer's actual scale activation exactly.
        return GaussianState(means, functional.normalize(self.quats, dim=-1),
                             self.log_scales.exp().clamp(.00045, .018), self.opacity_logits.sigmoid(),
                             self.sh, torch.where(self.role == 2, 2, 1))

    def soft_regularization(self, observed_mesh):
        surface, normal = self.surface(observed_mesh)
        n = self.surface_count; state = self.local_state(observed_mesh)
        covariance = state.covariance()[:n]
        variance = torch.einsum("ni,nij,nj->n", normal, covariance, normal)
        distance = self.normal_offset
        # A nonzero allowed band derived from pixel scale; penalize only
        # robust excess of expected squared distance, never zero thickness.
        allowance = self.initial_normal_offset.abs()+2*self.metric_per_pixel[:n]
        expected_sq = distance.square()+variance
        excess = (expected_sq.sqrt()-allowance).clamp_min(0)/allowance.clamp_min(1e-8)
        band = functional.huber_loss(excess[self.skin_band], torch.zeros_like(excess[self.skin_band]), reduction="mean")
        residual = self.surface_residual
        smooth = (residual[self.edges[:, 0]]-residual[self.edges[:, 1]]).square().mean()
        identity = residual.square().mean()
        offset_change = ((distance-self.initial_normal_offset)/self.metric_per_pixel[:n]).square().mean()
        # Hair/glasses/detail points are not subject to the skin plane loss.
        return {"skinSoftBand": band, "sharedSurfaceSmooth": smooth/self.metric_per_pixel.median().square(),
                "sharedIdentityResidual": identity/self.metric_per_pixel.median().square(),
                "normalOffsetChangePixels": offset_change}

    @torch.no_grad()
    def walk(self, optimizer=None):
        mesh = (self.reference_mesh+self.surface_residual).cpu().numpy()
        bary = (self.embedding/self.embedding.sum(-1, keepdim=True).clamp_min(1e-8)).cpu().numpy()
        ids, moved, changed, blocked = walk_embeddings(mesh, self.faces.cpu().numpy(), self.adjacency,
                                                        self.triangle_ids.cpu().numpy(), bary)
        self.triangle_ids.copy_(torch.as_tensor(ids, device=self.triangle_ids.device))
        self.embedding.copy_(torch.as_tensor(moved, device=self.embedding.device))
        if optimizer is not None and changed.any():
            mask = torch.as_tensor(changed, device=self.embedding.device)
            # Chart moments do not transform as world position moments.
            for key, value in optimizer.state.get(self.embedding, {}).items():
                if isinstance(value, torch.Tensor) and value.shape == self.embedding.shape:
                    value[mask] = 0
        return {"walkedOrClampedRows": int(changed.sum()), "barrierStops": blocked}

    @torch.no_grad()
    def replace_skin_parents(self, selected, optimizer, validate_children):
        """Two children take a parent's place; every point field follows it.

        Only photograph-supported skin is eligible. Surface interpolation is
        not labelled independently triangulated geometry. Validation is an
        actual per-child observation test supplied by the training data.
        """
        selected = torch.as_tensor(selected, dtype=torch.long, device=self.role.device)
        if len(selected) == 0 or len(selected.unique()) != len(selected):
            raise ValueError("nonempty_unique_skin_parents_required")
        if (selected < 0).any() or (selected >= self.surface_count).any() or (self.role[selected] != 0).any():
            raise ValueError("only_supported_skin_parents_can_split")
        n, s = len(self.role), self.surface_count
        triangles = (self.reference_mesh+self.surface_residual)[self.faces[self.triangle_ids[selected]]]
        old_bary = self.embedding[selected]/self.embedding[selected].sum(-1, keepdim=True)
        center = (triangles*old_bary[..., None]).sum(1)
        normal = functional.normalize(torch.linalg.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), dim=-1)
        rotations = quaternion_matrix(self.quats[selected])
        scales = self.log_scales[selected].exp()
        axis = scales.argmax(1)
        direction = rotations[torch.arange(len(selected), device=axis.device), :, axis]
        direction = functional.normalize(direction-(direction*normal).sum(1, keepdim=True)*normal, dim=-1)
        displacement = direction*scales.gather(1, axis[:, None])*.6
        children_ids, children_bary = [], []
        for sign in (-1, 1):
            target = center+sign*displacement
            bary = np.stack([barycentric_of(p, t) for p, t in zip(target.cpu().numpy(), triangles.cpu().numpy())])
            ids, bary, _, _ = walk_embeddings((self.reference_mesh+self.surface_residual).cpu().numpy(),
                self.faces.cpu().numpy(), self.adjacency, self.triangle_ids[selected].cpu().numpy(), bary)
            children_ids.append(torch.as_tensor(ids, device=selected.device))
            children_bary.append(torch.as_tensor(bary, dtype=self.embedding.dtype, device=selected.device))
        proposed_count = len(selected)
        child_valid = validate_children(torch.cat(children_ids), torch.cat(children_bary))
        if child_valid.shape != (2*proposed_count,) or child_valid.dtype != torch.bool:
            raise ValueError("per_child_boolean_evidence_required")
        valid = child_valid[:proposed_count] & child_valid[proposed_count:]
        if not valid.any():
            raise ValueError("split_child_observation_support_failed")
        selected = selected[valid]; axis = axis[valid]
        children_ids = [v[valid] for v in children_ids]
        children_bary = [v[valid] for v in children_bary]
        keep_surface = torch.ones(s, dtype=torch.bool, device=selected.device); keep_surface[selected] = False
        rest_surface = torch.where(keep_surface)[0]
        mapping = torch.cat((rest_surface, selected, selected, torch.arange(s, n, device=selected.device)))
        surface_map = mapping[:s+len(selected)]
        start, stop = len(rest_surface), len(rest_surface)+2*len(selected)
        parameter_maps = {"embedding": surface_map, "normal_offset": surface_map,
                          **{key: mapping for key in ("sh", "opacity_logits", "log_scales", "quats")}}
        for key, indices in parameter_maps.items():
            old = getattr(self, key); values = old.detach()[indices].clone()
            if key == "embedding": values[start:stop] = torch.cat(children_bary)
            if key == "log_scales":
                axes = torch.cat((axis, axis))
                values[torch.arange(start, stop, device=selected.device), axes] += np.log(.8)
            if key == "opacity_logits":
                tau = -torch.log1p(-values[start:stop].sigmoid().clamp_max(.999))
                values[start:stop] = torch.logit((-torch.expm1(-tau/1.6)).clamp(.001, .999))
            new = torch.nn.Parameter(values, requires_grad=old.requires_grad)
            setattr(self, key, new)
            for group in optimizer.param_groups:
                group["params"] = [new if p is old else p for p in group["params"]]
            state = optimizer.state.pop(old, {})
            new_state = {}
            for field, value in state.items():
                if isinstance(value, torch.Tensor) and value.shape == old.shape:
                    copied = value[indices].clone(); copied[start:stop] = 0
                    new_state[field] = copied
                else:
                    new_state[field] = value.clone() if isinstance(value, torch.Tensor) else value
            optimizer.state[new] = new_state
        self.triangle_ids = torch.cat((self.triangle_ids[rest_surface], *children_ids))
        self.initial_normal_offset = self.initial_normal_offset[surface_map].clone()
        self.initial_embedding = self.embedding.detach().clone()
        self.skin_band = self.skin_band[surface_map].clone()
        for key in ("role", "source_index", "origin_index", "confidence", "generation", "metric_per_pixel", "initial_log_scales"):
            setattr(self, key, getattr(self, key)[mapping].clone())
        self.generation[start:stop] += 1
        self.initial_log_scales[start:stop] = self.log_scales[start:stop].detach()
        return {"before": n, "after": len(self.role), "parentsRetired": len(selected),
                "proposedParents": proposed_count,"rejectedChildEvidence": proposed_count-len(selected),
                "children": 2*len(selected), "sampling": "photo_validated_surface_interpolation",
                "parentAndChildOverlap": False}


class CandidateTransaction:
    """Complete model + Adam snapshot, short recovery, then evidence decision.

    Recovery is finite; it cannot adjust the acceptance tolerances. The
    supplied audit must use held-out/development views in addition to training.
    """
    def __init__(self, model, optimizer):
        self.model, self.optimizer = model, optimizer
        self.snapshot = copy.deepcopy(model)
        self.optimizer_snapshot = copy.deepcopy(optimizer.state_dict())

    def rollback(self):
        self.model.__dict__.clear()
        self.model.__dict__.update(copy.deepcopy(self.snapshot.__dict__))
        # Restore param-group identity, then its complete Adam state.
        current = dict(self.model.named_parameters())
        groups = self.optimizer.param_groups
        # A transaction may change parameter shapes. Save group names before
        # mutation rather than trying to infer them from values after mutation.
        for group, names_in_group in zip(groups, self.group_names):
            group["params"] = [current[name] for name in names_in_group]
        self.optimizer.load_state_dict(self.optimizer_snapshot)

    def __enter__(self):
        inverse = {id(value): name for name, value in self.model.named_parameters()}
        self.group_names = [[inverse[id(p)] for p in group["params"]] for group in self.optimizer.param_groups]
        return self

    def run(self, mutate, recover, audit, *, recovery_steps=24):
        if not 1 <= recovery_steps <= 48:
            raise ValueError("recovery_budget_out_of_bounds")
        before = audit()
        mutation = mutate()
        initial = audit()
        catastrophic = any(initial[n]["hole"] > before[n]["hole"]+.05 for n in before)
        updates = 0
        if not catastrophic:
            for i in range(recovery_steps):
                recover(i); updates += 1
        after = audit()
        accepted = not catastrophic and all(
            after[n]["hole"] <= before[n]["hole"]+.005 and
            after[n]["rgb"] <= before[n]["rgb"]+.002 for n in before)
        if not accepted:
            self.rollback()
        return {"accepted": accepted, "catastrophic": catastrophic, "recoverySteps": updates,
                "before": before, "initialCandidate": initial, "afterRecovery": after, "mutation": mutation}

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rollback()
        return False
