"""Prepare a CPU-only same-reference display audit from an archived full draw.

The gsplat side is explicitly a prior scene-state draw, NOT a new PLY replay.
The browser side loads the exact exported PLY. No inference or training runs.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from audit_live_scene_display import prepare, sha, save_json, local_path, load_audit
from reconstruction_components_v2 import rectified_data
from probe_gs_contract import read_float_ply


def run(run, prepared, reference, out):
    run, prepared, out = map(local_path, (run, prepared, out))
    view = json.loads((run/'portrait.view.json').read_text())
    config = json.loads((run/'config.json').read_text())
    meta = json.loads((prepared/'preparation.json').read_text())
    if view['sourceFrame'] != reference:
        raise ValueError('cached_scene_comparison_requires_export_reference')
    source_hash = meta['sourceHash']
    if source_hash != config['sourceSha256'] or source_hash != view['sourceSha256']:
        raise ValueError('cached_source_mismatch')
    asset = run/'portrait.gaussian.ply'
    if sha(asset) != view['assetSha256'] or config['antialiased']:
        raise ValueError('cached_asset_hash_or_classic_contract')
    cached_path = run/'full-final'/(reference+'.npz')
    with np.load(cached_path, allow_pickle=False) as archived:
        cache = {key:archived[key].copy() for key in archived.files}
    h, w = cache['rgb'].shape[:2]
    if (w,h) != (1080,1920) or cache['alpha'].shape != (h,w):
        raise ValueError('expected_actual_native_1080_1920_draw')
    with np.load(prepared/'local_geometry.npz', allow_pickle=False) as geometry:
        world_index = list(geometry['world_names']).index(reference)
        local_index = list(geometry['names']).index(reference)
        np.testing.assert_allclose(cache['C'],geometry['C'][world_index],atol=1e-6,rtol=0)
        np.testing.assert_allclose(cache['F'],geometry['F'][local_index],atol=1e-6,rtol=0)
        np.testing.assert_allclose(cache['K'],geometry['K'],atol=1e-6,rtol=0)
        scale = float(geometry['scale'])
    source = local_path(meta['source'])
    masks = local_path(meta['masks'])
    distortion = meta.get('sourceDistortion')
    if distortion is None:
        distortion = json.loads((prepared/'pose-and-scale-audit.json').read_text())['sourceRadialDistortion']
    rgb, labels = rectified_data(source,masks,[reference],cache['K'],np.asarray(distortion))
    inputs = out.with_name(out.name+'-inputs')
    inputs.mkdir(parents=True,exist_ok=False)
    np.savez_compressed(inputs/'masks.npz',**labels[reference])
    cv2.imwrite(str(inputs/'source.png'),cv2.cvtColor((rgb[reference]*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    save_json(inputs/'camera.json',dict(sourceHash=source_hash,reference=reference,width=w,height=h,
        K=cache['K'].tolist(),C=cache['C'].tolist(),near=.01*scale,far=1e10*scale))
    result=prepare(asset,inputs/'camera.json',inputs/'masks.npz',inputs/'source.png',out)
    _,spec,receipt=load_audit(out)
    values=read_float_ply(asset); count=len(values['x'])
    with np.load(run/'portrait.components.npz',allow_pickle=False) as sidecar:
        if str(sidecar['asset_sha256'])!=receipt['assetHash'] or len(sidecar['component'])!=count:
            raise ValueError('cached_export_component_identity')
    np.savez_compressed(out/'gsplat.npz',rgb=cache['rgb'],alpha=cache['alpha'],q=cache['q'])
    gs=dict(assetHash=receipt['assetHash'],cameraHash=receipt['cameraHash'],
        pixelsHash=sha(out/'gsplat.npz'),points=count,shDegree=1,renderer='gsplat1.5.3',
        origin='archived_full_frame_scene_draw_not_a_new_PLY_replay',
        originalRenderPath=str(cached_path),originalRenderSha256=sha(cached_path),
        configHash=sha(run/'config.json'),exportViewHash=sha(run/'portrait.view.json'),
        optimizerStepsThisAudit=0,CUDAUsedThisAudit=False,
        state={'localStepsThisRun':config['localSteps'],'roomStepsThisRun':config['roomSteps'],
               'jointStepsThisRun':config['jointSteps'],
               'status':'research_candidate_not_complete_quality_approved'})
    save_json(out/'gsplat-receipt.json',gs)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('run','prepared','reference','out'):parser.add_argument('--'+key,required=True)
    print(json.dumps(run(**vars(parser.parse_args())),indent=2))
