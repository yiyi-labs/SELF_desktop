"""Explicit two-branch evidence, recoverability and same-asset handoff."""
from pathlib import Path
import argparse,json,shutil
import cv2,numpy as np
from audit_continuity_results import state_audit,montage
from reconstruction_dense_contract import write_json,digest

def run(uniform,coverage,prepared,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);uniform=Path(uniform);coverage=Path(coverage);prepared=Path(prepared)
    states={name:state_audit(folder) for name,folder in [('uniform',uniform),('coverage',coverage)]}
    a=json.loads((uniform/'result.json').read_text());b=json.loads((coverage/'result.json').read_text())
    ca=json.loads((uniform/'config.json').read_text());cb=json.loads((coverage/'config.json').read_text())
    if ca!=cb:raise ValueError('training_budget_or_config_differs')
    summaries={}
    for name in b['final']:
        summaries[name]={k:{'R0':b['baseline'][name][k],'uniform':a['final'][name][k],'coverage':v} for k,v in b['final'][name].items()}
    for name in ('frame_0010.png','frame_0035.png','frame_0145.png'):
        if name not in b['final']:continue
        # Fixed existing diagnostic views; never involved in point selection.
        src=cv2.cvtColor(cv2.imread(str(prepared/'rectified_observations'/name)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        r0=np.load(coverage/'baseline-images'/(name+'.npz'))['rgb'];old=np.load(uniform/'final-images'/(name+'.npz'))['rgb'];new=np.load(coverage/'final-images'/(name+'.npz'))['rgb']
        montage(out/(name+'-comparison.png'),[src,r0,old,new],['Source','R0 context','Uniform surface','Protected coverage'])
    write_json(out/'state-audit.json',states);write_json(out/'summary.json',dict(views=summaries,configExact=True,
        uniform={k:a[k] for k in ('seconds','trainingSeconds','allocatedMiB','reservedMiB','assetHash','failures')},
        coverage={k:b[k] for k in ('seconds','trainingSeconds','allocatedMiB','reservedMiB','assetHash','failures')},published=False,HarmonyOSTested=False))
    # Existing orbit interface requires sourceHash/reference in result. Old
    # training outputs remain unchanged; enrich metadata in a new adapter only.
    adapter=out/'orbit-input';adapter.mkdir();display=json.loads((coverage/'display.json').read_text())
    for file in ('candidate-research-only.ply','candidate-identities.npz','spec.json'):shutil.copyfile(coverage/file,adapter/file)
    write_json(adapter/'result.json',{**b,'sourceHash':display['sourceHash'],'reference':display['reference']})
    if digest(adapter/'candidate-research-only.ply')!=b['assetHash']:raise ValueError('adapter_asset_changed')
    shutil.copyfile(__file__,out/Path(__file__).name)
    print('FROZEN_SOURCE_AND_FULL_STATE_RESTORATION_PASSED',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('uniform','coverage','prepared','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.uniform,a.coverage,a.prepared,a.out)
