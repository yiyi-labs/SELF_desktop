"""One exact complete checkpoint -> reference PLY identity regression."""
import argparse,json,shutil
from pathlib import Path
from reconstruction_complete_context import load_complete
from reconstruction_portrait_pipeline import make_frame
from reconstruction_components_v3 import sha,save_json
from run_haze_shared_surface import export_state

def run(complete,out):
    out=Path(out);data,plan,model,contract=load_complete(complete,out)
    contract.pop('sourceExtra');f=model.baseline.adjusted_frame(make_frame(data,contract['reference'],crop=False))
    state=model.state(f);asset=out/'exact-reference.ply';export_state(state,asset)
    equal=sha(asset)==contract['completeAssetHash']
    save_json(out/'result.json',dict(sourceHash=data['sourceHash'],checkpointHash=contract['completeCheckpointHash'],
        originalAssetHash=contract['completeAssetHash'],reexportHash=sha(asset),byteEqual=equal,
        pointCount=len(state.means),reference=contract['reference'],K=f['K'].cpu().tolist(),C=f['C'].cpu().tolist(),
        qualityPassed=False,published=False))
    shutil.copyfile(__file__,out/Path(__file__).name)
    if not equal:raise ValueError('complete_reference_export_not_byte_equal')
    print('COMPLETE_BASELINE_BYTE_EQUAL',len(state.means),sha(asset),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    run(a.complete,a.out)