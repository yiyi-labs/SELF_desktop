"""CPU contracts for explicit live repair flags and their saved evidence."""
import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import (training_profile_options, reconstruct_test,
                                    repair_execution_receipt)


class RuntimeRepairTest(unittest.TestCase):
    def profile(self, **kw):
        return dict(executionAdapter='native-fullframe', observedFaceDomain=True,
                    denseSurfaces=True, sharedRoomSurface=True, **kw)

    def test_defaults_and_exact_boolean_types(self):
        for key in ('opaquePerson', 'opaqueBody', 'surfaceFootprint', 'roomWindowRecovery'):
            self.assertFalse(training_profile_options({})[key])
            for value in ('true', 'false', None, 0, 1):
                with self.subTest(key=key, value=value), self.assertRaisesRegex(ValueError, 'requires_boolean'):
                    training_profile_options(self.profile(**{key:value}))

    def test_constraints_and_body_research_boundary(self):
        for key in ('opaquePerson', 'surfaceFootprint', 'roomWindowRecovery'):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'requires_native_adapter'):
                training_profile_options({key:True})
        for key, error in (('opaquePerson','opaque_person_requires_observed_face'),
                           ('surfaceFootprint','surface_footprint_requires_observed_face'),
                           ('roomWindowRecovery','room_window_recovery_requires_shared_dense_surfaces')):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, error):
                training_profile_options({'executionAdapter':'native-fullframe',key:True})
        with self.assertRaisesRegex(ValueError, 'opaque_body_is_research_only'):
            training_profile_options(self.profile(opaquePerson=True,opaqueBody=True))
        options=training_profile_options(self.profile(opaquePerson=True,surfaceFootprint=True,roomWindowRecovery=True))
        self.assertTrue(options['opaquePerson']);self.assertFalse(options['opaqueBody'])

    def test_cli_exact_flags_and_defaults(self):
        class Stop(Exception):pass
        for enabled in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory);called=[]
                def command(argv,*a,**kw):called.extend(argv);raise Stop
                profile=self.profile(opaquePerson=enabled,surfaceFootprint=enabled,roomWindowRecovery=enabled)
                with patch('runtime.verified_preparation',return_value=root/'prepared'), \
                     patch('runtime.pipeline_entry',return_value=(root/'entry.py',0)):
                    with self.assertRaises(Stop):
                        reconstruct_test(root,{'sha256':'source'},profile,lambda *a,**k:None,None,None,command,None)
                for flag in ('--opaque-person','--surface-footprint','--room-window-recovery'):
                    self.assertEqual(flag in called,enabled)
                self.assertNotIn('--opaque-body',called)

    def test_wrapper_has_one_of_each_explicit_flag(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'live_fullframe.py').read_text())
        flags=[arg.value for n in ast.walk(tree) if isinstance(n,ast.Call) and
               isinstance(n.func,ast.Attribute) and n.func.attr=='add_argument'
               for arg in n.args if isinstance(arg,ast.Constant) and isinstance(arg.value,str)]
        for flag in ('--opaque-person','--opaque-body','--surface-footprint','--room-window-recovery'):
            self.assertEqual(flags.count(flag),1)

    def test_requested_repair_cannot_silently_skip(self):
        options=training_profile_options(self.profile(opaquePerson=True))
        with self.assertRaisesRegex(ValueError,'requested_actual_mismatch:opaquePerson'):
            repair_execution_receipt('unused',{},options)
        self.assertFalse(repair_execution_receipt('unused',{})['opaquePerson']['applied'])

    @staticmethod
    def write(path,value):
        path.write_text(json.dumps(value));return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_opaque_head_receipt_hash_no_body_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'opaque-interiors.json'
            sha=self.write(file,{'frame.png':{'regions':{'skin':{'opaqueInteriorPixels':4}}}})
            report={'opaquePerson':True,'opaqueBody':False,'opaqueInteriorsReceiptSha256':sha}
            result=repair_execution_receipt(root,report)
            self.assertEqual(result['opaquePerson']['scope'],'head_only')
            self.assertFalse(result['opaquePerson']['qualityPassed'])
            file.write_text('{}')
            with self.assertRaisesRegex(ValueError,'opaque_interiors_receipt_missing_or_changed'):
                repair_execution_receipt(root,report)

    def test_footprint_is_saved_fresh_prior_identity_not_quality_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            value={'sourceSha256':'source','priorStage':'fresh_initialization','changedCount':0,
                   'normalVariancePreserved':True}
            sha=self.write(root/'surface-footprint.json',value)
            (root/'surface-footprint-diagnostics.npz').write_bytes(b'opaque diagnostics fixture')
            report={'surfaceFootprint':value,'sourceSha256':'source',
                    'observedFaceDomain':{'surfaceFootprintSha256':sha}}
            result=repair_execution_receipt(root,report)['surfaceFootprint']
            self.assertEqual(result['changedCount'],0);self.assertFalse(result['qualityPassed'])
            report['observedFaceDomain']['surfaceFootprintSha256']='other'
            with self.assertRaisesRegex(ValueError,'footprint_prior_receipt_mismatch'):
                repair_execution_receipt(root,report)

    def test_room_zero_addition_and_manifest_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);manifest=root/'result.json'
            result={'status':'original_bundle_retained','addedCount':0,'originalPrefixBitwiseUnchanged':True}
            value={'manifestPath':str(manifest),'manifestSha256':self.write(manifest,
                {'sourceSha256':'source','roomWindowRecovery':result}),'result':result}
            self.write(root/'room-window-recovery.json',value)
            report={'sourceSha256':'source','roomWindowRecovery':True,
                    'roomWindowRecoveryReceipt':value,'denseSurfaces':{'roomWindowRecovery':result}}
            receipt=repair_execution_receipt(root,report)['roomWindowRecovery']
            self.assertEqual(receipt['addedCount'],0);self.assertFalse(receipt['qualityPassed'])
            report['denseSurfaces']['roomWindowRecovery']={**result,'addedCount':10}
            with self.assertRaisesRegex(ValueError,'dense_receipt_mismatch'):
                repair_execution_receipt(root,report)
            report['denseSurfaces']['roomWindowRecovery']=result
            manifest.write_text('{}')
            with self.assertRaisesRegex(ValueError,'manifest_changed'):
                repair_execution_receipt(root,report)


if __name__=='__main__':unittest.main()
