"""Fixed-topology shared canonical geometry and equal-budget appearance research.
Inputs are manifests and measured tracks, not a particular capture/frame layout.
"""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix,eye
from reconstruction_evidence_stage import load_stage
from reconstruction_canonical_surface import CanonicalSurfaceModel,vertex_rotations
from run_complete_geometry import collect_records
from reconstruction_surface_evidence import project
from reconstruction_portrait_pipeline import make_frame,masked_mean
from reconstruction_detail_controlled import evaluate_face
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import save_checkpoint,FrameSampler,restore_checkpoint,rng_state,restore_rng
from reconstruction_components_v3 import save_json,sha
from run_haze_shared_surface import export_state
from reconstruction_portrait_model import joined_state


def summary(v):
    return dict(count=len(v),median=float(np.median(v)),p90=float(np.quantile(v,.9)))


def run(manifest,measurements,old_tracks,out,steps=240,max_nfev=60):
    out=Path(out);start=time.perf_counter();data,plan,m,contract=load_stage(manifest,out,model_class=CanonicalSurfaceModel)
    shutil.copyfile(__file__,out/'algorithm-source'/Path(__file__).name)
    contract={**contract,"geometry":"one_canonical_vertex_field_same_D_for_measurement_and_render",
        "fixed":"K,F,C,scale,identity,expression,topology,hair,glasses,body,room",
        "maxNfev":max_nfev,"appearanceSteps":steps,"viewsPerStep":1,"seed":93030}
    save_json(out/'run-contract.json',contract);records,*_=collect_records(data,m,measurements,old_tracks)
    faces=m.portrait.faces.cpu().numpy();vertices=set()
    vertices={int(v) for t in records for v in faces[t['triangle']]}
    edges=m.portrait.edges.cpu().numpy()
    for _ in range(2):vertices.update(edges[np.isin(edges,list(vertices)).any(1)].reshape(-1).tolist())
    active=np.array(sorted(vertices));columns={int(v):i for i,v in enumerate(active)}
    N=len(active);metric=float(np.median([t['metric'] for t in records]));frames={};rot={}
    for n in sorted({o['name'] for t in records for o in t['obs']}):
        f=m.adjusted_frame(make_frame(data,n,crop=False));frames[n]=f
        rot[n]=vertex_rotations(m.canonical_reference,f['mesh']+m.surface_base,m.portrait.faces).cpu().numpy()
    observation_names=set(frames)
    if observation_names&(set(plan['development'])|set(plan['audit'])):
        raise ValueError("geometry_measurement_split_leakage")
    fit=[(t,o) for t in records for o in t['obs'][:-1]]
    es=[(columns[int(a)],columns[int(b)]) for a,b in edges if int(a) in columns and int(b) in columns]
    es=np.array(es,int)
    def xyz(t,o,field):
        tri=faces[t['triangle']];disp=np.stack([rot[o['name']][v]@field[columns[int(v)]] for v in tri])
        return o['R']@t['x0']+o['q']+(disp*t['bary'][:,None]).sum(0)
    def residual(raw):
        field=raw.reshape(N,3)*metric
        image=np.concatenate([(project(xyz(t,o,field)[None],o['F'],data['K'])[0][0]-o['uv'])/o['sigma'] for t,o in fit])
        smooth=(raw.reshape(N,3)[es[:,0]]-raw.reshape(N,3)[es[:,1]])*.15
        return np.r_[image,smooth.reshape(-1),raw*.08]
    J=lil_matrix((2*len(fit)+3*len(es)+3*N,3*N),dtype=int)
    for i,(t,o) in enumerate(fit):
        for v in faces[t['triangle']]:J[2*i:2*i+2,3*columns[int(v)]:3*columns[int(v)]+3]=1
    for i,(a,b) in enumerate(es):
        J[2*len(fit)+3*i:2*len(fit)+3*i+3,3*a:3*a+3]=1
        J[2*len(fit)+3*i:2*len(fit)+3*i+3,3*b:3*b+3]=1
    J[2*len(fit)+3*len(es):,:]=eye(3*N)
    init=np.zeros(3*N);print("CANONICAL_SOLVE",len(records),N,flush=True)
    result=least_squares(residual,init,jac_sparsity=J.tocsr(),bounds=(-np.full(3*N,4.),np.full(3*N,4.)),
        loss='soft_l1',max_nfev=max_nfev,x_scale='jac',ftol=1e-6)
    field=np.zeros_like(m.canonical_field.cpu().numpy());field[active]=result.x.reshape(N,3)*metric
    np.savez_compressed(out/'canonical-field.npz',field=field,activeVertices=active,metricPerPixel=metric)
    groups={}
    for label,delta in [('R0',np.zeros_like(field)),('canonical',field)]:
        vv={'source':[],'target':[],'third':[]};rows=[]
        for t in records:
            err=[]
            for j,o in enumerate(t['obs']):
                x=xyz(t,o,delta[active]);uv,z=project(x[None],o['F'],data['K'])
                e=float(np.linalg.norm(uv[0]-o['uv']));k='source' if j==0 else 'third' if j==len(t['obs'])-1 else 'target'
                vv[k].append(e);err.append(e)
            rows.append(dict(id=t['id'],names=[o['name'] for o in t['obs']],errors=err))
        groups[label]={k:summary(v) for k,v in vv.items()};save_json(out/(label+'-tracks.json'),rows)
    save_json(out/'geometry.json',dict(groups=groups,nfev=result.nfev,success=result.success,
        updatedVertices=int((np.linalg.norm(field,axis=1)>1e-10).sum()),metricPerPixel=metric,
        uncertainty="measurement sigma kept in absolute native pixels; no per-track max-eigen normalization",
        baselineCheckpointHash=contract['checkpointHash']))
    # Exact same sampler/parameter set/budget; appearance is a bounded diagnostic,
    # not a geometry or publication waiver. Failed full-scene context stays frozen.
    original={k:v.detach().clone() for k,v in m.state_dict().items()};initial_rng=rng_state()
    base=evaluate_face(m,data,plan,out/'R0-images');comparisons={};paths={}
    for label,usefield in [('appearance-control',False),('canonical-appearance',True)]:
        m.load_state_dict(original);restore_rng(initial_rng);m._transport_cache.clear()
        if usefield:m.canonical_field.copy_(torch.as_tensor(field,device='cuda'))
        for p in m.parameters():p.requires_grad_(False)
        p=m.portrait;mask=(m.component_origin[p.origin_index]==0)&(p.role!=2)
        rates={'sh':.0015,'opacity_logits':.004,'log_scales':.001,'quats':.0002}
        optim={k:torch.optim.Adam([getattr(p,k)],lr=lr) for k,lr in rates.items()}
        for k in rates:getattr(p,k).requires_grad_(True)
        sampler=FrameSampler(plan['train'],93030);branch=out/label;branch.mkdir()
        extra={'roomMetadata':m.room.metadata,'bodySources':m.body_sources}
        save_checkpoint(branch/'initial.pt',m,optim,{'views':sampler},stage=label,step=0,contract=contract,
            strategy={'density':'fixed_topology'},extra=extra)
        initial={k:getattr(p,k).detach().clone() for k in rates};curve=[];torch.cuda.reset_peak_memory_stats()
        for step in range(1,steps+1):
            for op in optim.values():op.zero_grad(set_to_none=True)
            n=sampler.next();f=make_frame(data,n,crop=False);r=m.render(f,'T0')
            valid=(f['masks']['face_core']|f['masks']['face_boundary'])&~f['masks']['unknown_or_occluded']
            loss=masked_mean((r['rgb']-f['rgb']).abs().mean(-1),valid)+.12*valid_window_structure(r['rgb'],f['rgb'],valid)+.03*masked_mean((1-r['alpha']).square(),valid)
            loss+=.0002*(p.log_scales-initial['log_scales']).square().mean()+.0005*p.sh[:,1:].square().mean()
            if not bool(torch.isfinite(loss)):raise RuntimeError("nonfinite_loss_candidate_rejected")
            loss.backward()
            for k in rates:
                v=getattr(p,k)
                if v.grad is not None:
                    if not bool(torch.isfinite(v.grad).all()):raise RuntimeError("nonfinite_gradient_candidate_rejected:"+k)
                    v.grad[~mask]=0
            for op in optim.values():op.step()
            with torch.no_grad():
                p.log_scales.clamp_(initial['log_scales']-np.log(1.2),initial['log_scales']+np.log(1.2))
            if step==1 or step%40==0:curve.append(dict(step=step,name=n,loss=float(loss.detach())));print(label,json.dumps(curve[-1]),flush=True)
            if step==steps//2:save_checkpoint(branch/'mid.pt',m,optim,{'views':sampler},stage=label,step=step,contract=contract,strategy={'density':'fixed_topology'},extra=extra)
            if time.perf_counter()-start>1800 or torch.cuda.memory_allocated()>6.8*1024**3:raise RuntimeError("finite_research_budget")
        save_checkpoint(branch/'final.pt',m,optim,{'views':sampler},stage=label,step=steps,contract=contract,strategy={'density':'fixed_topology'},extra=extra)
        metrics=evaluate_face(m,data,plan,branch/'final-images');delta={k:float((getattr(p,k).detach()-v).abs().mean()) for k,v in initial.items()}
        comparisons[label]=dict(metrics=metrics,curve=curve,parameterMeanAbsChange=delta,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576)
        f=m.adjusted_frame(make_frame(data,data['reference'],crop=False))
        s=joined_state(m.head_state(f).to_world(f['C'],f['F'],m.scale),m.room.state(),m.body_state(f['name']))
        export_state(s,branch/'fixed-research.ply');paths[label]=dict(path=str(branch/'fixed-research.ply'),hash=sha(branch/'fixed-research.ply'),count=len(s.means),reference=f['name'])
        restore_checkpoint(branch/'initial.pt',m,optim,{'views':sampler},contract=contract,device='cuda')
        save_checkpoint(branch/'restored.pt',m,optim,{'views':sampler},stage=label+'_restored',step=0,contract=contract,strategy={'density':'fixed_topology'},extra=extra)
    m.load_state_dict(original)
    save_json(out/'result.json',dict(geometry=groups,baseline=base,branches=comparisons,assets=paths,
        elapsedSeconds=time.perf_counter()-start,published=False,productionChanged=False,
        geometryTolerancePassed=all(groups['canonical'][k]['median']<=2 and groups['canonical'][k]['p90']<=4 for k in groups['canonical']),
        completeScenePassed=False,note="Diagnostic appearance does not establish geometry correctness. Hair/body/room are frozen; no joint update. No independent blind audit."))
    print("SURFACE_TRANSPORT_RESEARCH_COMPLETE",flush=True)
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    for k in ['manifest','measurements','old-tracks','out']:ap.add_argument('--'+k,required=True)
    ap.add_argument('--steps',type=int,default=240);ap.add_argument('--max-nfev',type=int,default=60)
    a=ap.parse_args()
    if not 1<=a.steps<=400 or not 1<=a.max_nfev<=80:raise ValueError("finite_budget_required")
    existed=Path(a.out).exists()
    try:run(a.manifest,a.measurements,a.old_tracks,a.out,a.steps,a.max_nfev)
    except Exception as exc:
        if not existed and Path(a.out).exists():
            save_json(Path(a.out)/'failure.json',dict(reason=str(exc),exception=type(exc).__name__,published=False,assetValidForRelease=False))
        raise
