"""Same-budget R0 appearance control vs bounded shared surface + recovery."""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch
from reconstruction_evidence_stage import load_stage
from reconstruction_photometric_surface import PhotometricSurfaceModel
from reconstruction_portrait_pipeline import make_frame,masked_mean,metrics
from reconstruction_reference_static import valid_window_structure
from reconstruction_detail_controlled import pixel_structure
from reconstruction_research_state import save_checkpoint,restore_checkpoint,FrameSampler,rng_state,restore_rng
from reconstruction_components_v3 import save_json,sha,exact_state_hash
from run_haze_shared_surface import export_state
from reconstruction_portrait_model import joined_state
from run_dense_surface_training import evaluation

def run(manifest,out,steps=240):
    start=time.perf_counter();out=Path(out);torch.manual_seed(93041);np.random.seed(93041)
    data,plan,m,contract=load_stage(manifest,out,model_class=PhotometricSurfaceModel)
    for n in ('run_photometric_surface_recovery.py','reconstruction_photometric_surface.py'):
        shutil.copyfile(Path(__file__).with_name(n),out/'algorithm-source'/n)
    contract.update(sources={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')},scope='fixed topology shared normal field; non-skin unchanged; complete T2 evaluation')
    p=m.portrait;labels=m.component_origin[p.origin_index[:p.surface_count]];ids=p.triangle_ids[:p.surface_count];supported=p.origin_index[:p.surface_count][labels==0]
    allowed=torch.unique(p.faces[ids[labels==0]].reshape(-1));m.active_vertices[allowed]=True
    # Freeze the one-ring boundary; no independently claimed boundary displacement.
    active=m.active_vertices.clone();edges=p.edges;boundary=edges[(active[edges[:,0]]!=active[edges[:,1]])];m.active_vertices[torch.unique(boundary.reshape(-1))]=False
    initial={k:v.detach().clone() for k,v in m.state_dict().items()};random=rng_state();raw=evaluation(m,data,plan,out/'R0-images');branches={};assets={}
    config=dict(steps=steps,geometryStart=80,geometryStop=180,geometryEvery=4,recoverySteps=60,normalBoundNativePixels=3,covarianceTransport='orientation_only_standard_GS; no_affine_shear_claim',topology='fixed',pose='F/K/reference/scale/identity/expression fixed',seed=93041,nativeFullFrame=True,published=False)
    save_json(out/'config.json',config);save_json(out/'contract.json',contract)
    for label,geometry in [('appearance-control',False),('shared-surface',True)]:
        m.load_state_dict(initial);restore_rng(random);m._transport_cache.clear()
        for v in m.parameters():v.requires_grad_(False)
        rates={'sh':.0015,'opacity_logits':.004,'log_scales':.001,'quats':.0002};ops={k:torch.optim.Adam([getattr(p,k)],lr=lr) for k,lr in rates.items()};ops['surface']=torch.optim.Adam([m.surface_control],lr=.002)
        sampler=FrameSampler(plan['train'],93041);branch=out/label;branch.mkdir();extra={'roomMetadata':m.room.metadata,'bodySources':m.body_sources,'config':config};curve=[]
        def save(n,step):save_checkpoint(branch/(n+'.pt'),m,ops,{'views':sampler},stage=label,step=step,contract=contract,strategy={'density':'fixed','events':[]},extra=extra)
        save('initial',0);torch.cuda.reset_peak_memory_stats();branch_start=time.perf_counter();skin=(m.component_origin[p.origin_index]==0)&(p.role!=2)
        for step in range(1,steps+1):
            geo=geometry and config['geometryStart']<=step<=config['geometryStop'] and step%4==0
            for k in rates:getattr(p,k).requires_grad_(not geo)
            m.surface_control.requires_grad_(geo)
            for op in ops.values():op.zero_grad(set_to_none=True)
            f=make_frame(data,sampler.next(),crop=False);r=m.render(f,'T0');valid=(f['masks']['face_core']|f['masks']['face_boundary'])&~f['masks']['glasses_visible']&~f['masks']['unknown_or_occluded'];err=(r['rgb']-f['rgb']).abs().mean(-1)
            loss=masked_mean(err,valid)+.12*valid_window_structure(r['rgb'],f['rgb'],valid)+.25*pixel_structure(r['rgb'],f['rgb'],valid)+.03*masked_mean((1-r['alpha']).square(),valid)
            loss+=.0002*(p.log_scales-initial['portrait.log_scales']).square().mean()+.0005*p.sh[:,1:].square().mean()
            if geo:
                u=m.surface_control.tanh();loss+=.002*u.square().mean()+.008*(u[edges[:,0]]-u[edges[:,1]]).square().mean()
            if not torch.isfinite(loss):raise ValueError('nonfinite_surface_loss')
            loss.backward()
            for k in rates:
                v=getattr(p,k)
                if v.grad is not None:v.grad[~skin]=0
            for n,v in m.named_parameters():
                if v.grad is not None and not torch.isfinite(v.grad).all():raise ValueError('nonfinite_surface_gradient:'+n)
            if geo:ops['surface'].step()
            else:
                for k in rates:ops[k].step()
            with torch.no_grad():p.log_scales.copy_(torch.maximum(torch.minimum(p.log_scales,initial['portrait.log_scales']+np.log(1.2)),initial['portrait.log_scales']-np.log(1.2)))
            if step==1 or step%40==0:
                row=dict(step=step,name=f['name'],geometry=geo,loss=float(loss.detach()));curve.append(row);print(label,json.dumps(row),flush=True)
            if step==steps//2:save('mid',step)
            if time.perf_counter()-branch_start>600 or torch.cuda.memory_allocated()/1048576>7100:raise ValueError('finite_surface_resources')
        save('candidate-final',steps);value=evaluation(m,data,plan,branch/'final-images');field=m.field().detach().cpu().numpy();np.savez_compressed(branch/'surface-field.npz',field=field,normal=m.canonical_normals.cpu().numpy(),active=m.active_vertices.cpu().numpy())
        failures=[]
        for n in plan['development']+plan['audit']:
            for part in ('face','hair','glasses'):
                if value[n][part]['fixedRgbL1']>raw[n][part]['fixedRgbL1']+(.001 if part=='face' else .003):failures.append(part+':'+n)
            if 'T2' in raw[n]:
                for part in ('room','neckCloth','face'):
                    if value[n]['T2'][part]['fixedRgbL1']>raw[n]['T2'][part]['fixedRgbL1']+.003:failures.append('T2-'+part+':'+n)
                if value[n]['T2']['faceRoomContribution']>raw[n]['T2']['faceRoomContribution']+.005:failures.append('T2-occlusion:'+n)
        f=m.adjusted_frame(make_frame(data,data['reference'],crop=False));s=joined_state(m.head_state(f).to_world(f['C'],f['F'],m.scale),m.room.state(),m.body_state(f['name']));asset=branch/'fixed-research.ply';export_state(s,asset)
        assets[label]=dict(path=str(asset),sha256=sha(asset),reference=f['name'],count=len(s.means));branches[label]=dict(metrics=value,failures=failures,curve=curve,seconds=time.perf_counter()-branch_start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,surfaceMaxOffset=float(np.linalg.norm(field,axis=1).max()),surfaceUpdatedVertices=int((np.linalg.norm(field,axis=1)>1e-10).sum()),parameterChanges={k:float((v-initial[k]).detach().abs().mean()) for k,v in m.named_parameters() if k in initial},nonregressionScreenPassed=not failures,releaseQualityPassed=False)
        restore_checkpoint(branch/'initial.pt',m,ops,{'views':sampler},contract=contract,device='cuda');save('restored',0)
    save_json(out/'result.json',dict(baseline=raw,branches=branches,assets=assets,seconds=time.perf_counter()-start,published=False,completeScenePassed=False,geometryEvidence='shared multiview photometric research with FLAME prior; new TAPIR tracks did not establish depth, no claim to measured details'))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.stage,a.out)
