import unittest
import numpy as np,torch
from reconstruction_canonical_surface import (vertex_rotations,transport_field,
    triangle_jacobians,transport_covariance)
from reconstruction_portrait_model import quaternion_matrix
from reconstruction_temporal_observations import select_windows,source_indices,crop_transform,pixels

class TransportTests(unittest.TestCase):
    def mesh(self):
        return torch.tensor([[0.,0,0],[1,0,0],[0,1,0],[1,1,0]],dtype=torch.float64),torch.tensor([[0,1,2],[1,3,2]])
    def test_rigid_pose_and_canonical_field_share_operator(self):
        x,f=self.mesh();a=.7;R=torch.tensor([[np.cos(a),0,np.sin(a)],[0,1,0],[-np.sin(a),0,np.cos(a)]],dtype=x.dtype)
        obs=x@R.T+torch.tensor([.3,-.1,.2])
        D=vertex_rotations(x,obs,f)
        d=torch.randn_like(x,requires_grad=True)*.01
        torch.testing.assert_close(transport_field(d,D),d@R.T)
        loss=transport_field(d,D).square().sum();g=torch.autograd.grad(loss,d)[0]
        torch.testing.assert_close(g,2*d)
        torch.testing.assert_close(vertex_rotations(x,x,f),torch.eye(3,dtype=x.dtype).expand(4,3,3))
    def test_full_covariance_strain_and_rotation(self):
        x,f=self.mesh();J=torch.tensor([[1.2,.2,0],[0,.8,0],[0,0,1.]],dtype=x.dtype)
        t=triangle_jacobians(x[f],(x@J.T)[f])
        torch.testing.assert_close(t,J.expand(2,3,3))
        q=torch.tensor([[1.,0,0,0],[.9,.1,.2,.3]],dtype=x.dtype);s=torch.tensor([[.01,.02,.003],[.02,.011,.005]],dtype=x.dtype)
        nq,ns=transport_covariance(q,s,t)
        r=quaternion_matrix(q);want=t@(r@torch.diag_embed(s.square())@r.transpose(-1,-2))@t.transpose(-1,-2)
        nr=quaternion_matrix(nq);actual=nr@torch.diag_embed(ns.square())@nr.transpose(-1,-2)
        torch.testing.assert_close(actual,want)
        self.assertTrue(bool((ns>0).all()))
    def test_vertex_identity_does_not_require_named_frames(self):
        x,f=self.mesh()
        for scale in (.1,7.,100.):
            D=vertex_rotations(x*scale,x*scale,f)
            torch.testing.assert_close(D,torch.eye(3,dtype=x.dtype).expand(4,3,3))
    def test_native_roi_roundtrip_across_landscape_portrait(self):
        for h,w in [(1920,1080),(720,1280),(320,500)]:
            rect=(11,13,w-17,h-19);_,m=crop_transform(np.zeros((h,w,3),np.uint8),rect)
            p=np.array([[11.2,13.8],[w/2,h/2],[w-17.1,h-19.2]])
            np.testing.assert_allclose(pixels(pixels(p,m),m,True),p,atol=1e-10)
    def test_timestamps_not_ids_and_anchor_preservation(self):
        rows=[dict(name=n,timestampSeconds=t,coverage=500,sharpness=10,cameraCenter=[t,0,0]) for n,t in zip(["z","a","large_id","x","next"],[0,.2,.4,.6,3.])]
        ws=select_windows(rows);self.assertEqual([r["name"] for r in ws[0]],["z","a","large_id","x"])
        times=np.arange(100)/30
        a=[dict(sourceIndexZeroBased=i,timestampSeconds=times[i]) for i in (2,7,23)]
        idx=source_indices(times,a,max_frames=10)
        self.assertTrue(set([2,7,23])<=set(idx));self.assertLessEqual(len(idx),10)
        a[0]["timestampSeconds"]+=.1
        with self.assertRaises(ValueError):source_indices(times,a)

    @unittest.skipUnless(torch.cuda.is_available(),"CUDA required")
    def test_native_covariance_pixels_and_isotropic_gradients(self):
        from reconstruction_portrait_model import GaussianState
        from reconstruction_portrait_pipeline import draw
        from reconstruction_canonical_surface import draw_covariance
        device="cuda";s=torch.tensor([[.023,.023,.023],[.015,.024,.01]],device=device,requires_grad=True)
        q=torch.tensor([[1.,0,0,0],[.9,.1,.2,.3]],device=device,requires_grad=True)
        means=torch.tensor([[-.09,0,2],[.1,.07,2.2]],device=device)
        state=GaussianState(means,q,s,torch.tensor([.7,.65],device=device),
            torch.ones((2,4,3),device=device)*.2,torch.tensor([1,1],device=device))
        K=torch.tensor([[200.,0,128],[0,200.,96],[0,0,1]],device=device);C=torch.eye(4,device=device)
        a=draw(state,C,K,256,192);b=draw_covariance(state,state.covariance(),C,K,256,192)
        for key in ("rgb","alpha","q"):torch.testing.assert_close(a[key],b[key],atol=2e-6,rtol=2e-5)
        ga=torch.autograd.grad(a["rgb"].sum()+a["alpha"].sum(),(s,q),retain_graph=True)
        gb=torch.autograd.grad(b["rgb"].sum()+b["alpha"].sum(),(s,q))
        for x,y in zip(ga,gb):
            self.assertTrue(bool(torch.isfinite(y).all()))
            torch.testing.assert_close(x,y,rtol=.001,atol=1e-4)

    def test_affine_rotation_about_patch_center_is_not_origin_translation(self):
        from reconstruction_temporal_observations import affine_center_delta
        a=.12;R=np.array([[np.cos(a),-np.sin(a)],[np.sin(a),np.cos(a)]])
        center=np.array([12.,12.]);translation=np.array([.6,-.8])
        W=np.c_[R,center+translation-R@center]
        np.testing.assert_allclose(affine_center_delta(W,(25,25)),translation,atol=1e-12)
        self.assertGreater(np.linalg.norm(W[:,2]-translation),1.)
    def test_affine_pixel_measurement_of_real_transformed_texture(self):
        import cv2
        from reconstruction_temporal_observations import bounded_native_affine,affine_center_delta
        rng=np.random.default_rng(31);im=cv2.GaussianBlur(rng.random((55,55)).astype(np.float32),(5,5),1)
        W=cv2.getRotationMatrix2D((27,27),3.,1.01);W[:,2]+=np.array([.55,-.4])
        dst=cv2.warpAffine(im,W,(55,55))
        warp,_,_=bounded_native_affine(im,dst)
        np.testing.assert_allclose(affine_center_delta(warp,im.shape),affine_center_delta(W,im.shape),atol=.15)

    def test_source_index_and_timestamp_bounds_are_not_silently_coerced(self):
        times=np.arange(12)/30
        for i,t in [(-1,times[-1]),(12,.4),(1.5,times[1])]:
            with self.assertRaises(ValueError):
                source_indices(times,[dict(sourceIndexZeroBased=i,timestampSeconds=t)])
        with self.assertRaises(ValueError):
            source_indices(np.array([0.,np.nan,.2]),[dict(sourceIndexZeroBased=0,timestampSeconds=0.)])
    def test_users_without_glasses_do_not_get_glasses_proposals(self):
        from run_complete_observations import distributed_queries
        im=np.random.default_rng(7).integers(0,256,(100,160,3),dtype=np.uint8)
        masks={k:np.zeros((100,160),bool) for k in ['face_core','hair_visible','glasses_visible','neck_cloth_visible','unknown_or_occluded']}
        masks['face_core'][25:75,35:125]=True
        q,roles=distributed_queries(im,masks)
        self.assertGreater(len(q),0);self.assertNotIn('glasses',roles)

if __name__=="__main__":unittest.main()
