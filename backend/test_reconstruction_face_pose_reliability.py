import unittest
import numpy as np
import cv2
from reconstruction_face_pose_reliability import (project,bounded_pose_candidate,three_view_cycles,
    source_ray_binding,PoseReliabilityConfig,native_face_features)


class FacePoseReliability(unittest.TestCase):
    def test_fixed_K_bounded_pose_recovers_small_observed_motion(self):
        x,y=np.meshgrid(np.linspace(-.05,.05,8),np.linspace(-.07,.07,8))
        points=np.stack([x.ravel(),y.ravel(),.007*np.sin(x.ravel()*60)],1)
        K=np.array([[1100.,0,540],[0,1100,960],[0,0,1.]])
        F=np.eye(4);F[2,3]=.55;true=F.copy();true[0,3]=.0004
        target,_=project(points,true,K);fit=np.arange(len(points))%5!=0
        candidate,report=bounded_pose_candidate(points,target,F,K,fit,np.ones(len(points)))
        self.assertLess(report['fitMedianAfter'],report['fitMedianBefore']*.1)
        self.assertLess(report['reservedMedianAfter'],.1)
        self.assertLessEqual(report['rotationDeltaDegrees'],.75+1e-8)
        np.testing.assert_array_equal(K,np.array([[1100.,0,540],[0,1100,960],[0,0,1.]]))
        self.assertFalse(report['acceptedForTraining'])

    def test_sparse_patch_cannot_be_used_for_pose(self):
        K=np.eye(3);F=np.eye(4);F[2,3]=1
        p=np.zeros((30,3));uv=np.zeros((30,2))
        candidate,report=bounded_pose_candidate(p,uv,F,K,np.ones(30,bool),np.ones(30))
        self.assertEqual(report['status'],'insufficient_image_distribution')
        np.testing.assert_array_equal(candidate,F)

    def test_cycle_requires_direct_third_observation(self):
        self.assertEqual(three_view_cycles({0:1,2:3},{1:4,3:5},{0:4,2:8}),[(0,1,4)])

    def test_ray_binding_is_true_3D_barycentric_projection(self):
        mesh=np.array([[-1.,-1,1],[1.,-1,1],[0,1,1]])
        result=source_ray_binding(np.zeros(2),mesh,np.array([[0,1,2]]),np.eye(4),np.eye(3))
        self.assertEqual(result[0],0);np.testing.assert_allclose(result[1],[.25,.25,.5])
        self.assertIsNone(source_ray_binding(np.array([5.,0]),mesh,np.array([[0,1,2]]),np.eye(4),np.eye(3)))

    def test_native_feature_crop_returns_full_frame_coordinates(self):
        rng=np.random.default_rng(731);gray=rng.integers(0,256,(350,500),dtype=np.uint8)
        mask=np.zeros_like(gray);mask[120:280,210:410]=255
        sift=cv2.SIFT_create(nfeatures=500,contrastThreshold=.006)
        points,descriptor,receipt=native_face_features(gray,mask,sift,padding=25)
        self.assertGreater(len(points),3)
        x0,y0,x1,y1=receipt['crop']
        direct,expected=sift.detectAndCompute(gray[y0:y1,x0:x1],mask[y0:y1,x0:x1])
        np.testing.assert_allclose(points,np.array([k.pt for k in direct])+[x0,y0],atol=1e-8)
        np.testing.assert_array_equal(descriptor,expected)
        self.assertFalse(receipt['resized'])


if __name__=='__main__':unittest.main()
