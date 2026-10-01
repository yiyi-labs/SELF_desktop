"""Post-experiment component rollback counterfactual; zero new training.
Tests whether a measured regression follows the room update or the body
update. Not an automatically selected best candidate or a new quality gate.
"""
from pathlib import Path
import argparse,json,shutil
import numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_components_v3 import save_json,sha,exact_state_hash
from reconstruction_portrait_pipeline import make_frame
from reconstruction_continuity_surface import physical_masks
from reconstruction_research_state import save_checkpoint,FrameSampler
from run_ray_surface_repair import ObservedSurfaceStage
from run_continuous_surface_repair import evaluate_complete,regression_screen
from run_haze_shared_surface import export_state


def run(complete,source,out):
    out=Path(out);source=Path(source)
    data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    source_contract=json.loads((source/'contract.json').read_text())
    if source_contract['completeCheckpointHash']!=contract['completeCheckpointHash']:raise ValueError('different_baseline')
    side=dict(np.load(Path(complete)/'candidate-identities.npz'))
    final=torch.load(source/'candidate-final.pt',map_location='cuda',weights_only=False)
    initial=torch.load(source/'initial.pt',map_location='cuda',weights_only=False)
    original=json.loads((source/'result.json').read_text());names=list(original['baseline']);masks=physical_masks(contract['spec']['prepared'],data,names)
    old,before=evaluate_complete(base,data,names,masks,out/'baseline-images');model=ObservedSurfaceStage(base,data,side)
    summaries={}
    for keep in ('room','body'):
        folder=out/(keep+'-only');folder.mkdir();shutil.copyfile(out/'spec.json',folder/'spec.json')
        state={k:(v if not k.startswith('patches.') or k.startswith('patches.'+keep+'.') else initial['model'][k]) for k,v in final['model'].items()}
        model.load_state_dict(state,strict=True)
        for p in model.parameters():p.requires_grad_(False)
        for k,v in state.items():
            if not torch.equal(v,model.state_dict()[k]):raise ValueError('counterfactual_restore_changed')
        _,after=evaluate_complete(model,data,names,masks,folder/'final-images',old)
        f=base.baseline.adjusted_frame(make_frame(data,contract['reference'],crop=False));asset=folder/'candidate-research-only.ply'
        export_state(model.state(f),asset);h=sha(asset)
        np.savez_compressed(folder/'candidate-identities.npz',**{**side,'asset_hash':np.array(h),'asset_sha256':np.array(h)})
        display=json.loads((Path(complete)/'display.json').read_text());display['assets']=[dict(label=keep+' only',ply=str(asset.resolve()),hash=h,count=len(side['point_id']))];save_json(folder/'display.json',display)
        result=dict(baseline=before,final=after,failures=regression_screen(before,after),sourceHash=data['sourceHash'],reference=contract['reference'],assetHash=h,
            intervention='kept '+keep+' update; other patch restored to initial parameters',newTrainingSteps=0,originalTrainingSteps=original['steps'],
            originalCheckpointHash=sha(source/'candidate-final.pt'),published=False,releaseQualityPassed=False,transactionAccepted=False)
        save_json(folder/'result.json',result)
        # No fabricated Adam resume: retain actual source separately, diagnostic CK is explicitly optimizer-free.
        save_checkpoint(folder/'candidate-final.pt',model,{}, {},stage='zero-training-component-counterfactual',step=0,contract=contract,strategy={'events':[]},extra=result)
        summaries[keep]=dict(failures=result['failures'],assetHash=h)
    save_json(out/'result.json',summaries)
    shutil.copyfile(__file__,out/Path(__file__).name)
    print(json.dumps(summaries),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('complete','source','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.complete,a.source,a.out)
