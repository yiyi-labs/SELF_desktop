"""Frozen-person local room counterfactuals, source-constrained covariance repair."""
import copy,json,time
import numpy as np,torch,cv2
from scipy.spatial.transform import Rotation
from reconstruction_portrait_pipeline import make_frame,draw,metrics
from reconstruction_portrait_model import joined_state,GaussianState
from reconstruction_surface_patch import weights
from reconstruction_components_v3 import save_json,exact_state_hash
from reconstruction_research_state import save_checkpoint
from audit_detail_controlled import png


def scene_state(model,f):
    f=model.adjusted_frame(f);head=model.head_state(f).to_world(f['C'],f['F'],model.scale)
    return joined_state(head,model.room.state(),model.body_state(f['name']))


@torch.no_grad()
def evaluate(model,data,names,out):
    out.mkdir();rows={}
    for name in names:
        f=make_frame(data,name,crop=False);r=model.render(f,'T2');rows[name]=metrics(r,f)
        x0,y0,x1,y1=make_frame(data,name)['rectangle']
        png(out/name,[f['rgb'][y0:y1,x0:x1].cpu().numpy(),r['rgb'][y0:y1,x0:x1].cpu().numpy()])
        np.savez_compressed(out/(name+'.npz'),rgb=r['rgb'].cpu().numpy(),alpha=r['alpha'].cpu().numpy(),q=r['q'].cpu().numpy())
    save_json(out/'metrics.json',rows);return rows


def run_occlusion(model,data,plan,out,contract):
    out.mkdir();start=time.perf_counter();person_hash=exact_state_hash(model.portrait);pose_hash=exact_state_hash(model.pose)
    for p in model.parameters():p.requires_grad_(False)
    names=[n for n in plan['train'] if n in data['worlds']]
    # Evenly spaced TRAIN observations only, fixed by list order, not face error.
    names=[names[i] for i in np.linspace(0,len(names)-1,6).round().astype(int)]
    testnames=list(dict.fromkeys(names+data['development']));room=model.room;nh=len(model.portrait.role);nr=len(room.params['means'])
    sums=torch.zeros(nr,device='cuda');rows=[]
    for name in names:
        f=make_frame(data,name,crop=False);s=scene_state(model,f);face=f['masks']['face_core']|f['masks']['glasses_visible']|f['masks']['face_boundary']
        value,info=weights(s,f['C'],f['K'],f['fullSize'][0],f['fullSize'][1],face,model.scale);local=value[nh:nh+nr];sums+=local/face.sum()
        rows.append({'name':name,'totalFaceRoomContribution':float(local.sum()/face.sum()),'contributors':int((local>.1).sum())})
    seed=data['room'];lookup={}
    for i,(kind,sid) in enumerate(zip(seed['source_kind'],seed['source_id'])):lookup.setdefault((int(kind),int(sid)),[]).append(i)
    measured={int(sid):xyz for sid,xyz,kind in zip(seed['source_id'],seed['xyz'],seed['source_kind']) if kind==0}
    groups={};ambiguous=[]
    for i in torch.where(sums>.0001)[0].cpu().tolist():
        kind=int(room.metadata['source_kind'][i]);sid=int(room.metadata['source_id'][i]);indices=lookup.get((kind,sid),[])
        triangles={tuple(sorted(map(int,seed['triangle_sources'][j]))) for j in indices}
        if len(triangles)!=1 or kind!=1:
            ambiguous.append({'index':i,'uid':int(room.metadata['point_uid'][i]),'kind':kind,'id':sid,'weight':float(sums[i]),'reason':'no_unique_supported_triangle'});continue
        key=next(iter(triangles));groups.setdefault(key,[]).append(i)
    ranked=sorted(groups,key=lambda key:float(sums[groups[key]].sum()),reverse=True)[:3]
    report={'selectionViews':names,'perView':rows,'unresolvedSources':ambiguous,'sourceGroups':[],'personFrozen':True,'faceHash':person_hash,'poseHash':pose_hash,'release':False}
    before=evaluate(model,data,testnames,out/'before');base=copy.deepcopy(room.state_dict());changes=[]
    # Counterfactual removal is diagnostic only. The repair below never removes
    # any point or changes alpha/colour and never moves the whole room.
    for number,key in enumerate(ranked):
        ids=torch.tensor(groups[key],device='cuda');source=np.stack([measured[k] for k in key]);center=source.mean(0);_,_,vt=np.linalg.svd(source-center);normal=vt[-1]
        entry={'triangleIDs':list(key),'indices':ids.cpu().tolist(),'pointUIDs':room.metadata['point_uid'][ids].cpu().tolist(),'faceWeight':float(sums[ids].sum()),'anchors':source.tolist()}
        with torch.no_grad():room.params['opacities'][ids]=-30
        cf=evaluate(model,data,testnames,out/f'counterfactual-{number}')
        room.load_state_dict(base)
        entry['counterfactual']={n:{'faceL1Delta':cf[n]['face']['fixedRgbL1']-before[n]['face']['fixedRgbL1'],
            'roomL1Delta':cf[n]['room']['fixedRgbL1']-before[n]['room']['fixedRgbL1'],'roomHoleDelta':cf[n]['room']['hole']-before[n]['room']['hole']} for n in testnames}
        # Plane depth precision: one native pixel at observed anchor depth.
        depths=[]
        for name in names:
            C=data['worlds'][name];z=(source@C[:3,:3].T+C[:3,3])[:,2];depths.extend(z[z>0].tolist())
        if not depths:entry['blocked']='no_positive_anchor_depth';report['sourceGroups'].append(entry);continue
        sigma=float(np.median(depths)/data['K'][0,0]*2.)
        s=room.state();cov=s.covariance()[ids].cpu().numpy();means=s.means[ids].cpu().numpy();distance=(means-center)@normal
        normalvar=np.einsum('i,nij,j->n',normal,cov,normal);normal_sigma=np.sqrt(normalvar.clip(0));projected=means-distance[:,None]*normal
        # No extrapolation: the centre must lie inside the source triangle.
        uv=np.linalg.lstsq((source[1:]-source[0]).T,(projected-source[0]).T,rcond=None)[0].T;bary=np.c_[1-uv.sum(1),uv]
        valid=(bary.min(1)>=0)&(np.abs(distance)<sigma*4)&(normal_sigma>sigma)
        entry.update(normal=normal.tolist(),pixelDerivedNormalSigma=sigma,meanPlaneDistance=distance.tolist(),normalSigma=normal_sigma.tolist(),eligible=valid.tolist(),
            interpretation='bounded source-supported surface hypothesis; 2px depth precision is an uncertainty bound, not measured truth')
        if valid.any():
            repaired=[]
            for V in cov[valid]:
                ratio=min(1.,sigma/np.sqrt(normal@V@normal));G=np.eye(3)+(ratio-1)*np.outer(normal,normal);repaired.append(G@V@G.T)
            vals,vec=np.linalg.eigh(np.array(repaired));neg=np.linalg.det(vec)<0;vec[neg,:,0]*=-1;q=Rotation.from_matrix(vec).as_quat()[:,[3,0,1,2]]
            changes.append((ids[torch.tensor(valid,device='cuda')],projected[valid],.5*np.log(vals.clip(1e-12)),q))
            entry['action']='constrain_normal_thickness_and_small_plane_residual; tangent_variance, opacity, SH retained'
        else:entry['action']='unchanged_no_source_supported_repair'
        report['sourceGroups'].append(entry)
    # Apply once to a copy of the frozen state; no tuning after dev inspection.
    with torch.no_grad():
        for ids,means,scales,quat in changes:
            room.params['means'][ids]=torch.tensor(means,device='cuda',dtype=torch.float32)
            room.params['scales'][ids]=torch.tensor(scales,device='cuda',dtype=torch.float32)
            room.params['quats'][ids]=torch.tensor(quat,device='cuda',dtype=torch.float32)
    after=evaluate(model,data,testnames,out/'after');changed=sum(len(c[0]) for c in changes)
    report.update(changedRoomPoints=changed,before=before,after=after,seconds=time.perf_counter()-start,optimizerSteps=0,
        alphaUnchanged=torch.equal(room.params['opacities'],base['params.opacities']),SHUnchanged=torch.equal(room.params['sh'],base['params.sh']),
        note='counterfactual removal never becomes delivered model; unknown sources remain unchanged')
    assert person_hash==exact_state_hash(model.portrait) and pose_hash==exact_state_hash(model.pose)
    save_checkpoint(out/'candidate.pt',model,{}, {},stage='O1-frozen-T2',step=0,contract=contract,extra={'roomMetadata':room.metadata,'bodySources':model.body_sources,'report':report})
    save_json(out/'result.json',report)
    # No automatic handoff, even if local counterfactual/repair looks better.
    room.load_state_dict(base);return {k:v for k,v in report.items() if k not in ('before','after','unresolvedSources')}
