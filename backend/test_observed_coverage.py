import unittest
import numpy as np
import torch
from scipy import sparse
from reconstruction_observed_coverage import covariance_projection,footprint_atlas,balanced_select,atlas_summary,balanced_region_mean,protected_exchange

class CoverageTests(unittest.TestCase):
    def arrays(self):
        return dict(means=np.array([[-.11,0,1.],[.1,0,1.],[0,0,-1.]]),quats=np.array([[1.,0,0,0]]*3),scales=np.array([[.04,.04,.01]]*3),opacity=np.full(3,.6))
    def test_projected_covariance(self):
        a=self.arrays();uv,z,c=covariance_projection(a['means'],a['quats'],a['scales'],np.eye(4),np.diag([100.,100.,1.]))
        self.assertAlmostEqual(c[0,0,0],16.3121);self.assertAlmostEqual(uv[0,0],-11.)
    def test_outside_center_and_behind(self):
        a=self.arrays();K=np.array([[100.,0,0],[0,100.,16],[0,0,1.]])
        # First centre outside, but covariance contributes inside at a lower floor.
        at,weights,meta=footprint_atlas(a,[dict(name='n',role='train',C=np.eye(4),K=K,mask=np.ones((32,32),bool))],cell=2,alpha_floor=.003)
        self.assertGreater(at[0].nnz,0);self.assertEqual(at[2].nnz,0)
    def test_role_guard(self):
        with self.assertRaisesRegex(ValueError,'training'):
            footprint_atlas(self.arrays(),[dict(role='development')])
    def test_budget_covers_weak_area(self):
        at=sparse.csr_matrix([[1.,0],[1.,0],[0,1.]])
        ids,_=balanced_select(at,np.ones(2),np.array([1,2,3]),2,batch=1)
        self.assertEqual(set(ids),{0,2})
        s=atlas_summary(at,ids,[dict(name='a',offset=0,cells=2)])
        self.assertEqual(s['a']['potentialSupport'],1.)
    def test_row_order_invariant(self):
        a=sparse.csr_matrix([[1.,0],[1.,0],[0,1.]]);uid=np.array([10,20,30]);perm=np.array([2,1,0])
        x,_=balanced_select(a,np.ones(2),uid,2,batch=1);y,_=balanced_select(a[perm],np.ones(2),uid[perm],2,batch=1)
        self.assertEqual(set(uid[x]),set(uid[perm][y]))
    def test_masked_loss_gradients(self):
        error=torch.arange(100,dtype=torch.float32).reshape(10,10).requires_grad_();mask=torch.ones(10,10,dtype=torch.bool);mask[:,0]=False
        value=balanced_region_mean(error,mask,tile=4,minimum_pixels=1);value.backward()
        self.assertTrue((error.grad[mask]>0).all());self.assertTrue((error.grad[~mask]==0).all())
    def test_constant_and_empty(self):
        e=torch.full((5,7),.4,requires_grad=True)
        self.assertAlmostEqual(float(balanced_region_mean(e,torch.ones_like(e,dtype=torch.bool),4,1).detach()),.4,places=6)
        self.assertEqual(float(balanced_region_mean(e,torch.zeros_like(e,dtype=torch.bool)).detach()),0.)
    def test_unique_surface_cannot_be_sacrificed(self):
        a=sparse.csr_matrix([[1.,0,0],[0,1,0],[0,1,1]])
        selected,info=protected_exchange(a,np.ones(3),np.arange(3),[0,1],[1,2])
        self.assertIn(0,selected);self.assertEqual(info['lostOriginalSamples'],0)
    def test_redundant_surface_exchange(self):
        a=sparse.csr_matrix([[1.,0],[1.,0],[0,1.]])
        selected,info=protected_exchange(a,np.ones(2),np.arange(3),[0,1],[0,2])
        self.assertEqual(set(selected),{0,2});self.assertEqual(len(info['swaps']),1)

if __name__=='__main__':unittest.main()
