"""Checkpoint integration regression: topology, untouched parts and fair budget."""
import sys,json
from pathlib import Path
import numpy as np,torch
from reconstruction_portrait_model import quaternion_matrix


def load(p):return torch.load(p,map_location='cpu',weights_only=False)
def run(root):
    a=load(root/'R1/initial.pt');b=load(root/'R2/initial.pt');x=load(root/'R1/candidate-final.pt');y=load(root/'R2/candidate-final.pt');mut=load(root/'R2/after-replacement.pt')
    assert a['model'].keys()==b['model'].keys() and all(torch.equal(a['model'][k],b['model'][k]) for k in a['model'])
    assert x['step']==y['step']==160 and x['samplers']==y['samplers']
    ev=y['extra']['mutation'];mapping=torch.tensor(ev['mapping']);uids=y['model']['portrait.stable_uid'];old=b['model'];new=mut['model'];final=y['model']
    children=torch.isin(uids,torch.tensor(ev['childUIDs']));retired=torch.tensor(ev['retiredUIDs']);assert not torch.isin(retired,uids).any();assert len(uids.unique())==len(uids)
    for key in ['source_index','origin_index','confidence','metric_per_pixel']:
        assert torch.equal(new['portrait.'+key],old['portrait.'+key][mapping]),key
    for key in old:
        if not key.startswith('portrait.'):assert torch.equal(old[key],final[key]),key
    for label,initial,end in [('R1',a,x),('R2',mut,y)]:
        active=torch.isin(end['model']['portrait.stable_uid'],torch.tensor(end['extra']['patchUIDs']))
        for key in ['sh','opacity_logits','log_scales','quats']:
            k='portrait.'+key;assert torch.equal(initial['model'][k][~active],end['model'][k][~active]),label+k
        for key in ['surface_residual','hair_delta','embedding','normal_offset','triangle_ids']:
            assert torch.equal(initial['model']['portrait.'+key],end['model']['portrait.'+key]),label+key
    n=len(uids);ns=len(new['portrait.triangle_ids']);bary=new['portrait.embedding'];assert bary.shape==(ns,3) and (bary>=-1e-6).all() and torch.allclose(bary.sum(1),torch.ones(ns),atol=1e-5)
    R=quaternion_matrix(new['portrait.quats']);sc=new['portrait.log_scales'].exp();cov=(R*sc[:,None,:].square())@R.transpose(1,2)
    R0=quaternion_matrix(old['portrait.quats']);sc0=old['portrait.log_scales'].exp();cov0=(R0*sc0[:,None,:].square())@R0.transpose(1,2)
    ids=torch.where(children)[0];parent=mapping[ids];mesh=old['portrait.reference_mesh']+old['portrait.surface_residual'];tri=mesh[old['portrait.faces'][old['portrait.triangle_ids'][parent]]]
    normal=torch.nn.functional.normalize(torch.linalg.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),dim=-1)
    variance=lambda V:torch.einsum('ni,nij,nj->n',normal,V,normal)
    err=((variance(cov[ids])-variance(cov0[parent])).abs()/variance(cov0[parent]).clamp_min(1e-12)).max();assert err<2e-5
    bindings=y['bindings']['face'];allnamed=set(final)
    assert all(k in allnamed for group in bindings for k in group)
    # The original Adam state remains in the initial checkpoint and all
    # moment arrays on the candidate have the current parameter shapes.
    opt=y['optimizers']['face']
    for group,names in zip(opt['param_groups'],bindings):
        for i,key in zip(group['params'],names):
            for field,value in opt['state'].get(i,{}).items():
                if torch.is_tensor(value) and value.ndim>0:assert value.shape==final[key].shape,(key,field)
    print(json.dumps({'passed':True,'sameInitialParameters':True,'sameViewSequenceAndBudget':True,'retired':len(retired),'children':int(children.sum()),
        'outsidePatchExactlyUnchanged':True,'normalCovarianceRelativeMax':float(err),'bindingsAndAdamShapes':True,'fullRestoreStatePresent':all(k in y for k in ['rng','samplers','strategy','optimizers','bindings'])}))
if __name__=='__main__':run(Path(sys.argv[1]))
