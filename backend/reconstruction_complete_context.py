"""Strict recovery of a complete continuity candidate, without changing its asset.
A failed research candidate remains a failed candidate; restoration is not a
quality approval. No publisher, USB or application imports.
"""
from pathlib import Path
import json
import numpy as np
import torch
from reconstruction_evidence_stage import load_stage
from reconstruction_components_v3 import sha, exact_state_hash
from run_continuity_surface_repair import ContinuityStage

def load_complete(folder, out):
    folder=Path(folder).resolve()
    result=json.loads((folder/'result.json').read_text())
    checkpoint=folder/'candidate-final.pt'
    ck=torch.load(checkpoint,map_location='cuda',weights_only=False)
    data,plan,base,contract=load_stage(folder/'spec.json',out)
    if result['sourceHash']!=data['sourceHash'] or ck['contract']['sourceHash']!=data['sourceHash']:
        raise ValueError('complete_source_changed')
    asset=folder/'candidate-research-only.ply'
    if sha(asset)!=result['assetHash']:
        raise ValueError('complete_asset_changed')
    extra=ck['extra']; config=extra['config']; arrays=extra['arrays']; meta=extra['meta']
    if str(arrays['source_hash'])!=data['sourceHash']:
        raise ValueError('surface_source_changed')
    base.room.metadata=extra['roomMetadata']; base.body_sources=extra['bodySources']
    model=ContinuityStage(base,data,meta,arrays,
        np.asarray(config['retiredHead'],int),np.asarray(config['retiredRoom'],int),
        np.asarray(config['retiredBody'],int),config['motionMode'])
    required=model.state_dict(); loaded=ck['model']
    if required.keys()!=loaded.keys():
        raise ValueError('complete_checkpoint_fields_differ')
    for key,value in required.items():
        if value.shape!=loaded[key].shape or value.dtype!=loaded[key].dtype:
            raise ValueError('complete_checkpoint_shape_or_type:'+key)
    model.load_state_dict(loaded,strict=True)
    if any(not torch.equal(value,model.state_dict()[key]) for key,value in loaded.items()):
        raise ValueError('complete_checkpoint_restore_not_exact')
    for p in model.parameters(): p.requires_grad_(False)
    reference=result['reference']
    contract.update(completeFolder=str(folder),completeCheckpointHash=sha(checkpoint),
        completeAssetHash=result['assetHash'],completeStateHash=exact_state_hash(model),
        reference=reference,baselineQualityPassed=False,
        newOptimization='new candidate optimizer; source parameters restored exactly',
        sourceExtra=extra)
    return data,plan,model,contract