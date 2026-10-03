import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

from reconstruction_live_room_completion import (deduplicate_new_surface,reference_occluded_region,
    complete_observed_room,unrepresented_sample_mask)
from reconstruction_live_dense_contract import digest,write_json


class RoomCompletionContract(unittest.TestCase):
    def test_uncovered_observed_room_not_limited_to_person_silhouette(self):
        old=dict(means=np.array([[0.,0.,2.]]),scales=np.array([[.1,.1,.01]]),normal=np.array([[0.,0.,1.]]))
        xyz=np.array([[0.,0.,2.],[3.,0.,2.],[-3.,0.,2.],[np.nan,0.,2.],[8.,0.,2.]])
        basis=np.tile(np.eye(3),(5,1,1));scales=np.tile([.1,.1,.01],(5,1))
        keep=unrepresented_sample_mask(xyz,basis,scales,np.array([1,1,1,1,0],bool),[old])
        np.testing.assert_array_equal(keep,[False,True,True,False,False])
        np.testing.assert_array_equal(old['means'],[[0.,0.,2.]])

    def test_only_compatible_new_samples_are_deduplicated(self):
        old=dict(means=np.array([[0.,0,2.]]),scales=np.array([[.1,.1,.01]]),normal=np.array([[0.,0,1.]]))
        fresh=dict(means=np.array([[0.,0,2.],[.02,0,2.],[0,0,2.2],[0.,0,2.]]),
            scales=np.tile([.1,.1,.01],(4,1)),normal=np.array([[0.,0,1.],[0.,0,1.],[0.,0,1.],[1.,0,0.]]))
        copy=old['means'].copy()
        np.testing.assert_array_equal(deduplicate_new_surface(fresh,[old]),[False,False,True,True])
        np.testing.assert_array_equal(old['means'],copy)

    def test_reference_occlusion_is_not_room_or_foreground(self):
        z=np.zeros((21,21),bool);face=z.copy();face[8:13,8:13]=True
        labels=dict(face_core=face,face_boundary=z,hair_visible=z,glasses_visible=z,
            unknown_or_occluded=z,room_visible=~face,neck_cloth_visible=z)
        prediction=dict(depth=np.ones((21,21)),K=np.array([[10.,0,10],[0,10.,10],[0,0,1]]),
            W2C=np.eye(4),nativeToProcessed=np.eye(3))
        result=reference_occluded_region(np.array([[0.,0,2],[0.,0,.8],[1.,0,2]]),labels,{},'ref',None,{},prediction)
        np.testing.assert_array_equal(result,[True,False,False])

    def test_empty_reference_set_retains_exact_parent_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);asset=root/'room.npz';np.savez(asset,means=np.zeros((3,3)))
            proof=root/'proof.json';write_json(proof,dict(qualified=True,roomAssetHash=digest(asset)))
            depth=root/'depth-manifest.json';write_json(depth,{})
            write_json(root/'request.json',dict(prepared='not_read_when_no_candidates'))
            parent=root/'parent.json';bundle=dict(sourceSha256='capture',reference='main',
                depthManifestPath=str(depth),depthManifestHash=digest(depth),
                components={'room':dict(path=str(asset),sha256=digest(asset),count=3,typedSupport=True,
                    surfaceCorrectionReceipt=str(proof),surfaceCorrectionReceiptSha256=digest(proof))})
            write_json(parent,bundle)
            with patch('reconstruction_live_room_completion.select_completion_references',return_value={'selected':[]}):
                result=complete_observed_room(parent,root/'completion')
            self.assertEqual(result['components'],bundle['components'])
            self.assertEqual(result['roomCompletion']['status'],'original_bundle_retained')
            self.assertEqual(result['roomCompletion']['addedCount'],0)
            self.assertEqual(json.loads(Path(result['manifestPath']).read_text()),result)

    def test_budget_cannot_expand_without_bound(self):
        with self.assertRaisesRegex(ValueError,'budget_contract'):
            complete_observed_room('unused','unused',extra_budget=8001)


if __name__=='__main__':unittest.main()
