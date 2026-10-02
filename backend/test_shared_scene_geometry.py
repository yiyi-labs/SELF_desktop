import unittest
import numpy as np
import torch
from reconstruction_shared_scene_geometry import (LayeredSurfaceField,guarded_surface_edges,
    canonicalize_sources,replace_same_order,surface_normals,polar_frame,bounded_singular_values)
from reconstruction_portrait_model import GaussianState,evaluate_sh1
from reconstruction_surface_continuity import transport_covariance

class SharedSceneGeometryTest(unittest.TestCase):
    def field(self):
        x,y=torch.meshgrid(torch.linspace(-.1,.1,5,dtype=torch.float64),torch.linspace(-.1,.1,5,dtype=torch.float64),indexing='ij')
        p=torch.stack((x.flatten(),y.flatten(),torch.full((25,),2.,dtype=torch.float64)),1)
        n=torch.tensor([0.,0.,1.],dtype=torch.float64).expand(25,3)
        t=torch.full((25,),.001,dtype=torch.float64)
        return LayeredSurfaceField(p,n,t,torch.full((25,),.002,dtype=torch.float64),controls=9),p,n,t
    def test_zero_field_and_nonzero_gradient(self):
        f,p,n,t=self.field();x,J=f(p,n,t)
        torch.testing.assert_close(x,p,atol=0,rtol=0)
        torch.testing.assert_close(J,torch.eye(3,dtype=p.dtype).expand(25,3,3),atol=0,rtol=0)
        x[:,0].sum().backward();self.assertGreater(float(f.delta.grad.abs().sum()),.01)
    def test_shared_field_jacobian(self):
        f,p,n,t=self.field();f.delta.data.copy_(torch.linspace(-.2,.2,f.delta.numel(),dtype=p.dtype).reshape_as(f.delta))
        query=p[8:9].clone().requires_grad_(True);x,J=f(query,n[8:9],t[8:9])
        numeric=torch.autograd.functional.jacobian(lambda z:f(z,n[8:9],t[8:9])[0],query)[0,:,0,:]
        torch.testing.assert_close(J[0],numeric,atol=1e-9,rtol=1e-8)
        self.assertGreater(float(torch.linalg.det(J).detach().min()),.7)
    def test_unknown_parallel_sheet_is_not_warped(self):
        f,p,n,t=self.field();f.delta.data.fill_(.5)
        other=p+torch.tensor([0.,0.,.3],dtype=p.dtype);x,J=f(other,n,t)
        torch.testing.assert_close(x,other,atol=0,rtol=0)
    def test_edges_respect_surface_and_owner(self):
        p=np.array([[0,0,2],[.01,0,2],[0,0,2.01],[.01,0,2.01]],float)
        n=np.tile([0,0,1.],(4,1));edges=guarded_surface_edges(p,n,np.full(4,.0001),np.array([0,0,0,4]),.001)
        self.assertIn((0,1),map(tuple,edges));self.assertFalse(any(2 in e or 3 in e for e in edges))
    def test_canonical_source_transport_and_missing_guard(self):
        from scipy.spatial.transform import Rotation
        T=np.eye(4);T[:3,:3]=Rotation.from_euler('y',25,degrees=True).as_matrix();T[:3,3]=[.2,0,.1]
        x=np.array([[.1,.05,2]],np.float32);q=np.array([[1.,0,0,0]],np.float32);sh=np.arange(12,dtype=np.float32).reshape(1,4,3)/20
        names=np.array(['source']);p,qq,c=canonicalize_sources(x,q,sh,names,{'source':T},verified=True)
        np.testing.assert_allclose(p@T[:3,:3].T+T[:3,3],x,atol=1e-6)
        ray=np.array([[.1,.2,1]],np.float32);inv=T[:3,:3].T
        np.testing.assert_allclose(evaluate_sh1(torch.tensor(c),torch.tensor(ray@inv.T,dtype=torch.float32)),evaluate_sh1(torch.tensor(sh),torch.tensor(ray)),atol=2e-6)
        with self.assertRaisesRegex(ValueError,'unverified'):canonicalize_sources(x,q,sh,names,{},verified=False)
        with self.assertRaisesRegex(ValueError,'missing'):canonicalize_sources(x,q,sh,names,{},verified=True)
    def test_same_order_protects_every_unmodified_field(self):
        s=GaussianState(torch.zeros(5,3),torch.tensor([[1.,0,0,0]]).repeat(5,1),torch.ones(5,3),torch.ones(5)*.5,torch.zeros(5,4,3),torch.arange(5))
        from reconstruction_components_v3 import pick
        ids=torch.tensor([1,3]);p=pick(s,ids);p.means+=.1;r=replace_same_order(s,ids,p)
        for k in GaussianState.__dataclass_fields__:torch.testing.assert_close(getattr(r,k)[[0,2,4]],getattr(s,k)[[0,2,4]],atol=0,rtol=0)
    def test_covariance_transport_matches_explicit_matrix(self):
        f,p,n,t=self.field();f.delta.data.fill_(.15);means,J=f(p,n,t)
        q=torch.tensor([[1.,0,0,0]],dtype=p.dtype).expand(25,4)
        s=GaussianState(p,q,torch.tensor([.02,.01,.001],dtype=p.dtype).expand(25,3),torch.full((25,),.7,dtype=p.dtype),torch.zeros(25,4,3,dtype=p.dtype),torch.zeros(25,dtype=torch.long))
        moved=transport_covariance(s,J,means,polar_frame(J))
        torch.testing.assert_close(moved.covariance(),J@s.covariance()@J.transpose(-1,-2),atol=1e-10,rtol=1e-8)
        self.assertTrue(torch.isfinite(moved.quats).all())
    def test_batched_factorizations_preserve_values_and_covariance_gradient(self):
        torch.manual_seed(11)
        J=(torch.eye(3,dtype=torch.float64)[None]+torch.randn(35,3,3,dtype=torch.float64)*.08).requires_grad_(True)
        large=bounded_singular_values(J,512);small=bounded_singular_values(J,7)
        torch.testing.assert_close(large,small,atol=1e-12,rtol=1e-12)
        ga=torch.autograd.grad(large.square().sum(),J,retain_graph=True)[0];gb=torch.autograd.grad(small.square().sum(),J)[0]
        torch.testing.assert_close(ga,gb,atol=1e-12,rtol=1e-12)
        torch.testing.assert_close(polar_frame(J,512),polar_frame(J,7),atol=1e-12,rtol=1e-12)

    @unittest.skipUnless(torch.cuda.is_available(),'requires actual CUDA')
    def test_locked_renderer_covariance_forward_and_backward(self):
        from reconstruction_canonical_surface import draw_covariance
        from reconstruction_portrait_pipeline import draw
        device='cuda';C=torch.eye(4,device=device);K=torch.tensor([[80.,0,32],[0,80,32],[0,0,1.]],device=device)
        s=GaussianState(torch.tensor([[0.,0.,2.],[.12,0.,2.2]],device=device,requires_grad=True),torch.tensor([[1.,0,0,0]]*2,device=device),torch.tensor([[.07,.05,.01]]*2,device=device),torch.tensor([.7,.6],device=device),torch.zeros(2,4,3,device=device),torch.tensor([1,0],device=device))
        a=draw(s,C,K,64,64);b=draw_covariance(s,s.covariance(),C,K,64,64)
        for k in ('rgb','alpha','q'):torch.testing.assert_close(a[k],b[k],atol=1e-6,rtol=1e-5)
        ga=torch.autograd.grad(a['rgb'].square().sum(),s.means,retain_graph=True)[0];gb=torch.autograd.grad(b['rgb'].square().sum(),s.means)[0]
        torch.testing.assert_close(ga,gb,atol=1e-4,rtol=2e-4)
if __name__=='__main__':unittest.main()