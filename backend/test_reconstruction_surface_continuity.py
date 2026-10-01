import unittest,numpy as np,torch
from reconstruction_surface_continuity import continuous_motion,SharedDisplacementField,projected_transition_gradient,transport_covariance,select_skin_contacts
from reconstruction_portrait_model import GaussianState

class SurfaceContinuityTests(unittest.TestCase):
    def state(self):
        return GaussianState(torch.tensor([[.0,.2,2.],[.1,.5,2.],[.0,.8,2.]]),torch.tensor([[1.,0,0,0]]).repeat(3,1),
            torch.tensor([[.02,.03,.01]]).repeat(3,1),torch.ones(3)*.7,torch.randn(3,4,3)*.1,torch.ones(3,dtype=torch.long)*4)
    def test_reference_identity_covariance_and_sh(self):
        s=self.state();r,J=continuous_motion(s,torch.eye(4),torch.eye(4),torch.tensor([1.,.5,0.]),torch.ones(3,3)*.2)
        torch.testing.assert_close(r.means,s.means);torch.testing.assert_close(r.covariance(),s.covariance(),rtol=2e-5,atol=1e-8)
        torch.testing.assert_close(r.sh,s.sh,rtol=2e-6,atol=1e-7)
    def test_position_derivative_contains_weight_gradient(self):
        s=self.state();H=torch.eye(4);H[0,3]=.2;B=torch.eye(4);w=torch.tensor([.8,.5,.2]);g=torch.tensor([[0.,-.5,0.]]).repeat(3,1)
        r,J=continuous_motion(s,H,B,w,g);expected=torch.eye(3).repeat(3,1,1);expected[:,0,1]=-.1
        torch.testing.assert_close(J,expected)
        cov=expected@s.covariance()@expected.transpose(-1,-2);torch.testing.assert_close(r.covariance(),cov,rtol=2e-5,atol=1e-8)
    def test_footprint_deformation_differs_from_rigid_orientation(self):
        s=self.state();H=torch.eye(4);H[1,3]=.2
        r,J=continuous_motion(s,H,torch.eye(4),torch.ones(3)*.5,torch.tensor([[0.,-.5,0.]]).repeat(3,1))
        self.assertGreater(float((r.covariance()-s.covariance()).abs().max()),1e-5)
        torch.testing.assert_close(r.sh[:,1:].square().sum(1),s.sh[:,1:].square().sum(1),rtol=2e-5,atol=1e-7)
    def test_field_is_shared_bounded_and_has_consistent_derivative(self):
        torch.manual_seed(2);p=torch.randn(20,3);m=SharedDisplacementField(p,.01,6);m.delta.data.normal_()
        x,J=m(p);self.assertLessEqual(float((x-p).abs().max().detach()),.010001)
        v=p[:1].clone().requires_grad_();actual=torch.autograd.functional.jacobian(lambda a:m(a)[0],v)[0,:,0,:]
        torch.testing.assert_close(actual,m(v)[1][0],rtol=1e-5,atol=1e-6)
        x.sum().backward();self.assertTrue(torch.isfinite(m.delta.grad).all());self.assertGreater(float(m.delta.grad.abs().sum()),0)
    def test_projected_gradient_matches_finite_difference(self):
        p=torch.tensor([[.1,.5,2.]]);C=torch.eye(4);K=torch.tensor([[300.,0,100],[0,300,100],[0,0,1.]])
        g=projected_transition_gradient(p,C,K,130,220,torch.tensor([True]))
        def w(x):
            q=x@K.T;u=(q[:,1]/q[:,2]-130)/90;return 1-3*u*u+2*u*u*u
        actual=torch.stack([(w(p+torch.eye(3)[k]*.0001)-w(p-torch.eye(3)[k]*.0001))/.0002 for k in range(3)],1)
        torch.testing.assert_close(g,actual,rtol=.005,atol=.001)
    def test_contacts_are_skin_only_and_bounded(self):
        neck=np.array([[0.,0.,2.],[1.,0.,2.]]);head=np.array([[0.,.01,2.]])
        a,b,r=select_skin_contacts(neck,head,np.diag([100.,100.,1.]),np.eye(4))
        self.assertEqual(a.tolist(),[0]);self.assertEqual(b.tolist(),[0]);self.assertFalse(r['skinClothWeld'])
    def test_material_weight_chain_matches_actual_deformation(self):
        s=self.state();A=torch.tensor([[1.05,.04,0],[0,.97,.02],[0,0,1.]])
        H=torch.eye(4);H[0,3]=.2;B=torch.eye(4);g=torch.tensor([0.,-.1,.03]);p=s.means
        field=p@A.T;w=.6+p@g;local=GaussianState(field,s.quats,s.scales,s.opacity,s.sh,s.parts)
        r,J=continuous_motion(local,H,B,w,g[None].repeat(len(p),1),field_jacobian=A[None].repeat(len(p),1,1))
        def actual(x):
            y=x@A.T;weight=.6+x@g;head=y@H[:3,:3].T+H[:3,3];body=y@B[:3,:3].T+B[:3,3]
            return weight[:,None]*head+(1-weight[:,None])*body
        for i in range(len(p)):
            jac=torch.autograd.functional.jacobian(actual,p[i:i+1])[0,:,0,:]
            torch.testing.assert_close(J[i],jac,rtol=1e-6,atol=1e-7)
        torch.testing.assert_close(r.means,actual(p))
    def test_full_surface_gradients_are_finite(self):
        s=self.state();m=SharedDisplacementField(s.means,.01,3);x,J=m(s.means)
        moved=GaussianState(x,s.quats,s.scales,s.opacity,s.sh,s.parts)
        H=torch.eye(4);H[0,3]=.02
        r,_=continuous_motion(moved,H,torch.eye(4),torch.ones(3)*.5,torch.ones(3,3)*.01,field_jacobian=J)
        (r.means.square().sum()+r.scales.sum()).backward();self.assertTrue(torch.isfinite(m.delta.grad).all())
if __name__=='__main__':unittest.main()
