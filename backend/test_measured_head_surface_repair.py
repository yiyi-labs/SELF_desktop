import unittest,torch
from run_measured_head_surface_repair import LocalMeasuredField,HeadMeasuredStage
from reconstruction_portrait_model import GaussianState

class FieldTests(unittest.TestCase):
    def test_compact_derivative_and_unknown_exact(self):
        torch.manual_seed(3);x=torch.randn(20,3);field=LocalMeasuredField(x,.01,6);field.delta.data.normal_()
        p=x[:1].clone().requires_grad_();v,J=field(p)
        g=torch.autograd.functional.jacobian(lambda q:field(q)[0],p)[0,:,0,:]
        torch.testing.assert_close(g,J[0],rtol=2e-5,atol=2e-6)
        far=torch.ones(3,3)*100;v,J=field(far);torch.testing.assert_close(v,far,rtol=0,atol=0)
        torch.testing.assert_close(J,torch.eye(3).repeat(3,1,1),rtol=0,atol=0)
    def test_zero_field_preserves_covariance_and_colour(self):
        from reconstruction_surface_continuity import transport_covariance
        x=torch.randn(12,3);field=LocalMeasuredField(x,.01,4)
        s=GaussianState(x,torch.nn.functional.normalize(torch.randn(12,4),dim=1),torch.rand(12,3)*.01+.001,
            torch.rand(12),torch.randn(12,4,3),torch.ones(12,dtype=torch.long))
        moved,J=field(x);r=transport_covariance(s,J,moved,torch.eye(3).repeat(12,1,1))
        torch.testing.assert_close(r.covariance(),s.covariance(),rtol=1e-4,atol=1e-8)
        torch.testing.assert_close(r.means,s.means,rtol=0,atol=0);torch.testing.assert_close(r.sh,s.sh,rtol=0,atol=0)
    def test_zero_updates_preserve_other_expression_state(self):
        from run_measured_head_surface_repair import relative_appearance
        from reconstruction_components_v3 import FreeComponent
        x=torch.randn(5,3);q=torch.nn.functional.normalize(torch.randn(5,4),dim=1)
        old=GaussianState(x,q,torch.rand(5,3)*.02+.001,torch.rand(5)*.8+.1,torch.randn(5,4,3),torch.ones(5,dtype=torch.long))
        patch=FreeComponent(old,torch.arange(5),torch.ones(5),'head-local',0.)
        current=GaussianState(x+.01,q.roll(1,0),old.scales*1.13,old.opacity*.9,old.sh+.07,old.parts)
        output=relative_appearance(current,patch.state(),old.scales,old.opacity,old.sh,patch.opacity)
        torch.testing.assert_close(output.means,current.means,rtol=0,atol=0)
        torch.testing.assert_close(output.quats,current.quats,rtol=0,atol=0)
        torch.testing.assert_close(output.scales,current.scales,rtol=1e-6,atol=1e-7)
        torch.testing.assert_close(output.opacity,current.opacity,rtol=1e-6,atol=1e-7)
        torch.testing.assert_close(output.sh,current.sh,rtol=1e-6,atol=1e-7)

class NativeInputTests(unittest.TestCase):
    def test_object_roi_keeps_original_pixels_and_projection(self):
        import numpy as np
        from prepare_measured_hair_mvs import native_object_crop
        image=np.arange(40*60*3,dtype=np.uint16).reshape(40,60,3);mask=np.zeros((40,60),bool);mask[11:22,18:31]=True
        K=np.array([[120.,0,30],[0,120.,20],[0,0,1.]])
        P=np.array([.1,.1,2.]);uv=(K@P)[:2]/P[2]
        tracks=[dict(xyz=P.tolist(),observations=[dict(name='a',uv=uv.tolist())])]
        images,masks,k,pts,bounds=native_object_crop({'a':image},{'a':mask},K,tracks,padding=2)
        x0,y0,x1,y1=bounds;np.testing.assert_array_equal(images['a'],image[y0:y1,x0:x1])
        np.testing.assert_allclose((k@P)[:2]/P[2],uv-[x0,y0]);np.testing.assert_allclose(pts[0]['observations'][0]['uv'],uv-[x0,y0])
        np.testing.assert_array_equal(K,[[120.,0,30],[0,120.,20],[0,0,1.]])
    def test_native_export_half_pixel_exactly_once(self):
        import numpy as np,tempfile
        from pathlib import Path
        from reconstruction_complete_contract import export_native_mvs_window
        from reconstruction_room_surface_repair import validate_imported_native_intrinsics
        K=np.array([[120.,0,3],[0,120.,2],[0,0,1.]])
        tracks=[dict(xyz=[0,0,2],observations=[dict(name='a.png',uv=[3.,2.])],color=[25,50,75],error=0.)]
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);meta=export_native_mvs_window(folder/'colmap',{'a.png':np.ones((5,7,3),np.uint8)},{'a.png':np.ones((5,7),bool)},['a.png'],{'a.png':np.eye(4)},K,tracks,input_pixel_center='opencv_integer')
            np.testing.assert_allclose(validate_imported_native_intrinsics(folder,{'contract':meta},K),K)
            row=(folder/'colmap/sparse/images.txt').read_text().splitlines()[1].split();np.testing.assert_allclose(list(map(float,row[:2])),[3.5,2.5])
            (folder/'colmap/sparse/cameras.txt').write_text('1 PINHOLE 7 5 120 120 3 2\n')
            with self.assertRaisesRegex(ValueError,'actual_OpenMVS_native_K_mismatch'):validate_imported_native_intrinsics(folder,{'contract':meta},K)

class FixedCameraTrackTests(unittest.TestCase):
    def test_retriangulation_preserves_real_observations(self):
        import numpy as np
        from prepare_measured_hair_mvs import retriangulate_fixed_records
        from reconstruction_surface_evidence import project
        K=np.array([[400.,0,100],[0,400.,100],[0,0,1.]])
        cameras={};obs=[];X=np.array([.05,.02,2.])
        for i in range(4):
            C=np.eye(4);C[0,3]=-.1*i;cameras[str(i)]=C
            obs.append(dict(name=str(i),uv=project(X[None],C,K)[0][0].tolist(),sigma=1.))
        t=dict(id='real',region='hair',observations=obs,xyz=[0,0,1])
        accepted,rejected=retriangulate_fixed_records([t],cameras,K)
        self.assertEqual((len(accepted),rejected),(1,0));np.testing.assert_allclose(accepted[0]['xyz'],X,atol=1e-6)
        self.assertEqual(accepted[0]['observations'],obs)
    def test_bad_third_view_not_filled_with_a_pose_or_point(self):
        import numpy as np
        from prepare_measured_hair_mvs import retriangulate_fixed_records
        from reconstruction_surface_evidence import project
        K=np.array([[400.,0,100],[0,400.,100],[0,0,1.]]);X=np.array([.05,.02,2.]);cameras={};obs=[]
        for i in range(4):
            C=np.eye(4);C[0,3]=-.1*i;cameras[str(i)]=C;uv=project(X[None],C,K)[0][0]
            if i==3:uv=uv+[20,0]
            obs.append(dict(name=str(i),uv=uv.tolist(),sigma=1.))
        accepted,rejected=retriangulate_fixed_records([dict(id='bad',region='hair',observations=obs)],cameras,K)
        self.assertEqual((len(accepted),rejected),(0,1))

if __name__=='__main__':unittest.main()
