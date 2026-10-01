"""Compare complete saved state, no optimizer, backward or training."""
import argparse,json
from pathlib import Path
import numpy as np,torch
from reconstruction_components_v3 import sha,save_json
def equal(a,b):
    if isinstance(a,torch.Tensor):return isinstance(b,torch.Tensor) and a.dtype==b.dtype and a.shape==b.shape and torch.equal(a,b)
    if isinstance(a,np.ndarray):return isinstance(b,np.ndarray) and a.dtype==b.dtype and np.array_equal(a,b,equal_nan=True)
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(equal(v,b[k]) for k,v in a.items())
    if isinstance(a,(tuple,list)):return type(a)==type(b) and len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    return a==b
def run(folders,out):
    out=Path(out)
    if out.exists():raise FileExistsError('independent_evidence_required')
    rows={}
    for folder in folders:
        p=Path(folder);a=torch.load(p/'initial.pt',map_location='cpu',weights_only=False);b=torch.load(p/'restored.pt',map_location='cpu',weights_only=False)
        values={k:equal(a[k],b[k]) for k in ('model','optimizers','bindings','samplers','rng','strategy','trainable')}
        rows[str(p)]=dict(fields=values,initialHash=sha(p/'initial.pt'),candidateHash=sha(p/'candidate-final.pt'),restoredHash=sha(p/'restored.pt'))
        if not all(values.values()):raise ValueError('state_restore_differs:'+str(p))
        del a,b
    save_json(out,dict(records=rows,published=False,geometryQualityCertified=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',action='append',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.folder,a.out)