"""Bounded, reversible native-pixel skin-capacity research stage.

Selection uses training photographs and current-model visibility, not dev RGB.
The mesh is a motion/surface prior, never claimed as measured pore geometry.
All loss forwards render the complete scene at its original canvas size.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random
import time

import cv2
import numpy as np
from scipy.spatial import cKDTree
import torch


APPEARANCE = ('sh', 'opacity_logits', 'log_scales', 'quats')


def restore_model_topology(model, state):
    """Restore a saved replacement checkpoint without redoing the split.

    This only resizes known point/embedding fields. All immutable surface,
    original hair and mesh fields must match the receiving parent model.
    The caller separately validates source and full-scene surfaceContract.
    """
    point_buffers = ('role', 'source_index', 'origin_index', 'confidence', 'generation',
                     'metric_per_pixel', 'initial_log_scales')
    surface_buffers = ('triangle_ids', 'initial_normal_offset', 'initial_embedding', 'skin_band')
    dynamic = set(point_buffers+surface_buffers+APPEARANCE+('embedding', 'normal_offset'))
    current = model.state_dict()
    if set(current) != set(state): raise ValueError('capacity_restore_incomplete_model_state')
    for key in set(current)-dynamic:
        if not torch.equal(current[key], state[key].to(current[key].device)):
            raise ValueError('capacity_restore_changed_immutable_field:'+key)
    n = len(state['role']); s = len(state['triangle_ids'])
    if not (0 < s <= n) or (state['role'][:s] == 2).any() or (state['role'][s:] != 2).any():
        raise ValueError('capacity_restore_surface_prefix')
    if ((state['triangle_ids'] < 0) | (state['triangle_ids'] >= len(state['faces']))).any():
        raise ValueError('capacity_restore_triangle')
    if state['embedding'].shape != (s, 3) or not torch.isfinite(state['embedding']).all():
        raise ValueError('capacity_restore_embedding')
    for key in point_buffers+APPEARANCE:
        if len(state[key]) != n: raise ValueError('capacity_restore_point_length:'+key)
    for key in surface_buffers+('embedding', 'normal_offset'):
        if len(state[key]) != s: raise ValueError('capacity_restore_surface_length:'+key)
    device = model.sh.device
    for key in point_buffers+surface_buffers: setattr(model, key, state[key].to(device).clone())
    for key in APPEARANCE+('embedding', 'normal_offset'):
        setattr(model, key, torch.nn.Parameter(state[key].to(device).clone(), requires_grad=getattr(model, key).requires_grad))
    model.load_state_dict(state, strict=True)
    return dict(pointCount=n, surfaceCount=s, topologyReplayed=False, completeModelRestored=True)


def sha_array(value):
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def skin_domain(labels):
    if 'training_skin' not in labels:
        raise ValueError('capacity_requires_observed_skin_not_landmark_oval')
    return (np.asarray(labels['training_skin'], bool)
            & ~np.asarray(labels['hair_visible'], bool)
            & ~np.asarray(labels['glasses_visible'], bool)
            & ~np.asarray(labels['unknown_or_occluded'], bool))


def project_footprint(means, covariance, F, K):
    """Native 1-sigma eigenvalues, explicitly not rasterizer radii or PSF.

    First-order covariance is used to propose a conservative interior margin.
    Actual full-canvas compositing contributions separately validate visibility.
    """
    means = np.asarray(means, np.float64)
    R = np.asarray(F, np.float64)[:3, :3]
    cam = means @ R.T + np.asarray(F)[:3, 3]
    z = np.maximum(cam[:, 2], 1e-8)
    p = cam @ np.asarray(K).T
    uv = p[:, :2] / z[:, None]
    J = np.zeros((len(means), 2, 3), np.float64)
    J[:, 0, 0] = K[0, 0]/z; J[:, 1, 1] = K[1, 1]/z
    J[:, 0, 2] = -K[0, 0]*cam[:, 0]/z**2
    J[:, 1, 2] = -K[1, 1]*cam[:, 1]/z**2
    cov = R @ np.asarray(covariance) @ R.T
    projected = J @ cov @ J.transpose(0, 2, 1)
    eig = np.linalg.eigvalsh(projected).clip(0)
    return uv, cam[:, 2], np.sqrt(eig[:, 1]), projected


def inside_support(uv, depth, sigma, distance, skin_depth, skin_q,
                   metric_per_pixel, *, margin=3., depth_sigma=None):
    h, w = distance.shape
    finite = np.isfinite(uv).all(1) & np.isfinite(depth) & np.isfinite(sigma)
    xy = np.rint(np.nan_to_num(uv)).astype(np.int64)
    inside = finite & (depth > .01) & (xy[:, 0] >= 0) & (xy[:, 0] < w) & (xy[:, 1] >= 0) & (xy[:, 1] < h)
    x = xy[:, 0].clip(0, w-1); y = xy[:, 1].clip(0, h-1)
    valid = inside & (distance[y, x] >= margin*sigma+2.) & (skin_q[y, x] > .1)
    allowance = 3*np.asarray(depth_sigma if depth_sigma is not None else metric_per_pixel)+2*np.asarray(metric_per_pixel)
    valid &= np.isfinite(skin_depth[y, x]) & (np.abs(skin_depth[y, x]-depth) <= allowance)
    return valid, x, y


def continuous_patch(points, normals, triangles, adjacency, eligible, score, max_parents=384):
    """One local graph component, with mesh-edge and normal barriers.

    Radius comes from this model's neighbour spacing, not a face coordinate or
    source frame. Neighbourhood is at most three actual triangle edges away.
    """
    ids = np.flatnonzero(eligible)
    if len(ids) < 8:
        raise ValueError('capacity_fewer_than_eight_supported_skin_parents')
    tree = cKDTree(points[ids]); distances, neighbours = tree.query(points[ids], k=min(12, len(ids)))
    allowed_tri = {}
    for tri in np.unique(triangles[ids]):
        reached = {int(tri)}; frontier = set(reached)
        for _ in range(3):
            frontier = {int(v) for t in frontier for v in adjacency[t] if v >= 0} - reached
            reached |= frontier
        allowed_tri[int(tri)] = reached
    compatible_distances = []
    for i, point in enumerate(ids):
        for d, other in zip(distances[i, 1:], neighbours[i, 1:]):
            oid = ids[int(other)]
            if (d > 1e-9 and triangles[oid] in allowed_tri[int(triangles[point])]
                    and np.dot(normals[point], normals[oid]) >= .90):
                compatible_distances.append(float(d)); break
    if not compatible_distances:
        raise ValueError('capacity_invalid_surface_spacing')
    spacing = float(np.median(compatible_distances))
    order = np.lexsort((ids, -score[ids]))
    best = []
    # A finite list of strong seeds; no threshold search using dev results.
    for root in order[:min(32, len(order))]:
        queue = [int(root)]; seen = {int(root)}; component = []
        while queue and len(component) < max_parents:
            current = queue.pop(0); point = ids[current]; component.append(point)
            for d, other in zip(distances[current, 1:], neighbours[current, 1:]):
                other = int(other)
                if other in seen or d > 4*spacing:
                    continue
                oid = ids[other]
                if (triangles[oid] not in allowed_tri[int(triangles[point])]
                        or np.dot(normals[point], normals[oid]) < .90
                        or np.linalg.norm(points[oid]-points[ids[root]]) > 10*spacing):
                    continue
                seen.add(other); queue.append(other)
        if len(component) > len(best):
            best = component
        if len(best) >= max_parents:
            break
    if len(best) < 8:
        raise ValueError('capacity_no_continuous_reliable_patch')
    return np.asarray(best, np.int64), dict(neighbourSpacing=spacing, geodesicHops=3,
        maximumRadius=10*spacing, compatibleNormalDot=.90, count=len(best))


def _world_state(scene, frame):
    from reconstruction_live_neck_motion import joined_covariant
    return joined_covariant(scene.portrait_state(frame).to_world(frame['C'], frame['F'], scene.scale),
                             scene.environment_state(frame))


@torch.no_grad()
def selected_pixels(scene, frame, selected):
    """Frozen one-channel evidence rendered WITH every other component."""
    from gsplat import rasterization
    state = _world_state(scene, frame); w, h = frame['fullSize']
    features = torch.zeros((len(state.means), 3), device=state.means.device)
    features[selected, 0] = 1
    image, _, _ = rasterization(state.means, None, None, state.opacity, features,
        frame['C'][None], frame['fullK'][None], w, h, covars=state.covariance(), packed=True,
        sh_degree=None, render_mode='RGB', rasterize_mode='classic', near_plane=.01*scene.scale,
        far_plane=1e10*scene.scale)
    return image[0, :, :, 0]


def select_patch(scene, data, output, *, max_parents=384):
    from reconstruction_portrait_pipeline import make_frame, write_json
    from reconstruction_live_neck_appearance import point_region_contributions
    if not 8 <= max_parents <= 512:
        raise ValueError('capacity_parent_budget_must_be_8_to_512')
    model = scene.portrait; n = model.surface_count; device = model.sh.device
    names = [name for name in data['train'] if data['local'][name]['role'] == 'train' and name in data['worlds']]
    if len(names) < 3:
        raise ValueError('capacity_requires_three_real_world_training_observations')
    support = np.zeros(n, np.int64); veto = np.zeros(n, bool)
    footprint = []; detail = np.zeros(n); obs = {}; rows = []
    with torch.no_grad():
        ref = model.local_state(model.reference_mesh)
        means = ref.means[:n].cpu().numpy(); cov = ref.covariance()[:n].cpu().numpy()
        _, normal = model.surface(model.reference_mesh); normals = normal.cpu().numpy()
        rotations = __import__('reconstruction_portrait_model').quaternion_matrix(model.quats[:n]).cpu().numpy()
        max_axis = model.log_scales[:n].argmax(1).cpu().numpy()
        direction = rotations[np.arange(n), :, max_axis]
        tangent = np.linalg.norm(direction-(direction*normals).sum(1)[:, None]*normals, axis=1)
        metric = model.metric_per_pixel[:n].cpu().numpy()
        for name in names:
            frame = make_frame(data, name, crop=False, device=str(device))
            domain = skin_domain(data['labels'][name])
            distance = cv2.distanceTransform(domain.astype(np.uint8), cv2.DIST_L2, 5)
            full = scene.render(frame, 'T2')
            skin_q = full['q'][..., 1].cpu().numpy()
            skin_depth = (full['q_depth'][..., 1]/full['q'][..., 1].clamp_min(1e-8)).cpu().numpy()
            state = scene.portrait_state(frame)
            local_means = state.means[:n].cpu().numpy(); local_cov = state.covariance()[:n].cpu().numpy()
            F = np.asarray(data['local'][name]['F']); uv, z, sigma, _ = project_footprint(local_means, local_cov, F, data['K'])
            depth_sigma = np.sqrt(np.einsum('i,nij,j->n', F[2, :3], local_cov, F[2, :3]).clip(0))
            valid, x, y = inside_support(uv, z, sigma, distance, skin_depth, skin_q, metric, depth_sigma=depth_sigma)
            # Current geometry/order are eligibility checks, never new depth truth.
            weights = point_region_contributions(_world_state(scene, frame), frame, domain, ~domain,
                unit_scale=scene.scale)[:n].cpu().numpy()
            valid &= (weights[:, 0] >= .25) & (weights[:, 0] >= .995*weights[:, 2])
            veto |= weights[:, 1] > .001
            rgb = np.asarray(data['rgb'][name], np.float32)
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)/8
            gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)/8
            energy = cv2.GaussianBlur(gx*gx+gy*gy, (0, 0), 1.)
            detail += energy[y, x]*valid; support += valid
            footprint.append(np.where(valid, sigma, np.nan))
            obs[name] = dict(distance=distance, depth=skin_depth, q=skin_q, domain=domain)
            rows.append(dict(imageName=name, role='train', domainSha256=sha_array(np.packbits(domain)),
                supportedPoints=int(valid.sum()), sigmaMedian=float(np.median(sigma[valid])) if valid.any() else None))
    sigma = np.nanmedian(np.stack(footprint), axis=0)
    role = model.role[:n].cpu().numpy()
    eligible = (support >= 3) & ~veto & (role == 0) & (tangent >= .6) & (sigma >= 2.)
    if hasattr(scene, 'neck_sh_editable'):
        eligible &= ~scene.neck_sh_editable[:n].cpu().numpy()
    # Photographic gradient is capacity-demand evidence, not geometric truth.
    detail /= np.maximum(support, 1)
    nn = cKDTree(means).query(means, k=2)[0][:, 1]
    ratio = np.exp(model.log_scales[:n].detach().cpu().numpy()).max(1)/np.maximum(nn, 1e-9)
    score = np.nan_to_num(sigma)*(1+np.sqrt(detail))*np.minimum(ratio, 4)
    selected, graph = continuous_patch(means, normals, model.triangle_ids.cpu().numpy(), model.adjacency,
                                       eligible, score, max_parents=max_parents)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    receipt = dict(method='native_footprint_observed_skin_actual_full_scene_contribution_connected_mesh_patch',
        sourceSha256=data['sourceHash'], trainNames=names, selectedCount=len(selected), selectedIds=selected.tolist(),
        selectedIdsSha256=sha_array(selected), eligibleCount=int(eligible.sum()), graph=graph, observations=rows,
        selectionLimits=dict(minViews=3, minSigma=2., footprintMarginSigma=3., edgePixels=2.,
            maximumNonSkinIntegratedContribution=.001, minSkinContributionFraction=.995),
        selectedSigmaQuantiles=np.quantile(sigma[selected], [.1, .5, .9]).tolist(),
        selectedNeighbourOverlapQuantiles=np.quantile(ratio[selected], [.1, .5, .9]).tolist(),
        estimatedChildrenFromLocalSpacing=np.maximum(2, np.ceil(ratio[selected]**2)).astype(int).tolist(),
        capacityDemandCaveat='neighbour-spacing area proxy; not a measured optical PSF or sufficient-detail claim',
        noDevelopmentRGBSelection=True, independentGeometryTruth=False,
        visibility='current_frozen_model_compositing_and_depth_not_independent_measurement')
    write_json(output/'selection.json', receipt)
    np.savez_compressed(output/'selection.npz', selected=selected, support=support, veto=veto,
                         sigma=sigma, score=score, source_hash=np.asarray(data['sourceHash']))
    return dict(selected=selected, names=names, observations=obs, receipt=receipt)


def replacement_mapping(old_count, old_surface, selected, valid):
    chosen = np.asarray(selected)[np.asarray(valid, bool)]
    rest = np.setdiff1d(np.arange(old_surface), chosen)
    mapping = np.concatenate((rest, chosen, chosen, np.arange(old_surface, old_count)))
    children = np.arange(len(rest), len(rest)+2*len(chosen))
    return mapping, children, chosen


def source_base_colour(rgb, points, F, coeff):
    """Recover DC colour residual, not RGB plus the old directional term."""
    from appearance_direction_contract import C1
    center = -np.asarray(F)[:3, :3].T @ np.asarray(F)[:3, 3]
    ray = np.asarray(points)-center
    ray /= np.maximum(np.linalg.norm(ray, axis=1, keepdims=True), 1e-12)
    basis = np.stack((-C1*ray[:, 1], C1*ray[:, 2], -C1*ray[:, 0]), axis=1)
    direction_colour = np.einsum('ni,nic->nc', basis, np.asarray(coeff)[:, 1:4])
    return np.asarray(rgb)-direction_colour


@torch.no_grad()
def child_observations(scene, data, plan, ids, bary, parents):
    """3D barycentric points; no screen-space centroid or nearest skin fill."""
    model = scene.portrait; n = len(ids); votes = np.zeros(n, np.int64)
    colors = []; metric = model.metric_per_pixel[parents].cpu().numpy()
    covariance = model.local_state(model.reference_mesh).covariance()[parents].cpu().numpy()
    offsets = model.normal_offset[parents]
    for name in plan['names']:
        row = data['local'][name]
        mesh = torch.as_tensor(row['mesh'], dtype=model.reference_mesh.dtype, device=model.sh.device)+model.surface_residual
        tri = mesh[model.faces[ids]]
        normal = torch.nn.functional.normalize(torch.linalg.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]), dim=-1)
        points = (tri*bary[..., None]).sum(1)+normal*offsets[:, None]
        F = np.asarray(row['F']); uv, z, sigma, _ = project_footprint(points.cpu().numpy(), covariance, F, data['K'])
        dstd = np.sqrt(np.einsum('i,nij,j->n', F[2, :3], covariance, F[2, :3]).clip(0))
        obs = plan['observations'][name]
        valid, x, y = inside_support(uv, z, sigma, obs['distance'], obs['depth'], obs['q'], metric, depth_sigma=dstd)
        rgb = np.asarray(data['rgb'][name], np.float32)
        # Native bilinear source samples; no sharpening, skin generation, or
        # colour borrowed from a neighbouring/background pixel when invalid.
        sampled = cv2.remap(rgb, uv[:, 0].astype(np.float32).reshape(1, -1),
            uv[:, 1].astype(np.float32).reshape(1, -1), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)[0]
        base_colour = source_base_colour(sampled, points.cpu().numpy(), F, model.sh[parents].cpu().numpy())
        colors.append(np.where(valid[:, None], base_colour, np.nan)); votes += valid
    color = np.nanmedian(np.stack(colors), axis=0)
    valid = (votes >= 3) & np.isfinite(color).all(1)
    return torch.as_tensor(valid, device=ids.device), color, votes


def replace_patch(scene, data, plan, optimizer, selected, uid, parent_uid):
    from appearance_direction_contract import C0
    model = scene.portrait; before = len(model.role); surface = model.surface_count
    selected = np.asarray(selected, np.int64); captured = {}
    old_initial_embedding = model.initial_embedding.detach().clone()
    def validate(ids, bary):
        parents = torch.as_tensor(np.tile(selected, 2), device=model.sh.device)
        valid, color, votes = child_observations(scene, data, plan, ids, bary, parents)
        captured.update(valid=valid.cpu().numpy(), color=color, votes=votes)
        return valid
    event = model.replace_skin_parents(selected, optimizer, validate)
    # Legacy replacement also creates empty Adam entries for frozen geometry
    # fields. They are not members of this appearance-only optimizer and would
    # otherwise make Adam.state_dict fail when resolving parameter IDs.
    optimizer_members = {id(p) for group in optimizer.param_groups for p in group['params']}
    for p in list(optimizer.state):
        if id(p) not in optimizer_members:
            if optimizer.state[p]:
                raise ValueError('capacity_unexpected_optimizer_state_for_frozen_parameter')
            del optimizer.state[p]
    valid = captured['valid'][:len(selected)] & captured['valid'][len(selected):]
    mapping, children, chosen = replacement_mapping(before, surface, selected, valid)
    next_uid = int(uid.max())+1
    new_uid = uid[mapping].copy(); new_parent_uid = parent_uid[mapping].copy()
    new_parent_uid[children] = uid[np.tile(chosen, 2)]
    new_uid[children] = np.arange(next_uid, next_uid+len(children))
    with torch.no_grad():
        # A robust source-only base colour, while retaining measured parent's
        # direction terms. Finite image optimization subsequently resolves it.
        color = captured['color'][np.tile(valid, 2)]
        model.sh[children, 0] = torch.as_tensor((color-.5)/C0, device=model.sh.device, dtype=model.sh.dtype)
        # The reusable legacy transaction resets initial_embedding globally.
        # Preserve untouched points' actual recorded prior; only new children
        # acquire new charts in this narrowly scoped stage.
        keep = np.ones(model.surface_count, bool); keep[children] = False
        model.initial_embedding[keep] = old_initial_embedding[torch.as_tensor(mapping[:model.surface_count][keep], device=model.sh.device)]
        if hasattr(scene, 'neck_sh_editable'):
            scene.neck_sh_editable = scene.neck_sh_editable[torch.as_tensor(mapping, device=model.sh.device)].clone()
    event.update(retiredUIDs=uid[chosen].tolist(), childUIDs=new_uid[children].tolist(),
        childParentUIDs=new_parent_uid[children].tolist(), sourceOnlyColour=True,
        childMinimumTrainingSupport=int(captured['votes'][np.tile(valid, 2)].min()),
        covarianceRule='existing_tangent_two_child_0.8_largest_axis; no_global_scale_change',
        colourRule='per_channel_median_of_native_RGB_minus_parent_directional_SH1; retained_parent_SH1')
    return event, mapping, children, new_uid, new_parent_uid


def masked_step(optimizer, params, allowed, frozen):
    """Do not let stale Adam momentum modify a protected point."""
    for key, p in params.items():
        if p.grad is not None:
            p.grad[~allowed] = 0
        for value in optimizer.state.get(p, {}).values():
            if isinstance(value, torch.Tensor) and value.shape == p.shape:
                value[~allowed] = 0
    torch.nn.utils.clip_grad_norm_(list(params.values()), 10.)
    optimizer.step()
    with torch.no_grad():
        for key, p in params.items():
            p[~allowed] = frozen[key][~allowed]
        params['log_scales'][allowed] = params['log_scales'][allowed].clamp(
            frozen['log_scales'][allowed]+np.log(.85), frozen['log_scales'][allowed]+np.log(1.08))
        params['opacity_logits'][allowed] = params['opacity_logits'][allowed].clamp(
            frozen['opacity_logits'][allowed]-1.5, frozen['opacity_logits'][allowed]+1.5)


def capture_rng():
    state = np.random.get_state()
    return dict(torch=torch.get_rng_state(), cuda=torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
        numpy=dict(kind=state[0], keys=torch.as_tensor(state[1].astype(np.int64)), position=state[2],
                   hasGaussian=state[3], cachedGaussian=state[4]), python=random.getstate())


@torch.no_grad()
def representation_metrics(scene, data, targets, selected):
    from reconstruction_portrait_pipeline import make_frame
    from reconstruction_live_neck_appearance import point_region_contributions
    model = scene.portrait; rows = {}
    for name in targets['all']:
        frame = make_frame(data, name, crop=False, device=str(model.sh.device))
        with np.load(Path(targets['directory'])/(name+'.npz'), allow_pickle=False) as a: mask = a['target']
        if int(mask.sum()) < 16: continue
        local = scene.portrait_state(frame)
        _, _, sigma, _ = project_footprint(local.means.cpu().numpy(), local.covariance().cpu().numpy(),
                                           np.asarray(data['local'][name]['F']), data['K'])
        q = point_region_contributions(_world_state(scene, frame), frame, mask, ~mask,
                                       unit_scale=scene.scale)[:len(model.role), 0].cpu().numpy()
        skin = model.role.cpu().numpy() != 2
        ids = np.asarray(selected); weights = q[ids]; valid = weights > 1e-7
        if not valid.any():
            rows[name] = dict(selectedSkinFraction=0., sigmaWeightedMedian=None, selectedPixels=0.); continue
        order = np.argsort(sigma[ids][valid]); values = sigma[ids][valid][order]
        cumulative = np.cumsum(weights[valid][order]); cumulative /= cumulative[-1]
        rows[name] = dict(selectedSkinFraction=float(weights.sum()/max(q[skin].sum(), 1e-8)),
            sigmaWeightedMedian=float(values[np.searchsorted(cumulative, .5)]),
            sigmaWeightedP90=float(values[min(len(values)-1, np.searchsorted(cumulative, .9))]),
            selectedPixels=float(weights.sum()), otherSkinPixels=float(q[skin].sum()-weights.sum()),
            contributionEvidence='actual_full_canvas_compositing', sigmaMeaning='native_analytic_one_sigma_not_radii_or_PSF')
    return rows


def _native_snapshot(scene, data, name, selected, path):
    from reconstruction_portrait_pipeline import make_frame
    frame = make_frame(data, name, crop=False, device=str(scene.portrait.sh.device))
    with torch.no_grad():
        r = scene.render(frame, 'T2')
        footprint = selected_pixels(scene, frame, selected).cpu().numpy()
        target = (footprint > .003) & skin_domain(data['labels'][name])
        # Fixed region always contains missing pixels. It is never recomputed
        # from the candidate's opacity or output after the replacement.
        np.savez_compressed(path, rgb=r['rgb'].cpu().numpy(), alpha=r['alpha'].cpu().numpy(),
            skin_q=r['q'][..., 1].cpu().numpy(), target=target,
            source_hash=np.asarray(data['sourceHash']), image_name=np.asarray(name))


def prepare_targets(scene, data, plan, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    development = [name for name, row in data['local'].items() if row['role'] == 'development' and name in data['worlds']]
    names = list(dict.fromkeys(plan['names']+development))
    for name in names:
        _native_snapshot(scene, data, name, plan['selected'], output/(name+'.npz'))
    return dict(directory=str(output.resolve()), train=plan['names'], development=development, all=names)


def _edge_error(rgb, target, mask):
    dx = (rgb[:, 1:]-rgb[:, :-1])-(target[:, 1:]-target[:, :-1])
    dy = (rgb[1:]-rgb[:-1])-(target[1:]-target[:-1])
    mx = mask[:, 1:] & mask[:, :-1]; my = mask[1:] & mask[:-1]
    total = dx.abs().mean(-1)[mx].sum()+dy.abs().mean(-1)[my].sum()
    return total/(mx.sum()+my.sum()).clamp_min(1)


@torch.no_grad()
def evaluate_patch(scene, data, targets, output):
    from reconstruction_portrait_pipeline import make_frame, write_json
    output = Path(output); output.mkdir(parents=True, exist_ok=True); rows = {}
    for name in targets['all']:
        frame = make_frame(data, name, crop=False, device=str(scene.portrait.sh.device)); r = scene.render(frame, 'T2')
        with np.load(Path(targets['directory'])/(name+'.npz'), allow_pickle=False) as a:
            mask = torch.as_tensor(a['target'], device=r['rgb'].device)
            old = torch.as_tensor(a['rgb'], device=r['rgb'].device)
            qa = torch.as_tensor(a['skin_q'], device=r['rgb'].device)
        if int(mask.sum()) < 16:
            rows[name] = dict(pixels=int(mask.sum()), status='patch_not_visible'); continue
        err = (r['rgb']-frame['rgb']).abs().mean(-1)
        old_err = (old-frame['rgb']).abs().mean(-1)
        protected = ~mask
        rows[name] = dict(pixels=int(mask.sum()), rgb=float(err[mask].mean()),
            oldRgb=float(old_err[mask].mean()), hole=float((r['q'][..., 1][mask]<.8).float().mean()),
            oldHole=float((qa[mask]<.8).float().mean()), edge=float(_edge_error(r['rgb'], frame['rgb'], mask)),
            oldEdge=float(_edge_error(old, frame['rgb'], mask)),
            protectedMean=float((r['rgb'][protected]-old[protected]).abs().mean()),
            protectedMax=float((r['rgb'][protected]-old[protected]).abs().max()),
            role='development' if name in targets['development'] else 'train')
        ys, xs = torch.where(mask); h, w = mask.shape
        x0, x1 = max(0, int(xs.min())-20), min(w, int(xs.max())+21)
        y0, y1 = max(0, int(ys.min())-20), min(h, int(ys.max())+21)
        images = [frame['rgb'][y0:y1, x0:x1], old[y0:y1, x0:x1], r['rgb'][y0:y1, x0:x1]]
        panel = torch.cat(images, 1).cpu().numpy()
        cv2.imwrite(str(output/(name+'.png')), cv2.cvtColor((panel.clip(0, 1)*255).astype(np.uint8), cv2.COLOR_RGB2BGR))
    write_json(output/'metrics.json', rows)
    return rows


def preservation_gate(rows):
    valid = [r for r in rows.values() if r.get('pixels', 0) >= 16]
    reasons = []
    if not valid:
        reasons.append('no_visible_fixed_patch')
    for name, r in rows.items():
        if r.get('pixels', 0) < 16:
            continue
        if r['hole'] > r['oldHole']+.005: reasons.append(name+':skin_coverage_regression')
        if r['rgb'] > r['oldRgb']+.002: reasons.append(name+':fixed_patch_rgb_regression')
        if r['edge'] > r['oldEdge']+.002: reasons.append(name+':real_edge_regression')
        if r['protectedMean'] > .0005 or r['protectedMax'] > .05:
            reasons.append(name+':outside_patch_changed')
    return dict(passed=not reasons, reasons=reasons, visualApprovalRequired=True,
                releaseApproved=False, developmentNotIndependentFinalTest=True)


def train_capacity(scene, data, plan, targets, output, *, steps=180, capacity=False, rounds=2):
    from reconstruction_portrait_pipeline import make_frame, write_json, surface_contract, ENGINE_VERSION
    if not 24 <= steps <= 240 or rounds not in (1, 2):
        raise ValueError('capacity_finite_budget_required')
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    model = scene.portrait; device = model.sh.device
    baseline = copy.deepcopy(model)
    neck_before = scene.neck_sh_editable.detach().clone() if hasattr(scene, 'neck_sh_editable') else None
    original_other = {k: v.detach().clone() for k, v in scene.named_parameters() if not k.startswith('portrait.')}
    for p in scene.parameters(): p.requires_grad_(False)
    params = {k: getattr(model, k) for k in APPEARANCE}
    for p in params.values(): p.requires_grad_(True)
    optimizer = torch.optim.Adam([dict(params=[params[k]], lr={'sh':.002, 'opacity_logits':.008,
        'log_scales':.0015, 'quats':.0005}[k], name=k) for k in APPEARANCE], eps=1e-8)
    uid = np.arange(len(model.role), dtype=np.int64); parent_uid = np.full(len(uid), -1, np.int64)
    allowed_np = np.zeros(len(uid), bool); allowed_np[plan['selected']] = True
    selected = plan['selected']; events = []; began = time.perf_counter()
    original_model = copy.deepcopy(model.state_dict())
    topology_map = np.arange(len(uid)); shape_map = np.arange(model.surface_count)
    representation_before = representation_metrics(scene, data, targets, selected)
    def checkpoint(label, step):
        torch.save(dict(engineVersion=ENGINE_VERSION, sourceSha256=data['sourceHash'], stage='face-capacity',
            variant='Rcap' if capacity else 'Rctrl', model=scene.state_dict(), optimizer=optimizer.state_dict(),
            surfaceContract=surface_contract(scene, data), step=step, rng=capture_rng(),
            sampler=dict(names=targets['train'], nextStep=step), uid=torch.as_tensor(uid), parentUID=torch.as_tensor(parent_uid),
            allowed=torch.as_tensor(allowed_np), events=copy.deepcopy(events), selection=plan['receipt'],
            resumeKind='new_Adam_same_trained_model; checkpoint_contains_actual_trial_Adam',
            density=dict(kind='finite_explicit_parent_replace_no_automatic_strategy', rounds=len(events))),
            output/('capacity-'+label+'.pt'))
    checkpoint('init', 0)
    if capacity:
        for iteration in range(rounds):
            # Largest-axis changes after a split. A normal-dominated maximum
            # is not blindly split again as if it were tangential detail.
            with torch.no_grad():
                from reconstruction_portrait_model import quaternion_matrix
                _, normals = model.surface(model.reference_mesh)
                R = quaternion_matrix(model.quats[selected])
                axis = model.log_scales[selected].argmax(1)
                v = R[torch.arange(len(selected), device=device), :, axis]
                n = normals[selected]
                safe = torch.linalg.vector_norm(v-(v*n).sum(1)[:, None]*n, dim=1) >= .6
                selected = np.asarray(selected)[safe.cpu().numpy()]
            if not len(selected):
                events.append(dict(round=iteration+1, parentsRetired=0, stop='next_largest_axis_not_tangential'))
                break
            event, mapping, children, uid, parent_uid = replace_patch(scene, data, plan, optimizer, selected, uid, parent_uid)
            shape_map = shape_map[mapping[:model.surface_count]]
            topology_map = topology_map[mapping]
            allowed_np = allowed_np[mapping]; allowed_np[children] = True
            event['round'] = iteration+1; events.append(event)
            selected = children
        checkpoint('replaced', 0)
    params = {k: getattr(model, k) for k in APPEARANCE}
    frozen = {k: p.detach().clone() for k, p in params.items()}
    allowed = torch.as_tensor(allowed_np, device=device)
    curve = []
    for step in range(steps):
        name = targets['train'][step % len(targets['train'])]
        frame = make_frame(data, name, crop=False, device=str(device))
        with np.load(Path(targets['directory'])/(name+'.npz'), allow_pickle=False) as a:
            mask = torch.as_tensor(a['target'], device=device)
            old = torch.as_tensor(a['rgb'], device=device)
            old_q = torch.as_tensor(a['skin_q'], device=device)
        optimizer.zero_grad(set_to_none=True); r = scene.render(frame, 'T2')
        error = (r['rgb']-frame['rgb']).abs().mean(-1)
        rgb = error[mask].mean() if mask.any() else error.sum()*0
        protection = (r['rgb'][~mask]-old[~mask]).abs().mean()
        # Short coverage recovery, not an opacity target or long distillation
        # of the parent's blurry RGB. Both arms use the exact same loss.
        coverage = (old_q[mask]-r['q'][..., 1][mask]).clamp_min(0).square().mean() if mask.any() else rgb*0
        edge = _edge_error(r['rgb'], frame['rgb'], mask)
        sh_prior = (params['sh'][allowed, 1:]-frozen['sh'][allowed, 1:]).square().mean()
        loss = rgb + .25*edge + 2*protection + (.15 if step < 48 else .03)*coverage + .001*sh_prior
        if not torch.isfinite(loss): raise ValueError('capacity_nonfinite_loss')
        loss.backward(); masked_step(optimizer, params, allowed, frozen)
        if step % 30 == 0 or step == steps-1:
            row = dict(step=step+1, imageName=name, rgb=float(rgb.detach()), realSourceEdge=float(edge.detach()),
                protected=float(protection.detach()), coverageRecovery=float(coverage.detach()))
            curve.append(row); print(json.dumps(dict(stage='Rcap' if capacity else 'Rctrl', **row)), flush=True)
        if step+1 == steps//2: checkpoint('mid', step+1)
    # All nonselected appearance values, motion and retained bindings remain
    # bitwise unchanged under explicit old-to-new mapping.
    for key in APPEARANCE:
        assert torch.equal(getattr(model, key)[~allowed], original_model[key][torch.as_tensor(topology_map, device=device)][~allowed]), key
    for key in ('embedding', 'normal_offset'):
        kept = ~allowed[:model.surface_count]
        assert torch.equal(getattr(model, key)[kept], original_model[key][torch.as_tensor(shape_map, device=device)][kept]), key
    for key in ('surface_residual', 'hair_delta', 'hair_base', 'reference_mesh', 'faces'):
        assert torch.equal(model.state_dict()[key], original_model[key]), key
    for key, value in scene.named_parameters():
        if key in original_other: assert torch.equal(value, original_other[key]), key
    checkpoint('final', steps)
    rows = evaluate_patch(scene, data, targets, output/'comparison')
    gate = preservation_gate(rows)
    representation_after = representation_metrics(scene, data, targets, np.flatnonzero(allowed_np))
    if capacity:
        for name, before_rep in representation_before.items():
            after_rep = representation_after.get(name, {})
            if after_rep.get('selectedSkinFraction', 0) < before_rep['selectedSkinFraction']-.05:
                gate['reasons'].append(name+':children_did_not_recover_parent_contribution')
            if before_rep.get('sigmaWeightedMedian') and (after_rep.get('sigmaWeightedMedian') is None
                    or after_rep['sigmaWeightedMedian'] >= before_rep['sigmaWeightedMedian']*.97):
                gate['reasons'].append(name+':capacity_did_not_narrow_effective_footprint')
        gate['passed'] = not gate['reasons']
    report = dict(stage='Rcap' if capacity else 'Rctrl', steps=steps, seconds=time.perf_counter()-began,
        events=events, curve=curve, metrics=rows, gate=gate, selectedInitial=len(plan['selected']),
        selectedFinal=int(allowed.sum()), beforePoints=len(baseline.role), finalPoints=len(model.role),
        allComponentsEveryLossForward=True, nativeFullCanvas=True, poseAndSharedGeometryFrozen=True,
        protectedParametersBitwiseUnchanged=True, noIndependentGeometryClaim=True, newAdam=True,
        pixelBudget=steps, recoveryIncludedInBudget=True,
        controlledDifference='photo_supported_parent_replacement_and_child_initialization' if capacity else 'no_replacement',
        representationBefore=representation_before, representationAfter=representation_after,
        finiteBudgetDoesNotProveSufficientNativeDetail=True,
        estimatedDemandExceedsFourChildren=int(sum(v>4 for v in plan['receipt']['estimatedChildrenFromLocalSpacing'])))
    write_json(output/'training.json', report)
    np.savez_compressed(output/'capacity-lineage.npz', uid=uid, parent_uid=parent_uid,
        original_point=topology_map, selected=allowed_np, source_id=model.source_index.cpu().numpy(),
        triangle_id=model.triangle_ids.cpu().numpy(), bary=model.embedding.detach().cpu().numpy(),
        confidence=model.confidence.cpu().numpy())
    def rollback():
        scene.portrait = baseline
        if neck_before is not None: scene.neck_sh_editable = neck_before
        return dict(restored=True, fullParentModelAndBindings=True, candidateEvidenceRetained=True)
    return report, rollback
