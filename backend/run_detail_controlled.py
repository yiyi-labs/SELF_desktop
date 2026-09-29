"""Independent bounded A/B branches. Never invokes joint or publishing on failure."""
from pathlib import Path
import argparse,json,random,shutil,time,subprocess,traceback
import numpy as np
import torch
import gsplat
from reconstruction_components_v3 import load_v3_prepared,save_json,sha
from reconstruction_portrait_pipeline import initialize_scene
from reconstruction_portrait_priority import validate_config,ResearchModel
from reconstruction_detail_controlled import DetailModel,train_portrait,train_static,evaluate_face,evaluate_room
from audit_portrait_priority_handoff import restore_tensors


def execute(args):
    base=Path(__file__).resolve().parent;out=args.output.resolve();old=args.baseline.resolve()
    if out.exists() or not out.is_relative_to(base/'.sources'):raise ValueError('new_private_run_required')
    out.mkdir(parents=True);started=time.perf_counter()
    c=validate_config(json.loads((old/'config.json').read_text()));plan=json.loads((old/'observations.json').read_text())
    c['joint_steps']=0;c['joint_frozen_steps']=0
    save_json(out/'config.json',c);snap=out/'algorithm-source';snap.mkdir()
    files=list(base.glob('reconstruction_*.py'))+[base/'run_detail_controlled.py',base/'audit_portrait_priority_handoff.py',base/'flame_open_model.py']
    for p in files:shutil.copyfile(p,snap/p.name)
    save_json(out/'code-hashes.json',{p.name:sha(p) for p in snap.iterdir()})
    if gsplat.__version__!='1.5.3' or not torch.cuda.is_available():raise RuntimeError('pinned_GPU_runtime_unavailable')
    random.seed(c['seed']);np.random.seed(c['seed']);torch.manual_seed(c['seed']);torch.cuda.reset_peak_memory_stats()
    data=load_v3_prepared(args.prepared)
    oldcontract=json.loads((old/'contract.json').read_text())
    for path,expected in oldcontract['observationFiles'].items():
        if sha(args.prepared/path)!=expected:raise ValueError('frozen_observation_changed:'+path)
    # Newly reserved local observations never used in this run's colour or
    # previous run's selected face colours / measured room seed training.
    used=set(plan['train']+plan['development']+plan['audit']+data['train'])
    available=sorted(n for n,r in data['local'].items() if n not in used and r['role']=='train')
    new=[available[int(i)] for i in np.linspace(0,len(available)-1,min(3,len(available))).round()] if available else []
    plan['new_audit']=new;plan['auditScope']='previous audit now development-review; new audit excluded from previous selected/current colour uses, not globally unseen'
    save_json(out/'observations.json',plan)
    for n in plan['audit']+new:data['local'][n]['role']='audit'
    contract={'sourceSha256':data['sourceHash'],'baselineRun':str(old),'baselineContractSha256':sha(old/'contract.json'),
        'initialCheckpointSha256':sha(old/'face-initial.pt'),'oldFaceFinalSha256':sha(old/'face-final.pt'),
        'modelSha256':data['modelHash'],'appearanceSha256':data['appearanceHash'],
        'observationsSha256':sha(out/'observations.json'),'configSha256':sha(out/'config.json'),
        'codeSha256':json.loads((out/'code-hashes.json').read_text()),
        'resume':'controlled warm-start of complete model; fresh Adam intentionally, not exact resume',
        'inputs':'frozen original observations and prior input archives verified; unchanged source paths',
        'newAuditScope':'local colour holdout for this study; prior geometry estimation allowed; historical worldwide blindness not claimed'}
    save_json(out/'contract.json',contract)
    save_json(out/'runtime.json',{'torch':torch.__version__,'gsplat':gsplat.__version__,'device':torch.cuda.get_device_name(),'cuda':torch.version.cuda})
    results={}
    for branch,cls in [('portrait_refine_v1',DetailModel),('room_fullimg_v1',ResearchModel)]:
        dest=out/branch;dest.mkdir();shutil.copyfile(args.prepared/'cloth_supported_seeds.npz',dest/'cloth_supported_seeds.npz')
        try:
            scene=initialize_scene(data,dest);model=cls(scene,data,plan['train']);del scene
            ck=torch.load(old/'face-initial.pt',map_location='cuda',weights_only=False);restore_tensors(model,ck['model'])
            model.room.metadata=ck['extra']['roomMetadata'];model.body_sources=ck['extra']['bodySources'];del ck
            if branch=='portrait_refine_v1':
                model.enable_components(data,plan['train']);save_json(dest/'components-initial.json',model.component_manifest())
                results[branch]=train_portrait(model,data,plan,c,dest,contract)
            else:results[branch]=train_static(model,data,c,dest,contract)
            del model;torch.cuda.empty_cache()
        except Exception as exc:
            results[branch]={'failed':repr(exc),'traceback':traceback.format_exc()};save_json(dest/'failure.json',results[branch]);print(traceback.format_exc(),flush=True)
    # Automatic refusal is distinct from approval: numeric success still needs
    # visible detail and independent geometry review before bounded joint.
    results['joint']={'executed':False,'reason':'requires portrait local/held-out/visual review; no automatic publication'}
    results['seconds']=time.perf_counter()-started;results['allocatedPeakMiB']=torch.cuda.max_memory_allocated()/1048576
    results['reservedPeakMiB']=torch.cuda.max_memory_reserved()/1048576;results['published']=False
    save_json(out/'result.json',results);print(json.dumps({k:v for k,v in results.items() if k not in ('portrait_refine_v1','room_fullimg_v1')}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('baseline',type=Path);p.add_argument('output',type=Path);execute(p.parse_args())
