import unittest
import tempfile
import json
import ast
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import numpy as np

from reconstruction_live_room_self_reference import eligible_self_correction,KIND,apply_self_reference_correction,AUTHORIZED_POLICY
from reconstruction_live_dense_contract import digest
from reconstruction_live_surface_binding import load_component


class SelfReferenceContractTests(unittest.TestCase):
    def test_only_one_obsolete_negative_is_separated(self):
        support=np.array([0,3,3,3,3,3,3]);free=np.array([2,3,1,2,2,2,2]);own=np.array([1,1,1,0,1,1,2])
        im=np.array([3,3,3,3,2,3,3]);co=np.array([3,3,3,3,3,2,3])
        np.testing.assert_array_equal(eligible_self_correction(support,free,own,im,co),[True,False,False,False,False,False,False])
        np.testing.assert_array_equal(support,[0,3,3,3,3,3,3])
        np.testing.assert_array_equal(free,[2,3,1,2,2,2,2])

    def asset(self):
        return dict(source_hash=np.asarray('source'),coordinate_frame=np.asarray('world'),means=np.zeros((1,3)),scales=np.ones((1,3)),
            quats=np.array([[1,0,0,0]]),opacity=np.array([.6]),sh=np.zeros((1,4,3)),support=np.array([1]),uid=np.array([4]),
            evidence_type=np.array([KIND]),static_image_support=np.array([3]),colour_support=np.array([3]),depth_free=np.array([2]),
            self_reference_free=np.array([1]),other_depth_free=np.array([1]))

    def test_no_implicit_acceptance_without_receipt_contract(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'x.npz';np.savez(path,**self.asset())
            with self.assertRaisesRegex(ValueError,'explicit_receipt'):load_component(path,'source','world',conditional_room=True)
            values=load_component(path,'source','world',conditional_room=True,self_reference_room=True)
            self.assertEqual(values['depth_free'][0],2);self.assertEqual(values['support'][0],1)

    def test_independent_free_or_colour_failure_still_fails(self):
        for key,value in [('other_depth_free',0),('depth_free',3),('colour_support',2),('self_reference_free',0)]:
            with self.subTest(key=key),tempfile.TemporaryDirectory() as td:
                a=self.asset();a[key]=np.array([value]);p=Path(td)/'x.npz';np.savez(p,**a)
                with self.assertRaises(ValueError):load_component(p,'source','world',conditional_room=True,self_reference_room=True)


class SelfReferenceAdapterTests(unittest.TestCase):
    def fixture(self,folder,*,qualified=True):
        folder=Path(folder);asset=folder/'room.npz';asset.write_bytes(b'unchanged-original-room')
        surface=folder/'surface.npz';surface.write_bytes(b'surface');report=folder/'report.json';report.write_text('{}')
        depth=folder/'depth.json';depth.write_text('{}');proof=folder/'proof.json'
        p=dict(kind='shared-static-track-surface-correction',qualified=qualified,sourceSha256='s',preparedSha256='p',localGeometrySha256='g',
            solverReportPath=str(report),solverReportSha256=digest(report),surfacePath=str(surface),surfaceSha256=digest(surface))
        proof.write_text(json.dumps(p));m=dict(sourceSha256='s',preparedSha256='p',localGeometrySha256='g',depthManifestPath=str(depth),depthManifestHash=digest(depth),
            components=dict(room=dict(path=str(asset),sha256=digest(asset),count=1,typedSupport=True,surfaceCorrectionReceipt=str(proof),surfaceCorrectionReceiptSha256=digest(proof))))
        path=folder/'result.json';path.write_text(json.dumps(m));return path,m

    def test_disabled_and_attempted_are_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            path,m=self.fixture(td);output=Path(td)/'new'
            with patch('reconstruction_live_room_self_reference.build_self_reference_candidate') as build:
                self.assertEqual(apply_self_reference_correction(path,output)['manifestPath'],str(path))
                m['roomSelfReferenceCorrection']={'status':'original_bundle_retained'};path.write_text(json.dumps(m))
                self.assertEqual(apply_self_reference_correction(path,output,authorized_policy=AUTHORIZED_POLICY)['manifestPath'],str(path))
                build.assert_not_called();self.assertFalse(output.exists())

    def test_absent_base_preserves_components(self):
        with tempfile.TemporaryDirectory() as td:
            path,m=self.fixture(td);m['components']['room'].pop('surfaceCorrectionReceipt');path.write_text(json.dumps(m))
            got=apply_self_reference_correction(path,Path(td)/'new',authorized_policy=AUTHORIZED_POLICY)
            self.assertEqual(got['components'],m['components']);self.assertEqual(got['roomSelfReferenceCorrection']['reason'],'no_qualified_base_surface')

    def test_declared_missing_dependency_and_changed_proof_fail(self):
        with tempfile.TemporaryDirectory() as td:
            path,m=self.fixture(td);(Path(td)/'surface.npz').unlink()
            with self.assertRaisesRegex(ValueError,'qualified_dependency_missing'):
                apply_self_reference_correction(path,Path(td)/'missing',authorized_policy=AUTHORIZED_POLICY)
            (Path(td)/'proof.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'present_dependency_changed'):
                apply_self_reference_correction(path,Path(td)/'bad',authorized_policy=AUTHORIZED_POLICY)
            (Path(td)/'proof.json').unlink()
            with self.assertRaisesRegex(ValueError,'declared_proof_missing'):
                apply_self_reference_correction(path,Path(td)/'gone',authorized_policy=AUTHORIZED_POLICY)

    def test_unqualified_retains_qualified_invokes_exact_parent(self):
        with tempfile.TemporaryDirectory() as td:
            path,m=self.fixture(td,qualified=False)
            got=apply_self_reference_correction(path,Path(td)/'bad',authorized_policy=AUTHORIZED_POLICY)
            self.assertEqual(got['roomSelfReferenceCorrection']['reason'],'no_qualified_surface')
        with tempfile.TemporaryDirectory() as td:
            path,m=self.fixture(td);output=Path(td)/'new'
            actual=Path(td)/'actual-result.json'
            with patch('reconstruction_live_room_self_reference.build_self_reference_candidate',return_value={'manifestPath':str(actual),'roomSelfReferenceCorrection':{}}) as build:
                got=apply_self_reference_correction(path,output,authorized_policy=AUTHORIZED_POLICY,budget=6000)
                self.assertEqual(got['manifestPath'],str(actual));build.assert_called_once_with(path.resolve(),output,budget=6000)
                self.assertTrue(json.loads(actual.read_text())['roomSelfReferenceCorrection']['invokedByLivePolicy'])

    def test_unknown_policy_and_excess_budget_fail(self):
        with tempfile.TemporaryDirectory() as td:
            path,_=self.fixture(td)
            for args in ({'authorized_policy':True},{'authorized_policy':AUTHORIZED_POLICY,'budget':6001}):
                with self.assertRaises(ValueError):apply_self_reference_correction(path,Path(td)/'new',**args)

    def test_pipeline_dispatches_existing_recovery_and_skips_resume(self):
        source=(Path(__file__).resolve().parents[1]/'reconstruction_portrait_pipeline.py').read_text()
        tree=ast.parse(source)
        block=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and
            "room_window_recovery" in ast.unparse(n.test) and 'resume_state is None' in ast.unparse(n.test))
        code=compile(ast.fix_missing_locations(ast.Module(body=[block],type_ignores=[])),'live-dispatch','exec')
        for resumed in (False,True):
            with self.subTest(resumed=resumed),tempfile.TemporaryDirectory() as td:
                p=Path(td)/'result.json';saved={'roomWindowRecovery':{'status':'done'}};p.write_text(json.dumps(saved))
                final={**saved,'manifestPath':str(p),'roomSelfReferenceCorrection':{'status':'conditional_candidates_added'}}
                env=dict(args=SimpleNamespace(room_window_recovery=True,resume_state='state' if resumed else None,output=Path(td)),
                    data={'dense_manifest':p},json=json,Path=Path,digest=digest,write_json=lambda *a:None)
                with patch('reconstruction_live_room_window_recovery.recover_static_window_surfaces') as recover, \
                     patch('reconstruction_live_room_self_reference.apply_self_reference_correction',return_value=final) as apply:
                    exec(code,env);recover.assert_not_called()
                    if resumed:apply.assert_not_called()
                    else:
                        apply.assert_called_once_with(p,Path(td)/'room-self-reference',authorized_policy=AUTHORIZED_POLICY)
                        self.assertEqual(env['recovery_receipt']['selfReferenceCorrection'],final['roomSelfReferenceCorrection'])

if __name__=='__main__':unittest.main()
