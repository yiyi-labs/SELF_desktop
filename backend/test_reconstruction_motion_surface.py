import unittest,copy
import numpy as np
from reconstruction_motion_geometry import motion_matrices,deduplicate_tracks,measured_geometry
from reconstruction_motion_patches import coverage_budget
from reconstruction_dense_contract import project
class MotionSurfaceContracts(unittest.TestCase):
    def test_reference_is_identity_and_rigid(self):
        names=['a','b','c'];ts={'a':1.,'b':2.,'c':3.};B=motion_matrices(names,ts,'b',np.ones(6)*.4,np.array([1.,2.,3.]),2.)
        np.testing.assert_allclose(B['b'],np.eye(4),atol=1e-12)
        for T in B.values():np.testing.assert_allclose(T[:3,:3].T@T[:3,:3],np.eye(3),atol=1e-12)
    def test_motion_scales_translation_without_scaling_shape(self):
        names=['a','b'];ts={'a':0.,'b':1.};raw=np.r_[np.zeros(3),np.ones(3)*.5]
        a=motion_matrices(names,ts,'a',raw,np.zeros(3),1.)['b'];b=motion_matrices(names,ts,'a',raw,np.zeros(3),2.)['b']
        np.testing.assert_allclose(b[:3,3],2*a[:3,3]);np.testing.assert_allclose(a[:3,:3],b[:3,:3])
    def test_dedup_needs_three_real_observations_and_same_part(self):
        obs=[dict(name=str(i),uv=[1.,2.],sigma=.5) for i in range(4)];tracks=[dict(id='a',region='face',observations=obs),dict(id='b',region='face',observations=obs),dict(id='c',region='hair',observations=obs)]
        kept,dups=deduplicate_tracks(tracks);self.assertEqual(len(kept),2);self.assertEqual(len(dups),1)
    def test_shared_xyz_and_third_view_with_fixed_cameras(self):
        K=np.array([[200.,0,100],[0,200,100],[0,0,1.]]);names=[str(i) for i in range(5)];C={};ts={}
        for i,n in enumerate(names):C[n]=np.eye(4);C[n][0,3]=(i-2)*.08;ts[n]=float(i)
        points=np.array([[-.1,-.1,2.],[.1,.1,1.8],[.0,.1,2.2],[.1,-.1,2.1]])
        tracks=[dict(id='x'+str(j),region='face',observations=[dict(name=n,uv=project(p[None],K,C[n])[0][0].tolist(),sigma=.5) for n in names]) for j,p in enumerate(points)]
        frozen={n:T.copy() for n,T in C.items()};g=measured_geometry(tracks,C,K,ts)
        self.assertEqual(len(g['records']),4);self.assertTrue(all(r['accepted'] for r in g['records']))
        self.assertLess(max(r['thirdError'] for r in g['records']),1e-6)
        for n in names:np.testing.assert_array_equal(C[n],frozen[n])
    def test_no_depth_evidence_is_not_fabricated(self):
        K=np.eye(3);C={str(i):np.eye(4) for i in range(4)};ts={str(i):float(i) for i in range(4)};t=[dict(id='x',region='hair',observations=[dict(name=n,uv=[.1,.1],sigma=1.) for n in C])]
        g=measured_geometry(t,C,K,ts);self.assertFalse(g['motionAccepted']);self.assertEqual(len(g['records']),0)
    def test_budget_balances_sparse_visible_cells(self):
        points=np.array([[0.,0.,1.],[.01,0,1.],[.02,0,1.],[.5,0,1.],[-.5,0,1.]])
        arr=dict(means=points,uid=np.arange(5),confidence=np.ones(5));K=np.array([[100.,0,100],[0,100,100],[0,0,1.]])
        ids=coverage_budget(arr,{'x':np.eye(4)},K,{'x':np.ones((200,200),bool)},3,2)
        self.assertIn(3,ids);self.assertIn(4,ids);self.assertEqual(len(np.unique(ids)),3)


from reconstruction_patch_transaction import PatchTransaction,compare_patch_views
from reconstruction_native_measurements import native_measurement,locate_patch
import cv2

class NativeMeasurementAndReplacement(unittest.TestCase):
    def test_real_unique_texture_is_localized_not_network_coordinate(self):
        rng=np.random.default_rng(42);source=rng.integers(0,256,(160,160),dtype=np.uint8)
        target=cv2.warpAffine(source,np.array([[1.,0,4.],[0,1.,-2.]],np.float32),(160,160))
        q=np.array([80.,80.]);p,record=native_measurement(source,target,q,q+[6.,0.])
        np.testing.assert_allclose(p,q+[4.,-2.],atol=.2);self.assertLess(record['fb'],.2)
    def test_no_texture_does_not_create_measurement(self):
        image=np.full((160,160),128,np.uint8)
        with self.assertRaises(ValueError):native_measurement(image,image,[80.,80.],[80.,80.])
    def test_texture_with_repeated_peaks_is_rejected(self):
        y,x=np.mgrid[:160,:160];im=(((x//4+y//4)%2)*255).astype(np.uint8)
        template=im[68:93,68:93].astype(np.float32)/255
        with self.assertRaises(ValueError):locate_patch(template,im,[80.,80.])
    def test_missing_pixels_remain_in_fixed_region_gate(self):
        h,w=12,12;target=np.ones((h,w,3),np.float32);mask=np.ones((h,w),bool)
        before=dict(rgb=target.copy(),alpha=np.ones((h,w)),foreground=np.zeros((h,w)),mask=mask,target=target)
        after={k:v.copy() for k,v in before.items()};after['alpha'][4:8,4:8]=0;after['rgb'][4:8,4:8]=0
        r=compare_patch_views({'x':before},{'x':after});self.assertFalse(r['passed']);self.assertIn('x:lost_coverage',r['failures'])
    def test_unknown_geometry_restores_original_identity_and_binding(self):
        old=dict(uid=np.array([0,1,2],np.int64),means=np.arange(9).reshape(3,3),triangle=np.array([2,3,4]),bary=np.eye(3))
        new={k:v[1:2].copy() for k,v in old.items()};new['uid'][:]=123
        tx=PatchTransaction(old,[1],new);self.assertNotIn(1,tx.trial['uid'])
        chosen=tx.decide(dict(passed=True),geometry_supported=False)
        for k in old:np.testing.assert_array_equal(chosen[k],old[k])
        chosen=tx.decide(dict(passed=True),geometry_supported=True)
        for k in old:np.testing.assert_array_equal(chosen[k][:2],old[k][[0,2]])
    def test_duplicate_uid_or_misaligned_sidecar_is_not_accepted(self):
        old=dict(uid=np.array([0,1,2]),parts=np.array([2,2,2]));new=dict(uid=np.array([2]),parts=np.array([2]))
        with self.assertRaises(ValueError):PatchTransaction(old,[1],new)
        with self.assertRaises(ValueError):PatchTransaction(old,[1],dict(uid=np.array([10]),parts=np.array([2,2])))
    def test_cannot_change_supervision_to_pass(self):
        b=dict(rgb=np.ones((4,4,3)),alpha=np.ones((4,4)),foreground=np.zeros((4,4)),mask=np.ones((4,4),bool),target=np.ones((4,4,3)))
        a={k:v.copy() for k,v in b.items()};a['mask'][0,0]=False
        with self.assertRaises(ValueError):compare_patch_views({'x':b},{'x':a})



from reconstruction_photometric_surface import relative_surface_rotation
from reconstruction_shared_surface import small_rotation_quaternion
from reconstruction_portrait_model import quaternion_matrix
import torch

class SharedSurfaceOrientation(unittest.TestCase):
    def test_zero_field_rotation_exact_with_finite_derivative(self):
        before=torch.tensor([[[0.,0.,0.],[2.,0.,0.],[0.,3.,0.]]]);after=before.clone().requires_grad_()
        r=relative_surface_rotation(before,after);self.assertTrue(torch.equal(r,torch.eye(3)[None]))
        q=small_rotation_quaternion(r);q[:,1:].sum().backward()
        self.assertTrue(torch.isfinite(after.grad).all());self.assertGreater(float(after.grad.abs().max()),0)
    def test_single_rigid_rotation_not_applied_twice(self):
        a=.06;r=torch.tensor([[np.cos(a),0,np.sin(a)],[0,1.,0],[-np.sin(a),0,np.cos(a)]],dtype=torch.float32)
        before=torch.tensor([[[0.,0.,0.],[2.,0.,0.],[0.,3.,0.]]]);after=before@r.T
        q=small_rotation_quaternion(relative_surface_rotation(before,after))
        torch.testing.assert_close(quaternion_matrix(q)[0],r,atol=1e-6,rtol=0)

if __name__=='__main__':unittest.main()
