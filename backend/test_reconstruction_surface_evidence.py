import unittest,tempfile,struct
from pathlib import Path
import cv2,numpy as np
from reconstruction_surface_evidence import project,measured_tracks,triangulate_track,export_colmap
from reconstruction_mvs_contract import read_mvs_cloud

class SurfaceContractTests(unittest.TestCase):
    def test_known_geometry_uses_same_shared_point(self):
        K=np.array([[800.,0,100],[0,800,120],[0,0,1]])
        C={};obs=[];X=np.array([.1,.03,2.5])
        for i,x in enumerate([-.2,0,.2]):
            m=np.eye(4);m[0,3]=x;C[str(i)]=m;uv,_=project(X[None],m,K);obs.append({'name':str(i),'uv':uv[0].tolist(),'sigma':.5})
        out,r=triangulate_track({'observations':obs},C,K);np.testing.assert_allclose(out,X,atol=1e-7);self.assertGreater(r['maxAngleDegrees'],5)
    def test_patch_refinement_known_subpixel_translation(self):
        rng=np.random.default_rng(7);g=(rng.random((240,240))*255).astype(np.uint8);g=cv2.GaussianBlur(g,(5,5),1)
        images={};masks={};names=[]
        for i in range(4):
            n=str(i);names.append(n);im=cv2.warpAffine(g,np.float32([[1,0,i*.65],[0,1,i*.3]]),(240,240));images[n]=cv2.cvtColor(im,cv2.COLOR_GRAY2RGB);masks[n]=np.ones((240,240),bool)
        tracks,r=measured_tracks(images,masks,names,max_corners=50)
        full=[t for t in tracks if len(t['observations'])==4];self.assertGreater(len(full),15)
        residual=[np.array(t['observations'][-1]['uv'])-t['observations'][0]['uv']-[1.95,.9] for t in full];self.assertLess(np.median(np.linalg.norm(residual,axis=1)),.12)
    def test_export_preserves_rgb_and_explicit_image_identity(self):
        with tempfile.TemporaryDirectory() as td:
            rgb=np.full((24,32,3),[35,80,110],np.uint8);mask=np.zeros((24,32),bool);mask[4:20,4:28]=True;K=np.array([[20.,0,16],[0,20,12],[0,0,1]])
            data=export_colmap(Path(td)/'scene',{'arbitrary_160.png':rgb},{'arbitrary_160.png':mask},['arbitrary_160.png'],{'arbitrary_160.png':np.eye(4)},K,[])
            back=cv2.cvtColor(cv2.imread(str(Path(td)/'scene/images/arbitrary_160.png')),cv2.COLOR_BGR2RGB);np.testing.assert_array_equal(back,rgb);self.assertEqual(data['imageIDs']['arbitrary_160.png'],1)
    def test_mvs_views_and_weights_are_not_dropped(self):
        header=b'ply\nformat binary_little_endian 1.0\nelement vertex 1\n'+b''.join(b'property float32 '+v+b'\n' for v in [b'x',b'y',b'z'])+b''.join(b'property uint8 '+v+b'\n' for v in [b'red',b'green',b'blue'])+b''.join(b'property float32 '+v+b'\n' for v in [b'nx',b'ny',b'nz'])+b'property list uint8 uint32 view_indices\nproperty list uint8 float32 view_weights\nend_header\n'
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'test.ply';p.write_bytes(header+struct.pack('<fffBBBfffBIIIBfff',1,2,3,4,5,6,0,0,1,3,0,2,4,3,.2,.4,.8));cloud=read_mvs_cloud(p);self.assertEqual(cloud['views'],[[0,2,4]]);self.assertEqual(len(cloud['weights'][0]),3)
            p.write_bytes(p.read_bytes()[:-2])
            with self.assertRaises(struct.error):read_mvs_cloud(p)

class RetirementTests(unittest.TestCase):
    def test_family_members_without_explicit_evidence_remain(self):
        from reconstruction_mvs_contract import explicit_retirement_mask
        mask=explicit_retirement_mask([10,11,12],[99,99,99],[0,0,0],99,[11])
        np.testing.assert_array_equal(mask,[False,True,False])
    def test_unknown_or_wrong_namespace_cannot_be_retired(self):
        from reconstruction_mvs_contract import explicit_retirement_mask
        with self.assertRaises(ValueError):explicit_retirement_mask([10],[99],[1],99,[10])
        with self.assertRaises(ValueError):explicit_retirement_mask([10],[99],[0],99,[12])
        with self.assertRaises(ValueError):explicit_retirement_mask([10],[99],[0],99,[10,10])

if __name__=='__main__':unittest.main()

