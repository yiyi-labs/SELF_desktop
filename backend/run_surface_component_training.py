"""Actual native-pixel training for a finite surface component, reusable stage.
Fixed topology and measured surface. Source RGB stays unchanged; missing
pixels inside the fixed target region remain in every reported error.
"""
import argparse,json,time,shutil
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_components_v3 import FreeComponent,save_json,sha
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import draw,masked_mean
from reconstruction_reference_static import valid_window_structure
from reconstruction_detail_controlled import pixel_structure
from reconstruction_research_state import save_checkpoint,FrameSampler,restore_checkpoint
from reconstruction_evidence_stage import load_stage
from run_haze_shared_surface import export_state
from audit_detail_controlled import png


def run(surface,manifest,out,steps=240):
    surface=Path(surface);out=Path(out);start=time.perf_counter();data,plan,old,basecontract=load_stage(manifest,out);obs=json.loads((surface/'observations.json').read_text());a=dict(np.load(surface/'surface.npz'));regions=dict(np.load(surface/'regions.npz'));names=obs['names'];K=torch.tensor(obs['contract']['K'],device='cuda',dtype=torch.float32);cameras={n:torch.tensor(v,device='cuda',dtype=torch.float32) for n,v in obs['contract']['cameras'].items()};worlds={n:torch.tensor(obs.get('worldC',obs['contract']['cameras'])[n],device='cuda',dtype=torch.float32) for n in names}
    tensor=lambda x:torch.as_tensor(x,device='cuda',dtype=torch.float32);N=len(a['means']);sh=torch.zeros(N,4,3,device='cuda');sh[:,0]=(tensor(a['rgb'])-.5)/.28209479177387814
    state=GaussianState(tensor(a['means']),tensor(a['quats']),tensor(a['scales']),torch.full((N,),.55,device='cuda'),sh,torch.full((N,),4,device='cuda',dtype=torch.long))
    model=FreeComponent(state,torch.arange(N,device='cuda'),tensor(a['support']),'upper-body-reference',float(np.median(a['scales'][:,0]))*.5)
    model.register_buffer('stable_uid',torch.tensor(a['point_uid'],device='cuda'));model.register_buffer('parent_uid',torch.tensor(a['parent_uid'],device='cuda'));model.register_buffer('surface_triangle',torch.tensor(a['triangle'],device='cuda'));model.register_buffer('surface_bary',tensor(a['bary']));model.offset.requires_grad_(False)
    rates={'sh':.006,'opacity':.018,'log_scales':.001,'quats':.0003};optim={k:torch.optim.Adam([getattr(model,k)],lr=v) for k,v in rates.items()};sampler=FrameSampler(names,92929);initial={k:v.detach().clone() for k,v in model.state_dict().items()};contract={**basecontract,'surfaceHash':sha(surface/'surface.npz'),'observationHash':sha(surface/'observations.json'),'cameraScope':'upper-body-local; B distinct from head F','stage':'finite_cloth_surface','notCompleteClothing':True}
    config={'steps':steps,'nativeCanvas':[1080,1920],'topology':'fixed finite surface','density':'off','rates':rates,'geometry':'frozen because bounded motion acceptance failed','loss':'fixed patch RGB + valid-window SSIM + fixed-mask alpha + scale prior','seed':92929,'publish':False};save_json(out/'config.json',config);curve=[]
    def checkpoint(label,step):save_checkpoint(out/(label+'.pt'),model,optim,{'views':sampler},stage='clothing_local',step=step,contract=contract,strategy={'density':'disabled_fixed_topology'},extra={'surface':a,'observations':obs,'config':config})
    def render(n,oldstate=False):
        s=old.body_state(n) if oldstate else model.state();C=worlds[n] if oldstate else cameras[n];return draw(s,C,K,1080,1920,unit_scale=data['scale'])
    @torch.no_grad()
    def evaluate(label):
        folder=out/label;folder.mkdir();result={}
        for n in names:
            r=render(n);ref=data['rgb'][n];mask=regions[n];allmask=data['labels'][n]['neck_cloth_visible']&~data['labels'][n]['unknown_or_occluded'];rgb=r['rgb'].cpu().numpy();alpha=r['alpha'].cpu().numpy();before=render(n,True)['rgb'].cpu().numpy();m=tensor(mask).bool();result[n]={'fixedPatchPixels':int(mask.sum()),'fixedPatchRgbL1':float(abs(rgb-ref).mean(-1)[mask].mean()) if mask.any() else None,'oldBodyPatchRgbL1':float(abs(before-ref).mean(-1)[mask].mean()) if mask.any() else None,'fullClothRgbL1':float(abs(rgb-ref).mean(-1)[allmask].mean()),'fullClothHole08':float((alpha[allmask]<.8).mean()),'patchHole08':float((alpha[mask]<.8).mean()) if mask.any() else None,'structure':float(pixel_structure(r['rgb'],tensor(ref),m))}
            np.savez_compressed(folder/(n+'.npz'),rgb=rgb,alpha=alpha,region=mask)
            ys,xs=np.where(mask)
            if len(xs):x0,x1=max(0,xs.min()-18),min(1080,xs.max()+19);y0,y1=max(0,ys.min()-18),min(1920,ys.max()+19);png(folder/n,[ref[y0:y1,x0:x1],before[y0:y1,x0:x1],rgb[y0:y1,x0:x1]])
        save_json(folder/'metrics.json',result);return result
    checkpoint('initial',0);before=evaluate('initial-images');torch.cuda.reset_peak_memory_stats();trainstart=time.perf_counter()
    eligible=[n for n in names if regions[n].sum()>=20];sampler=FrameSampler(eligible,92929)
    if not eligible:raise ValueError('no fixed patch pixels to train')
    for step in range(1,steps+1):
        for op in optim.values():op.zero_grad(set_to_none=True)
        n=sampler.next();r=render(n);target=tensor(data['rgb'][n]);mask=tensor(regions[n]).bool();err=(r['rgb']-target).abs().mean(-1)
        loss=masked_mean(err,mask)+.12*valid_window_structure(r['rgb'],target,mask)+.05*masked_mean((1-r['alpha']).square(),mask)+.003*(model.log_scales-initial['log_scales']).square().mean()+model.regularizer();loss.backward()
        for op in optim.values():op.step()
        with torch.no_grad():model.log_scales.clamp_(min=initial['log_scales']-np.log(1.4),max=initial['log_scales']+np.log(1.4))
        if step==1 or step%40==0:curve.append({'step':step,'name':n,'loss':float(loss.detach())});print(json.dumps(curve[-1]),flush=True)
        if step==steps//2:checkpoint('mid',step);evaluate('mid-images')
    checkpoint('candidate-final',steps);after=evaluate('final-images');export_state(model.state(),out/'fixed-garment.ply');np.savez_compressed(out/'fixed-garment.bindings.npz',**a,asset_hash=np.array(sha(out/'fixed-garment.ply')))
    # Original fixed head/room always participate in full T2. Substitute only
    # this actual finite body candidate to expose its incompleteness honestly.
    from reconstruction_portrait_pipeline import make_frame
    from reconstruction_portrait_model import joined_state
    ref=names[len(names)//2];f=old.adjusted_frame(make_frame(data,ref,crop=False));B=tensor(obs['B'][ref]);s=model.state();Bs=s.to_world(torch.eye(4,device='cuda'),B,1.)
    joint=joined_state(old.head_state(f).to_world(f['C'],f['F'],old.scale),old.room.state(),Bs);export_state(joint,out/'fixed-T2-garment-diagnostic.ply');jr=draw(joint,f['C'],f['K'],1080,1920,unit_scale=old.scale);np.savez_compressed(out/'T2-gsplat.npz',rgb=jr['rgb'].detach().cpu().numpy(),alpha=jr['alpha'].detach().cpu().numpy());png(out/'T2.png',[data['rgb'][ref],jr['rgb'].detach().cpu().numpy()]);C=f['C'].cpu().numpy();inv=np.linalg.inv(C);save_json(out/'display.json',{'assets':[{'label':'T2','ply':str(out/'fixed-T2-garment-diagnostic.ply'),'hash':sha(out/'fixed-T2-garment-diagnostic.ply'),'count':len(joint.means)}],'K':data['K'].tolist(),'C':C.tolist(),'width':1080,'height':1920,'camera':inv[:3,3].tolist(),'target':(inv[:3,3]+inv[:3,2]).tolist(),'up':(-inv[:3,1]).tolist(),'near':.01*old.scale,'far':1e10*old.scale,'sourceHash':data['sourceHash'],'reference':ref})
    save_json(out/'result.json',{'points':N,'steps':steps,'curve':curve,'before':before,'after':after,'updates':{k:float((getattr(model,k)-initial[k]).detach().abs().mean()) for k in rates},'trainEvaluationSeconds':time.perf_counter()-trainstart,'totalSeconds':time.perf_counter()-start,'allocatedMiB':torch.cuda.max_memory_allocated()/1048576,'reservedMiB':torch.cuda.max_memory_reserved()/1048576,'motionQualityAccepted':obs.get('motionQualityAccepted',False),'accepted':False,'reason':'finite cloth patch only; short-window body geometry not accepted; full garment coverage missing','published':False})
    restore_checkpoint(out/'initial.pt',model,optim,{'views':sampler},contract=contract,device='cuda');checkpoint('restored',0);print('CLOTH_ACTUAL_TRAINING_FINISHED_REJECTED_COMPLETE_ASSET',flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--surface',required=True);a.add_argument('--manifest',required=True);a.add_argument('--out',required=True);a.add_argument('--steps',type=int,default=240);s=a.parse_args();run(s.surface,s.manifest,Path(s.out).resolve(),s.steps)

