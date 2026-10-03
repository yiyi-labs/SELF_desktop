"""Finite Rctrl/Rcap full-scene face capacity comparison, no publishing."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import time

import numpy as np
import torch
from person_supervision_state import restore_person_supervision,copy_person_supervision_files


def run(parent, output, steps=180, max_parents=384, rounds=2):
    from portrait_pipeline import (load_prepared, initialize_scene, surface_contract,
        surface_contract_matches, audit_stages, audit_full_scene, export_candidate, digest, write_json)
    from live_face_domain import restore_recorded
    from reconstruction_live_face_capacity import select_patch, prepare_targets, train_capacity
    from code_identity import source_identity
    parent = Path(parent).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('new_run_id_required:'+str(output))
    if not torch.cuda.is_available():
        raise RuntimeError('GPU_unavailable_no_training_claim')
    config = json.loads((parent/'config.json').read_text())
    if config.get('soft') is not True or config.get('antialiased') is not False:
        raise ValueError('capacity_requires_explicit_soft_classic_full_scene_parent')
    if not config.get('observedFaceDomain') or not config.get('denseSurfaces'):
        raise ValueError('capacity_requires_observed_skin_dense_scene')
    if not 24 <= steps <= 240 or not 8 <= max_parents <= 512 or rounds not in (1, 2):
        raise ValueError('capacity_budget_outside_finite_reviewed_limits')
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    torch.manual_seed(280928)
    np.random.seed(280928)
    random.seed(280928)
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    prepared = Path(config['prepared'])
    data = load_prepared(prepared)
    checkpoint = torch.load(parent/'trained-state.pt', map_location='cuda', weights_only=True)
    restore_recorded(data, parent, config)
    data['reference'] = checkpoint['surfaceContract']['reference']
    data['dense_manifest'] = Path(config['denseSurfaces']['manifestPath'])
    shutil.copyfile(prepared/'cloth_supported_seeds.npz', output/'cloth_supported_seeds.npz')
    copy_person_supervision_files(parent,output,config)
    scene = initialize_scene(data, output)
    if not surface_contract_matches(surface_contract(scene, data), checkpoint['surfaceContract']):
        raise ValueError('capacity_parent_surface_contract_mismatch')
    if checkpoint['sourceSha256'] != data['sourceHash']:
        raise ValueError('capacity_parent_source_mismatch')
    if 'neck_sh_editable' in checkpoint['model']:
        scene.register_buffer('neck_sh_editable', checkpoint['model']['neck_sh_editable'].clone())
    scene.load_state_dict(checkpoint['model'], strict=True)
    scene.portrait.constraint_mode = 'soft'
    person_restore=restore_person_supervision(scene,data,parent,config,checkpoint)
    identity = source_identity()
    files = dict(identity['sourceFiles'])
    for name in ('reconstruction_live_face_capacity.py', 'run_live_face_capacity_trial.py',
                 'person_supervision_state.py'):
        files[name] = digest(Path(__file__).with_name(name))
    files = dict(sorted(files.items()))
    identity = {**identity, 'sourceFiles':files,
        'implementationSha256':hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
    snapshot = output/'algorithm-source'
    snapshot.mkdir()
    for name in files:
        shutil.copyfile(Path(__file__).with_name(name), snapshot/name)
    cfg = {**config, 'parentRun':str(parent), 'parentCheckpointSha256':digest(parent/'trained-state.pt'),
        'parentAssetSha256':digest(parent/'portrait.gaussian.ply'), 'localSteps':0, 'roomSteps':0,
        'hairCompositeSteps':0, 'faceCapacityStepsPerArm':steps, 'maxParents':max_parents, 'rounds':rounds,
        'implementation':identity, 'sourceFiles':files,
        'resumeKind':'complete_trained_model_with_new_Adam_equal_short_budget',
        'notProductionDefault':True, 'noPublishing':True,'personSupervisionRestore':person_restore}
    write_json(output/'config.json', cfg)
    try:
        plan = select_patch(scene, data, output/'selection', max_parents=max_parents)
        targets = prepare_targets(scene, data, plan, output/'frozen-native-targets')
        write_json(output/'targets.json', targets)
    except ValueError as error:
        write_json(output/'report.json', {**cfg, 'status':'selection_hard_block_no_training', 'reason':str(error),
            'seconds':time.perf_counter()-started, 'noFailedAssetPublished':True})
        raise
    arms = {}
    for label, capacity in (('Rctrl', False), ('Rcap', True)):
        # Reset the same sampler/RNG before each independent arm. Replacement
        # is deterministic; neither arm gets extra recovery image updates.
        torch.manual_seed(280928)
        np.random.seed(280928)
        random.seed(280928)
        arm = output/label
        report, rollback = train_capacity(scene, data, plan, targets, arm,
            steps=steps, capacity=capacity, rounds=rounds)
        write_json(arm/'config.json', {**cfg, 'variant':label})
        copy_person_supervision_files(parent,arm,config)
        candidate = arm/'candidate'
        candidate.mkdir()
        # Persist the actual candidate before rollback, even if a numerical
        # guard failed. A restored parent must not masquerade as the candidate.
        asset_hash = export_candidate(scene, data, candidate)
        full = audit_full_scene(scene, data, arm/'full-final')
        local = audit_stages(scene, data, arm/'local-final')
        report.update(candidateAssetSha256=asset_hash, fullFinal=full, localFinal=local,
            rollback=rollback(), status='research_candidate_requires_visual_review_not_release')
        write_json(arm/'report.json', report)
        arms[label] = report
        # Bitwise full parent state after rollback, including neck selection.
        for key, value in scene.state_dict().items():
            if not torch.equal(value, checkpoint['model'][key]):
                raise AssertionError('capacity_rollback_incomplete:'+key)
    torch.cuda.synchronize()
    comparison = {}
    for name, control in arms['Rctrl']['metrics'].items():
        cap = arms['Rcap']['metrics'][name]
        if control.get('pixels', 0) < 16:
            continue
        comparison[name] = dict(role=control['role'], rgbControl=control['rgb'], rgbCapacity=cap['rgb'],
            realEdgeControl=control['edge'], realEdgeCapacity=cap['edge'],
            skinHoleControl=control['hole'], skinHoleCapacity=cap['hole'])
    result = {**cfg, 'arms':arms, 'sameFixedRegionComparison':comparison,
        'status':'finite_capacity_comparison_complete_not_release_approved',
        'seconds':time.perf_counter()-started, 'allocatedPeakMiB':torch.cuda.max_memory_allocated()/2**20,
        'reservedPeakMiB':torch.cuda.max_memory_reserved()/2**20,
        'PlayCanvasTested':False, 'HarmonyOSTested':False, 'parentRestoredBitwise':True,
        'visualStructureReviewRequired':True}
    write_json(output/'report.json', result)
    print(json.dumps({k:result[k] for k in ('status', 'seconds', 'allocatedPeakMiB')}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('parent')
    p.add_argument('output')
    p.add_argument('--steps', type=int, default=180)
    p.add_argument('--max-parents', type=int, default=384)
    p.add_argument('--rounds', type=int, default=2)
    run(**vars(p.parse_args()))
