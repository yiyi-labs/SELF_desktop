import unittest,copy,numpy as np
from reconstruction_complete_contract import local_to_world,plan_patch,observed_completeness
from run_complete_observations import letterbox,map_pixels,regional_masks
class CompleteContractTests(unittest.TestCase):
    def test_scale_and_pose_relation(self):
        C=np.eye(4);C[:3,3]=[1,2,3];Q=np.eye(4);Q[:3,3]=[.2,.3,.4];B=local_to_world(C,Q,world_units_per_local_unit=10);Q[:3,3]*=10;np.testing.assert_allclose(C@B,Q)
        C[0,0]=2
        with self.assertRaises(ValueError):local_to_world(C,Q)
    def fixtures(self):
        base={'role':'component_candidate','sourceHash':'capture','canonicalFrame':'body','unitScale':1.,'checkpointHash':'base','pointUIDs':[1,2,3]};p={**base,'pointUIDs':[4,5],'scope':'patch','worldFromCanonical':{'t':np.eye(4).tolist()},'transformEvidence':{'t':True},'replacementEvidence':{'coveragePassed':True,'geometryPassed':True}};return base,p
    def test_patch_preserves_unselected_UIDs(self):
        b,p=self.fixtures();r=plan_patch(b,p,reference='t',retire_uids=[2]);self.assertEqual(r['retainedUIDs'],[1,3]);self.assertEqual(r['addedUIDs'],[4,5])
        with self.assertRaises(ValueError):plan_patch(b,p,reference='t',retire_uids=[1,2,3])
    def test_invalid_cross_time_and_failed_coverage_block(self):
        b,p=self.fixtures()
        with self.assertRaises(ValueError):plan_patch(b,p,reference='other',retire_uids=[2])
        p['replacementEvidence']['coveragePassed']=False
        with self.assertRaises(ValueError):plan_patch(b,p,reference='t',retire_uids=[2])
        p['canonicalFrame']='unrelated'
        with self.assertRaises(ValueError):plan_patch(b,p,reference='t',retire_uids=[])
    def test_bad_canonical_matrix_cannot_be_labelled_trusted(self):
        b,p=self.fixtures();p['worldFromCanonical']['t'][0][0]=2
        with self.assertRaises(ValueError):plan_patch(b,p,reference='t',retire_uids=[])
    def test_native_mvs_pixel_contract_is_explicit_and_nonmutating(self):
        import tempfile
        from pathlib import Path
        from reconstruction_complete_contract import export_native_mvs_window
        k=np.array([[100.,0,50],[0,100,40],[0,0,1]]);obs=[{'xyz':[0,0,2],'color':[128,128,128],'error':0,'observations':[{'name':'a.png','uv':[50,40]}]}]
        with tempfile.TemporaryDirectory() as root:
            r=export_native_mvs_window(Path(root)/'test',{'a.png':np.zeros((80,100,3),np.uint8)},{'a.png':np.ones((80,100),bool)},['a.png'],{'a.png':np.eye(4)},k,obs,input_pixel_center='opencv_integer')
            np.testing.assert_allclose(np.asarray(r['K'])[:2,2]-.5,k[:2,2]);self.assertEqual(obs[0]['observations'][0]['uv'],[50,40]);self.assertEqual(k[0,2],50)
            with self.assertRaises(ValueError):export_native_mvs_window(None,None,None,None,None,k,obs,input_pixel_center='COLMAP_half')
    def test_missing_visible_content_stays_in_denominator(self):
        r=observed_completeness(np.ones((2,3),bool),np.zeros((2,3),bool),np.array([[1,0,0],[0,0,0]]));self.assertEqual(r['visibleTarget'],6);self.assertEqual(r['unexplainedVisible'],5)
    def test_letterbox_pixel_centres_roundtrip(self):
        a=np.zeros((1920,1080,3),np.uint8);_,m=letterbox(a);p=np.array([[0,0],[539.2,959.6],[1079,1919]]);np.testing.assert_allclose(map_pixels(map_pixels(p,m),m,True),p,atol=1e-10);self.assertEqual(m['sx'],m['sy'])
    def test_full_clothing_spatial_partition_conserved(self):
        labels={k:np.zeros((50,40),bool) for k in ['face_core','glasses_visible','hair_visible','neck_cloth_visible']};labels['neck_cloth_visible'][12:48,2:37]=True;m=regional_masks(labels);parts=[v for k,v in m.items() if k.startswith(('upper_','lower_'))];np.testing.assert_array_equal(np.sum(parts,axis=0),labels['neck_cloth_visible'].astype(int))
if __name__=='__main__':unittest.main()
