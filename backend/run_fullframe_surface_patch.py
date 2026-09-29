"""R0/R1/R2/O1 finite research experiment. No publisher or production imports."""
from pathlib import Path
import argparse,copy,json,random,shutil,time,traceback,threading,subprocess
import cv2,numpy as np,torch
from reconstruction_components_v3 import load_v3_prepared,save_json,sha,exact_state_hash
from reconstruction_portrait_pipeline import initialize_scene,make_frame,draw,masked_mean,metrics
from reconstruction_portrait_priority import ResearchModel,face_optimizer
from reconstruction_detail_controlled import DetailModel,evaluate_face,pixel_structure
from reconstruction_fullframe import draw_frame,ViewGradientStatistics
from reconstruction_surface_patch import track_patch,select_patch,replace_patch,patch_mask,weights
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint
from audit_portrait_priority_handoff import restore_tensors
from audit_detail_controlled import summary,png


def full_render(self,frame,stage):
    f=self.adjusted_frame(frame);s=self.portrait.local_state(f['mesh'])
    if stage=='T0':return draw_frame(s,f['F'],f)
    raise ValueError('historical_local_evaluation_only')


def checkpoint(out,label,model,optim,sampler,contract,extra,step=0,strategy=None):
    return save_checkpoint(out/(label+'.pt'),model,optim,{'face':sampler} if sampler else {},stage=out.name,step=step,contract=contract,
        strategy=strategy,extra={**extra,'roomMetadata':model.room.metadata,'bodySources':model.body_sources})


def finite_train(model,data,plan,side,ids,out,contract,replace=False):
    out.mkdir();p=model.portrait;sampler=FrameSampler(plan['train'],5129);optimizer=face_optimizer(model)
    for v in model.parameters():v.requires_grad_(False)
    for k in ('sh','opacity_logits','log_scales','quats'):getattr(p,k).requires_grad_(True)
    steps=160;optim={'face':optimizer};extra={'plan':plan,'side':side,'patchUIDs':p.stable_uid[ids].cpu().tolist(),'freshAdam':True,'imageBackwardBudget':steps*2}
    checkpoint(out,'initial',model,optim,sampler,contract,extra)
    initial_rows=evaluate_face(model,data,plan,out/'initial-images');before_state=copy.deepcopy(model.state_dict());start=time.perf_counter();event=None
    if replace:
        chosen=set(json.loads((out.parent/'patch-selection.json').read_text())['connectedTriangles'])
        ids,event=replace_patch(model,optimizer,ids,chosen,data,plan['train'],side,np.load(out.parent/'source-edge-moments.npy'))
        extra['mutation']=event;extra['patchUIDs']=p.stable_uid[ids].cpu().tolist()
        checkpoint(out,'after-replacement',model,optim,sampler,contract,extra)
        evaluate_face(model,data,plan,out/'replaced-images')
    n=len(p.role);active=torch.zeros(n,device='cuda',dtype=torch.bool);active[ids]=True
    starts={k:getattr(p,k).detach().clone() for k in ('sh','opacity_logits','log_scales','quats')};curve=[];statrows=[]
    teacher=copy.deepcopy(model);restore_tensors(teacher,before_state)
    for v in teacher.parameters():v.requires_grad_(False)
    for step in range(1,steps+1):
        optimizer.zero_grad(set_to_none=True);stats=ViewGradientStatistics();views=[]
        for i in range(2):
            name=sampler.next();f=make_frame(data,name);r=model.render(f,'T0');r['info']['means2d'].retain_grad()
            x0,y0,x1,y1=f['rectangle'];pm=torch.tensor(patch_mask(data,name,side)[y0:y1,x0:x1],device='cuda')
            valid=f['masks']['face_core']|f['masks']['face_boundary'];err=(r['rgb']-f['rgb']).abs().mean(-1)
            loss=masked_mean(err,pm)+.2*masked_mean(err,valid)+.15*pixel_structure(r['rgb'],f['rgb'],pm)
            loss+=.04*masked_mean((1-r['alpha']).square(),valid)
            # Short coverage recovery only. Do not distil the old blurry RGB.
            if step<=24:
                with torch.no_grad():old=teacher.render(f,'T0')
                loss+=.12*(1-step/25)*masked_mean((r['alpha']-old['alpha']).square(),valid)
            loss+=.001*(p.log_scales[ids]-starts['log_scales'][ids]).square().mean()
            (loss*.5).backward();stats.consume(r['info']);views.append({'name':name,'loss':float(loss.detach())})
        for k in starts:
            value=getattr(p,k)
            if value.grad is not None:value.grad[~active]=0
        optimizer.step()
        # No hidden momentum update outside the authorised patch.
        with torch.no_grad():
            for k,original in starts.items():getattr(p,k)[~active]=original[~active]
        if step==1 or step%20==0:
            row={'step':step,'views':views,'statistics':stats.summary()};curve.append(row);print(json.dumps({'branch':out.name,**row}),flush=True)
        if step==steps//2:checkpoint(out,'mid',model,optim,sampler,contract,extra,step,strategy={'statistics':stats.summary(),'topologyAfterAllBackwards':True})
    checkpoint(out,'candidate-final',model,optim,sampler,contract,extra,steps,strategy={'statistics':stats.summary(),'topology':'fixed_after_initial_patch_transaction'})
    rows=evaluate_face(model,data,plan,out/'final-images')
    del teacher
    from reconstruction_patch_acceptance import region_check
    local_screen=region_check(data,plan,side,out/'initial-images',out/'final-images')
    accepted=local_screen['passed'] and all(rows[n]['face']['hole']<=initial_rows[n]['face']['hole']+.005 and rows[n]['face']['fixedRgbL1']<=initial_rows[n]['face']['fixedRgbL1']+.002 for n in plan['development']+plan['audit'])
    with torch.no_grad():
        update={k:float((getattr(p,k)[ids]-starts[k][ids]).abs().mean()) for k in starts}
        width={'initialMedianMaxAxis':float(starts['log_scales'][ids].exp().max(1).values.median()),'finalMedianMaxAxis':float(p.log_scales[ids].exp().max(1).values.median())}
    # This numerical screen never substitutes for subsequent visual inspection.
    if replace and not accepted:
        restored=restore_checkpoint(out/'initial.pt',model,optim,{'face':sampler},contract=contract,device='cuda')
        checkpoint(out,'rolled-back',model,optim,sampler,contract,restored['extra'],0)
    result={'steps':steps,'imageBackwards':steps*2,'seconds':time.perf_counter()-start,'numericalScreen':accepted,'visuallyAccepted':False,'published':False,'localScreen':local_screen,
        'updates':update,'width':width,'initial':summary(initial_rows),'candidate':summary(rows),'mutation':event,'curve':curve,'rollback':replace and not accepted}
    save_json(out/'result.json',result);return result


def execute(args):
    base=Path(__file__).resolve().parent;out=args.output.resolve();old=args.baseline.resolve()
    if out.exists() or not out.is_relative_to(base/'.sources'):raise ValueError('new_private_run_required')
    out.mkdir(parents=True);started=time.perf_counter();snap=out/'algorithm-source';snap.mkdir()
    files=list(base.glob('reconstruction_*.py'))+[Path(__file__),base/'audit_detail_controlled.py',base/'audit_portrait_priority_handoff.py',base/'flame_open_model.py']
    for f in files:shutil.copyfile(f,snap/f.name)
    hashes={f.name:sha(snap/f.name) for f in files};save_json(out/'code-hashes.json',hashes)
    plan=json.loads((old/'observations.json').read_text());plan.pop('new_audit',None);save_json(out/'observations.json',plan)
    c={'R1Steps':160,'R2StepsIncludingRecovery':160,'viewsPerStep':2,'parentCap':480,'childrenPerParent':4,'seed':5129,'projection':'full_native_then_ROI','joint':False}
    save_json(out/'config.json',c);contract={'inputRun':str(old),'sourceCode':hashes,'portrait':sha(old/'portrait_refine_v1/final.pt'),'room':sha(old/'room_fullimg_v1/final.pt'),'observations':sha(out/'observations.json'),'config':sha(out/'config.json')};save_json(out/'contract.json',contract)
    random.seed(5129);np.random.seed(5129);torch.manual_seed(5129);torch.cuda.reset_peak_memory_stats();resources=[];stop=threading.Event()
    def monitor():
        while not stop.is_set():
            try:resources.append({'elapsed':time.perf_counter()-started,'nvidiaSmi':subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True).strip()})
            except Exception as e:resources.append({'error':repr(e)})
            stop.wait(2)
    thread=threading.Thread(target=monitor,daemon=True);thread.start();results={}
    try:
        data=load_v3_prepared(args.prepared)
        for name in plan['audit']:data['local'][name]['role']='audit'
        init=out/'load';init.mkdir();shutil.copyfile(args.prepared/'cloth_supported_seeds.npz',init/'cloth_supported_seeds.npz')
        scene=initialize_scene(data,init);model=DetailModel(scene,data,plan['train']);del scene;model.enable_components(data,plan['train'])
        ck=torch.load(old/'portrait_refine_v1/final.pt',map_location='cuda',weights_only=False);restore_tensors(model,ck['model']);model.body_sources=ck['extra']['bodySources'];model.room.metadata=ck['extra']['roomMetadata']
        roomck=torch.load(old/'room_fullimg_v1/final.pt',map_location='cuda',weights_only=False)
        state=model.state_dict();state.update({k:v for k,v in roomck['model'].items() if k.startswith('room.')});restore_tensors(model,state);model.room.metadata=roomck['extra']['roomMetadata'];del ck,roomck
        checkpoint(out,'R0-frozen',model,{},None,contract,{'originalCompleteStates':True})
        results['R0']=summary(evaluate_face(model,data,plan,out/'R0-images'))
        # Re-evaluate the recoverable previous 900-step state with SAME full canvas.
        import types
        oldinit=out/'old-load';oldinit.mkdir();shutil.copyfile(args.prepared/'cloth_supported_seeds.npz',oldinit/'cloth_supported_seeds.npz')
        scene=initialize_scene(data,oldinit);history=ResearchModel(scene,data,plan['train']);del scene
        history.render=types.MethodType(full_render,history)
        historic=args.history/'face-final.pt';hc=torch.load(historic,map_location='cuda',weights_only=False);restore_tensors(history,hc['model']);del hc
        results['old900FullFrame']=summary(evaluate_face(history,data,plan,out/'old900-images'));del history
        base_model=copy.deepcopy(model)
        try:
            side,tracks=track_patch(model,data,plan['train'],out)
            from reconstruction_patch_correspondence import bounded_correspondence
            reliable_names,geometry_report=bounded_correspondence(model,data,out)
            plan={**plan,'train':reliable_names};save_json(out/'capacity-observations.json',plan)
            checkpoint(out,'common-start',model,{},None,contract,{'geometryCheck':geometry_report,'plan':plan})
            patch_start=copy.deepcopy(model)
            ids,allowed,score=select_patch(model,data,plan['train'],side,out)
            results['patch']=tracks
            if len(ids)<8:raise ValueError('connected_patch_too_small')
            for branch,replace in [('R1',False),('R2',True)]:
                candidate=copy.deepcopy(patch_start)
                try:results[branch]=finite_train(candidate,data,plan,side,ids,out/branch,contract,replace)
                except Exception as e:results[branch]={'error':repr(e),'traceback':traceback.format_exc()};save_json(out/(branch+'-failure.json'),results[branch]);print(traceback.format_exc(),flush=True)
                del candidate;torch.cuda.empty_cache()
        except Exception as e:results['patchFailure']={'error':repr(e),'traceback':traceback.format_exc()};save_json(out/'patch-failure.json',results['patchFailure']);print(traceback.format_exc(),flush=True)
        # O1 is independent of patch eligibility and keeps the exact R0 portrait.
        from reconstruction_t2_local import run_occlusion
        try:
            if args.skip_o1:results['O1']={'executed':False,'reason':'reuse independent first-run frozen O1; no repeated room experiment'}
            else:results['O1']=run_occlusion(base_model,data,plan,out/'O1',contract)
        except Exception as e:results['O1']={'error':repr(e),'traceback':traceback.format_exc()};save_json(out/'O1-failure.json',results['O1']);print(traceback.format_exc(),flush=True)
    finally:
        stop.set();thread.join(3);save_json(out/'resources.json',resources)
        results.update(seconds=time.perf_counter()-started,peakAllocatedMiB=torch.cuda.max_memory_allocated()/1048576,peakReservedMiB=torch.cuda.max_memory_reserved()/1048576,published=False)
        save_json(out/'result.json',results);print(json.dumps({k:v for k,v in results.items() if k in ('seconds','peakAllocatedMiB','peakReservedMiB','patchFailure')}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('baseline',type=Path);p.add_argument('history',type=Path);p.add_argument('output',type=Path);p.add_argument('--skip-o1',action='store_true');execute(p.parse_args())
