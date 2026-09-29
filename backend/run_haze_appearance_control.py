"""Finite appearance control; G1 stays blocked when shared geometry fails.
No failed geometry is disguised with appearance recovery.
"""
import copy,json,time
import numpy as np,torch
from run_haze_shared_surface import ROOT,setup,save
from reconstruction_detail_controlled import evaluate_face,pixel_structure
from reconstruction_portrait_pipeline import make_frame,masked_mean
from reconstruction_portrait_priority import face_optimizer
from reconstruction_research_state import FrameSampler
from reconstruction_components_v3 import save_json
from reconstruction_surface_patch import patch_mask
from audit_portrait_priority_handoff import restore_tensors
from audit_detail_controlled import png

def run():
    out,contract,data,plan,m=setup('Gctrl');geometry=ROOT/'G-geometry'
    initial=torch.load(geometry/'initial.pt',map_location='cuda',weights_only=False)
    m.attach_surface(initial['model']['surface_basis'],initial['model']['surface_bound']);restore_tensors(m,initial['model'])
    tracks=json.loads((geometry/'tracks.json').read_text())['tracks'];train=sorted({o['name'] for t in tracks for o in t['observations']})
    plan={**plan,'train':train};save_json(out/'training-plan.json',plan)
    p=m.portrait;basis=m.surface_basis;active_surface=(basis[p.faces[p.triangle_ids]].sum((1,2))>.01)&(m.component_origin[p.origin_index[:p.surface_count]]==0)
    active=torch.cat((active_surface,torch.zeros(len(p.role)-p.surface_count,device='cuda',dtype=torch.bool)))
    for v in m.parameters():v.requires_grad_(False)
    keys=('sh','opacity_logits','log_scales','quats')
    for k in keys:getattr(p,k).requires_grad_(True)
    optimizer=face_optimizer(m);sampler=FrameSampler(train,7299);ops={'appearance':optimizer};original={k:getattr(p,k).detach().clone() for k in keys}
    c={'steps':120,'imageBackwards':240,'geometry':'R0_fixed','activePoints':int(active.sum()),'G1':'blocked_geometry_per_view_regression','loss':'same_local_RGB_coverage_signed_difference_as_prior_control','seed':7299}
    save_json(out/'config.json',c);save(out,'initial',m,contract,ops,sampler,extra={'config':c,'activeUID':p.stable_uid[active]})
    evaluate_face(m,data,plan,out/'initial-images');curve=[];start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    for step in range(1,121):
        optimizer.zero_grad(set_to_none=True);views=[]
        for _ in range(2):
            name=sampler.next();f=make_frame(data,name);r=m.render(f,'T0');x0,y0,x1,y1=f['rectangle'];mask=torch.tensor(patch_mask(data,name,'right')[y0:y1,x0:x1],device='cuda');valid=f['masks']['face_core']|f['masks']['face_boundary']
            err=(r['rgb']-f['rgb']).abs().mean(-1);loss=masked_mean(err,mask)+.2*masked_mean(err,valid)+.15*pixel_structure(r['rgb'],f['rgb'],mask)+.04*masked_mean((1-r['alpha']).square(),valid)
            loss+=.001*(p.log_scales[active]-original['log_scales'][active]).square().mean();(loss*.5).backward();views.append({'name':name,'loss':float(loss.detach())})
        for k in keys:getattr(p,k).grad[~active]=0
        optimizer.step()
        with torch.no_grad():
            for k in keys:getattr(p,k)[~active]=original[k][~active]
        if step%20==0 or step==1:curve.append({'step':step,'views':views});print(json.dumps(curve[-1]),flush=True)
        if step==60:save(out,'mid',m,contract,ops,sampler,step=step,extra={'config':c,'activeUID':p.stable_uid[active]})
    save(out,'candidate-final',m,contract,ops,sampler,step=120,extra={'config':c,'activeUID':p.stable_uid[active]});after=evaluate_face(m,data,plan,out/'final-images')
    before=json.loads((out/'initial-images/metrics.json').read_text());rows={}
    dest=out/'comparisons';dest.mkdir()
    for n in plan['development']+plan['audit']:
        f=make_frame(data,n);x0,y0,x1,y1=f['rectangle'];mask=patch_mask(data,n,'right')[y0:y1,x0:x1];images=[f['rgb'].cpu().numpy()]
        row={'pixels':int(mask.sum())}
        for label,folder in [('G0',out/'initial-images'),('Gctrl',out/'final-images'),('shared-fixedF-rejected',geometry/'geometry-images'),('shared-boundedF-rejected',ROOT/'G-bounded-F/geometry-images')]:
            z=np.load(folder/(n+'.npz'));im=z['rgb'];row[label]=float(abs(im-images[0]).mean(-1)[mask].mean()) if mask.any() else None;images.append(im)
        rows[n]=row;png(dest/n,images)
    result={'rows':rows,'seconds':time.perf_counter()-start,'curve':curve,'updates':{k:float((getattr(p,k)[active]-original[k][active]).abs().mean()) for k in keys},
        'peakAllocatedMiB':torch.cuda.max_memory_allocated()/1048576,'peakReservedMiB':torch.cuda.max_memory_reserved()/1048576,'G1Executed':False,'G1Reason':'both_geometry_candidates_failed_multi_view_checks','published':False}
    save_json(out/'result.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('rows','curve')}),flush=True)
if __name__=='__main__':run()
