"""Opt-in fresh-prior skin covariance from local surface sampling density.

This is an initialization proposal, not measured skin microgeometry.  It neither
edits trained checkpoints nor changes points, colours, opacity or bindings.
Training observations establish semantic eligibility; held-out RGB is never read.
Coverage below is a local Gaussian overlap proxy, not rasterized alpha evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import math
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation


@dataclass(frozen=True)
class FootprintConfig:
    neighbours: int = 12
    minimum_neighbours: int = 6
    candidate_neighbours: int = 96
    triangle_hops: int = 5
    normal_cosine: float = .90
    tangent_spacing_factor: float = .80
    minimum_scale_ratio: float = .20
    maximum_scale_ratio: float = 1.25
    maximum_anisotropy: float = 3.
    maximum_angular_gap_degrees: float = 200.
    activation_scale_floor: float = .00045
    activation_scale_ceiling: float = .018
    coverage_target: float = .80
    maximum_proxy_drop: float = .15
    coverage_passes: int = 4


def _array(value):
    if hasattr(value, 'detach'):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


def _hash(value):
    a = np.ascontiguousarray(value)
    return hashlib.sha256(str(a.dtype).encode()+str(a.shape).encode()+a.tobytes()).hexdigest()


def _quantiles(value):
    a = np.asarray(value); a = a[np.isfinite(a)]
    return dict(zip(('minimum', 'p10', 'median', 'p90', 'maximum'),
                    np.quantile(a, [0, .1, .5, .9, 1]).tolist())) if len(a) else {}


def _validate(prior, vertices, faces):
    vertices = np.asarray(vertices, np.float64); faces = np.asarray(faces)
    ids = np.asarray(prior['surface_ids']); bary = np.asarray(prior['surface_bary'], np.float64)
    role = np.asarray(prior['role']); n = len(role); s = len(ids)
    if (vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all()
            or faces.ndim != 2 or faces.shape[1] != 3 or faces.dtype.kind not in 'iu'
            or np.any(faces < 0) or np.any(faces >= len(vertices))):
        raise ValueError('footprint_mesh_contract')
    if (ids.shape != (s,) or ids.dtype.kind not in 'iu' or np.any(ids < 0)
            or np.any(ids >= len(faces)) or bary.shape != (s, 3)
            or not np.isfinite(bary).all() or np.any(bary < -1e-6)
            or not np.allclose(bary.sum(1), 1, atol=1e-5, rtol=0)
            or not 0 < s <= n or np.any(role[:s] == 2) or np.any(role[s:] != 2)):
        raise ValueError('footprint_binding_contract')
    for key, shape in [('log_scales', (n, 3)), ('local_quats', (n, 4))]:
        if np.shape(prior[key]) != shape or not np.isfinite(prior[key]).all():
            raise ValueError('footprint_parameter_contract:'+key)
    if np.any(np.linalg.norm(prior['local_quats'], axis=1) < 1e-8):
        raise ValueError('footprint_zero_quaternion')
    if np.shape(prior['opacity_logits']) != (n,) or not np.isfinite(prior['opacity_logits']).all():
        raise ValueError('footprint_opacity_contract')
    return vertices, faces.astype(np.int64), ids.astype(np.int64), bary, role


def _triangle_frames(vertices, faces):
    tri = vertices[faces]; edge = tri[:, 1]-tri[:, 0]; other = tri[:, 2]-tri[:, 0]
    cross = np.cross(edge, other); area2 = np.linalg.norm(cross, axis=1)
    edge_norm = np.linalg.norm(edge, axis=1)
    size2 = np.maximum.reduce(((edge*edge).sum(1), (other*other).sum(1), ((other-edge)**2).sum(1)))
    valid = (size2 > 0) & (area2 > 1e-5*np.maximum(size2, np.finfo(float).tiny))
    normal = cross / np.maximum(area2[:, None], np.finfo(float).tiny)
    tangent = edge / np.maximum(edge_norm[:, None], np.finfo(float).tiny)
    basis = np.stack((tangent, np.cross(normal, tangent), normal), -1)
    return tri, basis, valid


def _adjacency(faces, normals, regions, cosine):
    edges = {}; adjacent = [set() for _ in faces]
    for i, face in enumerate(faces):
        for j in range(3):
            edges.setdefault(tuple(sorted((int(face[j]), int(face[(j+1) % 3])))), []).append(i)
    for entries in edges.values():
        if len(entries) != 2: continue
        a, b = entries
        if regions[a] < 0 or regions[a] != regions[b] or np.dot(normals[a], normals[b]) < cosine: continue
        adjacent[a].add(b); adjacent[b].add(a)
    return adjacent


def _project(points, F, K, shape):
    cam = points@F[:3, :3].T+F[:3, 3]; homogeneous = cam@K.T
    depth = cam[:, 2]; uv = homogeneous[:, :2]/np.maximum(depth[:, None], 1e-12)
    finite = np.isfinite(uv).all(1) & np.isfinite(depth)
    pixel = np.rint(np.nan_to_num(uv)).astype(np.int64)
    h, w = shape
    inside = finite & (depth > .01) & (pixel[:, 0] >= 0) & (pixel[:, 0] < w) & (pixel[:, 1] >= 0) & (pixel[:, 1] < h)
    return pixel[:, 0].clip(0, w-1), pixel[:, 1].clip(0, h-1), depth, inside, cam


def observed_skin_semantics(prior, data, faces, *, minimum_views=3, depth_function=None):
    """Train-only class-3 support at vertices/centre and retained sample points.

    At least two triangle vertices AND its centre must be observed skin.  Hair,
    glasses, unknown or class-5 face detail at any visible probe rejects that
    observation, not every other observation of the physical surface. The
    perspective-correct FLAME depth is only an occlusion proposal/consistency
    guard, explicitly not an independent measured first surface.
    """
    if minimum_views < 3: raise ValueError('footprint_minimum_three_training_views')
    reference = data.get('reference')
    if reference not in data['local'] or data['local'][reference].get('role') != 'train':
        raise ValueError('footprint_reference_must_be_training_observation')
    vertices, faces, ids, bary, role = _validate(prior, data['local'][reference]['mesh'], faces)
    if str(np.asarray(prior['source_sha256'])) != str(data['sourceHash']):
        raise ValueError('footprint_source_identity_mismatch')
    if depth_function is None:
        from reconstruction_shared_v2 import mesh_depth
        depth_function = mesh_depth
    tri_support = np.zeros(len(faces), np.int32); point_support = np.zeros(len(ids), np.int32)
    records = []; required = ('training_skin', 'training_face', 'hair_visible', 'glasses_visible', 'unknown_or_occluded')
    for name, row in data['local'].items():
        if row.get('role') != 'train': continue
        labels = data['labels'][name]
        if any(k not in labels for k in required):
            records.append(dict(imageName=name, status='missing_observed_semantics')); continue
        lab = {k: _array(labels[k]).astype(bool) for k in required}
        shape = lab['training_skin'].shape
        if len(shape) != 2 or any(v.shape != shape for v in lab.values()):
            raise ValueError('footprint_semantic_canvas_mismatch:'+name)
        mesh = _array(row['mesh']).astype(np.float64); F = _array(row['F']).astype(np.float64); K = _array(data['K']).astype(np.float64)
        if mesh.shape != vertices.shape or F.shape != (4, 4) or K.shape != (3, 3) or not np.isfinite(F).all() or not np.isfinite(K).all():
            raise ValueError('footprint_observation_geometry_contract:'+name)
        tri, basis, valid_tri = _triangle_frames(mesh, faces)
        probes = np.concatenate((tri, tri.mean(1)[:, None]), 1)
        samples = (tri[ids]*bary[:, :, None]).sum(1)
        points = np.concatenate((probes.reshape(-1, 3), samples))
        x, y, z, inside, cam = _project(points, F, K, shape)
        depth = np.asarray(depth_function((mesh, faces), F, K, shape[1], shape[0]))
        if depth.shape != shape: raise ValueError('footprint_depth_canvas_mismatch')
        # Native pixel-derived tolerance avoids a hard-coded face/video length.
        tolerance = 2*z/max(abs(K[0, 0]), abs(K[1, 1]), 1.)
        visible = inside & np.isfinite(depth[y, x]) & (z <= depth[y, x]+tolerance)
        normal_camera = basis[:, :, 2]@F[:3, :3].T
        centers = tri.mean(1)@F[:3, :3].T+F[:3, 3]
        front = valid_tri & ((normal_camera*(-centers)).sum(1) > 0)
        front_all = np.concatenate((np.repeat(front, 4), front[ids]))
        visible &= front_all
        rejected = (lab['hair_visible'] | lab['glasses_visible'] | lab['unknown_or_occluded']
                    | (lab['training_face'] & ~lab['training_skin']))
        skin = visible & lab['training_skin'][y, x] & ~rejected[y, x]
        probe_skin = skin[:len(faces)*4].reshape(-1, 4)
        probe_conflict = (visible & rejected[y, x])[:len(faces)*4].reshape(-1, 4).any(1)
        supported = probe_skin[:, 3] & (probe_skin[:, :3].sum(1) >= 2) & ~probe_conflict
        tri_support += supported; point_support += skin[len(faces)*4:]
        records.append(dict(imageName=name, status='training_semantics_evaluated',
            supportedTriangles=int(supported.sum()), supportedPoints=int(skin[len(faces)*4:].sum()),
            semanticsSha256=_hash(np.stack([lab[k] for k in required])), FHash=_hash(F), KHash=_hash(K)))
    _, basis, valid = _triangle_frames(vertices, faces)
    seed_regions = np.where((tri_support >= minimum_views) & valid, 0, -1)
    adjacency = _adjacency(faces, basis[:, :, 2], seed_regions, .90)
    regions = np.full(len(faces), -1, np.int32); component = 0
    for seed in np.flatnonzero(seed_regions >= 0):
        if regions[seed] >= 0: continue
        regions[seed] = component; stack = [int(seed)]
        while stack:
            for other in adjacency[stack.pop()]:
                if regions[other] < 0: regions[other] = component; stack.append(other)
        component += 1
    eligible = np.zeros(len(role), bool)
    eligible[:len(ids)] = (role[:len(ids)] == 0) & (point_support >= minimum_views) & (regions[ids] >= 0)
    return dict(triangle_regions=regions, point_eligible=eligible, triangle_support=tri_support,
        point_support=point_support, receipt=dict(method='train_observed_skin_probe_support_and_mesh_visibility',
        sourceSha256=str(data['sourceHash']), reference=reference, minimumViews=minimum_views,
        triangleCount=len(faces), eligibleTriangles=int((regions >= 0).sum()), eligiblePoints=int(eligible.sum()),
        componentCount=component, views=records, heldoutImagesRead=False, coloursRead=False,
        visibilityMeaning='FLAME prior z-buffer proposal, not measured first-surface truth',
        triangleRegionSha256=_hash(regions), pointEligibilitySha256=_hash(eligible)))


def _covariance(scales, quats):
    matrix = Rotation.from_quat(np.asarray(quats)[:, [1, 2, 3, 0]]).as_matrix()
    return (matrix*np.asarray(scales)[:, None, :]**2)@matrix.transpose(0, 2, 1)


def _overlap(probes, positions, covariances, opacity):
    delta = probes[:, None]-positions[None]
    inverse = np.linalg.inv(covariances)
    squared = np.einsum('pni,nij,pnj->pn', delta, inverse, delta)
    alpha = np.clip(opacity[None]*np.exp(-.5*np.maximum(squared, 0)), 0, 1-1e-9)
    return 1-np.exp(np.log1p(-alpha).sum(1))


def _check_config(c):
    if (not 6 <= c.minimum_neighbours <= c.neighbours <= 32
            or not c.neighbours < c.candidate_neighbours <= 256 or not 1 <= c.triangle_hops <= 10
            or not .7 <= c.normal_cosine < 1 or not .3 <= c.tangent_spacing_factor <= 1.5
            or not 0 < c.minimum_scale_ratio <= 1 <= c.maximum_scale_ratio <= 2
            or not 1 <= c.maximum_anisotropy <= 5 or not 180 < c.maximum_angular_gap_degrees < 300
            or not 0 < c.activation_scale_floor < c.activation_scale_ceiling
            or not 0 < c.coverage_target < 1 or not 0 < c.maximum_proxy_drop < .5
            or not 1 <= c.coverage_passes <= 8):
        raise ValueError('footprint_invalid_bounds')


def adapt_surface_footprints(prior, reference_mesh, faces, *, triangle_regions, point_eligible,
                             prior_stage, config=None, semantic_receipt=None):
    """Return (copied_prior, receipt, pointwise_diagnostics), without mutation.

    The required ``prior_stage`` makes this unsuitable for an implicit checkpoint
    warm-start.  The caller records its actual initialization file SHA as well.
    Point eligibility and same-region mesh connectivity are both mandatory.
    Normal variance n^T Sigma n is preserved; only tangent sampling is adapted.
    """
    if prior_stage != 'fresh_initialization': raise ValueError('footprint_only_fresh_initialization')
    c = config or FootprintConfig(); _check_config(c)
    vertices, faces, ids, bary, role = _validate(prior, reference_mesh, faces)
    n = len(role); s = len(ids); regions = np.asarray(triangle_regions); eligible = np.asarray(point_eligible)
    if regions.shape != (len(faces),) or regions.dtype.kind not in 'iu' or eligible.shape != (n,) or eligible.dtype != bool:
        raise ValueError('footprint_explicit_semantic_contract')
    tri, frame, valid_tri = _triangle_frames(vertices, faces)
    points = (tri[ids]*bary[:, :, None]).sum(1); normals = frame[ids, :, 2]
    # Fresh imports normally have zero offset. Use actual retained positions if
    # a prior already includes a bounded initial displacement; never reset it.
    if 'local_offsets' in prior:
        offsets = np.asarray(prior['local_offsets'])
        if offsets.shape != (n, 3) or not np.isfinite(offsets).all(): raise ValueError('footprint_offset_contract')
        points += normals*(np.tanh(offsets[:s, 0])*np.where(role[:s] == 0, .006, .012))[:, None]
    old_scales = np.exp(np.asarray(prior['log_scales'], np.float64))
    old_cov = _covariance(old_scales[:s], prior['local_quats'][:s]); cov = old_cov.copy()
    reasons = np.full(n, 'ineligible_semantics', dtype='<U48'); reasons[role != 0] = 'protected_non_skin_role'
    reasons[:s][eligible[:s] & (role[:s] == 0) & ~valid_tri[ids]] = 'degenerate_surface'
    range_ok = (old_scales[:s].min(1) >= c.activation_scale_floor) & (old_scales[:s].max(1) <= c.activation_scale_ceiling)
    reasons[:s][eligible[:s] & (role[:s] == 0) & ~range_ok] = 'input_activation_range_fallback'
    good = eligible[:s] & (role[:s] == 0) & (regions[ids] >= 0) & valid_tri[ids]
    good &= range_ok
    adjacency = _adjacency(faces, frame[:, :, 2], np.where(valid_tri, regions, -1), c.normal_cosine)
    reached = {}
    for t in np.unique(ids[good]):
        visited = {int(t)}; frontier = set(visited)
        for _ in range(c.triangle_hops):
            frontier = {a for b in frontier for a in adjacency[b]}-visited; visited |= frontier
        reached[int(t)] = visited
    candidates = np.flatnonzero(good); neighbourhoods = {}; proposed = np.zeros(n, bool)
    nn = np.full(n, np.nan); density_spacing = nn.copy(); tangent_old = np.full((n, 2), np.nan)
    tangent_new = tangent_old.copy(); normal_sigma = nn.copy(); neighbour_count = np.zeros(n, np.int32)
    if len(candidates) > c.minimum_neighbours:
        tree = cKDTree(points[candidates]); distances, near = tree.query(points[candidates], k=min(c.candidate_neighbours, len(candidates)))
        for row, point in enumerate(candidates):
            reasons[point] = 'insufficient_connected_neighbours'; t = int(ids[point]); B = frame[t, :, :2]; normal = normals[point]
            available = candidates[np.atleast_1d(near[row])]
            compatible = (available != point) & np.asarray([int(ids[j]) in reached[t] for j in available])
            compatible &= (normals[available]@normal >= c.normal_cosine)
            available = available[compatible]
            displacement = points[available]-points[point]; local = displacement@B
            radius = np.linalg.norm(local, axis=1)
            keep = radius > max(np.linalg.norm(np.ptp(vertices, axis=0))*1e-9, 1e-14)
            available, local, radius = available[keep][:c.neighbours], local[keep][:c.neighbours], radius[keep][:c.neighbours]
            if len(available) < c.minimum_neighbours: continue
            neighbour_count[point] = len(available); nn[point] = radius.min()
            angle = np.sort(np.arctan2(local[:, 1], local[:, 0])); gap = np.diff(np.r_[angle, angle[0]+2*np.pi]).max()
            if gap > math.radians(c.maximum_angular_gap_degrees): reasons[point] = 'one_sided_boundary_neighbourhood'; continue
            weights = np.minimum(1., (np.median(radius)/radius)**2)
            moment = np.einsum('n,ni,nj->ij', weights, local, local)/weights.sum()
            value, axes = np.linalg.eigh(moment)
            if value[0] <= 0 or math.sqrt(value[1]/value[0]) > c.maximum_anisotropy:
                reasons[point] = 'degenerate_or_line_neighbourhood'; continue
            # k/(pi*r_k²) estimates retained sample density. Second moment only
            # determines anisotropic shape, not an unnormalised k-dependent size.
            spacing = math.sqrt(math.pi*radius.max()**2/len(radius)); density_spacing[point] = spacing
            target = (c.tangent_spacing_factor*spacing)**2*value/math.sqrt(value.prod())
            tangent = (axes*target)@axes.T; old_tangent = B.T@old_cov[point]@B
            old_values = np.linalg.eigvalsh(old_tangent); normal_var = float(normal@old_cov[point]@normal)
            old_sigma, new_sigma = np.sqrt(old_values), np.sqrt(target)
            tangent_old[point] = old_sigma; normal_sigma[point] = math.sqrt(normal_var)
            ratio = new_sigma/old_sigma
            if (ratio < c.minimum_scale_ratio).any() or (ratio > c.maximum_scale_ratio).any():
                reasons[point] = 'bounded_scale_ratio_fallback'; continue
            candidate_cov = B@tangent@B.T+normal_var*np.outer(normal, normal)
            eigen = np.linalg.eigvalsh(candidate_cov)
            if eigen.min() < c.activation_scale_floor**2 or eigen.max() > c.activation_scale_ceiling**2:
                reasons[point] = 'activation_range_fallback'; continue
            cov[point] = candidate_cov; tangent_new[point] = new_sigma; proposed[point] = True
            reasons[point] = 'proposed'; neighbourhoods[point] = np.r_[point, available]
    opacity = 1/(1+np.exp(-np.clip(np.asarray(prior['opacity_logits'], np.float64)[:s], -700, 700)))
    before = np.full(n, np.nan); after = before.copy(); changed = proposed.copy()
    probes = {}
    for point, neighbours in neighbourhoods.items():
        # Centre plus actual same-surface half-way gaps. No screen-space fill.
        probes[point] = np.concatenate((points[point:point+1], (points[point]+points[neighbours[1:7]])*.5))
        before[point] = _overlap(probes[point], points[neighbours], old_cov[neighbours], opacity[neighbours]).min()
    for _ in range(c.coverage_passes):
        rejected = []
        for point in np.flatnonzero(changed):
            neighbours = neighbourhoods[int(point)]
            after[point] = _overlap(probes[int(point)], points[neighbours], cov[neighbours], opacity[neighbours]).min()
            required = min(c.coverage_target, max(0., before[point]-c.maximum_proxy_drop))
            if after[point] < required: rejected.append(point)
        if not rejected: break
        changed[rejected] = False; cov[rejected] = old_cov[rejected]; reasons[rejected] = 'local_overlap_proxy_fallback'
    # Re-evaluate after all neighbour fallbacks; never report a stale proxy.
    unstable = []
    for point in neighbourhoods:
        near = neighbourhoods[point]
        after[point] = _overlap(probes[point], points[near], cov[near], opacity[near]).min()
        if changed[point] and after[point] < min(c.coverage_target, max(0., before[point]-c.maximum_proxy_drop)):
            unstable.append(point)
    if unstable:
        # The bounded diagnostic did not converge; keep this input prior, not a
        # partly checked skin surface. No unbounded threshold search follows.
        reasons[changed] = 'proxy_transaction_not_stable'; changed[:] = False; cov[:] = old_cov
        for point in neighbourhoods: after[point] = before[point]
    output = {k: np.array(v, copy=True) for k, v in prior.items()}
    for point in np.flatnonzero(changed):
        values, matrix = np.linalg.eigh(cov[point])
        if np.linalg.det(matrix) < 0: matrix[:, 0] *= -1
        q = Rotation.from_matrix(matrix).as_quat()[[3, 0, 1, 2]]
        if np.dot(q, output['local_quats'][point]) < 0: q = -q
        output['local_quats'][point] = q; output['log_scales'][point] = np.log(np.sqrt(values)); reasons[point] = 'adapted'
    for key in prior:
        if key not in ('log_scales', 'local_quats') and not np.array_equal(output[key], prior[key]):
            raise AssertionError('footprint_changed_protected_field:'+key)
    if (not np.array_equal(output['log_scales'][~changed], prior['log_scales'][~changed])
            or not np.array_equal(output['local_quats'][~changed], prior['local_quats'][~changed])):
        raise AssertionError('footprint_changed_protected_rows')
    receipt = dict(method='connected_observed_skin_sampling_covariance', priorStage=prior_stage,
        sourceSha256=str(np.asarray(prior.get('source_sha256', ''))), pointCount=n, surfaceCount=s,
        eligibleCount=int(good.sum()), proposedCount=int(proposed.sum()), changedCount=int(changed.sum()),
        reasons={str(key): int(np.count_nonzero(reasons == key)) for key in np.unique(reasons)},
        config=asdict(c), semantics=semantic_receipt, neighbourSpacing=_quantiles(nn[changed]),
        densitySpacing=_quantiles(density_spacing[changed]), tangentSigmaBefore=_quantiles(tangent_old[changed]),
        tangentSigmaAfter=_quantiles(tangent_new[changed]), normalSigmaPreserved=_quantiles(normal_sigma[changed]),
        minimumLocalProxyBefore=_quantiles(before[changed]), minimumLocalProxyAfter=_quantiles(after[changed]),
        inputHashes={k: _hash(v) for k, v in prior.items()},
        outputHashes={k: _hash(v) for k, v in output.items()},
        pointCountBindingsAppearanceOpacityUnchanged=True, normalVariancePreserved=True,
        proxyIsActualRasterCoverage=False, coverageMeaning='compatible local Gaussian overlap at samples/midpoints; full-render validation required',
        geometryTruthClaimed=False, trainedCheckpointSupported=False, acceptedQuality=False)
    diagnostics = dict(changed=changed, proposed=proposed, reason=reasons, nearest_spacing=nn,
        density_spacing=density_spacing, neighbour_count=neighbour_count, old_tangent_sigma=tangent_old,
        proposed_tangent_sigma=tangent_new, preserved_normal_sigma=normal_sigma,
        local_proxy_before=before, local_proxy_after=after, triangle_id=ids.copy(),
        old_log_scales=np.array(prior['log_scales'], copy=True), new_log_scales=output['log_scales'].copy(),
        old_quats=np.array(prior['local_quats'], copy=True), new_quats=output['local_quats'].copy())
    neighbour_ids = np.full((n, c.neighbours+1), -1, np.int64)
    for point, neighbours in neighbourhoods.items(): neighbour_ids[point, :len(neighbours)] = neighbours
    diagnostics['neighbour_indices'] = neighbour_ids
    return output, receipt, diagnostics


def adapt_observed_surface_footprints(prior, data, faces, *, prior_stage, config=None, depth_function=None):
    semantic = observed_skin_semantics(prior, data, faces, depth_function=depth_function)
    output, receipt, diagnostics = adapt_surface_footprints(prior, data['local'][data['reference']]['mesh'], faces,
        triangle_regions=semantic['triangle_regions'], point_eligible=semantic['point_eligible'],
        prior_stage=prior_stage, config=config, semantic_receipt=semantic['receipt'])
    diagnostics.update(triangle_support=semantic['triangle_support'], point_support=semantic['point_support'],
        triangle_regions=semantic['triangle_regions'], semantic_eligible=semantic['point_eligible'])
    # Full native pinhole covariance is a footprint diagnostic, not gsplat's
    # finite radii, visibility, sorting or a measured image PSF.
    mesh = _array(data['local'][data['reference']]['mesh']); s = len(prior['surface_ids'])
    xyz = (mesh[np.asarray(faces)[prior['surface_ids']]]*prior['surface_bary'][:, :, None]).sum(1)
    F = _array(data['local'][data['reference']]['F']); K = _array(data['K'])
    cam = xyz@F[:3, :3].T+F[:3, 3]; projected = cam@K.T
    valid = projected[:, 2] > .01
    J = (K[None, :2, :]*projected[:, None, 2:3]-projected[:, :2, None]*K[None, 2:3, :])/np.maximum(projected[:, 2:3, None]**2, 1e-12)
    for name, value in [('before', prior), ('after', output)]:
        cov = _covariance(np.exp(value['log_scales'][:s]), value['local_quats'][:s])
        camera_cov = F[:3, :3]@cov@F[:3, :3].T
        projected_cov = J@camera_cov@J.transpose(0, 2, 1)
        sigma = np.sqrt(np.maximum(np.linalg.eigvalsh(projected_cov), 0)); sigma[~valid] = np.nan
        diagnostics['native_sigma_'+name] = sigma
        receipt['nativeSigma'+name.title()] = _quantiles(sigma[diagnostics['changed'][:s]])
    receipt['nativeFootprintMeaning'] = 'reference full-canvas first-order covariance sigma; not PSF, radii or visibility'
    return output, receipt, diagnostics
