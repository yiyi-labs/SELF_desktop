import unittest
import numpy as np
from reconstruction_dense_contract import *

class DenseContractTests(unittest.TestCase):
    def test_resize_full_and_crop_rays(self):
        K=np.array([[900.,0,540],[0,890,960],[0,0,1]])
        for rectangle in [(0,0,1080,1920),(100,300,800,1100)]:
            Ks,A=resized_camera(K,rectangle,(1080,1920),(280,504))
            uv=np.array([[140,340],[730,1000]],float)
            new=(np.c_[uv,np.ones(2)]@A.T)[:,:2]
            np.testing.assert_allclose(unproject(uv,np.ones(2),K,np.eye(4)),
                unproject(new,np.ones(2),Ks,np.eye(4)),atol=1e-12)
    def test_rotated_project_unproject(self):
        from scipy.spatial.transform import Rotation
        T=np.eye(4);T[:3,:3]=Rotation.from_rotvec([.2,-.3,.1]).as_matrix();T[:3,3]=[.1,.2,2]
        K=np.diag([800,800,1.]);K[:2,2]=[540,960]
        x=np.array([[.2,.1,.3],[-.1,.1,0.]])
        uv,z=project(x,K,T);np.testing.assert_allclose(unproject(uv,z,K,T),x,atol=1e-12)
    def test_one_scale_not_frame_scale(self):
        from scipy.spatial.transform import Rotation
        a=[];b=[];R=Rotation.from_rotvec([.1,.2,-.3]).as_matrix()
        for c in [[0,0,0],[1,0,0],[0,1,0],[0,0,1]]:
            t=np.eye(4);t[:3,3]=-np.array(c);a.append(t)
            q=np.eye(4);q[:3,:3]=R.T;q[:3,3]=-R.T@(2*np.array(c)+[3,4,5]);b.append(q)
        scale,info=align_camera_scale(a,b)
        self.assertAlmostEqual(scale,2);self.assertLess(info["cameraCentreRmsRelative"],1e-10)
    def test_occlusion_not_free_space(self):
        a=classify_depth([2,1,3,np.nan],[2,2,2,2])
        np.testing.assert_array_equal(a,[1,-1,2,0])
    def test_negative_depth_invalid(self):
        np.testing.assert_array_equal(classify_depth([-1,1],[1,-1]),[0,0])
    def test_bad_camera_rejected(self):
        T=np.eye(4);T[0,0]=2
        with self.assertRaises(ValueError):rigid_check(T)
    def test_stationary_scale_rejected(self):
        with self.assertRaises(ValueError):align_camera_scale([np.eye(4)]*3,[np.eye(4)]*3)
    def test_identity_and_split_gate(self):
        record=dict(imageName="a",W2C=np.eye(4).tolist(),role="train",sourceHash="x",imageHash="h",sourceIndexZeroBased=3)
        spec=dict(schema=SCHEMA,colour="original_srgb_rgb",depthMeaning="camera_z",matrixMeaning="W2C",sourceHash="x",observations=[record])
        self.assertTrue(validate_manifest(spec))
        record["role"]="development"
        with self.assertRaises(ValueError):validate_manifest(spec)
    def test_only_shared_parameter_alias_can_load(self):
        a=object();b=object();value=np.ones(3)
        result,aliases=complete_parameter_aliases({'a':a,'alias':a,'b':b},{'a':value,'b':np.zeros(2)})
        self.assertIs(result['alias'],value);self.assertEqual(aliases[0]['sameParameterAs'],'a')
    def test_independent_missing_weight_cannot_be_randomly_filled(self):
        with self.assertRaisesRegex(ValueError,'missing_independent_weight'):
            complete_parameter_aliases({'a':object(),'b':object()},{'a':np.ones(3)})
    def test_window_uses_capture_time_not_geometry_row(self):
        from run_dense_observations import select_names
        raw={'names':['b','c','a','d']};plan={'train':['a','b','c'],'development':['d'],'audit':[]}
        source={n:{'timestampSeconds':v,'sourceIndexZeroBased':int(v*10)} for n,v in [('a',0.),('b',1.),('c',2.),('d',3.)]}
        selected,index=select_names(raw,plan,3,source)
        self.assertEqual(selected,['a','b','c']);self.assertEqual(index['a'],2)
    def test_dense_sampling_exceeds_cv_short_without_changing_pixels(self):
        yy,xx=np.mgrid[:60,:80];image=np.stack([xx+2*yy,xx-yy,yy],axis=-1).astype(np.float32)
        uv=np.tile([[20.5,30.5],[45.,15.],[79.,59.]],(15000,1))
        sampled=bilinear(image,uv)
        np.testing.assert_allclose(sampled[:2],[[81.5,-10.,30.5],[75.,30.,15.]])
        np.testing.assert_allclose(sampled[0],sampled[39000]);self.assertEqual(sampled.shape,(45000,3))

    def test_surface_job_and_uid_contract(self):
        arr=dict(means=np.zeros((2,3)),quats=np.tile([1.,0,0,0],(2,1)),scales=np.ones((2,3)),
            opacity=np.ones(2)*.6,sh=np.zeros((2,4,3)),parts=np.array([2,2]),uid=np.array([4,5]),
            support=np.array([3,3]),confidence=np.ones(2),source_image=np.array(['a','b']),
            source_uv=np.zeros((2,2)),source_hash=np.array('source-a'))
        self.assertTrue(validate_surface_source({'sourceHash':'source-a'},{'head':arr},'source-a'))
        with self.assertRaisesRegex(ValueError,'surface_source_mismatch'):
            validate_surface_source({'sourceHash':'source-a'},{'head':arr},'source-b')
        wrong=dict(arr,source_hash=np.array('source-b'))
        with self.assertRaisesRegex(ValueError,'surface_array_source_mismatch'):
            validate_surface_source({'sourceHash':'source-a'},{'head':wrong},'source-a')
        wrong=dict(arr,uid=np.array([4,4]))
        with self.assertRaisesRegex(ValueError,'surface_uid_collision'):
            validate_surface_source({'sourceHash':'source-a'},{'head':wrong},'source-a')
        wrong=dict(arr);wrong.pop('source_uv')
        with self.assertRaisesRegex(ValueError,'surface_fields_missing'):
            validate_surface_source({'sourceHash':'source-a'},{'head':wrong},'source-a')
    def test_existing_run_is_not_mutated_by_cli_failure(self):
        import tempfile,subprocess,sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/'old-run';folder.mkdir();(folder/'receipt.json').write_text('old')
            command=[sys.executable,str(Path(__file__).with_name('run_dense_observations.py'))]
            for k in ('prepared','split','tool'):command+=['--'+k,str(Path(directory)/'missing')]
            command+=['--out',str(folder)]
            result=subprocess.run(command,capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual([p.name for p in folder.iterdir()],['receipt.json'])
            self.assertEqual((folder/'receipt.json').read_text(),'old')

if __name__=="__main__":unittest.main()
