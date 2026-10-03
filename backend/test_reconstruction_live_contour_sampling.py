import unittest
import numpy as np
from reconstruction_live_contour_sampling import surface_samples
from reconstruction_live_dense import surface_samples as legacy


class ContourSamplingTest(unittest.TestCase):
    def setUp(self):
        self.K=np.array([[10.,0,5],[0,10.,5],[0,0,1.]])
        self.T=np.eye(4)

    def test_regular_interior_is_unchanged(self):
        depth=np.full((12,12),2.)
        old=legacy(depth,self.K,self.T)
        new=surface_samples(depth,self.K,self.T)
        for a,b in zip(old,new[:5]):np.testing.assert_array_equal(a,b)

    def test_depth_boundary_uses_real_same_surface_neighbour(self):
        depth=np.full((12,12),4.);depth[:,:6]=2.
        ownership=depth==2
        old=legacy(depth,self.K,self.T)
        uv,xyz,basis,scale,good,receipt=surface_samples(depth,self.K,self.T,ownership=ownership)
        row=np.flatnonzero((uv[:,0]==5)&(uv[:,1]==5))[0]
        self.assertFalse(old[4][row]);self.assertTrue(good[row]);self.assertTrue(receipt['fallbackX'][row])
        np.testing.assert_array_equal(xyz[row],old[1][row])
        np.testing.assert_allclose(basis[row],np.eye(3),atol=1e-12)
        self.assertFalse(good[uv[:,0]>5].any())
        self.assertAlmostEqual(scale[row,0],.3)

    def test_no_normal_is_invented_for_one_pixel_sliver(self):
        depth=np.full((12,12),2.);ownership=np.zeros_like(depth,bool);ownership[:,5]=True
        result=surface_samples(depth,self.K,self.T,ownership=ownership)
        self.assertFalse(result[4].any())

    def test_foreground_and_background_do_not_share_derivatives(self):
        depth=np.full((12,12),2.);ownership=np.ones_like(depth,bool);ownership[:,6:]=False
        result=surface_samples(depth,self.K,self.T,ownership=ownership)
        chosen=(result[0][:,0]==5)&result[4]
        self.assertTrue(result[-1]['fallbackX'][chosen].all())
        depth[:,4]=np.nan
        changed=surface_samples(depth,self.K,self.T,ownership=ownership)
        self.assertFalse(changed[4][changed[0][:,0]==5].any())


if __name__=='__main__':unittest.main()
