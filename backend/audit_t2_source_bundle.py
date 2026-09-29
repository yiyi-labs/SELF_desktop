"""One bounded O1 source-bundle recovery, not a global seed boundary.
Only face-contributing descendants with verified original static observations
are eligible. Sparse bundle support does not certify a complete wall surface.
"""
import argparse,copy,json,shutil,time
from pathlib import Path
import numpy as np,torch,pycolmap
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from reconstruction_components_v3 import load_v3_prepared,save_json,sha,exact_state_hash
from reconstruction_portrait_pipeline import initialize_scene
from reconstruction_detail_controlled import DetailModel
from audit_portrait_priority_handoff import restore_tensors
from reconstruction_research_state import save_checkpoint
from reconstruction_t2_local import evaluate


def run(a):
    out=a.output;out.mkdir(exist_ok=False);start=time.perf_counter();data=load_v3_prepared(a.prepared);plan=json.loads((a.run/'observations.json').read_text())
    shutil.copyfile(a.prepared/'cloth_supported_seeds.npz',out/'cloth_supported_seeds.npz');scene=initialize_scene(data,out);model=DetailModel(scene,data,plan['train']);model.enable_components(data,plan['train']);del scene
    ck=torch.load(a.run/'R0-frozen.pt',map_location='cuda',weights_only=False);restore_tensors(model,ck['model']);model.room.metadata=ck['extra']['roomMetadata'];model.body_sources=ck['extra']['bodySources']
    for p in model.parameters():p.requires_grad_(False)
    old=json.loads((a.run/'O1/result.json').read_text());names=old['selectionViews'];allnames=list(dict.fromkeys(names+data['development']));room=model.room
    before=old['before'];base=copy.deepcopy(room.state_dict());person_hash=exact_state_hash(model.portrait);groups={}
    for r in old['unresolvedSources']:
        if r['kind']==0:groups.setdefault(r['id'],[]).append(r)
    selected=sorted(groups,key=lambda k:sum(r['weight'] for r in groups[k]),reverse=True)[:3]
    mapping=pycolmap.Reconstruction(data['staticMap']);results=[];changes=[];s0=room.state();means=s0.means.cpu().numpy();cov=s0.covariance().cpu().numpy()
    for sid in selected:
        records=groups[sid];ids=[r['index'] for r in records];p=mapping.points3D[sid];obs=[]
        for track in p.track.elements:
            im=mapping.images[track.image_id];name=im.name
            if name not in data['train'] or name not in data['worlds']:continue
            camera=mapping.cameras[im.camera_id];uv=im.points2D[track.point2D_idx].xy
            ray=camera.cam_from_img(uv);xy=data['K']@np.r_[ray,1.];xy=xy[:2]/xy[2];x,y=np.rint(xy).astype(int);mask=data['labels'][name];h,w=mask['room_visible'].shape
            if not (0<=x<w and 0<=y<h) or not mask['room_visible'][y,x] or mask['unknown_or_occluded'][y,x]:continue
            obs.append((name,data['worlds'][name],xy))
        row={'sourceID':sid,'indices':ids,'uids':[r['uid'] for r in records],'faceWeight':sum(r['weight'] for r in records),'observations':[{'name':n,'rectifiedXY':uv.tolist()} for n,C,uv in obs],
            'originalXYZ':p.xyz.tolist(),'originalCOLMAPError':p.error,'sourceMeaning':'estimated static track, not independently measured surface'}
        # Counterfactual group removal determines collateral effects only.
        with torch.no_grad():room.params['opacities'][ids]=-30
        cf=evaluate(model,data,allnames,out/f'counterfactual-{sid}');room.load_state_dict(base)
        row['counterfactual']={n:{'faceDelta':cf[n]['face']['fixedRgbL1']-before[n]['face']['fixedRgbL1'],
            'roomDelta':cf[n]['room']['fixedRgbL1']-before[n]['room']['fixedRgbL1'],'roomHoleDelta':cf[n]['room']['hole']-before[n]['room']['hole']} for n in allnames}
        if len(obs)<3:row['blocked']='fewer_than_three_valid_static_track_observations';results.append(row);continue
        def residual(x):
            r=[]
            for name,C,uv in obs:
                v=C[:3,:3]@x+C[:3,3];q=data['K']@v;r.extend(q[:2]/q[2]-uv)
            return np.array(r)
        fit=least_squares(residual,p.xyz,max_nfev=20,loss='huber',f_scale=1.)
        eigen,V=np.linalg.eigh(fit.jac.T@fit.jac);condition=float(eigen[-1]/max(eigen[0],1e-12));err=float(np.sqrt(np.mean(residual(fit.x)**2)))
        row.update(fitXYZ=fit.x.tolist(),reprojectionRMS=err,condition=condition)
        if condition>1e6 or err>2.5:row['blocked']='source_bundle_unreliable';results.append(row);continue
        uncertainty=V@np.diag(max(1.,err)**2/np.maximum(eigen,1e-9))@V.T
        # Experimental recovery: preserve each selected kernel's tangent spread
        # where supported by the bundle, bound unsupported drift to 3 sigma.
        # This is not applied to all GS and is NOT accepted as a wall truth model.
        ev,Q=np.linalg.eigh(uncertainty);bound=3*np.sqrt(ev.clip(1e-10));applied=[]
        for i in ids:
            local=(means[i]-fit.x)@Q;distance=float(np.linalg.norm(local/bound))
            var=Q.T@cov[i]@Q;over=np.sqrt(np.diag(var).clip(1e-12))/bound
            if distance<=3 and max(over)<=3:continue
            moved=local/max(1.,distance);position=fit.x+Q@moved
            G=Q@np.diag(np.minimum(1.,1/over))@Q.T;newcov=G@cov[i]@G.T
            value,vec=np.linalg.eigh(newcov)
            if np.linalg.det(vec)<0:vec[:,0]*=-1
            q=Rotation.from_matrix(vec).as_quat()[[3,0,1,2]]
            changes.append((i,position,.5*np.log(value.clip(1e-12)),q))
            applied.append({'index':i,'priorXYZ':means[i].tolist(),'bundleMahalanobis3Sigma':distance,'priorSigmaOver3Sigma':over.tolist(),'repairedXYZ':position.tolist()})
        row.update(bundleCovariance=uncertainty.tolist(),threeSigmaAxes=bound.tolist(),applied=applied,
            hypothesis='recover unsupported source-lineage spread; remaining wall coverage must be independently checked, not inferred from this point')
        results.append(row)
    with torch.no_grad():
        for i,pos,ls,q in changes:
            room.params['means'][i]=torch.tensor(pos,device='cuda',dtype=torch.float32);room.params['scales'][i]=torch.tensor(ls,device='cuda',dtype=torch.float32);room.params['quats'][i]=torch.tensor(q,device='cuda',dtype=torch.float32)
    after=evaluate(model,data,allnames,out/'after');assert person_hash==exact_state_hash(model.portrait)
    report={'groups':results,'changedPoints':len(changes),'before':before,'after':after,'seconds':time.perf_counter()-start,'frozenPortraitHash':person_hash,
        'opacityChanged':False,'SHChanged':False,'pointDeletion':0,'optimizerSteps':0,'localPointRefitMaximumEvaluations':20,'release':False,
        'limits':'source bundle bounds are a recovery hypothesis for diagnosed floaters, not a final surface support boundary; room collateral losses remain failures'}
    save_json(out/'result.json',report);save_checkpoint(out/'candidate.pt',model,{}, {},stage='O1-source-bundle-recovery',step=0,contract=ck['contract'],extra={'roomMetadata':room.metadata,'bodySources':model.body_sources,'report':report})
    shutil.copyfile(Path(__file__),out/Path(__file__).name);save_json(out/'source.json',{'scriptSha256':sha(Path(__file__)),'inputCheckpoint':sha(a.run/'R0-frozen.pt'),'reference':data['reference'],'sourceSha256':data['sourceHash']})
    print(json.dumps({'changedPoints':len(changes),'seconds':report['seconds']}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('run',type=Path);p.add_argument('output',type=Path);run(p.parse_args())
