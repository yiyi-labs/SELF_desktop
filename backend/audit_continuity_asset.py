"""Identity-preserving adapter to existing frozen PLY/display audits.

Only independent research outputs are written. Original candidate, sidecar,
production viewer, reference cameras and historical assets are not modified.
"""
import argparse,json,shutil
from pathlib import Path
import numpy as np
from reconstruction_dense_contract import digest,write_json
from audit_dense_surface_asset import run as orbit


def run(folder,out):
    folder=Path(folder).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    result=json.loads((folder/'result.json').read_text());spec=json.loads((folder/'spec.json').read_text())
    side=dict(np.load(folder/'candidate-identities.npz'));asset=folder/'candidate-research-only.ply';h=digest(asset)
    if h!=result['assetHash'] or str(side['asset_hash'])!=h:raise ValueError('candidate_identity_changed')
    adapter=out/'adapter';adapter.mkdir()
    shutil.copyfile(asset,adapter/asset.name)
    np.savez_compressed(adapter/'candidate-identities.npz',**side,asset_sha256=np.array(h))
    write_json(adapter/'result.json',result);write_json(adapter/'spec.json',spec)
    shutil.copyfile(__file__,out/Path(__file__).name)
    orbit(adapter,out/'frozen-ply')
    display=json.loads((out/'frozen-ply/display.json').read_text())
    write_json(out/'identity-map.json',{'candidate':str((adapter/'candidate-identities.npz').resolve())})
    write_json(out/'provenance.json',dict(sourceHash=result['sourceHash'],assetHash=h,originalAsset=str(asset),originalSidecarHash=digest(folder/'candidate-identities.npz'),
        adapterSidecarHash=digest(adapter/'candidate-identities.npz'),reference=result['reference'],camera=display['C'],K=display['K'],
        renderer='gsplat1.5.3; orbit around recorded prior reference head origin',published=False,HarmonyOSTested=False))


def display_input(source,out):
    """Resolve a legacy audit's backend-relative paths in a NEW input directory.
    Camera/colour/asset bytes remain identical; no previous output is edited.
    """
    source=Path(source).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    conf=json.loads(source.read_text());base=Path(__file__).resolve().parent
    for asset in conf['assets']:
        path=Path(asset['ply']);path=(base/path).resolve() if not path.is_absolute() else path
        if digest(path)!=asset['hash']:raise ValueError('display_asset_changed')
        asset['ply']=str(path)
    write_json(out/'display.json',conf)
    write_json(out/'provenance.json',dict(sourceDisplay=str(source),sourceDisplayHash=digest(source),pathOnlyAdaptation=True,published=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True);g.add_argument('--folder');g.add_argument('--display-source');p.add_argument('--out',required=True);a=p.parse_args()
    if a.folder:run(a.folder,a.out)
    else:display_input(a.display_source,a.out)
