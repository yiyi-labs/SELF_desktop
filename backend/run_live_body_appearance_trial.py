"""One fixed-budget body SH diagnostic from a complete trained scene."""
from pathlib import Path
import argparse
import hashlib
import json
import random
import shutil
import time
import cv2
import numpy as np
import torch

from portrait_pipeline import (load_prepared,initialize_scene,surface_contract,
    surface_contract_matches,audit_stages,audit_full_scene,export_candidate,digest,write_json,make_frame,metrics)
from reconstruction_live_body_appearance import restore_opaque_body_appearance
from live_face_domain import restore_recorded
from code_identity import source_identity
from person_supervision_state import restore_person_supervision,copy_person_supervision_files


def body_audit(scene,data,out):
    from compare_live_opaque_person_runs import region_metrics
    out.mkdir(parents=True,exist_ok=False);report={}
    with torch.no_grad():
        for name in sorted(scene.body_train_names):
            frame=make_frame(data,name,crop=False);render=scene.render(frame,'T2')
            values={key:render[key].cpu().numpy() for key in ('rgb','alpha','q')}
            source=frame['rgb'].cpu().numpy()
            np.savez_compressed(out/(name+'.npz'),**values,K=data['K'],C=data['worlds'][name],F=data['local'][name]['F'])
            pair=np.concatenate((source,values['rgb']),1)
            cv2.imwrite(str(out/(name+'.png')),cv2.cvtColor((pair*255).round().clip(0,255).astype(np.uint8),cv2.COLOR_RGB2BGR))
            report[name]={region:region_metrics(values,source,frame['masks'][region].cpu().numpy())
                for region in ('opaque_cloth','opaque_body_skin','opaque_skin','observed_neck_cloth','observed_room','hair_visible','glasses_visible')}
    write_json(out/'report.json',report);return report


def run(parent,output):
    parent=Path(parent).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    if not torch.cuda.is_available():raise RuntimeError('GPU_unavailable_no_training_claim')
    config=json.loads((parent/'config.json').read_text())
    if not config.get('opaquePerson') or config.get('soft') is not True or config.get('antialiased') is not False:
        raise ValueError('body_trial_requires_opaque_soft_classic_parent')
    output.mkdir(parents=True)
    torch.set_num_threads(4);torch.manual_seed(280928);np.random.seed(280928);random.seed(280928)
    torch.cuda.reset_peak_memory_stats();started=time.perf_counter()
    prepared=Path(config['prepared']);data=load_prepared(prepared)
    checkpoint=torch.load(parent/'trained-state.pt',map_location='cuda',weights_only=True)
    restore_recorded(data,parent,config)
    data['reference']=checkpoint['surfaceContract']['reference']
    data['dense_manifest']=Path(config['denseSurfaces']['manifestPath'])
    shutil.copyfile(prepared/'cloth_supported_seeds.npz',output/'cloth_supported_seeds.npz')
    copy_person_supervision_files(parent,output,config)
    scene=initialize_scene(data,output)
    if not surface_contract_matches(surface_contract(scene,data),checkpoint['surfaceContract']):raise ValueError('body_trial_surface_contract_changed')
    if checkpoint['sourceSha256']!=data['sourceHash']:raise ValueError('body_trial_source_changed')
    if 'neck_sh_editable' in checkpoint['model']:
        scene.register_buffer('neck_sh_editable',checkpoint['model']['neck_sh_editable'].clone())
    scene.load_state_dict(checkpoint['model'],strict=True);scene.portrait.constraint_mode='soft'
    person_restore=restore_person_supervision(scene,data,parent,config,checkpoint)
    identity=source_identity();files=dict(identity['sourceFiles'])
    for name in ('reconstruction_live_body_appearance.py','run_live_body_appearance_trial.py','compare_live_opaque_person_runs.py',
                 'person_supervision_state.py'):
        files[name]=digest(Path(__file__).with_name(name))
    files=dict(sorted(files.items()));identity={**identity,'sourceFiles':files,
        'implementationSha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}
    snapshot=output/'algorithm-source';snapshot.mkdir()
    for name in files:shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    cfg={**config,'parentRun':str(parent),'parentCheckpointSha256':digest(parent/'trained-state.pt'),
         'parentAssetSha256':digest(parent/'portrait.gaussian.ply'),
         'localSteps':0,'roomSteps':0,'hairCompositeSteps':0,'sourceFiles':files,'implementation':identity,
         'bodyAppearanceSteps':120,'bodyAppearanceLearningRate':.008,
         'resumeKind':'complete_model_warm_start_new_Adam_body_SH_only',
         'extraStepsOnlyForFiniteDiagnosisNotQualityAB':True,'notProductionDefault':True,
         'personSupervisionRestore':person_restore}
    write_json(output/'config.json',cfg)
    initial=audit_full_scene(scene,data,output/'full-initial');body_before=body_audit(scene,data,output/'body-initial')
    trained=restore_opaque_body_appearance(scene,data,output/'body-training',steps=120,learning_rate=.008)
    body_after=body_audit(scene,data,output/'body-final');final=audit_full_scene(scene,data,output/'full-final')
    local=audit_stages(scene,data,output/'final');asset=export_candidate(scene,data,output)
    torch.cuda.synchronize()
    report={**cfg,'status':'diagnostic_not_accepted_or_published','plySha256':asset,
            'fullInitial':initial,'fullFinal':final,'final':local,'bodyInitial':body_before,'bodyFinal':body_after,
            'trainings':[trained],'seconds':time.perf_counter()-started,
            'allocatedPeakMiB':torch.cuda.max_memory_allocated()/2**20,'reservedPeakMiB':torch.cuda.max_memory_reserved()/2**20}
    write_json(output/'report.json',report)
    print(json.dumps({key:report[key] for key in ('status','plySha256','seconds','allocatedPeakMiB')}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('parent');parser.add_argument('output')
    run(**vars(parser.parse_args()))
