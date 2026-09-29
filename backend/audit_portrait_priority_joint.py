"""Attribute frozen-person transfer and joint regression without training."""
from pathlib import Path
import argparse,json,shutil
import numpy as np
import torch
from reconstruction_components_v3 import load_v3_prepared,save_json,exact_state_hash
from reconstruction_portrait_pipeline import initialize_scene,make_frame,metrics
from reconstruction_portrait_priority import ResearchModel
from audit_portrait_priority_handoff import restore_tensors

@torch.no_grad()
def run(args):
    out=args.output.resolve();base=Path(__file__).resolve().parent/'.sources'
    if out.exists() or not out.is_relative_to(base):raise ValueError('new_isolated_audit_required')
    out.mkdir(parents=True);plan=json.loads((args.run/'observations.json').read_text())
    data=load_v3_prepared(args.prepared)
    for n in plan['audit']:data['local'][n]['role']='audit'
    shutil.copyfile(args.prepared/'cloth_supported_seeds.npz',out/'cloth_supported_seeds.npz')
    scene=initialize_scene(data,out);model=ResearchModel(scene,data,plan['train']);del scene
    result={}
    for label in ('room-final','T3-final','T4-final'):
        ck=torch.load(args.run/(label+'.pt'),map_location='cuda',weights_only=False);restore_tensors(model,ck['model'])
        rows={}
        for name in data['development']+[data['reference']]:
            f=make_frame(data,name);values={s:model.render(f,s) for s in ('T0','T1','T2')}
            rows[name]={s:metrics(v,f) for s,v in values.items()}
            rows[name]['T01RGB']={'mean':float((values['T0']['rgb']-values['T1']['rgb']).abs().mean()),
                'max':float((values['T0']['rgb']-values['T1']['rgb']).abs().max())}
        state=ck.get('strategy') or ck['extra']['roomMetadata'];p=model.room.params
        drift=(p['means']-state['initial_means']).norm(dim=1)/data['scale']
        scale_ratio=(p['scales']-state['initial_scales']).exp().max(1).values
        result[label]={'portraitExactHash':exact_state_hash(model.portrait),'rows':rows,
            'rootAnchorDisplacementModelUnitsQuantiles':torch.quantile(drift,torch.tensor([.5,.9,.99],device='cuda')).cpu().tolist(),
            'scaleRatioToRootQuantiles':torch.quantile(scale_ratio,torch.tensor([.5,.9,.99],device='cuda')).cpu().tolist(),
            'note':'root seed stability proxy; not independent depth truth'}
    result['T3PreservedPersonExactly']=result['room-final']['portraitExactHash']==result['T3-final']['portraitExactHash']
    result['T4ChangedPerson']=result['T3-final']['portraitExactHash']!=result['T4-final']['portraitExactHash']
    save_json(out/'report.json',result)
    print(json.dumps({k:result[k] for k in ('T3PreservedPersonExactly','T4ChangedPerson')}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('run',type=Path);p.add_argument('output',type=Path);run(p.parse_args())
