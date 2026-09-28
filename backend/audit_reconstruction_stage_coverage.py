"""Stage 0 only: immutable-parameter, zero-training coverage cross replay.

S is a z-buffered prepared-surface hypothesis, not geometry truth. U uses
installed gsplat conics, compensated opacity and actual tile intersections.
A and RGB always come from the unchanged production-research forward.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack, contextmanager
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import time
from unittest.mock import patch

import cv2
import numpy as np
import torch
from gsplat.cuda._wrapper import rasterize_to_pixels
from gsplat.strategy import DefaultStrategy

from flame_open_model import FlameOpen, MODEL
from probe_gs_contract import read_float_ply
from reconstruction_components_v3 import FreeComponent
from reconstruction_portrait_model import GaussianState, joined_state
from reconstruction_portrait_pipeline import draw, make_frame
from reconstruction_shared_v2 import initialize, posed

ANCHOR = '27c9810bf0746d8e4382eb218e89276954767d7d'
ALPHA_THRESHOLD = 1.0 / 255.0  # Verified against installed gsplat 1.5.3.
FIELDS = tuple(GaussianState.__dataclass_fields__)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def json_write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                   allow_nan=False), encoding='utf-8')


def subset(state, selection):
    return GaussianState(**{k: getattr(state, k)[selection].detach() for k in FIELDS})


def state_hash(state):
    h = hashlib.sha256()
    for key in FIELDS:
        h.update(key.encode()); h.update(getattr(state, key).detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


@contextmanager
def zero_training():
    def prohibited(*args, **kwargs):
        raise AssertionError('stage0_forbids_optimizer_backward_and_density')
    with ExitStack() as stack:
        for obj, name in [(torch.optim, 'Adam'), (torch.Tensor, 'backward'),
                          (torch.autograd, 'backward'), (torch.autograd, 'grad'),
                          (DefaultStrategy, '__init__')]:
            stack.enter_context(patch.object(obj, name, prohibited))
        stack.enter_context(torch.no_grad())
        yield


class Inputs:
    """Hash every read input; no write method and no implicit cache mutation."""
    def __init__(self):
        self.records = {}

    def touch(self, path):
        path = Path(path).resolve()
        if str(path) not in self.records:
            self.records[str(path)] = {'sha256': sha(path), 'bytes': path.stat().st_size}
        return path

    def npz(self, path):
        with np.load(self.touch(path), allow_pickle=False) as z:
            return {key: z[key] for key in z.files}

    def js(self, path):
        return json.loads(self.touch(path).read_text(encoding='utf-8-sig'))

    def verify(self):
        changed = [path for path, value in self.records.items()
                   if sha(path) != value['sha256']]
        if changed:
            raise RuntimeError('audit_input_changed:' + repr(changed))


class LazyPixels:
    def __init__(self, root, labels, inputs):
        self.root, self.labels, self.inputs = root, labels, inputs

    def __getitem__(self, name):
        path = self.root / (name + '.npz' if self.labels else name)
        if self.labels:
            return self.inputs.npz(path)
        image = cv2.imread(str(self.inputs.touch(path)))
        if image is None:
            raise ValueError('missing_recorded_image:' + name)
        return cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0


def freeze_contract(backend, run, prepared, inputs):
    root = backend.parent
    git = ['git', '-c', 'safe.directory=' + str(root), '-C', str(root)]
    pointer = root / '.git'
    if pointer.is_file():
        location = pointer.read_text().strip().removeprefix('gitdir: ')
        if len(location) > 2 and location[1] == ':' and str(root).startswith('/mnt/'):
            location = '/mnt/' + location[0].lower() + location[2:].replace('\\', '/')
            git = ['git', '--git-dir=' + location, '--work-tree=' + str(root)]

    head = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
    if subprocess.run(git + ['merge-base', '--is-ancestor', ANCHOR, head], capture_output=True).returncode:
        raise ValueError('audit_requires_anchor_ancestry:' + head)
    reused = ['flame_open_model.py', 'probe_gs_contract.py', 'reconstruction_shared_v2.py',
              'reconstruction_components_v3.py', 'reconstruction_portrait_model.py',
              'reconstruction_portrait_pipeline.py', 'appearance_direction_contract.py',
              'probe_flame_real_appearance.py', 'probe_flame_observations.py']
    for name in reused:
        source = inputs.touch(backend / name).read_bytes().replace(b'\r\n', b'\n')
        blob = subprocess.check_output(git + ['show', ANCHOR + ':backend/' + name])
        if source != blob.replace(b'\r\n', b'\n'):
            raise ValueError('unreviewed_reused_source:' + name)
    config = inputs.js(run / 'config.json')
    for name, expected in config['sourceFiles'].items():
        if sha(inputs.touch(run / 'algorithm-source' / name)) != expected:
            raise ValueError('runtime_snapshot_changed:' + name)
    old = inputs.touch(prepared / 'algorithm-snapshot/reconstruction_shared_v2.py')
    def function(source, name):
        tree = ast.parse(source.read_text())
        return ast.dump(next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                             and n.name == name), include_attributes=False)
    for name in ['initialize', 'posed', 'make_frame']:
        if function(old, name) != function(backend / 'reconstruction_shared_v2.py', name):
            raise ValueError('historical_function_not_exact:' + name)
    if importlib.metadata.version('gsplat') != '1.5.3':
        raise ValueError('only_audited_gsplat_1_5_3_supported')
    import gsplat
    gsroot = Path(gsplat.__file__).parent
    for relative in ['rendering.py', 'cuda/_wrapper.py', 'cuda/include/Common.h',
                     'cuda/csrc/RasterizeToPixels3DGSFwd.cu', 'cuda/csrc/ProjectionEWA3DGSFused.cu']:
        inputs.touch(gsroot / relative)
    if '#define ALPHA_THRESHOLD (1.f / 255.f)' not in (gsroot / 'cuda/include/Common.h').read_text():
        raise ValueError('kernel_alpha_threshold_changed')
    current = ast.parse((backend / 'reconstruction_components_v3.py').read_text())
    recorded = ast.parse((run / 'algorithm-source/reconstruction_components_v3.py').read_text())
    select = lambda tree: ast.dump(next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FreeComponent'), include_attributes=False)
    if select(current) != select(recorded):
        raise ValueError('component_state_semantics_changed')
    return config


def load_data(prepared, inputs):
    meta = inputs.js(prepared / 'preparation.json')
    original_backend = prepared.parent.parent
    def resolve(value):
        path = Path(value)
        return path if path.is_absolute() else original_backend / path
    source = resolve(meta['source']); prior_path = resolve(meta['appearance'])
    for path, expected in [(source / 'capture.mp4', meta['sourceHash']),
                           (prior_path, meta['appearanceHash']), (MODEL, meta['modelHash'])]:
        if sha(inputs.touch(path)) != expected:
            raise ValueError('input_hash_mismatch:' + str(path))
    from flame_open_model import EMBEDDING
    inputs.touch(EMBEDDING)
    raw = inputs.npz(prepared / 'local_geometry.npz')
    names = raw['names'].tolist(); worlds = raw['world_names'].tolist()
    if len(set(names)) != len(names) or len(set(worlds)) != len(worlds):
        raise ValueError('duplicate_observation_name')
    local = {name: {'mesh': raw['meshes'][i], 'F': raw['F'][i],
                    'marks': raw['marks'][i], 'role': str(raw['roles'][i])}
             for i, name in enumerate(names)}
    return {**meta, 'source': source, 'prior': inputs.npz(prior_path),
            'appearance': str(prior_path), 'local': local,
            'worlds': {n: raw['C'][i] for i, n in enumerate(worlds)},
            'rgb': LazyPixels(prepared / 'rectified_observations', False, inputs),
            'labels': LazyPixels(prepared / 'rectified_observations', True, inputs),
            'K': raw['K'], 'scale': float(raw['scale']), 'geometry': FlameOpen(24, 12),
            'room': inputs.npz(prepared / 'static_surface_seeds.npz'),
            'components': {k: inputs.npz(prepared / (k + '_multiview_seeds.npz'))
                           for k in ('hair', 'glasses')}}


def read_asset(ply, sidecar, inputs, device='cuda'):
    table = read_float_ply(inputs.touch(ply)); side = inputs.npz(sidecar)
    if str(side['asset_sha256']) != sha(ply):
        raise ValueError('ply_sidecar_hash_mismatch')
    count = len(table['x'])
    if len(side['component']) != count:
        raise ValueError('ply_component_count_mismatch')
    array = lambda names: np.stack([table[n] for n in names], axis=1)
    rest = array(['f_rest_' + str(i) for i in range(45)]).reshape(count, 3, 15).transpose(0, 2, 1)
    if np.any(rest[:, 3:] != 0):
        raise ValueError('unexpected_SH_above_degree_one')
    tensor = lambda x: torch.from_numpy(np.ascontiguousarray(x)).to(device)
    state = GaussianState(tensor(array(['x', 'y', 'z'])),
                          tensor(array(['rot_' + str(i) for i in range(4)])),
                          tensor(array(['scale_' + str(i) for i in range(3)])).exp(),
                          tensor(table['opacity']).sigmoid(),
                          tensor(np.concatenate((array(['f_dc_' + str(i) for i in range(3)])[:, None], rest[:, :3]), axis=1)),
                          tensor(side['component']).long())
    return state, side


def recover_states(data, run, prepared, out, inputs):
    scratch = out / 'recovered-initialization'; scratch.mkdir()
    shutil.copyfile(inputs.touch(prepared / 'cloth_supported_seeds.npz'), scratch / 'cloth_supported_seeds.npz')
    params, source_ids = initialize(data, scratch, 'cuda')
    for value in params.values():
        value.requires_grad_(False)
    room_mask = params['part'][:, 0].long() == 0
    initial = GaussianState(params['means'][room_mask], params['quats'][room_mask],
                            params['scales'][room_mask].exp(), params['opacities'][room_mask].sigmoid(),
                            params['sh'][room_mask], params['part'][room_mask, 0].long())
    ck = torch.load(inputs.touch(run / 'C-static.pt'), map_location='cuda', weights_only=True)
    component = FreeComponent(initial, source_ids['id'][room_mask.cpu().numpy()],
                              params['support'][room_mask, 0], 'world-static', .01 * data['scale'])
    component.load_state_dict(ck['room'])
    for parameter in component.parameters():
        parameter.requires_grad_(False)
    if not torch.equal(initial.means, component.base) or not torch.allclose(initial.scales, component.initial_scales, atol=1e-7, rtol=1e-6):
        raise ValueError('recovered_initial_state_disagrees_with_checkpoint')
    final = component.state()
    old = {k: torch.from_numpy(v).to('cuda') for k, v in inputs.npz(prepared / 'trained_parameters.npz').items()}
    means, quats, scales, sh, parts = posed(old, data, data['reference'])
    old_state = GaussianState(means, torch.nn.functional.normalize(quats, dim=-1), scales,
                              old['opacities'].sigmoid(), sh, parts)
    old_room = subset(old_state, parts == 0)
    v3_asset, _ = read_asset(run / 'portrait.gaussian.ply', run / 'portrait.components.npz', inputs)
    v2_asset, v2_side = read_asset(prepared / 'portrait.gaussian.ply', prepared / 'portrait.components.npz', inputs)
    for directory in (run, prepared):
        view = inputs.js(directory / 'portrait.view.json')
        if view['sourceFrame'] != data['reference']:
            raise ValueError('reference_frame_mismatch')
    states = {'v3_initial': initial, 'v3_360': final, 'v3_ply': subset(v3_asset, v3_asset.parts == 0),
              'v2_final': old_room, 'v2_ply': subset(v2_asset, v2_asset.parts == 0)}
    init_scales = {'v3_initial': initial.scales, 'v3_360': component.initial_scales,
                   'v3_ply': component.initial_scales,
                   'v2_final': old['initial_scales'][parts == 0].exp(),
                   'v2_ply': torch.from_numpy(v2_side['initial_scales'][v2_side['component'] == 0]).to('cuda').exp()}
    fixed_person = subset(v3_asset, v3_asset.parts != 0)
    return states, init_scales, fixed_person, v2_asset


def support_surface(seed, C, K, width, height, near):
    """Z-buffer the recorded triangle hypotheses; never claim measured truth."""
    measured = {int(i): p for i, p, k in zip(seed['source_id'], seed['xyz'], seed['source_kind']) if k == 0}
    tri_ids = np.unique(np.sort(seed['triangle_sources'][seed['source_kind'] == 1], axis=1), axis=0)
    triangles = np.array([[measured[int(i)] for i in ids] for ids in tri_ids], np.float64)
    depth = np.full((height, width), np.inf, np.float32)
    winner = np.full((height, width), -1, np.int32)
    rejected = 0
    for index, triangle in enumerate(triangles):
        camera = triangle @ C[:3, :3].T + C[:3, 3]
        if np.all(camera[:, 2] <= near):
            continue
        if np.any(camera[:, 2] <= near):
            raise ValueError('support_triangle_crosses_near_plane_requires_explicit_clipping')
        uvw = camera @ K.T; uv = uvw[:, :2] / uvw[:, 2:]
        x0, y0 = np.maximum(np.floor(uv.min(0) - .5).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(uv.max(0) - .5).astype(int) + 1, [width, height])
        if x0 >= x1 or y0 >= y1:
            continue
        a, b, c = uv
        denominator = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(denominator) < 1e-10:
            rejected += 1; continue
        yy, xx = np.mgrid[y0:y1, x0:x1]; xx = xx+.5; yy = yy+.5
        w0 = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/denominator
        w1 = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/denominator
        w2 = 1-w0-w1
        inside = (w0 >= -1e-8) & (w1 >= -1e-8) & (w2 >= -1e-8)
        inverse_z = w0/camera[0, 2]+w1/camera[1, 2]+w2/camera[2, 2]
        z = np.divide(1., inverse_z, out=np.full_like(inverse_z, np.inf), where=inverse_z > 0)
        old = depth[y0:y1, x0:x1]; take = inside & (z < old)
        old[take] = z[take]; winner[y0:y1, x0:x1][take] = index
    return {'depth': depth, 'triangle': winner, 'S_raw': np.isfinite(depth)}, {
        'uniqueTriangleHypotheses': len(triangles), 'degenerateProjectedTriangles': rejected,
        'notGroundTruth': True, 'visibility': 'nearest recorded room triangle plus observed foreground exclusion'}


def effective_footprints(info, width, height):
    """Same tile lists, conics, pixel centres and alpha cutoff as CUDA forward.

    U is eligibility BEFORE transmittance/occlusion. A remains the actual draw.
    Sum optical depth is only a forward-contract diagnostic, not replacement A.
    """
    offsets = info['isect_offsets'].reshape(-1).long()
    ids = info['flatten_ids'].long(); device = ids.device
    end = torch.cat((offsets[1:], offsets.new_tensor([len(ids)])))
    tile_ids = torch.repeat_interleave(torch.arange(len(offsets), device=device), end-offsets)
    tile = int(info['tile_size']); columns = int(info['tile_width'])
    yy, xx = torch.meshgrid(torch.arange(tile, device=device), torch.arange(tile, device=device), indexing='ij')
    xx = xx.flatten()[None]; yy = yy.flatten()[None]
    counts = torch.zeros(width*height, dtype=torch.int32, device=device)
    tau = torch.zeros(width*height, dtype=torch.float32, device=device)
    for start in range(0, len(ids), 1024):
        row = ids[start:start+1024]; tid = tile_ids[start:start+1024]
        x = (tid % columns)[:, None]*tile+xx; y = (tid//columns)[:, None]*tile+yy
        valid = (x < width) & (y < height)
        delta_x = info['means2d'][row, 0:1]-x-.5
        delta_y = info['means2d'][row, 1:2]-y-.5
        conic = info['conics'][row]
        sigma = .5*(conic[:, 0:1]*delta_x.square()+conic[:, 2:3]*delta_y.square())+conic[:, 1:2]*delta_x*delta_y
        a = (info['opacities'][row, None]*torch.exp(-sigma)).clamp(max=.999)
        valid &= (sigma >= 0) & (a >= ALPHA_THRESHOLD)
        pixel = (y*width+x)[valid].long(); a = a[valid]
        counts.scatter_add_(0, pixel, torch.ones_like(pixel, dtype=torch.int32))
        tau.scatter_add_(0, pixel, -torch.log1p(-a))
    counts = counts.reshape(height, width); tau = tau.reshape(height, width)
    return {'U': counts > 0, 'overlap': counts, 'optical_depth': tau,
            'all_eligible_alpha': -torch.expm1(-tau)}


def termination_check(info, alpha, all_alpha):
    """Audit worst pixels against the CUDA exclusive early-stop convention."""
    delta = (all_alpha-alpha).abs()
    pixels = torch.topk(delta.flatten(), min(12, delta.numel())).indices
    width = alpha.shape[1]; tile = int(info['tile_size']); cols = int(info['tile_width'])
    offsets = info['isect_offsets'].reshape(-1).long(); flat = info['flatten_ids'].long()
    discrepancies = []
    for pixel in pixels.tolist():
        y, x = divmod(pixel, width); tid = (y//tile)*cols+x//tile
        end = int(offsets[tid+1]) if tid+1 < len(offsets) else len(flat)
        rows = flat[int(offsets[tid]):end]
        d = info['means2d'][rows]-info['means2d'].new_tensor([x+.5,y+.5])
        c = info['conics'][rows]
        sigma=.5*(c[:,0]*d[:,0].square()+c[:,2]*d[:,1].square())+c[:,1]*d[:,0]*d[:,1]
        a=(info['opacities'][rows]*torch.exp(-sigma)).clamp(max=.999)
        a=torch.where((sigma>=0)&(a>=ALPHA_THRESHOLD),a,torch.zeros_like(a))
        T=torch.cumprod(1-a,0); stop=torch.where(T<=1e-4)[0]
        index=int(stop[0])-1 if len(stop) else len(T)-1
        expected=1-float(T[index]) if index>=0 else 0.
        error=abs(expected-float(alpha[y,x])); discrepancies.append(error)
        if error>.0008: raise ValueError('exclusive_termination_mismatch:'+str(error))
    return {'allEligibleVsActualMaxAbs':float(delta.max()),
            'worstPixelExclusiveReplayMaxAbs':max(discrepancies),
            'pixelsCompared':len(discrepancies),
            'note':'all-eligible optical depth includes candidates skipped by exclusive early stop; A is always actual CUDA output'}


def cohort_contribution(info, flags, width, height):
    colors = flags[info['gaussian_ids'].long()].contiguous()
    result, alpha = rasterize_to_pixels(info['means2d'], info['conics'], colors,
        info['opacities'], width, height, int(info['tile_size']), info['isect_offsets'],
        info['flatten_ids'], packed=True, absgrad=False)
    return result[0], alpha[0, :, :, 0]


def cpu(value):
    return value.detach().cpu().numpy() if torch.is_tensor(value) else value


def quantiles(value):
    value = np.asarray(cpu(value)); value = value[np.isfinite(value)]
    return dict(zip(['min', 'p10', 'p50', 'p90', 'p99', 'max'], np.quantile(value, [0, .1, .5, .9, .99, 1]).tolist())) if value.size else None


def state_stats(state, initial_scale):
    maximum = state.scales.max(-1).values
    ratio = (state.scales / initial_scale).max(-1).values
    return {'count': len(state.means), 'hash': state_hash(state),
            'xyzMin': cpu(state.means.min(0).values).tolist(), 'xyzMax': cpu(state.means.max(0).values).tolist(),
            'scale': quantiles(state.scales), 'maxAxis': quantiles(maximum), 'opacity': quantiles(state.opacity),
            'scaleRatio': quantiles(ratio), 'over2x': int((ratio > 2).sum()), 'over5x': int((ratio > 5).sum())}


def analyze(S, U, A, q_room, rgb, target, mask, cohort=None):
    S, U, A, q_room, rgb, target, mask = map(cpu, [S, U, A, q_room, rgb, target, mask])
    mask = mask.astype(bool); error = np.abs(rgb-target).mean(-1)
    def mean(x, m=mask):
        return float(np.asarray(x)[m].mean()) if m.any() else None
    strata = {'noS': ~S, 'S_noU': S & ~U, 'S_U_lowA': S & U & (A < .8),
              'S_U_highA_badRgb': S & U & (A >= .8) & (error > .1),
              'S_U_highA_lowRgbError': S & U & (A >= .8) & (error <= .1)}
    result = {'pixels': int(mask.sum()), 'S': mean(S), 'U': mean(U), 'meanAlpha': mean(A),
              'alphaAbove': {str(t): mean(A > t) for t in [.01, .2, .8]}, 'alphaBelow08': mean(A < .8), 'q_room': mean(q_room), 'rgbL1': mean(error),
              'highAlphaRgbErrorOver01': mean((A >= .8) & (error > .1)),
              'highAlphaRgbErrorOver005': mean((A >= .8) & (error > .05)),
              'exclusiveFractions': {k: mean(v) for k, v in strata.items()},
              'S_U_lowAlphaMean': mean(A, mask & S & U & (A < .8)),
              'rgbOnHighAlpha': mean(error, mask & (A >= .8)),
              'alphaQuantiles': quantiles(A[mask]), 'floatRgbRange': [float(rgb.min()), float(rgb.max())]}
    gray_r = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY); gray_t = cv2.cvtColor(target, cv2.COLOR_RGB2GRAY)
    edge = lambda gray: cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)/8,
                                     cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)/8)
    safe = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    result['gradientMagnitudeL1'] = mean(np.abs(edge(gray_r)-edge(gray_t)), safe)
    if cohort is not None:
        cohort = cpu(cohort)
        result['cohortQ'] = {name: mean(cohort[:, :, i]) for i, name in enumerate(['scaleOver2x', 'scaleOver5x', 'largestAxisOnePercent'])}
        result['cohortOver2ShareRoomQ'] = float(cohort[:, :, 0][mask].sum()/max(q_room[mask].sum(), 1e-9))
        region = mask & ~S
        result['cohortOver2ShareRoomQOutsideS'] = float(cohort[:, :, 0][region].sum()/max(q_room[region].sum(), 1e-9))
    result['spatialGrid3x3'] = {}
    for gy in range(3):
        for gx in range(3):
            region = np.zeros_like(mask)
            region[gy*mask.shape[0]//3:(gy+1)*mask.shape[0]//3,
                   gx*mask.shape[1]//3:(gx+1)*mask.shape[1]//3] = True
            region &= mask
            result['spatialGrid3x3'][str(gy)+','+str(gx)] = {'pixels':int(region.sum()),
                'S':mean(S,region),'U':mean(U,region),'A':mean(A,region),'rgbL1':mean(error,region),
                'SnoU':mean(S & ~U,region), 'SUlowA':mean(S & U & (A<.8),region)}
    region_image = np.zeros((*mask.shape, 3), np.uint8)
    palette = [[130, 80, 180], [255, 155, 35], [40, 140, 240], [240, 65, 70], [65, 185, 130]]
    for (_, region), color in zip(strata.items(), palette):
        region_image[mask & region] = color
    return result, region_image, error


def png(path, rgb):
    image = np.round(np.clip(cpu(rgb), 0, 1)*255).astype(np.uint8)
    if image.ndim == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    if not cv2.imwrite(str(path), image):
        raise OSError(str(path))


def labeled_tile(image, label, target_height=360):
    image = np.clip(cpu(image), 0, 1).astype(np.float32)
    if image.ndim == 2: image = np.repeat(image[:, :, None], 3, axis=2)
    image = cv2.resize(image, (int(image.shape[1]*target_height/image.shape[0]), target_height), interpolation=cv2.INTER_AREA)
    tile = np.zeros((target_height+32, image.shape[1], 3), np.float32); tile[32:] = image
    cv2.putText(tile, label, (5, 21), cv2.FONT_HERSHEY_SIMPLEX, .42, (1, 1, 1), 1, cv2.LINE_AA)
    return tile


def replay_frame(data, states, initial_scales, fixed_person, v2_asset, name, out):
    directory = out / Path(name).stem; directory.mkdir()
    frame = make_frame(data, name, crop=False, half=True)
    target = cpu(frame['rgb']); height, width = target.shape[:2]
    masks = {k: cpu(v) for k, v in frame['masks'].items()}; mask = masks['room_visible']
    C, K = cpu(frame['C']), cpu(frame['K'])
    support, support_meta = support_surface(data['room'], C, K, width, height, .01*data['scale'])
    S = support['S_raw'] & mask & ~masks['unknown_or_occluded']
    np.savez_compressed(directory / 'observation.npz', rgb=target, K=K, C=C, F=cpu(frame['F']), **masks, **support, S_visible=S)
    png(directory / 'source.png', target)
    png(directory / 'prepared-support.png', target*.4+S[:, :, None]*np.array([.08, .45, .20]))
    result = {'imageName': name, 'width': width, 'height': height, 'K': K.tolist(), 'C': C.tolist(),
              'reference': data['reference'], 'roomMaskPixels': int(mask.sum()),
              'roomAndUnknownPixels': int((mask & masks['unknown_or_occluded']).sum()),
              'prepared': support_meta, 'comparisons': {}}
    for state_name, state in states.items():
        ratio = (state.scales/initial_scales[state_name]).max(-1).values
        axis = state.scales.max(-1).values
        flags = torch.stack((ratio > 2, ratio > 5, axis >= torch.quantile(axis, .99)), -1).float()
        for aa in (False, True):
            tag = state_name + ('-aa' if aa else '-classic')
            rendered = draw(state, frame['C'], frame['K'], width, height, unit_scale=data['scale'], antialiased=aa)
            fp = effective_footprints(rendered['info'], width, height)
            difference = (fp['all_eligible_alpha']-rendered['alpha']).abs().max().item()
            termination = termination_check(rendered['info'], rendered['alpha'], fp['all_eligible_alpha'])
            coh, ca = cohort_contribution(rendered['info'], flags, width, height)
            if not torch.allclose(ca, rendered['alpha'], atol=2e-6, rtol=0):
                raise ValueError('cohort_forward_alpha_changed')
            metric, regions, error = analyze(S, fp['U'], rendered['alpha'], rendered['q'][:, :, 0],
                                             rendered['rgb'], frame['rgb'], mask, coh)
            metric['footprintAlphaMaxDifference'] = difference
            metric['exclusiveTerminationCheck'] = termination
            metric['overlapQuantiles'] = quantiles(cpu(fp['overlap'])[mask])
            metric['emptyUHasNonzeroAlphaPixels'] = int(((~fp['U']) & (rendered['alpha'] > 1e-6)).sum())
            combined = draw(joined_state(fixed_person, state), frame['C'], frame['K'], width, height,
                            unit_scale=data['scale'], antialiased=aa)
            cm, _, _ = analyze(S, fp['U'], combined['alpha'], combined['q'][:, :, 0], combined['rgb'], frame['rgb'], mask)
            metric['fixedPersonComposite'] = cm
            metric['roomQRemovedByPerson'] = float((rendered['q'][:, :, 0]-combined['q'][:, :, 0])[frame['masks']['room_visible']].mean())
            info = rendered['info']
            np.savez_compressed(directory / (tag + '.npz'), U=cpu(fp['U']), A=cpu(rendered['alpha']),
                q_room=cpu(rendered['q'][:, :, 0]), rgb=cpu(rendered['rgb']), error=error,
                overlap=cpu(fp['overlap']), optical_depth=cpu(fp['optical_depth']), cohort_q=cpu(coh),
                full_A=cpu(combined['alpha']), full_q_room=cpu(combined['q'][:, :, 0]), full_rgb=cpu(combined['rgb']),
                means2d=cpu(info['means2d']), conics=cpu(info['conics']), radii=cpu(info['radii']),
                projected_opacity=cpu(info['opacities']), gaussian_ids=cpu(info['gaussian_ids']))
            panel = np.concatenate([labeled_tile(target, 'source / fixed mask'), labeled_tile(S, 'S: surface hypothesis'),
                labeled_tile(fp['U'], 'U: effective footprint'), labeled_tile(rendered['alpha'], 'A: actual accumulated'),
                labeled_tile(rendered['rgb'], tag), labeled_tile(regions/255., 'S/U/A/RGB attribution')], axis=1)
            png(directory / (tag + '.png'), panel)
            png(directory / (tag + '-composite.png'), combined['rgb'])
            result['comparisons'][tag] = metric
            print(name, tag, json.dumps({k:metric[k] for k in ['S','U','meanAlpha','rgbL1']}), flush=True)
    # Whole-pipeline comparison: v2 person + v2 room + AA vs v3 person + room + classic.
    whole_v2 = draw(v2_asset, frame['C'], frame['K'], width, height, unit_scale=data['scale'], antialiased=True)
    np.savez_compressed(directory / 'whole-v2-aa.npz', rgb=cpu(whole_v2['rgb']), A=cpu(whole_v2['alpha']), q_room=cpu(whole_v2['q'][:, :, 0]))
    png(directory / 'whole-v2-aa.png', whole_v2['rgb'])
    result['wholePipelineV2AA'] = analyze(S, cpu(fp['U']), whole_v2['alpha'], whole_v2['q'][:, :, 0], whole_v2['rgb'], frame['rgb'], mask)[0]
    # Exact forward comparison of exported/reloaded assets; not a new PLY parser test.
    for prefix, first in [('v3', 'v3_360'), ('v2', 'v2_final')]:
        for mode in ['classic', 'aa']:
            a = np.load(directory / (first+'-'+mode+'.npz'))
            b = np.load(directory / (prefix+'_ply-'+mode+'.npz'))
            result.setdefault('exportReplay', {})[prefix+'-'+mode] = {k: {'maxAbs': float(np.abs(a[k]-b[k]).max()),
                'meanAbs': float(np.abs(a[k]-b[k]).mean())} for k in ['A','q_room','rgb']}
    json_write(directory / 'metrics.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', nargs='+', default=['frame_0035.png'])
    args = parser.parse_args()
    if args.output.exists(): raise ValueError('never_overwrite_audit_run')
    args.output.mkdir(parents=True)
    started = time.perf_counter(); inputs = Inputs(); backend = Path(__file__).resolve().parent
    with zero_training():
        config = freeze_contract(backend, args.run, args.prepared, inputs)
        data = load_data(args.prepared, inputs)
        states, initial_scales, person, v2_asset = recover_states(data, args.run, args.prepared, args.output, inputs)
        protected = {k: state_hash(v) for k, v in states.items()}; protected['person'] = state_hash(person)
        for name in args.frames:
            if name not in data['worlds'] or name not in data['development']:
                raise ValueError('requested_frame_not_recorded_world_development:' + name)
        for key, state in states.items():
            np.savez_compressed(args.output/(key+'-frozen-state.npz'), **{n:cpu(getattr(state,n)) for n in FIELDS},
                                covariance=cpu(state.covariance()), initial_scale=cpu(initial_scales[key]))
        provenance = data['room']
        summary = {'anchor': ANCHOR, 'runtimeConfig': config, 'reference': data['reference'], 'newTrainingSteps': 0,
            'guard': 'Adam/backward/autograd.grad/DefaultStrategy blocked, torch.no_grad active',
            'sourceHash': data['sourceHash'], 'gsplat': importlib.metadata.version('gsplat'),
            'torch': torch.__version__, 'gpu': torch.cuda.get_device_name(0),
            'fixedPersonStateHash': state_hash(person),
            'states': {k:state_stats(v, initial_scales[k]) for k,v in states.items()},
            'prepared': {'points':len(provenance['xyz']), 'duplicateXYZ':len(provenance['xyz'])-len(np.unique(provenance['xyz'],axis=0)),
                'support':quantiles(provenance['support']), 'triangleHypothesisNotTruth':True},
            'frames': []}
        torch.cuda.reset_peak_memory_stats()
        for name in args.frames:
            summary['frames'].append(replay_frame(data, states, initial_scales, person, v2_asset, name, args.output))
        for key,state in states.items():
            if state_hash(state)!=protected[key]: raise ValueError('audit_changed_parameters:'+key)
        if state_hash(person)!=protected['person']: raise ValueError('audit_changed_person')
        inputs.verify()
        summary['seconds'] = time.perf_counter()-started
        summary['peakAllocatedBytes'] = torch.cuda.max_memory_allocated()
        summary['peakReservedBytes'] = torch.cuda.max_memory_reserved()
        summary['inputs'] = inputs.records
        summary['adapterSha256'] = sha(Path(__file__))
        shutil.copyfile(__file__, args.output / Path(__file__).name)
        json_write(args.output / 'summary.json', summary)
        print('COMPLETED', args.output, summary['seconds'], flush=True)


if __name__ == '__main__':
    main()
