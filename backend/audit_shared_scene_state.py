"""Exact complete-scene, Adam/RNG/sampler rollback and source identity audit."""
from pathlib import Path
import argparse,json,shutil
import torch,numpy as np
from reconstruction_components_v3 import sha,save_json


def same(a,b):
    if isinstance(a,torch.Tensor):return isinstance(b,torch.Tensor) and torch.equal(a,b)
    if isinstance(a,np.ndarray):return isinstance(b,np.ndarray) and np.array_equal(a,b)
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
    if isinstance(a,(list,tuple)):return type(a)==type(b) and len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
    return a==b


def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(exist_ok=False);shutil.copyfile(__file__,out/Path(__file__).name)
    contract=json.loads((root/'contract.json').read_text());complete=Path(contract['completeFolder'])
    if sha(complete/'candidate-final.pt')!=contract['completeCheckpointHash'] or sha(complete/'candidate-research-only.ply')!=contract['completeAssetHash']:raise ValueError('complete_source_changed')
    side=dict(np.load(complete/'candidate-identities.npz'));rows={}
    for label in ('appearance-control','shared-geometry'):
        folder=root/label
        a,b,c=[torch.load(folder/(name+'.pt'),map_location='cpu',weights_only=False) for name in ('initial','candidate-final','restored')]
        checks={k:same(a[k],c[k]) for k in ('model','trainable','optimizers','bindings','samplers','rng','strategy','scheduler','extra','contract')}
        baseline=[k for k in a['model'] if k.startswith('baseline.')]
        protected=all(torch.equal(a['model'][k],b['model'][k]) for k in baseline)
        ids=dict(np.load(folder/'candidate-identities.npz'));identity=same({k:v for k,v in side.items() if k not in ('asset_hash','asset_sha256')},{k:v for k,v in ids.items() if k not in ('asset_hash','asset_sha256')})
        steps={key:[float(value['step']) for value in op['state'].values() if 'step' in value] for key,op in b['optimizers'].items()}
        rows[label]=dict(rollback=checks,protectedBaselineExact=protected,protectedFields=len(baseline),identityExact=identity,optimizerSteps=steps,
            pointCount=len(ids['point_id']),assetHash=sha(folder/'candidate-research-only.ply'),checkpoints={n:sha(folder/(n+'.pt')) for n in ('initial','mid','candidate-final','restored')})
        if not all(checks.values()) or not protected or not identity:raise ValueError('rollback_or_identity_failed:'+label)
    save_json(out/'result.json',dict(rows=rows,sourceHash=contract['sourceHash'],completeAssetHash=contract['completeAssetHash'],releaseApproved=False,published=False))
    print(json.dumps(rows),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.root,a.out)