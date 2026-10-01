import unittest
import numpy as np
import torch
from reconstruction_ray_surface import sample_mask,moment_error,draw_moments,transport_patch
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import draw
from reconstruction_components_v3 import FreeComponent

class SurfaceContracts(unittest.TestCase):
    def test_boundary_never_clamps_into_valid_pixel(self):
        m=np.ones((5,7),bool)
        self.assertEqual(sample_mask(m,np.array([[-1.,2],[7.,2],[2.,2],[np.nan,1.]])).tolist(),[False,False,True,False])
    def test_opacity_scaling_does_not_reduce_normalized_error(self):
        q=torch.tensor([.8]);m=torch.tensor([1.6]);s=torch.tensor([4.]);d=torch.tensor([2.])
        torch.testing.assert_close(moment_error(q,m,s,d),moment_error(q*.2,m*.2,s*.2,d))
    def test_two_surfaces_not_just_average_depth(self):
        q=torch.tensor([1.]);m=torch.tensor([2.]);s=torch.tensor([5.]);d=torch.tensor([2.])
        self.assertAlmostEqual(float(moment_error(q,m,s,d)),.25)
        self.assertEqual(float(moment_error(q,m,torch.tensor([4.]),d)),0.)
    @unittest.skipUnless(torch.cuda.is_available(),'actual CUDA required')
    def test_same_forward_and_parameter_gradients(self):
        dev='cuda';means=torch.tensor([[-.1,0,2.],[0,0,3.],[.1,.05,2.5]],device=dev,requires_grad=True)
        scales=torch.tensor([[.1,.15,.03],[.8,.4,.1],[.05,.1,.02]],device=dev,requires_grad=True)
        opacity=torch.tensor([.7,.8,.65],device=dev,requires_grad=True)
        sh=torch.zeros((3,4,3),device=dev,requires_grad=True)
        quat=torch.tensor([[1.,0,0,0]]*3,device=dev,requires_grad=True)
        state=GaussianState(means,quat,scales,opacity,sh,torch.tensor([1,0,4],device=dev))
        C=torch.eye(4,device=dev);K=torch.tensor([[100.,0,32],[0,100.,32],[0,0,1]],device=dev)
        a=draw(state,C,K,64,64);b=draw_moments(state,C,K,64,64,1.)
        for k in ('rgb','q','alpha'):torch.testing.assert_close(a[k],b[k],atol=1e-6,rtol=1e-5)
        self.assertLess(float((b['q'].sum(-1)-b['alpha']).abs().max()),1e-5)
        params=(means,scales,opacity,sh,quat)
        ga=torch.autograd.grad(a['rgb'].square().mean(),params,retain_graph=True)
        gb=torch.autograd.grad(b['rgb'].square().mean(),params,retain_graph=True)
        for x,y in zip(ga,gb):torch.testing.assert_close(x,y,atol=1e-6,rtol=1e-4)
        loss=moment_error(b['q'][...,0],b['first'][...,0],b['second'][...,0],torch.full((64,64),2.8,device=dev))
        grad=torch.autograd.grad(loss[b['q'][...,0]>.1].mean(),means)[0]
        self.assertTrue(torch.isfinite(grad).all());self.assertGreater(float(grad[1].abs().sum()),0.)
    @unittest.skipUnless(torch.cuda.is_available(),'actual CUDA required')
    def test_motion_transport_keeps_ids_and_rotates_offset(self):
        dev='cuda';x=torch.tensor([[0.,0,3.]],device=dev);q=torch.tensor([[.71321,.31789,-.38191,.47231]],device=dev)
        s=GaussianState(x,q,torch.full((1,3),.1,device=dev),torch.tensor([.6],device=dev),torch.zeros((1,4,3),device=dev),torch.tensor([4],device=dev))
        p=FreeComponent(s,torch.tensor([71],device=dev),torch.ones(1,device=dev),'reference-world',.1)
        ref=p.state();ref=GaussianState(*(getattr(ref,k).detach().clone() for k in GaussianState.__dataclass_fields__))
        a=transport_patch(s,ref,p)
        for k in GaussianState.__dataclass_fields__:self.assertTrue(torch.equal(getattr(a,k),getattr(s,k)),k)
        # A separate identity reference makes the 90-degree offset direction explicit.
        with torch.no_grad():p.quats[:]=torch.tensor([[1.,0,0,0]],device=dev)
        ref=p.state();ref=GaussianState(*(getattr(ref,k).detach().clone() for k in GaussianState.__dataclass_fields__))
        with torch.no_grad():p.offset[0,0]=1.
        moved=GaussianState(x,torch.tensor([[2**-.5,0,0,2**-.5]],device=dev),s.scales,s.opacity,s.sh,s.parts)
        b=transport_patch(moved,ref,p)
        self.assertAlmostEqual(float(b.means[0,0].detach()),0.,places=6)
        self.assertAlmostEqual(float(b.means[0,1].detach()),float(torch.tanh(torch.tensor(1.))*.1),places=6)
        self.assertEqual(int(p.source_ids[0]),71)

    def test_flat_background_all_pixels_have_rgb_supervision(self):
        from run_ray_surface_repair import observed_loss
        rgb=torch.full((16,16,3),.4,requires_grad=True);alpha=torch.ones((16,16))
        target=torch.full_like(rgb,.5);empty=torch.zeros((16,16),dtype=torch.bool)
        masks={k:empty.clone() for k in ('face','hair','neck','cloth')};masks['room']=~empty
        loss=observed_loss({'rgb':rgb,'alpha':alpha},{'rgb':target},masks,{'error':torch.zeros((16,16)),'alpha':alpha},False)
        grad=torch.autograd.grad(loss,rgb)[0]
        self.assertTrue((grad.abs().sum(-1)>0).all())
    def test_depth_error_is_invariant_to_scene_units(self):
        q=torch.tensor([.7]);a=torch.tensor([2.1]);b=torch.tensor([7.]);d=torch.tensor([3.])
        torch.testing.assert_close(moment_error(q,a,b,d),moment_error(q,a*17,b*17**2,d*17))

if __name__=='__main__':unittest.main()
