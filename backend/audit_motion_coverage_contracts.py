"""Actual native render/gradient and complete-state preservation contract tests.
Research artefacts only. Synthetic field perturbation is not a quality result.
"""
import argparse,json,shutil
from pathlib import Path
import numpy as np,torch
from reconstruction_evidence_stage import load_stage
from reconstruction_photometric_surface import PhotometricSurfaceModel
from reconstruction_detail_controlled import DetailModel
from reconstruction_portrait_pipeline import make_frame,draw
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_components_v3 import save_json,sha,exact_state_hash
from reconstruction_joint_visibility import load_recorded_ply
from run_haze_shared_surface import export_state


def run(stage,out):
    data,plan,m,contract=load_stage(stage,out,model_class=PhotometricSurfaceModel);out=Path(out)
    shutil.copyfile(__file__,out/Path(__file__).name);p=m.portrait;f=make_frame(data,plan['train'][0],crop=False)
    before=exact_state_hash(p);original=DetailModel.head_state(m,f)
    with torch.no_grad():
        zero=m.render(f,'T0');base=DetailModel.render(m,f,'T0');zeroErrors={k:float((zero[k]-base[k]).abs().max()) for k in ('rgb','alpha','q')}
    save_json(out/'zero-field.json',zeroErrors)
    if max(zeroErrors.values())>2e-4:raise ValueError('zero_field_native_render_changed')
    labels=m.component_origin[p.origin_index[:p.surface_count]];skin=labels==0
    m.active_vertices[torch.unique(p.faces[p.triangle_ids[skin]].reshape(-1))]=True
    with torch.no_grad():m.surface_control[m.active_vertices]=.1
    m.surface_control.requires_grad_(True);s=m.head_state(f);cov=s.covariance();fixed=torch.ones(len(s.means),dtype=torch.bool,device='cuda');fixed[:p.surface_count]=~skin
    originalCov=original.covariance()
    equalMeans=torch.equal(s.means[fixed],original.means[fixed]);equalCov=torch.equal(cov[fixed],originalCov[fixed])
    if not equalMeans or not equalCov:raise ValueError('non_skin_geometry_changed')
    r=m.render(f,'T0');valid=f['masks']['face_core']&~f['masks']['unknown_or_occluded'];loss=(r['rgb'][valid]-f['rgb'][valid]).square().mean();loss.backward()
    grad=m.surface_control.grad
    if grad is None or not torch.isfinite(grad).all() or not bool(grad.abs().max()>0):raise ValueError('shared_surface_gradient_missing')
    with torch.no_grad():
        factored=m.head_state(f);relative=float((factored.covariance()-cov).abs().max()/cov.abs().max())
        af=m.adjusted_frame(f);face=m.render(f,'T0');fr=draw(factored,af['F'],af['K'],f['rgb'].shape[1],f['rgb'].shape[0]);factorError=float((face['rgb']-fr['rgb']).abs().max())
        save_json(out/'factor.json',dict(relative=relative,renderMax=factorError))
        if relative>1e-5 or factorError>3e-4:raise ValueError('export_covariance_not_same_render')
        ref=make_frame(data,data['reference'],crop=False);af=m.adjusted_frame(ref);state=joined_state(m.head_state(af).to_world(af['C'],af['F'],m.scale),m.room.state(),m.body_state(af['name']))
        asset=out/'perturbed-contract-only.ply';export_state(state,asset);z=load_recorded_ply(asset,p.surface_count)
        reload=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],state.parts)
        h,w=af['rgb'].shape[:2];a=draw(state,af['C'],af['K'],w,h,unit_scale=m.scale);b=draw(reload,af['C'],af['K'],w,h,unit_scale=m.scale)
        plyError=float((a['rgb']-b['rgb']).abs().max());conservation=float((b['q'].sum(-1)-b['alpha']).abs().max())
        plyMean=float((a['rgb']-b['rgb']).abs().mean())
        baselineState=joined_state(DetailModel.head_state(m,af).to_world(af['C'],af['F'],m.scale),m.room.state(),m.body_state(af['name']))
        baselineAsset=out/'R0-contract-only.ply';export_state(baselineState,baselineAsset);bz=load_recorded_ply(baselineAsset,p.surface_count)
        baselineReload=GaussianState(bz['means'],bz['quats'],bz['scales'],bz['opacity'],bz['sh'][:,:4],baselineState.parts)
        ba=draw(baselineState,af['C'],af['K'],w,h,unit_scale=m.scale);bb=draw(baselineReload,af['C'],af['K'],w,h,unit_scale=m.scale)
        oldPlyMax=float((ba['rgb']-bb['rgb']).abs().max());oldPlyMean=float((ba['rgb']-bb['rgb']).abs().mean())
        # Exact same fields/scales roundtrip as the existing frozen R0. Float32
        # log-scale/normalized-quaternion serialization can move threshold/ties.
        # Retain original absolute screen failure; compare new excess separately.
        absolutePlyPassed=plyError<=3e-4 and conservation<=1e-5
        regressionPlyPassed=plyMean<=oldPlyMean+1e-6 and plyError<=oldPlyMax+3e-4 and conservation<=1e-5
        save_json(out/'ply-numerical.json',dict(newMax=plyError,newMean=plyMean,oldMax=oldPlyMax,oldMean=oldPlyMean,absolutePassed=absolutePlyPassed,regressionPassed=regressionPlyPassed,exactSerializationClaim=False))
    if exact_state_hash(p)!=before:raise ValueError('baseline_portrait_parameters_changed')
    save_json(out/'result.json',dict(sourceHash=data['sourceHash'],baselineCheckpointHash=contract['checkpointHash'],zeroFieldNativeErrors=zeroErrors,nonSkinMeansExact=equalMeans,nonSkinCovarianceExact=equalCov,portraitParametersExact=True,gradientMax=float(grad.abs().max()),gradientNonzero=int((grad!=0).sum()),covarianceRelativeMax=relative,factorRenderMax=factorError,plyRenderMax=plyError,plyRenderMean=plyMean,baselinePlyMax=oldPlyMax,baselinePlyMean=oldPlyMean,absolutePlyScreenPassed=absolutePlyPassed,qConservationMax=conservation,assetHash=sha(asset),assetRole='synthetic_field_contract_test_not_person_quality',renderAndGeometryContractPassed=True,plyRegressionPassed=regressionPlyPassed,allPassed=absolutePlyPassed and regressionPlyPassed,published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.stage,a.out)
