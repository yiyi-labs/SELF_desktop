"""One bounded alternating F step after the fixed-F shared-surface test.
All observations keep the same shared anchors and nonzero reliability weights.
"""
import copy,json,time
import numpy as np,torch
from run_haze_shared_surface import (ROOT,setup,save,residuals,error_report)
from reconstruction_components_v3 import save_json
from reconstruction_research_state import restore_checkpoint
from reconstruction_detail_controlled import evaluate_face
from audit_portrait_priority_handoff import restore_tensors

def run():
    out,contract,data,plan,m=setup('G-bounded-F');previous=ROOT/'G-geometry'
    initial=torch.load(previous/'initial.pt',map_location='cuda',weights_only=False)
    m.attach_surface(initial['model']['surface_basis'],initial['model']['surface_bound']);restore_tensors(m,initial['model'])
    tracks=json.loads((previous/'tracks.json').read_text())['tracks'];e,meta=residuals(m,data,tracks);before=error_report(e,meta);del e
    fit=torch.tensor([r['use']=='fit' and r['role']!='third-withheld' for r in meta],device='cuda')
    source=torch.tensor([r['role']=='source' and r['use']=='fit' for r in meta],device='cuda')
    confidence=torch.tensor([r['weight'] for r in meta],device='cuda')
    sources={t['observations'][0]['name'] for t in tracks};targets={r['name'] for r in meta if r['use']=='fit' and r['role']=='target'}
    active=torch.tensor([n in targets and n not in sources and n!=m.pose.reference for n in m.pose.names],device='cuda')
    pose_start=m.pose.delta.detach().clone()
    for p in m.parameters():p.requires_grad_(False)
    m.surface_control.requires_grad_(True);m.pose.delta.requires_grad_(True)
    opts={'surface':torch.optim.Adam([m.surface_control],lr=.035),'pose':torch.optim.Adam([m.pose.delta],lr=.008)}
    config={'steps':120,'alternating':'even surface only, odd partial F only','rawPoseCap':.20,'sourceImageTolerancePx':.35,'sourceF':sorted(sources),'referenceF':m.pose.reference,'KIdentityExpressionScaleWorld':'fixed','appearance':'frozen','fixedWeights':True}
    save_json(out/'config.json',config);save(out,'initial',m,contract,opts,extra={'tracks':tracks,'config':config});curve=[];start=time.perf_counter()
    for step in range(1,121):
        for opt in opts.values():opt.zero_grad(set_to_none=True)
        err,_=residuals(m,data,tracks);robust=torch.nn.functional.smooth_l1_loss(err,torch.zeros_like(err),beta=1,reduction='none').sum(-1)
        # Explicit bounded-source consistency, not learnable weight rejection.
        loss=(robust[fit]*confidence[fit]).sum()/confidence[fit].sum()
        loss+=2*(err[source].norm(dim=-1)-.35).clamp_min(0).square().mean()
        loss+=.015*(m.displacement()/m.surface_bound).square().mean()+.08*(m.pose.delta-pose_start).square().mean()
        loss.backward();m.pose.delta.grad[~active]=0
        opts['surface' if step%2==0 else 'pose'].step()
        with torch.no_grad():
            m.pose.delta.copy_(torch.maximum(torch.minimum(m.pose.delta,pose_start+.20),pose_start-.20));m.pose.delta[~active]=pose_start[~active]
        if step%20==0 or step==1:curve.append({'step':step,'loss':float(loss.detach())});print(curve[-1],flush=True)
        if step==60:save(out,'mid',m,contract,opts,step=step,extra={'tracks':tracks,'config':config})
    errors,_=residuals(m,data,tracks);after=error_report(errors,meta);fail=[]
    if after['groups']['source']['p90']>.75 or after['groups']['source']['max']>1.5:fail.append('source_anchor_drift')
    for key in ('target','third-withheld','withheld-track'):
        if after['groups'][key]['median']>=before['groups'][key]['median']:fail.append('no_shared_improvement:'+key)
    for key,old in before['groups'].items():
        if key.startswith('frame_') and key not in sources:
            new=after['groups'][key]
            if new['median']>old['median']+.25 or new['p90']>old['p90']+.5:fail.append('view_regression:'+key)
    mesh=m.portrait.reference_mesh+m.surface_base;ta=mesh[m.portrait.faces];tb=(mesh+m.displacement())[m.portrait.faces]
    na=torch.linalg.cross(ta[:,1]-ta[:,0],ta[:,2]-ta[:,0]);nb=torch.linalg.cross(tb[:,1]-tb[:,0],tb[:,2]-tb[:,0]);ratio=nb.norm(dim=-1)/na.norm(dim=-1).clamp_min(1e-10);cos=torch.nn.functional.cosine_similarity(na,nb,dim=-1)
    if ratio.min()<.65 or cos.min()<.97:fail.append('surface_distortion')
    save(out,'candidate-final',m,contract,opts,step=120,extra={'tracks':tracks,'config':config})
    evaluate_face(m,data,plan,out/'geometry-images')
    report={'before':before,'after':after,'geometryScreen':not fail,'failures':fail,'curve':curve,'seconds':time.perf_counter()-start,
        'poseMaxRawChange':float((m.pose.delta-pose_start).abs().max()),'areaRatioMin':float(ratio.min()),'normalCosMin':float(cos.min()),'surfaceMaxPixels':float(m.displacement().norm(dim=-1).max()/m.portrait.metric_per_pixel.median()),'published':False}
    save_json(out/'result.json',report)
    if fail:restore_checkpoint(out/'initial.pt',m,opts,{},contract=contract,device='cuda');save(out,'restored',m,contract,opts,extra={'rejected':fail})
    print(json.dumps({k:v for k,v in report.items() if k not in ('before','after','curve')}),flush=True)
if __name__=='__main__':run()
