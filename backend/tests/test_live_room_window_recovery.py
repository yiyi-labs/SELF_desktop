import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
from live_room_window_recovery import depth_agreement,surface_pair_overlap,recover_static_window_surfaces,make_window_proposal,verify_window_proposal,projected_room_footprints,original_candidate_support
from live_dense_contract import digest,write_json


def surface(depth,translation=0):
    k=np.array([[60.,0,31.5],[0,60.,31.5],[0,0,1.]])
    c=np.eye(4);c[0,3]=translation
    return dict(referenceDepthAfter=np.full((64,64),depth),K=k,W2C=c,nativeToProcessed=np.eye(3))


class RecoveryContract(unittest.TestCase):
    def test_fresh_recovery_entry_continues_to_bounded_second_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data,dense,parent_path=self.fixture(root)
            asset=root/'room.npz';np.savez(asset,means=np.zeros((1,3)))
            proof=root/'proof.json';write_json(proof,{'qualified':True})
            parent=json.loads(parent_path.read_text());parent.update(components={'room':dict(path=str(asset),sha256=digest(asset),count=1,
                surfaceCorrectionReceipt=str(proof),surfaceCorrectionReceiptSha256=digest(proof))},
                depthManifestHash=digest(dense/'depth-manifest.json'),acceptedWindows=[['world',1]])
            write_json(parent_path,parent);write_json(dense/'request.json',{'prepared':str(data['prepared'])})
            initial=dict(reference='a.png',window=0,eligible=True,mapTrackEvidence=True,trackCounts={'fit':20,'validation':12},newAreaCells=200)
            backup={**initial,'reference':'b.png','newAreaCells':100}
            selection={'selected':[initial],'candidates':[initial,backup]}
            output=root/'automatic'
            def second(parent,first,out,**options):
                self.assertEqual(Path(parent),output/'result.json');self.assertEqual(Path(first),output)
                self.assertTrue(options['allow_typed_conditional']);self.assertEqual(options['extra_budget'],30000)
                old=json.loads(Path(parent).read_text());self.assertEqual(old['roomWindowRecovery']['outcomes'][0]['status'],'independent_validation_failed')
                Path(out).mkdir();value={**old,'manifestPath':str(Path(out)/'result.json'),'roomWindowSecondReference':{'status':'original_bundle_retained'}}
                write_json(Path(out)/'result.json',value);return value
            with patch('live_dense.read_prepared',return_value=data), \
                 patch('live_room_completion.select_completion_references',return_value=selection), \
                 patch('live_shared_room_surface.run_shared_surface',return_value={'accepted':False}), \
                 patch('live_room_retry.retry_room_reference',side_effect=second) as retry:
                final=recover_static_window_surfaces(parent_path,output,allow_typed_conditional=True)
                retry.assert_called_once()
            self.assertEqual(Path(final['manifestPath']),output/'second-reference/result.json')
            self.assertNotIn('roomWindowSecondReference',json.loads((output/'result.json').read_text()))

    def test_missing_or_rejected_base_surface_preserves_bundle_without_selection(self):
        for rejected in (False,True):
            with self.subTest(rejected=rejected), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);asset=root/'room.npz';np.savez(asset,means=np.zeros((1,3)))
                depth=root/'depth-manifest.json';write_json(depth,{'sourceHash':'source'})
                row=dict(path=str(asset),sha256=digest(asset),count=1)
                if rejected:
                    proof=root/'rejected-proof.json';write_json(proof,{'qualified':False})
                    row.update(surfaceCorrectionReceipt=str(proof),surfaceCorrectionReceiptSha256=digest(proof))
                parent=root/'result.json';write_json(parent,dict(sourceSha256='source',components={'room':row},
                    depthManifestPath=str(depth),depthManifestHash=digest(depth),acceptedWindows=[['world',1]]))
                before=asset.read_bytes();parent_bytes=parent.read_bytes()
                with patch('live_dense.read_prepared',side_effect=AssertionError('must not read capture')), \
                     patch('live_room_completion.select_completion_references',side_effect=AssertionError('must not select')), \
                     patch('live_shared_room_surface.run_shared_surface',side_effect=AssertionError('must not solve')):
                    result=recover_static_window_surfaces(parent,root/'fallback')
                self.assertEqual(result['roomWindowRecovery']['reason'],'no_qualified_base_surface')
                self.assertEqual(result['components'],{'room':row})
                self.assertEqual(result['roomWindowRecovery']['addedCount'],0)
                self.assertFalse(result['roomWindowRecovery']['solverInvoked'])
                self.assertEqual(asset.read_bytes(),before);self.assertEqual(parent.read_bytes(),parent_bytes)
                self.assertTrue(Path(result['manifestPath']).is_file())

    def test_changed_base_receipt_is_error_not_evidence_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);asset=root/'room.npz';np.savez(asset,means=np.zeros((1,3)))
            depth=root/'depth.json';write_json(depth,{})
            proof=root/'proof.json';write_json(proof,{'qualified':True});before=digest(proof)
            parent=root/'parent.json';write_json(parent,dict(components={'room':dict(path=str(asset),sha256=digest(asset),count=1,
                surfaceCorrectionReceipt=str(proof),surfaceCorrectionReceiptSha256=before)},depthManifestPath=str(depth),depthManifestHash=digest(depth)))
            write_json(proof,{'qualified':False})
            with self.assertRaisesRegex(ValueError,'base_receipt_changed'):
                recover_static_window_surfaces(parent,root/'failed')

    def test_original_conditional_support_is_not_forged_depth_or_relaxed_free(self):
        fresh=dict(support=np.array([3,1,0,1,0]),depth_free=np.array([0,1,2,0,0]),
            static_image_support=np.array([3,3,4,2,4]),colour_support=np.array([3,3,4,4,2]),
            evidence_type=np.array(['depth_consistent_shared_surface','conditional_shared_surface','conditional_shared_surface','conditional_shared_surface','conditional_shared_surface']))
        strict,allowed=original_candidate_support(fresh,True)
        np.testing.assert_array_equal(strict,[True,False,False,False,False])
        np.testing.assert_array_equal(allowed,[True,True,False,False,False])
        np.testing.assert_array_equal(fresh['support'],[3,1,0,1,0])
        _,default=original_candidate_support(fresh)
        np.testing.assert_array_equal(default,strict)
    def fixture(self,root):
        prepared=root/'prepared';prepared.mkdir();(prepared/'rectified_observations').mkdir()
        for name in ('preparation.json','local_geometry.npz'):(prepared/name).write_text(name)
        (prepared/'rectified_observations/a.png').write_bytes(b'source-pixel-contract')
        dense=root/'dense';dense.mkdir();k=np.eye(3);c=np.eye(4)
        np.savez(dense/'a.npz',W2C=c,K=k,nativeToProcessed=k,sourceHash=np.asarray('source'),imageName=np.asarray('a.png'))
        row=dict(imageName='a.png',group='world',window=0,file='a.npz',role='train',sourceHash='source',
            scaleGatePassed=True,depthHash=digest(dense/'a.npz'),imageHash=digest(prepared/'rectified_observations/a.png'))
        write_json(dense/'depth-manifest.json',dict(sourceHash='source',observations=[row]))
        write_json(dense/'result.json',dict(acceptedWindows=[['world',1]],windowComparisons=[dict(group='world',windows=[0,1],accepted=False)]))
        write_json(dense/'request.json',{})
        parent=root/'parent.json';write_json(parent,dict(depthManifestPath=str(dense/'depth-manifest.json'),sourceSha256='source',
            preparedSha256=digest(prepared/'preparation.json'),localGeometrySha256=digest(prepared/'local_geometry.npz')))
        return dict(prepared=prepared,world={'a.png':c},K=k),dense,parent

    def test_proposal_preserves_rejection_and_checks_fixed_camera(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data,dense,parent=self.fixture(root);out=root/'proposal.json'
            original=(dense/'result.json').read_bytes();make_window_proposal(parent,'a.png',0,out)
            with patch('live_dense.training_name_scopes',return_value={'geometryTrain':['a.png']}):
                result=verify_window_proposal(out,data,dense,'a.png',0)
                self.assertTrue(result['permitsSolveOnly']);self.assertEqual((dense/'result.json').read_bytes(),original)
                data['world']['a.png'][0,3]=1
                with self.assertRaises(AssertionError):verify_window_proposal(out,data,dense,'a.png',0)

    def test_source_image_and_train_boundary_cannot_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data,dense,parent=self.fixture(root);out=root/'proposal.json'
            make_window_proposal(parent,'a.png',0,out)
            with patch('live_dense.training_name_scopes',return_value={'geometryTrain':[]}):
                with self.assertRaisesRegex(ValueError,'fixed_train'):verify_window_proposal(out,data,dense,'a.png',0)
            (data['prepared']/'rectified_observations/a.png').write_bytes(b'changed')
            with patch('live_dense.training_name_scopes',return_value={'geometryTrain':['a.png']}):
                with self.assertRaisesRegex(ValueError,'source_image_changed'):verify_window_proposal(out,data,dense,'a.png',0)

    def test_failed_scale_does_not_gain_solver_permission(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data,dense,parent=self.fixture(root)
            manifest=json.loads((dense/'depth-manifest.json').read_text());manifest['observations'][0]['scaleGatePassed']=False
            write_json(dense/'depth-manifest.json',manifest)
            with self.assertRaisesRegex(ValueError,'scale_invalid'):make_window_proposal(parent,'a.png',0,root/'proposal.json')

    def test_overlap_preserves_original_threshold_and_insufficient_is_unknown(self):
        self.assertTrue(depth_agreement(np.full(128,.039))['qualified'])
        self.assertFalse(depth_agreement(np.full(127,.01))['qualified'])
        self.assertFalse(depth_agreement(np.full(128,.041))['qualified'])
        self.assertFalse(depth_agreement(np.r_[np.zeros(100),np.full(28,.11)])['qualified'])

    def test_same_static_plane_with_camera_motion_agrees(self):
        mask=np.ones((64,64),bool)
        result=surface_pair_overlap(surface(2),surface(2,.05),mask,mask)
        self.assertTrue(result['qualified'])

    def test_different_depth_not_silently_filtered_or_called_occluded(self):
        mask=np.ones((64,64),bool)
        result=surface_pair_overlap(surface(2),surface(3),mask,mask)
        self.assertFalse(result['qualified'])
        self.assertEqual(result['directions'][0]['nearerThanOther3pct'],225)

    def test_unknown_or_foreground_not_room_support(self):
        result=surface_pair_overlap(surface(2),surface(2),np.ones((64,64),bool),np.zeros((64,64),bool))
        self.assertFalse(result['qualified'])
        self.assertEqual(result['directions'][0]['count'],0)

    def test_budget_cannot_create_unbounded_trials(self):
        for kwargs in ({'max_surfaces':3},{'max_evaluations':41},{'extra_budget':30001},{'max_surfaces':True}):
            with self.assertRaisesRegex(ValueError,'budget'):recover_static_window_surfaces('missing','not-created',**kwargs)

    def test_native_footprint_contains_off_canvas_kernel_and_does_not_expand_alpha(self):
        values=dict(means=np.array([[-1.1,0,2.]]),scales=np.array([[.2,.1,.01]]),
                    quats=np.array([[1.,0,0,0]]),opacity=np.array([.6]))
        k=np.array([[60.,0,31.5],[0,60.,31.5],[0,0,1.]])
        maps=projected_room_footprints(values,k,np.eye(4),(64,64))
        self.assertEqual(maps['projectedKernels'],1)
        self.assertGreater(maps['peak'][32,0],.1)
        self.assertLessEqual(maps['peak'].max(),.6)
        self.assertEqual(maps['peak'][32,63],0)

    def test_union_alpha_does_not_depend_on_sort_order(self):
        values=dict(means=np.array([[0,0,2.],[0,0,3.]]),scales=np.array([[.1,.1,.01],[.15,.15,.01]]),
                    quats=np.array([[1.,0,0,0],[1.,0,0,0]]),opacity=np.array([.6,.5]))
        k=np.array([[60.,0,31.5],[0,60.,31.5],[0,0,1.]])
        a=projected_room_footprints(values,k,np.eye(4),(64,64))
        b=projected_room_footprints({k:v[::-1] for k,v in values.items()},k,np.eye(4),(64,64))
        np.testing.assert_allclose(a['alpha'],b['alpha'],atol=1e-7)


if __name__=='__main__':unittest.main()
