"""Check source-ray anchors after bounded target-pose correction; no training."""
import argparse,json,torch,numpy as np
from pathlib import Path
from reconstruction_research_state import BoundedHeadPose
from reconstruction_components_v3 import save_json

def run(a):
    frozen=torch.load(a.run/'R0-frozen.pt',map_location='cpu',weights_only=False);common=torch.load(a.run/'common-start.pt',map_location='cpu',weights_only=False)
    obs=json.loads((a.run/'observations.json').read_text());raw=dict(np.load(a.prepared/'local_geometry.npz'));names=list(map(str,raw['names']));K=torch.tensor(raw['K'],dtype=torch.float32);geometry=torch.load(a.run/'bounded-correspondence.pt',map_location='cpu',weights_only=False)
    reference=json.loads((a.run/'load/initialization.json').read_text())['reference']
    pose0=BoundedHeadPose(obs['train'],reference);pose1=BoundedHeadPose(obs['train'],reference);pose0.delta.data.copy_(frozen['model']['pose.delta']);pose1.delta.data.copy_(common['model']['pose.delta']);rows=[]
    for r in geometry['records']:
        index=names.index(r['a']);mesh=torch.tensor(raw['meshes'][index])+frozen['model']['portrait.surface_residual'];tri=mesh[frozen['model']['portrait.faces'][r['triangle']]];xyz=(tri*r['bary'][...,None]).sum(1);F=torch.tensor(raw['F'][index])
        def project(pose):
            f=pose(r['a'],F);v=xyz@f[:3,:3].T+f[:3,3];u=v@K.T;return u[:,:2]/u[:,2:]
        delta=(project(pose0)-project(pose1)).norm(dim=-1).detach().numpy();rows.append({'source':r['a'],'target':r['b'],'medianSourceDriftPx':float(np.median(delta)),'p90SourceDriftPx':float(np.quantile(delta,.9)),'maxSourceDriftPx':float(delta.max())})
    fixed=[k for k in frozen['model'] if k!='pose.delta'];assert all(torch.equal(frozen['model'][k],common['model'][k]) for k in fixed)
    result={'rows':rows,'allOtherModelTensorsExactlyFrozen':True,'maxSourceAnchorDrift':max(r['maxSourceDriftPx'] for r in rows),'note':'post-correction validation; target residual optimizer did not jointly minimise source and target errors'}
    save_json(a.run/'source-anchor-review.json',result);print(json.dumps(result))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('run',type=Path);run(p.parse_args())
