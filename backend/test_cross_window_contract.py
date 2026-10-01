import unittest
import numpy as np
import torch
from reconstruction_motion_geometry import motion_matrices,quadratic_motion_matrices
from run_context_appearance_repair import transport_colour_delta

class MotionContractTests(unittest.TestCase):
    def test_reference_identity_scale_and_cameras(self):
        names=['a','b','c'];times=dict(a=0.,b=.5,c=1.);pivot=np.array([.1,.2,1.])
        a=quadratic_motion_matrices(names,times,'b',np.ones(12),pivot,2.)
        np.testing.assert_allclose(a['b'],np.eye(4),atol=0)
        for B in a.values():
            np.testing.assert_allclose(B[:3,:3].T@B[:3,:3],np.eye(3),atol=1e-12)
            self.assertAlmostEqual(np.linalg.det(B[:3,:3]),1.)
    def test_zero_motion_exact_and_default_velocity_unchanged(self):
        names=['a','b','c'];times=dict(a=0.,b=.5,c=1.);pivot=np.array([0,0,1.])
        a=quadratic_motion_matrices(names,times,'b',np.zeros(12),pivot,1.)
        b=motion_matrices(names,times,'b',np.zeros(6),pivot,1.)
        for n in names:np.testing.assert_array_equal(a[n],b[n])
    def test_colour_delta_follows_each_point_rotation(self):
        from reconstruction_portrait_model import rotate_sh1
        torch.manual_seed(4);s=torch.randn(2,4,3)
        R=torch.stack([torch.eye(3),torch.tensor([[0.,-1,0],[1,0,0],[0,0,1]])])
        result=transport_colour_delta(s,R)
        for i in range(2):torch.testing.assert_close(result[i:i+1],rotate_sh1(s[i:i+1],R[i]))
        torch.testing.assert_close(transport_colour_delta(torch.zeros_like(s),R),torch.zeros_like(s),rtol=0,atol=0)

class ContextStageTests(unittest.TestCase):
    def test_mixed_scene_is_partitioned_and_unmodified_head_stays_exact(self):
        from unittest.mock import patch
        from run_context_appearance_repair import ContextAppearanceStage
        from reconstruction_portrait_model import GaussianState
        from types import SimpleNamespace
        torch.manual_seed(7);N=8
        s=GaussianState(torch.randn(N,3),torch.nn.functional.normalize(torch.randn(N,4),dim=1),torch.rand(N,3)*.01+.001,
            torch.rand(N)*.7+.1,torch.randn(N,4,3),torch.tensor([0,0,1,2,3,4,4,4]))
        class Base(torch.nn.Module):
            def __init__(self):super().__init__();self.scale=1.;self.baseline=SimpleNamespace(adjusted_frame=lambda f:f)
            def state(self,f):return s
        with patch('run_context_appearance_repair.make_frame',return_value={}):
            model=ContextAppearanceStage(Base(),dict(reference='x'),dict(point_id=np.arange(N)))
        self.assertEqual(set(model.patches),{'room','body'})
        r=model.state({})
        torch.testing.assert_close(r.means,s.means,rtol=0,atol=0);torch.testing.assert_close(r.scales,s.scales,rtol=0,atol=0)
        torch.testing.assert_close(r.sh,s.sh,rtol=0,atol=0);torch.testing.assert_close(r.opacity,s.opacity,rtol=1e-6,atol=1e-7)
        with torch.no_grad():model.patches['body'].sh.add_(.1)
        r=model.state({});torch.testing.assert_close(r.sh[s.parts!=4],s.sh[s.parts!=4],rtol=0,atol=0)
        torch.testing.assert_close(r.means,s.means,rtol=0,atol=0)


if __name__=='__main__':unittest.main()
