"""Isolated complete-scene context appearance recovery.
Frozen geometry, density, head, C/F/K/scale; actual native RGB supervision.
Not a geometry repair or publisher. Original source state and identities persist.
"""
from pathlib import Path
import argparse,json,time,shutil
import numpy as np,torch
from reconstruction_complete_context import load_complete
from reconstruction_components_v3 import FreeComponent,pick,sha,save_json,exact_state_hash
from reconstruction_portrait_model import GaussianState,quaternion_matrix,rotate_sh1
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_continuity_surface import physical_masks
from reconstruction_reference_static import valid_window_structure
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint
from run_continuous_surface_repair import evaluate_complete,regression_screen
from run_haze_shared_surface import export_state


def transport_colour_delta(delta,R):
    vector=torch.stack((-delta[:,3],-delta[:,1],delta[:,2]),1)
    moved=torch.einsum('nij,njc->nic',R,vector)
    return torch.stack((delta[:,0],-moved[:,1],moved[:,2],-moved[:,0]),1)


class ContextAppearanceStage(torch.nn.Module):
    def __init__(self,base,data,side):
        super().__init__();self.baseline=base;self.scale=base.scale
        f=base.baseline.adjusted_frame(make_frame(data,data['reference'],crop=False));s=base.state(f);dev=s.means.device
        self.patches=torch.nn.ModuleDict()
        for label,part in [('room',0),('body',4)]:
            ids=torch.where(s.parts==part)[0];self.register_buffer(label+'_ids',ids);p=pick(s,ids)
            self.patches[label]=FreeComponent(p,torch.tensor(side['point_id'][ids.cpu().numpy()],device=dev),torch.ones(len(ids),device=dev),'reference-world',0.)
            self.register_buffer(label+'_sh',p.sh.clone());self.register_buffer(label+'_opacity',p.opacity.clone());self.register_buffer(label+'_rotation',quaternion_matrix(p.quats).clone())
    def state(self,f):
        s=self.baseline.state(f);sh=s.sh.clone();alpha=s.opacity.clone()
        for label,patch in self.patches.items():
            ids=getattr(self,label+'_ids');cur=pick(s,ids);R=quaternion_matrix(cur.quats)@getattr(self,label+'_rotation').transpose(-1,-2)
            colour=cur.sh+transport_colour_delta(patch.sh-getattr(self,label+'_sh'),R)
            opacity=cur.opacity+(patch.opacity.sigmoid()-getattr(self,label+'_opacity'))
            sh[ids]=colour;alpha[ids]=opacity.clamp(.001,.999)
        return GaussianState(s.means,s.quats,s.scales,alpha,sh,s.parts)
    def render(self,f):
        f=self.baseline.baseline.adjusted_frame(f);h,w=f['rgb'].shape[:2]
        return draw(self.state(f),f['C'],f['K'],w,h,unit_scale=self.scale)

def run(complete,out,steps=240):
    out=Path(out);start=time.perf_counter();torch.manual_seed(100107)
    data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    shutil.copyfile(__file__,out/'algorithm-source'/Path(__file__).name)
    side=dict(np.load(Path(complete)/'candidate-identities.npz'))
    model=ContextAppearanceStage(base,data,side);frozen=exact_state_hash(base)
    for p in model.parameters():p.requires_grad_(False)
    rates=dict(sh=.002,opacity=.002);parameters={label+'.'+k:getattr(patch,k) for label,patch in model.patches.items() for k in rates};ops={k:torch.optim.Adam([p],lr=rates[k.split('.')[-1]]) for k,p in parameters.items()}
    for p in parameters.values():p.requires_grad_(True)
    initial={k:v.clone() for k,v in model.state_dict().items()}
    train=[n for n in plan['train'] if n in data['worlds']]
    eval_names=list(dict.fromkeys([contract['reference']]+extra['meta']['names']+plan['development']+plan['audit']))
    eval_names=[n for n in eval_names if n in data['worlds']]
    masks=physical_masks(contract['spec']['prepared'],data,list(dict.fromkeys(train+eval_names)))
    old,before=evaluate_complete(base,data,eval_names,masks,out/'baseline-images')
    # Full-frame protection RGB comes only from training observations, not held-out.
    baseline_train={}
    with torch.no_grad():
        for n in train:
            r=base.render(make_frame(data,n,crop=False));baseline_train[n]=(r['rgb']-torch.tensor(data['rgb'][n],device='cuda')).abs().mean(-1).cpu().numpy()
    sampler=FrameSampler(train,100107);curve=[]
    config=dict(train=train,evaluate=eval_names,steps=steps,geometryFixed=True,topologyFixed=True,
        clothingSupervisionWindow=extra['meta']['names'],outsideBodyWindow='unknown; body loss omitted',
        roomAllValidNativePixels=True,allComponentsVisible=True,headFrozen=True,maximumAlphaChange=.03,published=False)
    save_json(out/'config.json',config);contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')};save_json(out/'contract.json',contract)
    def ck(label,step):save_checkpoint(out/(label+'.pt'),model,ops,{'views':sampler},stage='full-context-appearance',step=step,contract=contract,strategy={'events':[],'topology':'fixed'},extra=dict(config=config,sourceContinuity=extra))
    ck('initial',0);torch.cuda.reset_peak_memory_stats();train_clock=time.perf_counter()
    for step in range(1,steps+1):
        for op in ops.values():op.zero_grad(set_to_none=True)
        n=sampler.next();f=make_frame(data,n,crop=False);r=model.render(f);err=(r['rgb']-f['rgb']).abs().mean(-1)
        labels=[('room',.5)]+([('cloth',1.),('neck',1.)] if n in extra['meta']['names'] else [])
        loss=err.sum()*0
        for part,weight in labels:
            mask=torch.tensor(masks[n][part],device='cuda')
            loss+=weight*(masked_mean(err,mask)+.12*valid_window_structure(r['rgb'],f['rgb'],mask))
        for part,weight in [('face',2.),('hair',1.),('cloth',1.),('neck',1.)]:
            mask=torch.tensor(masks[n][part],device='cuda')
            prior=torch.tensor(baseline_train[n],device='cuda')
            loss+=weight*masked_mean((err-prior-.001).clamp_min(0),mask)
        loss+=sum(.001*(p.sh[:,1:]-getattr(model,label+'_sh')[:,1:]).square().mean() for label,p in model.patches.items())
        if not torch.isfinite(loss):raise ValueError('nonfinite_context_loss')
        loss.backward()
        for p in parameters.values():
            if p.grad is None or not torch.isfinite(p.grad).all():raise ValueError('nonfinite_context_gradient')
        for op in ops.values():op.step()
        with torch.no_grad():
            for label,patch in model.patches.items():
                original=getattr(model,label+'_opacity');lo=(original-.03).clamp(.001,.999);hi=(original+.03).clamp(.001,.999)
                patch.opacity.clamp_(torch.logit(lo),torch.logit(hi))
        if step==steps//2:ck('mid',step)
        if step==1 or step%60==0:
            row=dict(step=step,name=n,loss=float(loss.detach()));curve.append(row);print(json.dumps(row),flush=True)
        if time.perf_counter()-train_clock>600 or torch.cuda.memory_allocated()/1048576>6500:raise ValueError('context_resource_budget')
    ck('candidate-final',steps)
    _,final=evaluate_complete(model,data,eval_names,masks,out/'final-images',old)
    failures=regression_screen(before,final)
    f=base.baseline.adjusted_frame(make_frame(data,contract['reference'],crop=False))
    asset=out/'candidate-research-only.ply';export_state(model.state(f),asset);asset_hash=sha(asset)
    np.savez_compressed(out/'candidate-identities.npz',**{**side,'asset_hash':np.array(asset_hash)})
    display=json.loads((Path(complete)/'display.json').read_text());display['assets']=[dict(label='context appearance research',ply=str(asset.resolve()),hash=asset_hash,count=len(side['point_id']))];save_json(out/'display.json',display)
    result=dict(baseline=before,final=final,failures=failures,steps=steps,curve=curve,sourceHash=data['sourceHash'],assetHash=asset_hash,
        trainSeconds=time.perf_counter()-train_clock,seconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
        parameterChanges={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if k.startswith('patches.') and v.is_floating_point()},
        geometryRepaired=False,transactionAccepted=False,releaseQualityPassed=False,published=False,frozenBaselineExact=exact_state_hash(base)==frozen)
    save_json(out/'result.json',result)
    restore_checkpoint(out/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda')
    if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()) or exact_state_hash(base)!=frozen:raise ValueError('context_restore_failed')
    ck('restored',0);print(json.dumps({k:result[k] for k in ('assetHash','failures','seconds','allocatedMiB','reservedMiB')}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--out',required=True);p.add_argument('--steps',type=int,default=240);a=p.parse_args()
    try:run(a.complete,a.out,a.steps)
    except Exception as e:
        import traceback
        if Path(a.out).exists():save_json(Path(a.out)/'failure.json',dict(message=str(e),traceback=traceback.format_exc(),published=False))
        raise
