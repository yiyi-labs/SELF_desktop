import unittest
import inspect
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import live_shared_room_surface as shared
from live_shared_room_surface import basis_weights,shared_points,point_fold
from live_dense_contract import project,unproject,digest,write_json


class SharedRoomSurfaceContract(unittest.TestCase):
    def fixture(self):
        return np.array([[40.,0,30],[0,40.,40],[0,0,1.]]),np.eye(4),np.array([[20.,25],[41.4,50.2]])

    def test_partition_and_zero_state_preserve_original_world_points(self):
        K,C,uv=self.fixture();depth=np.array([2.,3.]);ids,w=basis_weights(uv,61,81,6,8)
        np.testing.assert_allclose(w.sum(1),1)
        actual=shared_points(np.zeros(48),uv,depth,K,C,(6,8),(61,81))
        np.testing.assert_allclose(actual,unproject(uv,depth,K,C),atol=1e-12)

    def test_one_surface_has_coherent_multiview_parallax(self):
        K,C,uv=self.fixture();depth=np.array([2.,3.]);X=shared_points(np.full(48,.1),uv,depth,K,C,(6,8),(61,81))
        target=C.copy();target[0,3]=.3
        front,z=project(X,K,C);side,sidez=project(X,K,target)
        np.testing.assert_allclose(front,uv,atol=1e-12)
        np.testing.assert_allclose(side[:,0]-front[:,0],K[0,0]*.3/z,atol=1e-12)
        np.testing.assert_allclose(z,sidez)

    def test_field_is_continuous_across_cell_boundary(self):
        values=np.arange(48,dtype=float)*.001
        ids,w=basis_weights(np.array([[12.-1e-7,33],[12.+1e-7,33]]),61,81,6,8)
        delta=(values[ids]*w).sum(1)
        self.assertLess(abs(delta[0]-delta[1]),1e-8)

    def test_repeat_observations_cannot_change_physical_point_fold(self):
        names=['front','side','later']
        self.assertEqual(len({point_fold(10671) for n in names}),1)
        self.assertGreater(len({point_fold(i) for i in range(100)}),1)

    def test_one_image_is_one_vote_and_conflicting_source_is_ambiguous(self):
        rows=[dict(imageName='a',uv=[1.,2.]),dict(imageName='a',uv=[1.,2.]),
              dict(imageName='b',uv=[3.,4.]),dict(imageName='c',uv=[5.,6.]),dict(imageName='c',uv=[5.8,6.])]
        kept,audit=shared.distinct_image_observations(rows)
        self.assertEqual([r['imageName'] for r in kept],['a','b'])
        self.assertEqual(audit['duplicateSamePixelObservations'],1)
        self.assertEqual(audit['ambiguousImageNames'],['c'])
        self.assertEqual(len(kept),2) # Never a three-view track from five list entries.

    def test_budget_never_reselects_original_outside_surface(self):
        fresh=dict(means=np.c_[np.arange(10),np.zeros((10,2))],scales=np.ones((10,3))*.1,
            layer=np.full(10,'room'),uid=np.arange(10),confidence=np.ones(10),support=np.ones(10)*3)
        selected=shared.replacement_budget_indices(7,fresh,10)
        np.testing.assert_array_equal(selected[:7],np.arange(7))
        self.assertEqual(len(selected),10);self.assertTrue(np.all(selected[7:]>=7))
        np.testing.assert_array_equal(shared.replacement_budget_indices(7,fresh,7),np.arange(7))
        with self.assertRaisesRegex(ValueError,'cannot_preserve_original_content'):
            shared.replacement_budget_indices(7,fresh,6)


class SharedRoomLiveStage(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);prepared=self.root/'prepared';prepared.mkdir()
        (prepared/'preparation.json').write_text('{}');(prepared/'local_geometry.npz').write_bytes(b'geometry')
        depth=self.root/'depth';depth.mkdir();write_json(depth/'depth-manifest.json',{'sourceHash':'source'})
        write_json(depth/'request.json',dict(prepared=str(prepared),sourceHash='source'))
        self.parent=self.root/'bundle.json';asset=self.root/'room.npz';asset.write_bytes(b'original-room')
        self.bundle=dict(sourceSha256='source',preparedSha256=digest(prepared/'preparation.json'),
            localGeometrySha256=digest(prepared/'local_geometry.npz'),
            depthManifestPath=str(depth/'depth-manifest.json'),depthManifestHash=digest(depth/'depth-manifest.json'),
            components={'room':dict(path='room.npz',sha256=digest(asset),count=30)},
            manifestPath=str(self.parent))
        write_json(self.parent,self.bundle);self.original=digest(self.parent)
        self.output=self.root/'new-stage'

    def test_opt_in_is_disabled_by_default(self):
        from live_dense import augment_prepared
        self.assertIs(inspect.signature(augment_prepared).parameters['shared_room_surface'].default,False)

    def test_explicit_missing_evidence_preserves_original_asset(self):
        with patch.object(shared,'run_shared_surface',side_effect=shared.SharedRoomEvidenceUnavailable('not_enough_tracks')):
            result=shared.apply_shared_room_correction(self.parent,self.output)
        self.assertEqual(result['components']['room']['sha256'],self.bundle['components']['room']['sha256'])
        self.assertEqual(Path(result['components']['room']['path']),self.root/'room.npz')
        self.assertEqual(Path(result['manifestPath']),self.output/'result.json')
        receipt=json.loads((self.output/'not-applied-receipt.json').read_text())
        self.assertFalse(receipt['qualified']);self.assertFalse(receipt['solvePerformed'])
        self.assertFalse(receipt['assetsChanged']);self.assertEqual(digest(self.parent),self.original)

    def test_validation_failure_is_recorded_without_export(self):
        def failed(prepared,depth,output,**kwargs):
            output.mkdir();report={'accepted':False};write_json(output/'report.json',report);return report
        with patch.object(shared,'run_shared_surface',side_effect=failed),patch.object(shared,'export_shared_room_initialization') as exporter:
            result=shared.apply_shared_room_correction(self.parent,self.output,reference_fallback=False)
        exporter.assert_not_called()
        self.assertEqual(result['sharedRoomCorrection']['reason'],'shared_surface_validation_not_qualified')
        receipt=json.loads((self.output/'not-applied-receipt.json').read_text())
        self.assertTrue(receipt['solvePerformed']);self.assertEqual(receipt['solverReportSha256'],digest(self.output/'solve/report.json'))

    def test_programming_error_propagates_without_success_bundle(self):
        with patch.object(shared,'run_shared_surface',side_effect=RuntimeError('programming defect')):
            with self.assertRaisesRegex(RuntimeError,'programming defect'):
                shared.apply_shared_room_correction(self.parent,self.output)
        self.assertFalse((self.output/'result.json').exists())
        self.assertFalse((self.output/'not-applied-receipt.json').exists())

    def test_geometric_fit_without_supported_candidate_preserves_parent_explicitly(self):
        def solve(prepared,depth,output,**kwargs):
            output.mkdir();report={'accepted':True};write_json(output/'report.json',report);return report
        with patch.object(shared,'run_shared_surface',side_effect=solve),patch.object(shared,'export_shared_room_initialization',
                side_effect=shared.SharedRoomEvidenceUnavailable('shared_surface_no_supported_room_candidates')):
            result=shared.apply_shared_room_correction(self.parent,self.output)
        self.assertEqual(result['sharedRoomCorrection']['status'],'not_applied')
        self.assertEqual(result['sharedRoomCorrection']['reason'],'shared_surface_no_supported_room_candidates')
        self.assertEqual(result['components']['room']['sha256'],self.bundle['components']['room']['sha256'])

    def test_changed_input_is_contract_error_not_evidence_fallback(self):
        Path(self.bundle['depthManifestPath']).write_text('{"changed":true}')
        with patch.object(shared,'run_shared_surface') as solver:
            with self.assertRaisesRegex(ValueError,'depth_manifest_changed'):
                shared.apply_shared_room_correction(self.parent,self.output)
        solver.assert_not_called();self.assertFalse((self.output/'result.json').exists())

    def test_success_names_terminal_manifest_and_preserves_source_dependencies(self):
        def solve(prepared,depth,output,**kwargs):
            output.mkdir();report={'accepted':True};write_json(output/'report.json',report);return report
        def export(solved,parent,output,budget):
            output.mkdir();self.assertEqual(budget,30)
            result={**self.bundle,'manifestPath':str(output/'result.json')}
            write_json(output/'result.json',result);return result
        with patch.object(shared,'run_shared_surface',side_effect=solve),patch.object(shared,'export_shared_room_initialization',side_effect=export):
            result=shared.apply_shared_room_correction(self.parent,self.output)
        self.assertEqual(Path(result['manifestPath']),self.output/'initialization/result.json')
        self.assertEqual(json.loads(Path(result['manifestPath']).read_text()),result)
        self.assertFalse(result['sharedRoomCorrection']['visualQualityPassed'])
        self.assertEqual(result['sourceSha256'],'source')
        self.assertEqual(result['preparedSha256'],self.bundle['preparedSha256'])
        self.assertEqual(digest(self.parent),self.original)

    def test_requested_completion_uses_terminal_bundle_and_returns_final_manifest(self):
        def solve(prepared,depth,output,**kwargs):
            output.mkdir();report={'accepted':True};write_json(output/'report.json',report);return report
        def export(solved,parent,output,budget):
            output.mkdir();return {**self.bundle,'manifestPath':str(output/'result.json')}
        completed={'manifestPath':'distinct-completion-result.json'}
        with patch.object(shared,'run_shared_surface',side_effect=solve),patch.object(shared,'export_shared_room_initialization',side_effect=export),\
                patch('live_room_completion.complete_observed_room',return_value=completed) as completion:
            result=shared.apply_shared_room_correction(self.parent,self.output,complete_observed=True)
        self.assertEqual(result,completed)
        self.assertEqual(Path(completion.call_args.args[0]),self.output/'initialization/result.json')

    def test_replay_reuses_qualified_geometry_without_solver(self):
        old=self.root/'old-solve';old.mkdir();write_json(old/'report.json',{'accepted':True})
        (old/'shared-surface.npz').write_bytes(b'locked-surface')
        receipt=dict(kind='shared-static-track-surface-correction',qualified=True,
            **{k:self.bundle[k] for k in ('sourceSha256','preparedSha256','localGeometrySha256')},
            solverReportPath=str(old/'report.json'),solverReportSha256=digest(old/'report.json'),
            surfacePath=str(old/'shared-surface.npz'),surfaceSha256=digest(old/'shared-surface.npz'))
        receipt_path=self.root/'old-receipt.json';write_json(receipt_path,receipt)
        def export(solved,parent,output,budget):
            output.mkdir();return {**self.bundle,'manifestPath':str(output/'result.json')}
        with patch.object(shared,'run_shared_surface') as solver,patch.object(shared,'export_shared_room_initialization',side_effect=export):
            result=shared.apply_shared_room_correction(self.parent,self.output,replay_receipt=receipt_path)
        solver.assert_not_called()
        self.assertFalse(result['sharedRoomCorrection']['replayedGeometry']['solverInvoked'])
        self.assertEqual(digest(self.output/'solve/shared-surface.npz'),receipt['surfaceSha256'])

    def test_replay_rejects_mismatched_capture(self):
        receipt=dict(kind='shared-static-track-surface-correction',qualified=True,sourceSha256='another-video')
        path=self.root/'wrong-receipt.json';write_json(path,receipt)
        with patch.object(shared,'run_shared_surface') as solver:
            with self.assertRaisesRegex(ValueError,'replay_identity_changed'):
                shared.apply_shared_room_correction(self.parent,self.output,replay_receipt=path)
        solver.assert_not_called()

    def test_independent_room_reference_retains_person_reference_and_primary_failure(self):
        parent=json.loads(self.parent.read_text());parent['reference']='person-reference';write_json(self.parent,parent)
        attempts=[]
        def solve(prepared,depth,output,**kwargs):
            attempts.append(kwargs.get('reference','person-reference'));output.mkdir()
            if 'reference' not in kwargs:
                write_json(output/'input-failure.json',{'reason':'insufficient_independent_tracks'})
                raise shared.SharedRoomEvidenceUnavailable('shared_surface_insufficient_independent_tracks')
            report={'accepted':True,'reference':kwargs['reference']};write_json(output/'report.json',report);return report
        def selection(parent,output,max_candidates):
            self.assertEqual(max_candidates,2);output.mkdir();value={'selected':[{'reference':'room-reference','window':1}]};write_json(output/'report.json',value);return value
        def export(solved,parent_path,output,budget):
            self.assertEqual(solved,self.output/'reference-attempt-1/solve');output.mkdir()
            return {**parent,'manifestPath':str(output/'result.json')}
        with patch.object(shared,'run_shared_surface',side_effect=solve),patch.object(shared,'export_shared_room_initialization',side_effect=export),patch('live_room_reference.inspect_room_references',side_effect=selection):
            result=shared.apply_shared_room_correction(self.parent,self.output)
        self.assertEqual(attempts,['person-reference','room-reference'])
        self.assertEqual(result['reference'],'person-reference')
        self.assertEqual(result['sharedRoomCorrection']['surfaceReference'],'room-reference')
        self.assertTrue((self.output/'solve/input-failure.json').exists())
        receipt=json.loads((self.output/'reference-attempts.json').read_text())
        self.assertEqual(receipt['heldMinimum'],12);self.assertFalse(receipt['thresholdsChanged'])

    def test_alternative_reference_does_not_swallow_programming_error(self):
        parent=json.loads(self.parent.read_text());parent['reference']='person-reference';write_json(self.parent,parent)
        def solve(prepared,depth,output,**kwargs):
            if 'reference' not in kwargs:raise shared.SharedRoomEvidenceUnavailable('shared_surface_insufficient_independent_tracks')
            raise RuntimeError('alternative programming bug')
        def selection(parent,output,max_candidates):
            output.mkdir();value={'selected':[{'reference':'room-reference','window':1}]};write_json(output/'report.json',value);return value
        with patch.object(shared,'run_shared_surface',side_effect=solve),patch('live_room_reference.inspect_room_references',side_effect=selection):
            with self.assertRaisesRegex(RuntimeError,'alternative programming bug'):shared.apply_shared_room_correction(self.parent,self.output)
        self.assertFalse((self.output/'result.json').exists())


if __name__=='__main__':unittest.main()
