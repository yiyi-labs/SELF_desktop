"""Executable native GPU pixel/gradient regression; no production assets."""
import json,torch
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import draw
from reconstruction_fullframe import draw_frame,ViewGradientStatistics

def run():
    torch.manual_seed(51);device='cuda';w,h=160,192
    K=torch.tensor([[120.,0,69.],[0,123.,91.],[0,0,1.]],device=device);C=torch.eye(4,device=device)
    values=[torch.tensor([[-.42,0.,1.],[.02,.03,1.1],[.07,.03,1.6],[1.5,.1,2.]],device=device),
        torch.tensor([[1.,0,0,0]]*4,device=device),torch.tensor([[.28,.12,.05],[.015,.018,.012],[.19,.17,.08],[.8,.6,.1]],device=device),
        torch.tensor([.5,.7,.65,.5],device=device),torch.randn(4,4,3,device=device)*.1]
    parts=torch.tensor([1,1,0,0],device=device);results=[];stats=ViewGradientStatistics()
    for rect in [(50,60,105,130),(6,8,83,100),(87,92,152,180)]:
        a,b,c,d=rect;f={'rgb':torch.zeros(d-b,c-a,3,device=device),'K':K.clone(),'fullK':K,'fullSize':(w,h),'rectangle':rect,'nativeScale':1}
        f['K'][0,2]-=a;f['K'][1,2]-=b
        def call(adapter):
            vs=[v.clone().requires_grad_() for v in values];s=GaussianState(*vs,parts)
            if adapter:r=draw_frame(s,C,f,absgrad=True)
            else:
                full=draw(s,C,K,w,h,absgrad=True);r={k:(v[b:d,a:c] if k!='info' else v) for k,v in full.items()}
            r['info']['means2d'].retain_grad()
            loss=r['rgb'].square().sum()+r['alpha'].square().sum()*.1+r['q'][...,0].sum()*.02
            loss.backward()
            if adapter:stats.consume(r['info'])
            return {k:r[k].detach() for k in ('rgb','alpha','q')},[v.grad.clone() for v in vs]
        x,g=call(False);y,j=call(True)
        error=max(float((x[k]-y[k]).abs().max()) for k in x);grad=max(float((a-b).abs().max()) for a,b in zip(g,j))
        print(json.dumps({'debugPixel':error,'debugGradient':grad,'gradientMagnitude':max(float(a.abs().max()) for a in g)}),flush=True)
        assert error<1e-6 and all(torch.allclose(a,b,rtol=2e-5,atol=2e-5) for a,b in zip(g,j))
        results.append({'roi':rect,'pixelMax':error,'parameterGradientMax':grad})
    assert len(stats.views)==3 and all(v['width']==w and v['height']==h for v in stats.views)
    assert all(v['gradientL1']>0 for v in stats.summary())
    from types import SimpleNamespace
    from reconstruction_portrait_pipeline import SceneAssembly
    from reconstruction_portrait_priority import ResearchModel
    from reconstruction_detail_controlled import DetailModel
    from reconstruction_portrait_model import joined_state
    st=GaussianState(*values,parts);empty=GaussianState(*[v[:0] for v in values],parts[:0])
    frame={**f,'F':C,'C':C,'mesh':torch.zeros(1,3,device=device),'name':'synthetic'}
    shim=SimpleNamespace(portrait=SimpleNamespace(local_state=lambda mesh:st),head_state=lambda f:st,adjusted_frame=lambda f:f,
        scale=1.,environment_state=lambda:empty,room=SimpleNamespace(state=lambda:empty),body_state=lambda name:empty)
    reference=draw_frame(st,C,frame)
    crop_only={k:v for k,v in frame.items() if k!='fullK'}
    assert torch.equal(draw_frame(st,C,crop_only)['rgb'],reference['rgb'])
    try:draw_frame(st,C,{k:v for k,v in crop_only.items() if k!='fullSize'})
    except ValueError:pass
    else:raise AssertionError('missing canvas metadata accepted')
    for cls in (SceneAssembly,ResearchModel,DetailModel):
        for stage in ('T0','T1','T2'):
            value=cls.render(shim,frame,stage)
            assert torch.allclose(value['rgb'],reference['rgb'],rtol=1e-5,atol=1e-6),(cls.__name__,stage)
            assert value['info']['width']==w and value['info']['height']==h
    try:draw_frame(GaussianState(*values,parts),C,{**f,'fullK':K+1})
    except ValueError:pass
    else:raise AssertionError('wrong K accepted')
    print(json.dumps({'passed':True,'cases':results,'statistics':stats.summary(),'coverage':'off-ROI large kernel, off-axis, fine kernel, skin/room mutual occlusion, K metadata rejection; means/quats/scales/alpha/SH gradients'}))
if __name__=='__main__':run()
