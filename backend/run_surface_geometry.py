"""Shared free-XYZ measurement solve; soft surface prior, fixed identity/K/F.
Measurements and model geometry are distinct. One physical track has one X,
with expression transport from its initial local chart, not frozen barycentric
position. Data-only depth singular values are recorded before priors.
"""
import argparse,json,time,copy
from pathlib import Path
import cv2,numpy as np,torch
from scipy.optimize import least_squares
from scipy.sparse import coo_matrix,eye
from scipy.sparse.linalg import lsqr
from reconstruction_evidence_stage import load_stage
from reconstruction_surface_evidence import measured_tracks,project
from reconstruction_patch_correspondence import intersect
from reconstruction_components_v3 import save_json
from reconstruction_shared_surface import triangle_frames
from reconstruction_portrait_pipeline import make_frame
from reconstruction_detail_controlled import evaluate_face
from reconstruction_research_state import save_checkpoint


def run(manifest,out,cache=None):
    out=Path(out);start=time.perf_counter();data,plan,m,contract=load_stage(manifest,out);p=m.portrait;faces=p.faces.cpu().numpy();base=p.surface_residual.detach().cpu().numpy();K=data['K'];reference=p.reference_mesh.detach().cpu().numpy()+base
    names=sorted(set(data['train'])-set(plan['audit'])-set(plan['development']));chains=[]
    for n in names:
        if not chains or int(n[6:10])-int(chains[-1][-1][6:10])>3 or len(chains[-1])>=6:chains.append([])
        chains[-1].append(n)
    chains=[c for c in chains if len(c)>=4][:10]
    config={'trackWindows':chains,'maxCornersPerWindow':180,'solver':'scipy_TRF_soft_l1','maxNfevPerTrack':80,'fixed':'K,F,identity,scale,expression,topology,SH/alpha/scale','surfacePriorPixels':3.,'boundPixels':6.,'minimumDataSingularRatio':.01,'thirdTolerancePixels':.5,'thirdP90Tolerance':1.,'appearanceBudgetSteps':160,'appearanceViewsPerStep':2,'published':False}
    save_json(out/'config.json',config);tracks=[];stats=[];frames={}
    def frame(n):
        if n not in frames:
            f=m.adjusted_frame(make_frame(data,n,crop=False));mesh=f['mesh'].cpu().numpy()+base;frames[n]=(mesh,f['F'].detach().cpu().numpy())
        return frames[n]
    if cache:
        stored=json.loads(Path(cache).read_text());tracks=stored["tracks"];stats=stored["measurements"]
    for ci,chain in enumerate([] if cache else chains):
        ims={n:(data['rgb'][n]*255).round().astype(np.uint8) for n in chain};masks={}
        for n in chain:
            lab=data['labels'][n];mask=lab['face_core']&~lab['glasses_visible']&~lab['unknown_or_occluded'];marks=data['local'][n]['marks'];lip=marks[13,1];lip*=1920 if lip<=1.5 else 1;mask=mask.copy();mask[int(lip)-5:]=False;masks[n]=mask
        measured,stat=measured_tracks(ims,masks,chain,max_corners=180,refine=True);stat['names']=chain;stats.append(stat)
        for t in measured:
            if len(t['observations'])<4:continue
            n=t['observations'][0]['name'];mesh,F=frame(n);hit=intersect(mesh,faces,F,K,np.array(t['observations'][0]['uv']))
            if hit is None:continue
            tid,bary=hit;tri=faces[tid];x0=(mesh[tri]*bary[:,None]).sum(0)
            B0=triangle_frames(torch.tensor(mesh[tri][None])).numpy()[0]
            obs=[]
            for o in t['observations']:
                mt,Ft=frame(o['name']);Bt=triangle_frames(torch.tensor(mt[tri][None])).numpy()[0];R=Bt@B0.T;q=(mt[tri]*bary[:,None]).sum(0)-R@x0;obs.append({**o,'R':R,'q':q,'F':Ft})
            metric=float((x0@F[:3,:3].T+F[:3,3])[2]/K[0,0]);fit=obs[:-1]
            def raw_project(x,o):return project((o['R']@x+o['q'])[None],o['F'],K)[0][0]
            def datares(v,oo=fit):return np.concatenate([(raw_project(x0+v*metric,o)-o['uv'])/o['sigma'] for o in oo])
            def residual(v):return np.r_[datares(v),v/3.]
            before=[float(np.linalg.norm(raw_project(x0,o)-o['uv'])) for o in obs]
            J=np.stack([(datares(np.eye(3)[k]*.001)-datares(-np.eye(3)[k]*.001))/.002 for k in range(3)],1);sv=np.linalg.svd(J,compute_uv=False)
            sol=least_squares(residual,np.zeros(3),bounds=(-np.ones(3)*6,np.ones(3)*6),loss='soft_l1',f_scale=1.,max_nfev=80,x_scale='jac')
            xyz=x0+sol.x*metric;after=[float(np.linalg.norm(raw_project(xyz,o)-o['uv'])) for o in obs]
            # Leave weak-depth tracks at prior. No learned suppression of weights.
            reliable=bool(sv[-1]/sv[0]>=.01 and after[-1]<=before[-1]+.5 and np.median(after[:-1])<np.median(before[:-1]) and np.linalg.norm(sol.x)<5.5)
            delta=B0.T@(xyz-x0);Bref=triangle_frames(torch.tensor(reference[tri][None])).numpy()[0];canonical_delta=Bref@delta
            tracks.append({'id':t['id'],'triangle':int(tid),'bary':bary.tolist(),'initialXYZ':x0.tolist(),'solvedXYZ':xyz.tolist(),'canonicalDelta':canonical_delta.tolist(),'metric':metric,'observations':t['observations'],'before':before,'after':after,'dataSingularValues':sv.tolist(),'reliableDepth':bool(sv[-1]/sv[0]>=.01),'usedForSurface':reliable,'nfev':sol.nfev})
        print(json.dumps({'chain':chain,'newTracks':len(measured),'solvedTotal':len(tracks)}),flush=True)
    save_json(out/'tracks.json',{'measurements':stats,'tracks':tracks})
    good=[t for t in tracks if t['usedForSurface']];vcount=len(reference);rr=[];cc=[];vv=[]
    for i,t in enumerate(good):
        for v,b in zip(faces[t['triangle']],t['bary']):rr.append(i);cc.append(v);vv.append(b)
    A=coo_matrix((vv,(rr,cc)),shape=(len(good),vcount)).tocsr();edges=p.edges.cpu().numpy();allowed=set(int(v) for t in good for v in faces[t['triangle']])
    for _ in range(2):
        use=np.isin(edges,list(allowed)).any(1);allowed.update(edges[use].reshape(-1).tolist())
    allowed=np.array(sorted(allowed),int);L=coo_matrix((np.tile([1.,-1.],len(edges)),(np.repeat(np.arange(len(edges)),2),edges.reshape(-1))),shape=(len(edges),vcount)).tocsr()
    from scipy.sparse import vstack
    W=vstack([A[:,allowed],L[:,allowed]*.15,eye(len(allowed))*.08]).tocsr();rhs=np.array([t['canonicalDelta'] for t in good]);disp=np.zeros_like(reference)
    if len(good):
        for axis in range(3):disp[allowed,axis]=lsqr(W,np.r_[rhs[:,axis],np.zeros(len(edges)+len(allowed))],atol=1e-10,btol=1e-10,iter_lim=160)[0]
        maxnorm=np.linalg.norm(disp,axis=1).max();cap=float(np.median([t['metric'] for t in good]))*3
        if maxnorm>cap:disp*=cap/maxnorm
    np.savez_compressed(out/'surface-field.npz',displacement=disp,sourceTrackIds=np.array([t['id'] for t in good]))
    save_checkpoint(out/'initial.pt',m,{}, {},stage='free_shared_XYZ',step=0,contract=contract,extra={'roomMetadata':m.room.metadata,'bodySources':m.body_sources})
    evaluate_face(m,data,plan,out/'G0-images');m.measured_surface_field.copy_(torch.tensor(disp,device='cuda'))
    evaluate_face(m,data,plan,out/'G1-geometry-images')
    # Evaluate continuous surface, not just independently solved X variables.
    summaries={}
    for t in tracks:
        tri=faces[t['triangle']];bary=np.array(t['bary']);ds=(disp[tri]*bary[:,None]).sum(0);Bref=triangle_frames(torch.tensor(reference[tri][None])).numpy()[0]
        for j,o in enumerate(t['observations']):
            mt,F=frame(o['name']);Bt=triangle_frames(torch.tensor(mt[tri][None])).numpy()[0];x=(mt[tri]*bary[:,None]).sum(0)+Bt@Bref.T@ds;uv,_=project(x[None],F,K);err=float(np.linalg.norm(uv[0]-o['uv']));role='third' if j==len(t['observations'])-1 else 'fit'
            for key in (role,o['name']):summaries.setdefault(key,{'before':[],'after':[]});summaries[key]['before'].append(t['before'][j]);summaries[key]['after'].append(err)
    failures=[]
    for k,v in summaries.items():
        a=np.array(v['before']);b=np.array(v['after']);v.update(n=len(a),beforeMedian=float(np.median(a)),afterMedian=float(np.median(b)),beforeP90=float(np.quantile(a,.9)),afterP90=float(np.quantile(b,.9)))
        if v['afterMedian']>v['beforeMedian']+.5 or v['afterP90']>v['beforeP90']+1:failures.append(k)
    if not good:failures.append('no_reliable_free_depth')
    if 'third' not in summaries or summaries['third']['afterMedian']>=summaries['third']['beforeMedian']:failures.append('no_third_improvement')
    before=json.loads((out/'G0-images/metrics.json').read_text());after=json.loads((out/'G1-geometry-images/metrics.json').read_text())
    for n in plan['development']+plan['audit']:
        if after[n]['face']['fixedRgbL1']>before[n]['face']['fixedRgbL1']+.002:failures.append('RGB_regression:'+n)
    save_checkpoint(out/'candidate-final.pt',m,{}, {},stage='free_shared_XYZ',step=sum(t['nfev'] for t in tracks),contract=contract,extra={'roomMetadata':m.room.metadata,'bodySources':m.body_sources,'solver':'saved tracks XYZ + scipy diagnostics; no Adam in geometry'})
    result={'tracks':len(tracks),'reliableDepth':sum(t['reliableDepth'] for t in tracks),'surfaceTracks':len(good),'updatedVertices':int((np.linalg.norm(disp,axis=1)>1e-9).sum()),'maxDisplacement':float(np.linalg.norm(disp,axis=1).max()),'groups':summaries,'failures':failures,'geometryAccepted':not failures,'seconds':time.perf_counter()-start,'allocatedMiB':torch.cuda.max_memory_allocated()/1048576,'reservedMiB':torch.cuda.max_memory_reserved()/1048576,'published':False}
    save_json(out/'result.json',result)
    if failures:m.measured_surface_field.zero_();save_checkpoint(out/'restored.pt',m,{}, {},stage='free_shared_XYZ_restored',step=0,contract=contract,extra={'roomMetadata':m.room.metadata,'bodySources':m.body_sources})
    print(json.dumps({k:v for k,v in result.items() if k!='groups'}),flush=True)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--manifest',required=True);a.add_argument('--out',required=True);a.add_argument('--tracks-cache');s=a.parse_args();run(s.manifest,s.out,s.tracks_cache)

