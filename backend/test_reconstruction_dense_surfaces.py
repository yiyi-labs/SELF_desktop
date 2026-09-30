import unittest
import numpy as np
from reconstruction_dense_surfaces import native_uv,surface_samples,multiview_support
from reconstruction_dense_contract import resized_camera

class DenseSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.K=np.array([[100.,0,20],[0,100,20],[0,0,1.]])
        self.T=np.eye(4);self.depth=np.ones((40,40),np.float32)*2
    def test_planar_covariance_and_no_normal_flip(self):
        uv,xyz,basis,scale,valid=surface_samples(self.depth,self.K,self.T,2)
        self.assertTrue(valid.all());self.assertTrue(np.allclose(xyz[:,2],2))
        self.assertTrue(np.allclose(np.linalg.det(basis),1));self.assertTrue((scale>0).all())
        self.assertTrue(np.all(scale[:,2]<scale[:,0]))
    def test_depth_jump_excluded(self):
        self.depth[:,20:]=4
        uv,xyz,basis,scale,valid=surface_samples(self.depth,self.K,self.T,1)
        self.assertTrue((~valid[uv[:,0]==19]).all())
    def test_native_pixel_inverse(self):
        K,A=resized_camera(self.K,[4,6,34,36],(40,40),(28,28))
        q=np.array([[0.,0.],[27,27.]])
        p=native_uv(q,A);h=np.c_[p,np.ones(2)]@A.T
        np.testing.assert_allclose(h[:,:2],q,atol=1e-12)
    def test_unique_views_not_window_duplicates(self):
        labels={'a':{'room_visible':np.ones((40,40),bool),'unknown_or_occluded':np.zeros((40,40),bool)}}
        row={'imageName':'a'};arr={'K':self.K,'W2C':self.T,'depth':self.depth,'confidence':np.ones((40,40)), 'nativeToProcessed':np.eye(3)}
        sup,free,occ,ok=multiview_support(np.array([[0,0,2.]]),0,[(row,arr)]*3,labels,3)
        self.assertEqual(sup[0],1);self.assertFalse(ok[0])
    def test_occluded_not_accepted_or_free_space(self):
        labels={n:{'room_visible':np.ones((40,40),bool),'unknown_or_occluded':np.zeros((40,40),bool)} for n in 'abc'}
        arr={'K':self.K,'W2C':self.T,'depth':self.depth,'confidence':np.ones((40,40)), 'nativeToProcessed':np.eye(3)}
        rows=[({'imageName':n},arr) for n in 'abc']
        sup,free,occ,ok=multiview_support(np.array([[0,0,3.]]),0,rows,labels,3)
        self.assertEqual(sup[0],0);self.assertEqual(free[0],0);self.assertEqual(occ[0],3);self.assertFalse(ok[0])
    def test_predicted_multiview_agreement_is_only_hypothesis(self):
        labels={n:{'room_visible':np.ones((40,40),bool),'unknown_or_occluded':np.zeros((40,40),bool)} for n in 'abc'}
        arr={'K':self.K,'W2C':self.T,'depth':self.depth,'confidence':np.ones((40,40)), 'nativeToProcessed':np.eye(3)}
        sup,free,occ,ok=multiview_support(np.array([[0,0,2.]]),0,[({'imageName':n},arr) for n in 'abc'],labels,3)
        self.assertEqual(sup[0],3);self.assertTrue(ok[0])

if __name__=='__main__':unittest.main()