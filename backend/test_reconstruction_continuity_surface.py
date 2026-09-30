import unittest
import numpy as np
import torch
from reconstruction_continuity_surface import smooth_transition,blend_rigid_state,ShortWindowBodyMotion,spatial_neighbours,neck_region
from reconstruction_portrait_model import GaussianState

def sample():
    return GaussianState(torch.tensor([[0.,0.,1.],[0.,.5,1.],[0.,1.,1.]]),
        torch.tensor([[1.,0,0,0]]).repeat(3,1),torch.ones(3,3)*.02,
        torch.ones(3)*.5,torch.arange(36,dtype=torch.float32).reshape(3,4,3)/100,torch.ones(3,dtype=torch.long)*4)

class ContinuityTests(unittest.TestCase):
    def test_neck_association_excludes_arms_and_preserves_observed_gaps(self):
        face=np.zeros((200,180),bool);face[20:80,65:115]=True
        skin=np.zeros_like(face);skin[84:116,78:102]=True;skin[130:190,10:35]=True
        skin[92:95,86:90]=False
        actual=neck_region(skin,face)
        self.assertTrue(actual[85,80]);self.assertFalse(actual[140,20]);self.assertFalse(actual[93,87])
        self.assertFalse((actual&~skin).any());self.assertFalse(neck_region(skin,np.zeros_like(face)).any())
    def test_reference_identity_all_fields(self):
        s=sample();o=blend_rigid_state(s,torch.eye(4),torch.eye(4),torch.tensor([1.,.5,0.]))
        for k in GaussianState.__dataclass_fields__:torch.testing.assert_close(getattr(s,k),getattr(o,k),rtol=0,atol=0)
    def test_endpoints_and_continuity(self):
        s=sample();H=torch.eye(4);H[0,3]=.1;B=torch.eye(4);B[0,3]=-.1
        o=blend_rigid_state(s,H,B,torch.tensor([1.,.5,0.]));torch.testing.assert_close(o.means[:,0],torch.tensor([.1,0.,-.1]))
        w=smooth_transition(torch.tensor([0.,.25,.5,.75,1.]),0,1)
        self.assertEqual(float(w[0]),1);self.assertEqual(float(w[-1]),0);self.assertTrue(bool((torch.diff(w)<=0).all()))
    def test_shared_motion_reference_and_gradient(self):
        m=ShortWindowBodyMotion({'a':0,'b':1,'c':2},'b',[0,0,0],1,device='cpu');s=sample()
        o=m.state(s,'b');torch.testing.assert_close(o.means,s.means,rtol=0,atol=0)
        m.state(s,'c').means.sum().backward();self.assertTrue(torch.isfinite(m.velocity.grad).all());self.assertGreater(float(m.velocity.grad.abs().sum()),0)
        with self.assertRaises(ValueError):m.state(s,'unknown')
    def test_physical_layers_no_cross_edges(self):
        x=np.array([[0,0,0],[.01,0,0],[.011,0,0]]);q=np.tile([1,0,0,0],(3,1));sc=np.ones((3,3))*.01
        e=spatial_neighbours(x,q,sc,np.array([4,4,5]));self.assertEqual(e.tolist(),[[0,1]])
    def test_invalid_transition(self):
        with self.assertRaises(ValueError):smooth_transition(torch.ones(2),2,1)
    def test_transition_keeps_motion_orientation_and_sh_gradients(self):
        m=ShortWindowBodyMotion({'a':0,'b':1,'c':2},'b',[0,0,0],1,device='cpu');s=sample();B=m.matrix('c')
        o=blend_rigid_state(s,torch.eye(4),B,torch.tensor([1.,.5,0.]))
        (o.quats[:,1:].sum()+o.sh.sum()+o.means.sum()).backward()
        self.assertTrue(torch.isfinite(m.velocity.grad).all());self.assertGreater(float(m.velocity.grad[:3].abs().sum()),0)
        torch.testing.assert_close(o.covariance()[0],s.covariance()[0],rtol=0,atol=0)
    def test_intermediate_sh_transport_is_a_rotation_not_colour_averaging(self):
        s=sample();H=torch.eye(4);H[:3,:3]=torch.tensor([[0.,-1,0],[1,0,0],[0,0,1]])
        o=blend_rigid_state(s,H,torch.eye(4),torch.tensor([1.,.5,0.]))
        torch.testing.assert_close(o.sh[:,1:].square().sum(1),s.sh[:,1:].square().sum(1),rtol=1e-6,atol=1e-7)
        torch.testing.assert_close(o.sh[:,0],s.sh[:,0],rtol=0,atol=0)

if __name__=='__main__':unittest.main()
