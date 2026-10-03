"""Hold the complete portrait bitwise fixed while comparing trained room runs."""
import argparse
import copy
import json
from pathlib import Path
import shutil

import torch

from reconstruction_portrait_pipeline import (load_prepared, initialize_scene,
    surface_contract, surface_contract_matches, audit_full_scene, digest, write_json)
from reconstruction_live_face_domain import restore_recorded


def run(parent, candidate, output):
    parent, candidate, out = map(lambda p: Path(p).resolve(), (parent, candidate, output))
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    configs = [json.loads((p/'config.json').read_text()) for p in (parent, candidate)]
    states = [torch.load(p/'trained-state.pt', map_location='cuda', weights_only=True) for p in (parent, candidate)]
    if states[0]['sourceSha256'] != states[1]['sourceSha256']:
        raise ValueError('frozen_room_source_mismatch')
    data = load_prepared(Path(configs[0]['prepared']))
    restore_recorded(data, parent, configs[0])
    data['reference'] = states[0]['surfaceContract']['reference']
    rows=[]
    for folder, config, state in zip((parent, candidate), configs, states):
        dst=out/folder.name; dst.mkdir()
        if config['prepared'] != configs[0]['prepared']:
            raise ValueError('frozen_room_prepared_mismatch')
        data['dense_manifest']=Path(config['denseSurfaces']['manifestPath'])
        shutil.copyfile(data['prepared']/'cloth_supported_seeds.npz', dst/'cloth_supported_seeds.npz')
        scene=initialize_scene(data,dst)
        if not surface_contract_matches(surface_contract(scene,data),state['surfaceContract']):
            raise ValueError('frozen_room_surface_contract')
        if 'neck_sh_editable' in state['model']:
            scene.register_buffer('neck_sh_editable',state['model']['neck_sh_editable'].clone())
        scene.load_state_dict(state['model'],strict=True)
        portrait={k.removeprefix('portrait.'):v for k,v in states[0]['model'].items() if k.startswith('portrait.')}
        scene.portrait.load_state_dict(portrait,strict=True)
        for k,v in scene.portrait.state_dict().items():
            if not torch.equal(v,portrait[k]): raise AssertionError('frozen_portrait_changed:'+k)
        for k,v in scene.state_dict().items():
            if not k.startswith('portrait.') and not torch.equal(v,state['model'][k]):
                raise AssertionError('frozen_room_other_component_changed:'+k)
        scene.portrait.constraint_mode='soft'
        with torch.no_grad(): metrics=audit_full_scene(scene,data,dst/'full-final')
        # Diagnostic only: no formal asset export and no optimization.
        rows.append(dict(run=str(folder),checkpointSha256=digest(folder/'trained-state.pt'),metrics=metrics,
            portraitSourceCheckpoint=digest(parent/'trained-state.pt'),portraitBitwiseIdentical=True))
        del scene
    write_json(out/'report.json',dict(sourceSha256=data['sourceHash'],rows=rows,
        optimizerCreated=False,trainingSteps=0,exportedAsset=False,
        limitations='Frozen trained portrait attribution only; trained environment and body differ. Not a new published model.'))
    print(json.dumps(dict(output=str(out),portraitBitwiseIdentical=True)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('parent');p.add_argument('candidate');p.add_argument('output')
    run(**vars(p.parse_args()))
