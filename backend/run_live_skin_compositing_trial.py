"""Finite same-geometry dual-backdrop skin diagnostic, never publish."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import torch
from portrait_pipeline import (load_prepared,initialize_scene,
    surface_contract,surface_contract_matches,audit_stages,audit_full_scene,export_candidate,digest,write_json)
from live_skin_compositing import restore_skin_compositing
from code_identity import source_identity
from person_supervision_state import restore_person_supervision,copy_person_supervision_files


def run(parent, output, steps=180):
    parent=Path(parent).resolve()
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(4)
    torch.manual_seed(280928)
    torch.cuda.reset_peak_memory_stats()
    started=time.perf_counter()
    config=json.loads((parent/'config.json').read_text())
    prepared=Path(config['prepared'])
    if config.get('soft') is not True or config.get('antialiased') is not False:
        raise ValueError('face_trial_requires_explicit_soft_classic_parent')
    data=load_prepared(prepared)
    checkpoint=torch.load(parent/'trained-state.pt',map_location='cuda',weights_only=True)
    from live_face_domain import restore_recorded
    restore_recorded(data,parent,config)
    copy_person_supervision_files(parent,output,config)
    data['reference']=checkpoint['surfaceContract']['reference']
    data['dense_manifest']=Path(config['denseSurfaces']['manifestPath'])
    shutil.copyfile(prepared/'cloth_supported_seeds.npz',output/'cloth_supported_seeds.npz')
    scene=initialize_scene(data,output)
    if not surface_contract_matches(surface_contract(scene,data),checkpoint['surfaceContract']):
        raise ValueError('face_trial_scene_contract_changed')
    if checkpoint['sourceSha256']!=data['sourceHash']:
        raise ValueError('face_trial_source_changed')
    if 'neck_sh_editable' in checkpoint['model']:
        scene.register_buffer('neck_sh_editable',checkpoint['model']['neck_sh_editable'].clone())
    scene.load_state_dict(checkpoint['model'],strict=True)
    scene.portrait.constraint_mode='soft'
    person_restore=restore_person_supervision(scene,data,parent,config,checkpoint)
    identity=source_identity()
    files=identity['sourceFiles']
    for name in ('live_skin_compositing.py','run_live_skin_compositing_trial.py',
                 'person_supervision_state.py'):
        files[name]=digest(Path(__file__).with_name(name))
    identity={**identity,'sourceFiles':dict(sorted(files.items())),
        'implementationSha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}
    snapshot=output/'algorithm-source'
    snapshot.mkdir()
    for name in files:
        shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    cfg={**config,'parentRun':str(parent),'parentCheckpointSha256':digest(parent/'trained-state.pt'),
         'parentAssetSha256':digest(parent/'portrait.gaussian.ply'),'skinCompositingSteps':steps,
         'localSteps':0,'roomSteps':0,'hairCompositeSteps':0,'sourceFiles':files,'implementation':identity,
         'resumeKind':'same_full_model_new_Adam_only_skin_appearance','dualBackdropOnlyOnObservedInteriorSkin':True,
         'personSupervisionRestore':person_restore}
    write_json(output/'config.json',cfg)
    before=audit_full_scene(scene,data,output/'full-initial')
    trained=restore_skin_compositing(scene,data,output,steps)
    local=audit_stages(scene,data,output/'final')
    full=audit_full_scene(scene,data,output/'full-final')
    asset=export_candidate(scene,data,output)
    torch.cuda.synchronize()
    result={**cfg,'status':'research_not_release_approved','plySha256':asset,'fullInitial':before,
        'fullFinal':full,'final':local,'trainings':[trained],'seconds':time.perf_counter()-started,
        'allocatedPeakMiB':torch.cuda.max_memory_allocated()/2**20,'reservedPeakMiB':torch.cuda.max_memory_reserved()/2**20}
    write_json(output/'report.json',result)
    print(json.dumps({k:result[k] for k in ('plySha256','seconds','allocatedPeakMiB')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('parent')
    p.add_argument('output')
    p.add_argument('--steps',type=int,default=180)
    run(**vars(p.parse_args()))
