import unittest
import numpy as np
import torch
from reconstruction_portrait_model import GaussianState
from reconstruction_kernel_factorization import quadrature_children

class FactorizationContract(unittest.TestCase):
    def parent(self,alpha=.1):
        return GaussianState(torch.tensor([[.2,-.3,2.]]),torch.tensor([[.9238795,.0,.3826834,.0]]),
            torch.tensor([[.1,.4,.2]]),torch.tensor([alpha]),torch.arange(12,dtype=torch.float32).reshape(1,4,3)/30,
            torch.tensor([0]))
    def test_density_mean_and_covariance(self):
        old=self.parent();child,uid,meta=quadrature_children(old,[21],order=7)
        w=torch.tensor(meta['massWeights'])
        mean=(child.means*w[:,None]).sum(0)
        delta=child.means-mean
        cov=((child.covariance()+delta[:,:,None]*delta[:,None,:])*w[:,None,None]).sum(0)
        torch.testing.assert_close(mean,old.means[0],atol=1e-6,rtol=1e-5)
        torch.testing.assert_close(cov,old.covariance()[0],atol=1e-6,rtol=1e-5)
    def test_orientation_and_human_not_generated(self):
        old=self.parent();child,_,meta=quadrature_children(old,[21])
        self.assertTrue(torch.equal(child.sh,old.sh.expand(len(child.means),4,3)))
        self.assertTrue(torch.equal(child.quats,old.quats.expand(len(child.means),4)))
        self.assertTrue(torch.all(child.parts==0))
        self.assertFalse(meta['preservesAlphaCompositing'])
    def test_identity_deterministic_and_unique(self):
        a=quadrature_children(self.parent(),[21]); b=quadrature_children(self.parent(),[21])
        self.assertEqual(len(set(a[1])),len(a[1]))
        np.testing.assert_array_equal(a[1],b[1])
        self.assertEqual(a[2]['parentUID'],[21]*49)
    def test_rank_axes_not_fixed_world_axes(self):
        old=self.parent();child,_,_=quadrature_children(old,[21])
        torch.testing.assert_close(child.scales[:,0],torch.full((49,),.1))
        torch.testing.assert_close(child.scales[:,1],torch.full((49,),.4*.45))
        torch.testing.assert_close(child.scales[:,2],torch.full((49,),.2*.45))
    def test_clamped_opacity_is_recorded(self):
        child,_,meta=quadrature_children(self.parent(.99),[21])
        self.assertGreater(meta['peakClampCount'],0)
        self.assertFalse(meta['preservesDensityMoments'])
        self.assertTrue(meta['preservesQuadratureMomentsBeforeClamp'])
        self.assertLessEqual(float(child.opacity.max()),.995001)
    def test_parent_not_mutated(self):
        old=self.parent();before=[v.clone() for v in old.__dict__.values()]
        quadrature_children(old,[21])
        for a,b in zip(before,old.__dict__.values()):self.assertTrue(torch.equal(a,b))
    def test_invalid_configuration(self):
        for config in (dict(order=2),dict(fraction=1),dict(axes=(0,0))):
            with self.assertRaises(ValueError):quadrature_children(self.parent(),[21],**config)

if __name__=='__main__':unittest.main()