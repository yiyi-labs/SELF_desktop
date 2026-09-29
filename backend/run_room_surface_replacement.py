"""Bounded real-MVS room replacement transaction; all T2 groups always render.
Family ID locates suspects; each new point is a measured multi-view surface,
not an expansion of that sparse source into a plane.
"""
import argparse,json,time,copy
from pathlib import Path
import cv2,numpy as np,torch
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from reconstruction_evidence_stage import load_stage
from reconstruction_mvs_contract import read_mvs_cloud,explicit_retirement_mask
from reconstruction_components_v3 import FreeComponent,pick,save_json,sha
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_research_state import save_checkpoint,FrameSampler,restore_checkpoint
from reconstruction_reference_static import valid_window_structure
from reconstruction_surface_evidence import project
from run_haze_shared_surface import export_state
from audit_detail_controlled import png


def run(manifest,mvs,source_id,out,steps=180,retirement=None):
    out=Path(out).resolve();start=time.perf_counter();data,plan,m,contract=load_stage(manifest,out);mvs=Path(mvs);observations=json.loads((mvs/'contract.json').read_text());names=observations['names'];cloud=read_mvs_cloud(mvs/'dense.ply');xyz=cloud['xyz'];K=data['K'];C=data['worlds'];d=torch.device('cuda');t=lambda a:torch.as_tensor(a,device=d,dtype=torch.float32)
    import pycolmap
    mapping=pycolmap.Reconstruction(data['staticMap']);seed=mapping.points3D[source_id].xyz;reference=names[len(names)//2];seeduv,_=project(seed[None],C[reference],K);uv,z=project(xyz,C[reference],K);valid=(z>0)&(np.max(abs(uv-seeduv),axis=1)<180)&(np.linalg.norm(cloud['normal'],axis=1)>.8);ids=np.where(valid)[0];support=[];rgb=[];kept=[]
    for i in ids:
        colors=[];views=cloud['views'][i]
        if any(v<0 or v>=len(names) for v in views):raise ValueError('MVS view ID mapping mismatch')
        for vi in views:
            n=names[vi];u,depth=project(xyz[i:i+1],C[n],K);x,y=np.rint(u[0]).astype(int);lab=data['labels'][n]
            if depth[0]>0 and 1<=x<1079 and 1<=y<1919 and lab['room_visible'][y-1:y+2,x-1:x+2].all() and not lab['unknown_or_occluded'][y-1:y+2,x-1:x+2].any():colors.append(np.median(data['rgb'][n][y-1:y+2,x-1:x+2],axis=(0,1)))
        if len(colors)>=3:kept.append(i);support.append(len(colors));rgb.append(np.median(colors,axis=0))
    ids=np.array(kept);save_json(out/'selection.json',{'sourceLocator':source_id,'reference':reference,'sourceProjection':seeduv.tolist(),'nativePixelRadius':180,'MVS_total':len(xyz),'selected':len(ids),'cloudHash':sha(mvs/'dense.ply'),'physicalGeometry':'actual multi-view fused depths/normals, multiple surfaces allowed','oldFogFootprintIsNotTarget':True})
    if len(ids)<12:save_json(out/'result.json',{'blocked':'insufficient_valid_MVS_surface','points':len(ids)});return
    pts=xyz[ids];norm=cloud['normal'][ids];norm/=np.linalg.norm(norm,axis=1,keepdims=True);axis=np.tile([1.,0,0],(len(ids),1));axis[abs(norm[:,0])>.8]=[0,1,0];u=np.cross(axis,norm);u/=np.linalg.norm(u,axis=1,keepdims=True);v=np.cross(norm,u);q=Rotation.from_matrix(np.stack([u,v,norm],axis=-1)).as_quat()[:,[3,0,1,2]]
    nn=cKDTree(pts).query(pts,k=min(5,len(pts)))[0][:,1:].mean(1);_,depth=project(pts,C[reference],K);pixel=depth/K[0,0];tangent=np.clip(nn*.65,pixel*1.1,pixel*6);scales=np.stack([tangent,tangent,pixel*.25],1);sh=torch.zeros(len(ids),4,3,device=d);sh[:,0]=(t(rgb)-.5)/.28209479177387814
    gs=GaussianState(t(pts),t(q),t(scales),torch.full((len(ids),),.65,device=d),sh,torch.zeros(len(ids),dtype=torch.long,device=d));new=FreeComponent(gs,torch.tensor(ids,device=d),t(support),'world',float(np.median(pixel))*.5);new.offset.requires_grad_(False);new.register_buffer('stable_uid',torch.arange(len(ids),device=d)+int(m.room.metadata['point_uid'].max())+1);new.register_buffer('parent_uid',torch.full((len(ids),),-1,device=d,dtype=torch.long));oldstate=m.room.state();
    if retirement is None:raise ValueError('explicit_contribution_audited_UIDs_required_not_entire_family')
    authorization=json.loads(Path(retirement).read_text());uids=torch.tensor(authorization['uids'],device=d,dtype=torch.long)
    if sha(authorization['evidencePath'])!=authorization['evidenceHash']:raise ValueError('retirement_evidence_changed')
    remove=torch.tensor(explicit_retirement_mask(m.room.metadata['point_uid'].cpu(),m.room.metadata['source_id'].cpu(),m.room.metadata['source_kind'].cpu(),source_id,authorization['uids']),device=d)
    if int(remove.sum())!=len(uids) or not torch.all((m.room.metadata['source_id'][remove]==source_id)&(m.room.metadata['source_kind'][remove]==0)):raise ValueError('suspect_UID_or_source_mismatch')
    keep=~remove;remaining=pick(oldstate,keep);fixed={k:v.detach().clone() for k,v in new.state_dict().items()};rates={'sh':.004,'opacity':.02,'log_scales':.001,'quats':.0003};optim={k:torch.optim.Adam([getattr(new,k)],lr=lr) for k,lr in rates.items()};sampler=FrameSampler(names,92929);contract={**contract,'cloudHash':sha(mvs/'dense.ply'),'retiredUID':m.room.metadata['point_uid'][remove].tolist(),'stage':'finite_physical_room_surface_replacement','steps':steps};save_json(out/'training-contract.json',contract)
    regions={}
    for n in names:
        pix,_=project(pts,C[n],K);lo=np.maximum([0,0],np.floor(pix.min(0)-16)).astype(int);hi=np.minimum([1080,1920],np.ceil(pix.max(0)+17)).astype(int);mask=np.zeros((1920,1080),bool);mask[lo[1]:hi[1],lo[0]:hi[0]]=True;regions[n]=mask&data['labels'][n]['room_visible']&~data['labels'][n]['unknown_or_occluded']
    def render(n,candidate):
        f=m.adjusted_frame(make_frame(data,n,crop=False));room=joined_state(remaining,new.state()) if candidate else oldstate;s=joined_state(m.head_state(f).to_world(f['C'],f['F'],m.scale),room,m.body_state(n));return draw(s,f['C'],f['K'],1080,1920,unit_scale=m.scale),s
    evalnames=list(dict.fromkeys(names+[data['reference']]+[n for n in plan['development'] if n in data['worlds']]))
    @torch.no_grad()
    def evaluate(label,candidate):
        folder=out/label;folder.mkdir();rows={}
        for n in evalnames:
            r,s=render(n,candidate);face=data['labels'][n]['face_core'];room=data['labels'][n]['room_visible'];target=t(data['rgb'][n]);err=(r['rgb']-target).abs().mean(-1);row={}
            for key,mask in [('face',face),('room',room),('targetSurface',regions.get(n,np.zeros_like(face)))]:
                mm=t(mask).bool();row[key]={'pixels':int(mask.sum()),'rgbL1':float(masked_mean(err,mm)) if mask.any() else None,'alpha':float(masked_mean(r['alpha'],mm)) if mask.any() else None,'qRoom':float(masked_mean(r['q'][...,0],mm)) if mask.any() else None}
            rows[n]=row;np.savez_compressed(folder/(n+'.npz'),rgb=r['rgb'].cpu().numpy(),alpha=r['alpha'].cpu().numpy(),qRoom=r['q'][...,0].cpu().numpy());png(folder/n,[data['rgb'][n],r['rgb'].cpu().numpy()])
        save_json(folder/'metrics.json',rows);return rows
    def ck(label,step):save_checkpoint(out/(label+'.pt'),new,optim,{'views':sampler},stage='room_surface',step=step,contract=contract,strategy={'density':'fixed actual MVS support'},extra={'sourceIndices':ids,'surfaceNormals':norm,'initialScales':scales,'oldRoom':m.room.state_dict(),'oldMetadata':m.room.metadata,'removedMask':remove,'regions':regions})
    before=evaluate('old-images',False);initial=evaluate('initial-images',True);ck('initial',0);curve=[];torch.cuda.reset_peak_memory_stats();trainstart=time.perf_counter()
    for step in range(1,steps+1):
        for op in optim.values():op.zero_grad(set_to_none=True)
        n=sampler.next();r,_=render(n,True);mask=t(regions[n]).bool();target=t(data['rgb'][n]);loss=masked_mean((r['rgb']-target).abs().mean(-1),mask)+.12*valid_window_structure(r['rgb'],target,mask)+.04*masked_mean((1-r['alpha']).square(),mask)+new.regularizer();loss.backward()
        for op in optim.values():op.step()
        with torch.no_grad():new.log_scales.clamp_(min=fixed['log_scales']-np.log(1.4),max=fixed['log_scales']+np.log(1.4))
        if step==1 or step%30==0:curve.append({'step':step,'name':n,'loss':float(loss.detach())});print(json.dumps(curve[-1]),flush=True)
        if step==steps//2:ck('mid',step)
    ck('candidate-final',steps);after=evaluate('final-images',True);ref=data['reference'];r,s=render(ref,True);export_state(s,out/'fixed-B-T2.ply');np.savez_compressed(out/'B-T2-gsplat.npz',rgb=r['rgb'].detach().cpu().numpy(),alpha=r['alpha'].detach().cpu().numpy());f=m.adjusted_frame(make_frame(data,ref,crop=False));cv=f['C'].cpu().numpy();inv=np.linalg.inv(cv);save_json(out/'display.json',{'assets':[{'label':'B-T2','ply':str(out/'fixed-B-T2.ply'),'hash':sha(out/'fixed-B-T2.ply'),'count':len(s.means)}],'K':data['K'].tolist(),'C':cv.tolist(),'width':1080,'height':1920,'camera':inv[:3,3].tolist(),'target':(inv[:3,3]+inv[:3,2]).tolist(),'up':(-inv[:3,1]).tolist(),'near':.01*m.scale,'far':1e10*m.scale,'sourceHash':data['sourceHash'],'reference':ref})
    failures=[]
    for n in evalnames:
        if after[n]['room']['rgbL1']>before[n]['room']['rgbL1']+.002:failures.append('room_content_regression:'+n)
        if after[n]['face']['rgbL1']>before[n]['face']['rgbL1']+.002:failures.append('face_regression:'+n)
    if after[ref]['face']['qRoom']>.05:failures.append('T2_room_still_occludes_face')
    save_json(out/'result.json',{'retired':int(remove.sum()),'newPoints':len(ids),'before':before,'initial':initial,'after':after,'curve':curve,'failures':failures,'accepted':False,'publication':'never_auto','steps':steps,'totalSeconds':time.perf_counter()-start,'trainEvalSeconds':time.perf_counter()-trainstart,'allocatedMiB':torch.cuda.max_memory_allocated()/1048576,'reservedMiB':torch.cuda.max_memory_reserved()/1048576,'semanticNote':'room multiple physical surface sample, not full-scene replacement','published':False})
    restore_checkpoint(out/'initial.pt',new,optim,{'views':sampler},contract=contract,device='cuda');ck('restored',0);save_json(out/'restoration.json',{'newComponentRestored':all(torch.equal(v,new.state_dict()[k]) for k,v in fixed.items()),'oldRoomKeptUntouched':True,'candidateNotInstalledIntoOriginalModel':True,'sourceFamilyIsNotWholeHaze':True})
    print('ROOM_SURFACE_REPLACEMENT_CANDIDATE_COMPLETE_NOT_PUBLISHED',flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--mvs',required=True);p.add_argument('--source-id',type=int,required=True);p.add_argument('--out',required=True);p.add_argument('--retirement',required=True);a=p.parse_args();run(a.manifest,a.mvs,a.source_id,a.out,retirement=a.retirement)


