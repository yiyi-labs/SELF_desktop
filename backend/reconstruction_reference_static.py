# Strategy adaptation based on gsplat 1.5.3, Copyright 2025 Nerfstudio Team.
# Apache-2.0; see docs/evidence/portrait-priority-training-20260929/gsplat-1.5.3-LICENSE.txt.
# Modified here: finite growth budgets, lineage, conservative pruning and explicit reset scheduling.
"""Isolated static-room optimizer adapter for the installed gsplat 1.5.3.

Reuses its gradient statistics and topology operations. Static observation
masks are independent of seed/triangle coverage. No production imports.
"""
from __future__ import annotations
import math
import torch
import torch.nn.functional as F
from gsplat.strategy import DefaultStrategy
from gsplat.strategy.ops import duplicate, split, remove, reset_opa
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import masked_mean


def valid_static_mask(frame):
    m=frame['masks']
    return m['room_visible'] & ~m['unknown_or_occluded'] & torch.isfinite(frame['rgb']).all(-1)


def valid_window_structure(prediction, target, mask, size=7):
    """SSIM only where the entire window contains actual valid observations.

    No multiplication of RGB by a mask before neighbourhood statistics.
    """
    if min(mask.shape)<size: return prediction.sum()*0
    x=prediction.permute(2,0,1)[None]; y=target.permute(2,0,1)[None]
    pool=lambda v:F.avg_pool2d(v,size,1)
    valid=pool(mask.float()[None,None])>=1-1e-6
    mx,my=pool(x),pool(y); vx=(pool(x*x)-mx*mx).clamp_min(0); vy=(pool(y*y)-my*my).clamp_min(0)
    covariance=pool(x*y)-mx*my
    ssim=((2*mx*my+.01**2)*(2*covariance+.03**2))/((mx*mx+my*my+.01**2)*(vx+vy+.03**2))
    return masked_mean((1-ssim).mean(1)[0]*.5,valid[0,0])


def static_loss(rendered,frame):
    mask=valid_static_mask(frame)
    if not mask.any(): raise ValueError('no_valid_static_pixels')
    error=(rendered['rgb']-frame['rgb']).abs().mean(-1)
    rgb=masked_mean(error,mask)
    coverage=masked_mean((1-rendered['alpha']).square(),mask)
    structure=valid_window_structure(rendered['rgb'],frame['rgb'],mask)
    # Every valid room pixel participates, including missing rendered pixels.
    value=rgb+.12*structure+.06*coverage
    return value,{'rgb':float(rgb.detach()),'structure':float(structure.detach()),
        'coverageLoss':float(coverage.detach()),'validPixels':int(mask.sum()),
        'holeAlpha08':float(masked_mean((rendered['alpha']<.8).float(),mask)),
        'qRoom':float(masked_mean(rendered['q'][...,0],mask))}


class StaticGaussians(torch.nn.Module):
    def __init__(self,values,sources,support):
        super().__init__()
        keys=('means','scales','quats','opacities','sh')
        self.params=torch.nn.ParameterDict({k:torch.nn.Parameter(values[k].detach().clone()) for k in keys})
        n=len(self.params['means']); d=self.params['means'].device
        self.metadata={
            'point_uid':torch.arange(n,device=d,dtype=torch.long),
            'parent_uid':torch.full((n,),-1,device=d,dtype=torch.long),
            'source_id':torch.as_tensor(sources['id'],device=d,dtype=torch.long),
            'source_kind':torch.as_tensor(sources['kind'],device=d,dtype=torch.long),
            'support':torch.as_tensor(support,device=d).reshape(-1),
            'generation':torch.zeros(n,device=d,dtype=torch.long),
            'initial_means':values['means'].detach().clone(),
            'initial_scales':values['scales'].detach().clone()}
    def state(self):
        p=self.params
        return GaussianState(p['means'],F.normalize(p['quats'],dim=-1),p['scales'].exp(),
            p['opacities'].sigmoid(),p['sh'],torch.zeros(len(p['means']),device=p['means'].device,dtype=torch.long))
    def optimizers(self,scene_scale):
        rates={'means':.00016*scene_scale,'scales':.003,'quats':.001,'opacities':.025,'sh':.0025}
        return {k:torch.optim.Adam([p],lr=rates[k],eps=1e-15) for k,p in self.params.items()}


class BudgetedStaticStrategy(DefaultStrategy):
    """One ordinary gradient strategy with explicit finite research budgets.

    Uses the pinned upstream ops (including Adam/extra tensor remapping), with
    capped growth and no global scale-prune. Source IDs are ancestry, not new
    measurements. Opacity reset is explicit, avoiding the installed version's
    ambiguous bitwise condition; this does not patch the installed package.
    """
    def __init__(self,*,start=120,stop=600,every=100,max_points=40000,max_growth=1024,reset_steps=(300,)):
        super().__init__(refine_start_iter=start,refine_stop_iter=stop+1,refine_every=every,
            reset_every=1000000000,absgrad=False,verbose=False)
        self.max_points=max_points;self.max_growth=max_growth;self.reset_steps=tuple(reset_steps)
    def initialize_for(self,room,scene_scale):
        state=self.initialize_state(scene_scale=scene_scale)
        state.update(room.metadata);state['next_uid']=len(room.params['means']);state['events']=[]
        return state
    @torch.no_grad()
    def _assign_child_ids(self,state,start,count,parent_ids):
        state['parent_uid'][start:start+count]=parent_ids
        state['point_uid'][start:start+count]=torch.arange(state['next_uid'],state['next_uid']+count,device=parent_ids.device)
        state['generation'][start:start+count]+=1;state['next_uid']+=count
    @torch.no_grad()
    def _grow_gs(self,params,optimizers,state,step):
        n=len(params['means']);limit=min(self.max_growth,self.max_points-n)
        if limit<=0:return 0,0
        score=state['grad2d']/state['count'].clamp_min(1)
        eligible=torch.where((score>self.grow_grad2d)&(state['count']>=3))[0]
        ids=eligible[torch.argsort(score[eligible],descending=True)[:limit]]
        large=params['scales'].exp().max(-1).values>self.grow_scale3d*state['scene_scale']
        dupli=torch.zeros(n,dtype=torch.bool,device=score.device);dupli[ids[~large[ids]]]=True
        divide=torch.zeros_like(dupli);divide[ids[large[ids]]]=True
        nd=int(dupli.sum());ns=int(divide.sum())
        if nd:
            parent=state['point_uid'][dupli].clone()
            duplicate(params=params,optimizers=optimizers,state=state,mask=dupli)
            self._assign_child_ids(state,n,nd,parent)
            # Optical depth is shared rather than doubled at identical centres.
            p=params['opacities'];opa=1-torch.sqrt(1-p[:n][dupli].sigmoid())
            p[torch.where(dupli)[0]]=torch.logit(opa.clamp(1e-6,1-1e-6));p[n:]=torch.logit(opa.clamp(1e-6,1-1e-6))
            for value in optimizers['opacities'].state.get(p,{}).values():
                if isinstance(value,torch.Tensor) and value.shape==p.shape:value[torch.where(dupli)[0]]=0
        if ns:
            divide=torch.cat((divide,torch.zeros(nd,device=score.device,dtype=torch.bool)))
            parent=state['point_uid'][divide].clone().repeat(2);rest=len(divide)-ns
            split(params=params,optimizers=optimizers,state=state,mask=divide,revised_opacity=True)
            self._assign_child_ids(state,rest,2*ns,parent)
        return nd,ns
    @torch.no_grad()
    def step_post_backward(self,params,optimizers,state,step,info,packed=False):
        if step>=self.refine_stop_iter:return
        self._update_state(params,state,info,packed=packed)
        if step in self.reset_steps:
            reset_opa(params=params,optimizers=optimizers,state=state,value=.1)
            state['events'].append({'step':step,'type':'opacity_reset','cap':.1,'count':len(params['means'])})
            state['grad2d'].zero_();state['count'].zero_();return
        since_reset=min([step-x for x in self.reset_steps if x<step] or [step])
        if step>self.refine_start_iter and step%self.refine_every==0 and since_reset>=self.refine_every:
            before=len(params['means']);nd,ns=self._grow_gs(params,optimizers,state,step)
            # Only persistent, observed near-transparent points. Size alone is
            # not evidence of invalid room geometry. Every removal is recorded.
            prune=(params['opacities'].sigmoid()<self.prune_opa)&(state['count']>=20)
            count=int(prune.sum())
            if count and count<len(prune):remove(params=params,optimizers=optimizers,state=state,mask=prune)
            elif count==len(prune):count=0
            state['events'].append({'step':step,'type':'topology','before':before,'duplicates':nd,
                'splitParents':ns,'pruned':count,'after':len(params['means'])})
            state['grad2d'].zero_();state['count'].zero_()
            self.check_sanity(params,optimizers)


def static_regularization(room,state):
    p=room.params
    # Soft, world-unit priors. No S/triangle mask restricts supported learning.
    spread=(p['means']-state['initial_means'])/max(float(state['scene_scale']),1e-8)
    oversize=(p['scales']-state['initial_scales']-math.log(4)).clamp_min(0)
    return .002*spread.square().mean()+.003*oversize.square().mean()+.0001*p['sh'][:,1:].square().mean()
