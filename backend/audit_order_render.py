"""Actual fixed-native-canvas rendering check for a point-order-only adapter."""
from pathlib import Path
import argparse,json,shutil
import numpy as np,torch
from reconstruction_joint_visibility import load_recorded_ply
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import draw
from reconstruction_components_v3 import sha,save_json

@torch.no_grad()
def run(source,ordered,out):
    source=Path(source);ordered=Path(ordered);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    conf=json.loads((ordered/'display.json').read_text());spec=json.loads((ordered/'spec.json').read_text());raw=dict(np.load(Path(spec['prepared'])/'local_geometry.npz'))
    C=torch.tensor(conf['C'],device='cuda');K=torch.tensor(conf['K'],device='cuda');w,h=conf['width'],conf['height'];results=[]
    for folder in (source,ordered):
        identities=dict(np.load(folder/'candidate-identities.npz'));asset=folder/'candidate-research-only.ply'
        if sha(asset)!=str(identities['asset_hash']):raise ValueError('identity_changed')
        z=load_recorded_ply(asset,max(1,int((identities['source_namespace']==0).sum())))
        s=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],torch.tensor(identities['component'],device='cuda'))
        r=draw(s,C,K,w,h,unit_scale=float(raw['scale']));results.append({k:r[k].cpu().numpy() for k in ('rgb','alpha','q')})
    differences={k:dict(max=float(np.max(np.abs(results[0][k]-results[1][k]))),mean=float(np.mean(np.abs(results[0][k]-results[1][k])))) for k in results[0]}
    save_json(out/'result.json',dict(differences=differences,sourceAssetHash=sha(source/'candidate-research-only.ply'),orderedAssetHash=sha(ordered/'candidate-research-only.ply'),sourceHash=conf['sourceHash'],reference=conf['reference'],camera=conf['C'],K=conf['K'],size=[w,h],renderer='gsplat1.5.3',maximumTolerance=1e-5,passed=all(r['max']<=1e-5 for r in differences.values()),published=False))
    shutil.copyfile(__file__,out/Path(__file__).name);print(json.dumps(differences),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('source','ordered','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.source,a.ordered,a.out)