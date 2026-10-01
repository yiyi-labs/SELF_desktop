"""Independent fixed-topology export repair. No retraining or old asset overwrite."""
from pathlib import Path
import argparse,json,shutil
import numpy as np,torch
from reconstruction_components_v3 import sha,save_json
from reconstruction_asset_order import appended_to_original,permute_float_ply
from probe_gs_contract import read_float_ply

def run(folder,complete,out):
    folder=Path(folder).resolve();complete=Path(complete).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    source=folder/'candidate-research-only.ply';before=sha(source)
    result=json.loads((folder/'result.json').read_text());baseResult=json.loads((complete/'result.json').read_text())
    ck=torch.load(folder/'candidate-final.pt',map_location='cpu',weights_only=False)
    rows=ck['model']['head_rows'].numpy();original=dict(np.load(complete/'candidate-identities.npz'))
    if before!=result['assetHash'] or str(original['asset_hash'])!=baseResult['assetHash']:raise ValueError('asset_provenance_changed')
    count=len(original['point_id']);permutation=appended_to_original(count,rows)
    asset=out/source.name;permute_float_ply(source,asset,permutation);after=sha(asset)
    a=read_float_ply(source);b=read_float_ply(asset)
    exact=all(np.array_equal(a[k][permutation],b[k],equal_nan=True) for k in a)
    if not exact or sha(source)!=before:raise ValueError('export_values_or_input_changed')
    np.savez_compressed(out/'candidate-identities.npz',**{**original,'asset_hash':np.array(after),'asset_sha256':np.array(after)})
    np.savez_compressed(out/'vertex-permutation.npz',output_to_input=permutation,updated_original_rows=rows)
    for name in ('spec.json',):shutil.copyfile(folder/name,out/name)
    display=json.loads((complete/'display.json').read_text());display['assets']=[dict(label='fixed order face research',ply=str(asset),hash=after,count=count)];save_json(out/'display.json',display)
    result.update(assetHash=after,sourceHash=baseResult['sourceHash'],reference=baseResult['reference'],pointCount=count,postExportOrderOnly=True,originalAssetHash=before)
    save_json(out/'result.json',result)
    shutil.copyfile(__file__,out/Path(__file__).name);shutil.copyfile(Path(__file__).with_name('reconstruction_asset_order.py'),out/'reconstruction_asset_order.py')
    save_json(out/'order-contract.json',dict(originalAssetHash=before,orderedAssetHash=after,sourceHash=baseResult['sourceHash'],checkpointHash=sha(folder/'candidate-final.pt'),reference=baseResult['reference'],floatPropertiesExact=exact,
        originalRowsUIDNamespaceAndSemanticsRestored=True,pointCount=count,productionEditorTested=False,HarmonyOSTested=False,published=False))
    print(json.dumps(dict(hash=after,pointCount=count,exact=exact)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('folder','complete','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.folder,a.complete,a.out)