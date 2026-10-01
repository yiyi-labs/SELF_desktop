"""Exact own-checkpoint restore and native head-only diagnostic, no adoption."""
from pathlib import Path
import json,argparse,shutil
import numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_components_v3 import sha,save_json
from reconstruction_portrait_pipeline import make_frame,draw
from reconstruction_portrait_model import joined_state
from reconstruction_components_v3 import pick
from reconstruction_continuity_surface import physical_masks
from reconstruction_research_state import FrameSampler,restore_checkpoint
from run_measured_head_surface_repair import LocalMeasuredField,HeadMeasuredStage
from run_continuous_surface_repair import write_image

def run(complete,run_folder,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);folder=Path(run_folder)
    data,plan,base,source=load_complete(complete,out/'loading');contract=json.loads((folder/'contract.json').read_text());conf=json.loads((folder/'config.json').read_text())
    fs=torch.load(folder/'field.pt',map_location='cuda',weights_only=True);field=LocalMeasuredField(fs['nodes'],float(fs['maximum']),len(fs['nodes']));field.load_state_dict(fs,strict=True)
    names=list(dict.fromkeys([source['reference']]+[n for n in plan['development']+plan['audit'] if n in data['local']]))
    masks=physical_masks(contract['spec']['prepared'],data,names);states={};records={}
    with torch.no_grad():
        for n in names:
            f=base.baseline.adjusted_frame(make_frame(data,n,crop=False));h,w=f['rgb'].shape[:2];s=pick(base.baseline.head_state(f),base.keep_head)
            r=draw(s,f['F'],f['K'],w,h);states[n]=dict(rgb=r['rgb'].cpu().numpy(),q=r['q'].cpu().numpy(),alpha=r['alpha'].cpu().numpy())
    for label in ['appearance-control','measured-candidate']:
        ck=folder/label/'candidate-final.pt';payload=torch.load(ck,map_location='cuda',weights_only=False)
        ids=payload['extra']['ids'];model=HeadMeasuredStage(base,data,field,ids,label=='measured-candidate')
        rates={'sh':.002,'opacity':.005,'log_scales':.001};ops={k:torch.optim.Adam([getattr(model.patch,k)],lr=lr) for k,lr in rates.items()};samplers={'views':FrameSampler(conf['train'],100105)}
        restore_checkpoint(ck,model,ops,samplers,contract=contract,device='cuda')
        dest=out/label;dest.mkdir();rows={}
        with torch.no_grad():
            for n in names:
                f=make_frame(data,n,crop=False);r=model.render_local(f);rgb=r['rgb'].cpu().numpy();alpha=r['alpha'].cpu().numpy();q=r['q'].cpu().numpy();row={}
                for part,index in [('face',1),('hair',2)]:
                    m=masks[n][part];target=data['rgb'][n]
                    row[part]=dict(beforeL1=float(np.abs(states[n]['rgb']-target).mean(-1)[m].mean()),afterL1=float(np.abs(rgb-target).mean(-1)[m].mean()),beforeContribution=float(states[n]['q'][...,index][m].mean()),afterContribution=float(q[...,index][m].mean()))
                rows[n]=row;target=data['rgb'][n];head=masks[n]['face']|masks[n]['hair'];y,x=np.where(head)
                bounds=(max(0,int(x.min())-24),max(0,int(y.min())-24),min(rgb.shape[1],int(x.max())+25),min(rgb.shape[0],int(y.max())+25));x0,y0,x1,y1=bounds
                write_image(dest/(n+'.png'),[v[y0:y1,x0:x1] for v in [target,states[n]['rgb'],rgb]])
                np.savez_compressed(dest/(n+'.npz'),rgb=rgb[y0:y1,x0:x1],alpha=alpha[y0:y1,x0:x1],q=q[y0:y1,x0:x1],rectangle=bounds)
        records[label]=dict(checkpointHash=sha(ck),metrics=rows);save_json(dest/'metrics.json',rows)
        del model,ops,payload;torch.cuda.empty_cache()
    save_json(out/'result.json',dict(records=records,sourceHash=data['sourceHash'],nativeFullFrameThenCrop=True,headOnlyIsNotFullScene=True,published=False))
    shutil.copyfile(__file__,out/Path(__file__).name)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--run',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.complete,a.run,a.out)
