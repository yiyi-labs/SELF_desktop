"""Explicit same-asset display input, never chooses a best candidate automatically."""
import argparse,json,shutil
from pathlib import Path
import numpy as np
from reconstruction_components_v3 import sha,save_json
def run(folders,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);assets=[];identities={};records=[]
    for label,folder in folders:
        folder=Path(folder).resolve();result=json.loads((folder/'result.json').read_text())
        asset=folder/'candidate-research-only.ply';side=dict(np.load(folder/'candidate-identities.npz'))
        if sha(asset)!=result['assetHash'] or str(side['asset_hash'])!=result['assetHash']:
            raise ValueError('asset_changed:'+label)
        display=json.loads((folder/'display.json').read_text())
        if not assets:conf=dict(display);conf['assets']=[]
        elif any(display[k]!=conf[k] for k in ('K','C','width','height','reference','sourceHash')):
            raise ValueError('camera_contract_differs')
        dest=out/(label+'-identities.npz');side['asset_sha256']=np.array(result['assetHash'])
        np.savez_compressed(dest,**side);identities[label]=str(dest.resolve())
        assets.append(dict(label=label,ply=str(asset),hash=result['assetHash'],count=len(side['point_id'])))
        records.append(dict(label=label,folder=str(folder),assetHash=result['assetHash'],
            checkpointHash=sha(folder/'candidate-final.pt'),status='research; not release-approved'))
    conf['assets']=assets;save_json(out/'display.json',conf);save_json(out/'identity-map.json',identities)
    save_json(out/'provenance.json',dict(records=records,sourceHash=conf['sourceHash'],reference=conf['reference'],published=False))
    shutil.copyfile(__file__,out/Path(__file__).name)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',action='append',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    run([v.split('=',1) for v in a.folder],a.out)