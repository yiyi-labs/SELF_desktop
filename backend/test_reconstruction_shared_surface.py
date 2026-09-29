"""Meaningful regression: surface gradients, source constraints, covariance transport."""
import unittest
import torch
from reconstruction_shared_surface import triangle_frames,small_rotation_quaternion
from reconstruction_portrait_model import quaternion_matrix
class SharedSurfaceTests(unittest.TestCase):
    def test_transport_gradient_and_identity(self):
        tri=torch.tensor([[[0.,0,0],[1,0,0],[0,1,0]]],dtype=torch.double)
        dz=torch.tensor(.05,dtype=torch.double,requires_grad=True)
        moved=tri+torch.stack((dz*0,dz*0,dz)).reshape(1,1,3)*torch.tensor([[[0.],[0.],[1.]]])
        R=triangle_frames(moved)@triangle_frames(tri).transpose(-1,-2)
        q=small_rotation_quaternion(R)
        self.assertTrue(torch.allclose(quaternion_matrix(q),R,atol=1e-8))
        covariance=(quaternion_matrix(q)*torch.tensor([1.,4.,.1])[None,None,:])@quaternion_matrix(q).transpose(-1,-2)
        covariance[0,1,2].backward();self.assertGreater(abs(dz.grad.item()),1.)
        ident=small_rotation_quaternion(torch.eye(3,dtype=torch.double)[None])
        self.assertTrue(torch.equal(ident,torch.tensor([[1.,0,0,0]],dtype=torch.double)))
    def test_bounded_rotation_gradcheck(self):
        tri=torch.tensor([[[0.,0,0],[1,0,0],[0,1,.03]]],dtype=torch.double,requires_grad=True)
        self.assertTrue(torch.autograd.gradcheck(lambda t:small_rotation_quaternion(triangle_frames(t)),(tri,),atol=1e-5))
if __name__=='__main__':unittest.main()

class SharedObservationTests(unittest.TestCase):
    def make_model(self):
        from reconstruction_shared_surface import SharedSurfaceModel
        m=SharedSurfaceModel.__new__(SharedSurfaceModel);torch.nn.Module.__init__(m)
        m.portrait=torch.nn.Module();m.portrait.register_buffer('faces',torch.tensor([[0,1,2]]))
        m.portrait.surface_residual=torch.nn.Parameter(torch.zeros(3,3,dtype=torch.double),requires_grad=False)
        m.attach_surface(torch.ones(3,1,dtype=torch.double),.1)
        return m
    def test_one_anchor_multiple_observations_have_surface_gradients(self):
        m=self.make_model();mesh=torch.tensor([[0.,0,1],[1,0,1],[0,1,1]],dtype=torch.double)
        bary=torch.tensor([[.3,.4,.3]],dtype=torch.double);tri=torch.tensor([0]);K=torch.diag(torch.tensor([100.,100.,1.],dtype=torch.double))
        source=torch.eye(4,dtype=torch.double);other=source.clone();other[0,3]=.2
        us,_=m.project_anchors(mesh,source,K,tri,bary);ut,_=m.project_anchors(mesh,other,K,tri,bary)
        g1=torch.autograd.grad(us.sum(),m.surface_control,retain_graph=True)[0];g2=torch.autograd.grad(ut.sum(),m.surface_control)[0]
        self.assertGreater(g1.norm(),0);self.assertGreater(g2.norm(),0);self.assertFalse(torch.allclose(g1,g2))
        self.assertEqual(m.surface_control.numel(),3) # one shared variable, not one per view
        with torch.no_grad():m.surface_control.fill_(100)
        self.assertLessEqual(float(m.displacement().norm(dim=-1).max()),.10000001)
    def test_model_serialization_keeps_surface_base_and_binding(self):
        m=self.make_model();m.surface_control.data.fill_(.2);state=m.state_dict();other=self.make_model();other.load_state_dict(state,strict=True)
        self.assertTrue(torch.equal(m.displacement(),other.displacement()));self.assertTrue(torch.equal(m.portrait.faces,other.portrait.faces))
