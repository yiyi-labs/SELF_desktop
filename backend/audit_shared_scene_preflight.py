"""Exact frozen pixels and real geometry backward after bounded matrix batching."""
from pathlib import Path
import argparse,json,shutil,torch,numpy as np
from reconstruction_complete_context import load_complete
from reconstruction_components_v3 import save_json,sha,exact_state_hash
from run_shared_scene_geometry import SharedRoomStage
from reconstruction_portrait_pipeline import make_frame
from reconstruction_shared_scene_geometry import bounded_singular_values


def run(complete,checkpoint,recorded_images,out):
    out=Path(out);data,plan,base,contract=load_complete(complete,out)
    shutil.copyfile(__file__,out/'algorithm-source'/Path(__file__).name)
    model=SharedRoomStage(base,data,contract['reference'],True)
    ck=torch.load(checkpoint,map_location='cuda',weights_only=False)
    if ck['contract']['sourceHash']!=data['sourceHash']:raise ValueError('preflight_source_changed')
    model.load_state_dict(ck['model'],strict=True)
    protected=exact_state_hash(base);f=make_frame(data,contract['reference'],crop=False)
    old=np.load(Path(recorded_images)/(f['name']+'.npz'))
    with torch.no_grad():
        r=model.render(f);errors={k:float(np.abs(r[k].cpu().numpy()-old[k]).max()) for k in ('rgb','alpha','q')}
    if max(errors.values())>2e-5:raise ValueError('batched_forward_changed:'+str(errors))
    for p in model.parameters():p.requires_grad_(False)
    model.field.delta.requires_grad_(True);torch.cuda.empty_cache();torch.cuda.reset_peak_memory_stats()
    r=model.render(f);p,J=model.field(model.patch.base,model.normal,model.thickness)
    loss=(r['rgb']-f['rgb']).abs().mean()+.05*(bounded_singular_values(J)-1).square().mean()
    loss.backward();peak=torch.cuda.max_memory_allocated()/1048576;reserved=torch.cuda.max_memory_reserved()/1048576
    report=dict(sourceHash=data['sourceHash'],checkpointHash=sha(checkpoint),errors=errors,
        geometryGradientFinite=bool(torch.isfinite(model.field.delta.grad).all()),geometryGradientL1=float(model.field.delta.grad.abs().sum()),
        allocatedMiB=peak,reservedMiB=reserved,deviceTotalMiB=torch.cuda.get_device_properties(0).total_memory/1048576,
        protectedCheckpointExact=exact_state_hash(base)==protected,published=False)
    save_json(out/'result.json',report);print(json.dumps(report),flush=True)
    if peak>6144:raise ValueError('preflight_peak_exceeds_budget')
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('complete','checkpoint','recorded-images','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.complete,a.checkpoint,a.recorded_images,a.out)