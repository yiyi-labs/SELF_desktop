"""CPU preparation/restore contract; no render, optimizer construction or training."""
from pathlib import Path
import argparse,json,shutil,time
import numpy as np
import torch
from reconstruction_components_v3 import load_v3_prepared,save_json,sha
from reconstruction_portrait_pipeline import initialize_scene,make_frame
from reconstruction_portrait_priority import validate_config,observation_plan,ResearchModel,pose_landmark_loss
from reconstruction_research_state import validate_research_manifest


def run(args):
    out=args.output.resolve();private=Path(__file__).resolve().parent/'.sources'
    if not out.is_relative_to(private) or out.exists():raise ValueError('new_isolated_output_required')
    out.mkdir(parents=True);start=time.perf_counter()
    try:
        config=validate_config(json.loads(args.config.read_text(encoding='utf-8-sig')))
        data=load_v3_prepared(args.prepared);plan=observation_plan(data,config)
        for name in plan['audit']:data['local'][name]['role']='audit'
        shutil.copyfile(args.prepared/'cloth_supported_seeds.npz',out/'cloth_supported_seeds.npz')
        scene=initialize_scene(data,out,device='cpu');model=ResearchModel(scene,data,plan['train'])
        frame=make_frame(data,plan['train'][0],device='cpu');_,landmarks=pose_landmark_loss(model,data,frame)
        state=model.portrait.local_state(frame['mesh']);prior=data['prior']
        if len(state.means)!=len(prior['role']):raise ValueError('lost_prior_points')
        if not np.array_equal(state.sh.detach().numpy(),prior['sh_coeff']):raise ValueError('altered_imported_SH')
        if not np.array_equal(model.portrait.source_index.numpy(),prior['source_index']):raise ValueError('lost_source_ids')
        for path in config['geometry_archives']:
            if not Path(path).is_file():raise ValueError('missing_geometry_archive:'+path)
        shapes={k:{'shape':list(v.shape),'dtype':str(v.dtype)} for k,v in model.state_dict().items()}
        hashes={str(p):sha(p) for p in [args.prepared/'local_geometry.npz',Path(data['appearance']),*map(Path,config['geometry_archives'])]}
        save_json(out/'observations.json',plan)
        save_json(out/'report.json',{'status':'CPU_input_contract_passed_not_GPU_training','seconds':time.perf_counter()-start,
            'sourceSha256':data['sourceHash'],'appearanceSha256':data['appearanceHash'],'frozenInputs':hashes,
            'headPoints':len(model.portrait.role),'surfacePoints':model.portrait.surface_count,
            'roomPoints':len(model.room.params['means']),'bodyPoints':len(model.body['means']),
            'selectedFaceViews':len(plan['train']),'localOnlySelected':[n for n in plan['train'] if n not in data['worlds']],
            'auditViews':plan['audit'],'landmarkCheck':landmarks,'stateFields':shapes,
            'jointInput':validate_research_manifest(data,data['reference'],data['train']),
            'CUDA':torch.cuda.is_available(),'trainingPerformed':False,'published':False,
            'remaining':['real GPU forward/backward','visual acceptance','garment motion and neck continuity','independent hair/glasses structure','fixed PLY handoff']})
        print(json.dumps({'headPoints':len(model.portrait.role),'faceViews':len(plan['train']),
            'localOnlyViews':sum(n not in data['worlds'] for n in plan['train']),'seconds':time.perf_counter()-start}),flush=True)
    except Exception as error:
        save_json(out/'failure.json',{'error':repr(error),'trainingPerformed':False});raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('config',type=Path);p.add_argument('output',type=Path)
    run(p.parse_args())
