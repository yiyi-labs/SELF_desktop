"""Read-only numerical/asset/state evidence, no auto acceptance or publishing."""
from pathlib import Path
import argparse,json,shutil
import numpy as np,torch,cv2
from reconstruction_components_v3 import save_json,sha
from reconstruction_dense_contract import digest

def same(a,b):
    if isinstance(a,torch.Tensor):return isinstance(b,torch.Tensor) and a.shape==b.shape and a.dtype==b.dtype and torch.equal(a,b)
    if isinstance(a,np.ndarray):return isinstance(b,np.ndarray) and np.array_equal(a,b)
    if isinstance(a,dict):return isinstance(b,dict) and set(a)==set(b) and all(same(a[k],b[k]) for k in a)
    if isinstance(a,(list,tuple)):return type(a)==type(b) and len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
    return a==b

def run(folders,body,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);summary=[]
    for folder in map(Path,folders):
        config=json.loads((folder/'config.json').read_text());reference=json.loads((folder/'contract.json').read_text())['reference'];rows=[]
        for label in ('original-control','surface-replacement'):
            p=folder/label;r=json.loads((p/'result.json').read_text())
            checkpoints={name:torch.load(p/(name+'.pt'),map_location='cpu',weights_only=False) for name in ('initial','restored','mid','candidate-final')}
            a,b=checkpoints['initial'],checkpoints['restored'];restore={k:same(a[k],b[k]) for k in ('model','optimizers','samplers','rng','strategy','trainable','bindings') if k in a}
            if not all(restore.values()):raise ValueError('inexact_restoration:'+label)
            change={k:float((v-checkpoints['candidate-final']['model'][k]).abs().max()) for k,v in a['model'].items() if k.startswith('baseline.') and v.is_floating_point()}
            if any(change.values()):raise ValueError('unauthorized_baseline_update')
            if digest(p/'candidate-research-only.ply')!=r['assetHash']:raise ValueError('asset_hash_changed')
            source=dict(np.load(folder/'baseline-images'/(reference+'.npz')));initial=dict(np.load(p/'initial-images'/(reference+'.npz')))
            pixel={k:float(np.abs(source[k]-initial[k]).max()) for k in ('rgb','alpha','q')}
            if label=='original-control' and max(pixel.values())>1e-5:raise ValueError('control_not_original_pixels')
            dev=[n for n in r['baseline'] if n not in config['train']]
            table={part:{t:float(np.mean([r[t][n][part]['rgb'] for n in dev])) for t in ('baseline','initial','final')} for part in ('face','hair','neck','cloth','room')}
            row=dict(label=label,failures=r['failures'],developmentRGB=table,restore=restore,
                frozenMaxChange=max(change.values()),initialDifference=pixel,count=r['count'],assetHash=r['assetHash'],
                steps=r['steps'],trainSeconds=r['trainSeconds'],allocatedMiB=r['allocatedMiB'],reservedMiB=r['reservedMiB'],
                fileHashes={name+'.pt':sha(p/(name+'.pt')) for name in checkpoints},transactionAccepted=r['transactionAccepted'],published=r['published'])
            rows.append(row);del checkpoints
        summary.append(dict(folder=str(folder.resolve()),branches=rows,totalSeconds=json.loads((folder/'result.json').read_text())['seconds']))
    report=dict(runs=summary,body=json.loads((Path(body)/'result.json').read_text()),noPublication=True,HarmonyOSTested=False,newVideoTested=False)
    save_json(out/'summary.json',report);shutil.copyfile(__file__,out/Path(__file__).name);print(json.dumps(report),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',action='append',required=True);p.add_argument('--body',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.folder,a.body,a.out)