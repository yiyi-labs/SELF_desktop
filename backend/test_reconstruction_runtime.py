"""Routing cannot substitute a different person's cached reconstruction."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import reconstruction_worker as worker
from reconstruction_runtime import (engine_profile,verified_preparation,PORTRAIT_TEST,
                                    worker_identity_status,training_execution_receipt,
                                    training_profile_options,reconstruct_test,
                                    release_preparation_cuda_cache,retain_local_fit_state,
                                    observed_face_execution_receipt)
from reconstruction_live_prepare import selected_names


class RuntimeTest(unittest.TestCase):
    def test_preparation_cache_release_keeps_live_tensors_and_separates_parent_peak(self):
        with patch('torch.cuda.is_initialized',return_value=True), \
             patch('torch.cuda.max_memory_allocated',return_value=10*2**20), \
             patch('torch.cuda.max_memory_reserved',return_value=20*2**20), \
             patch('torch.cuda.memory_allocated',side_effect=[3*2**20,3*2**20]), \
             patch('torch.cuda.memory_reserved',side_effect=[20*2**20,4*2**20]), \
             patch('torch.cuda.empty_cache') as release,patch('gc.collect') as collect:
            r=release_preparation_cuda_cache()
        self.assertEqual(r['allocatedAfterReleaseMiB'],3);self.assertEqual(r['reservedAfterReleaseMiB'],4)
        self.assertEqual(r['allocatedPeakMiB'],10);release.assert_called_once_with();collect.assert_called_once_with()

    def test_local_fit_original_bytes_and_manifest_survive_pixel_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);prepared=root/'prepared';prepared.mkdir();state=root/'state';state.mkdir()
            for name in ('local-fit-init.pt','local-fit-mid.pt','local-fit-state.pt','local_geometry.npz'):
                (prepared/name).write_bytes(name.encode())
            manifest=b'{"source":"/old/private/temporary"}'
            (prepared/'preparation.json').write_bytes(manifest)
            r=retain_local_fit_state(prepared,state)
            self.assertEqual((state/'local-fit/preparation.json').read_bytes(),manifest)
            self.assertEqual(len(r['sha256']),5);self.assertFalse(r['originalPixelsRetained'])
            self.assertTrue(r['originalManifestPreserved'])

    def test_unknown_or_unauthorized_profile_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/"engine-profile.json"
            self.assertEqual(engine_profile(root)["engine"],"gsplat-colmap")
            for value in ({"engine":"unknown"},{"engine":PORTRAIT_TEST}):
                profile.write_text(json.dumps(value))
                with self.assertRaises(ValueError):engine_profile(root)

    def test_cache_requires_exact_capture_and_private_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cache=root/".sources/cache";cache.mkdir(parents=True)
            (cache/"preparation.json").write_text(json.dumps({"sourceHash":"a"}))
            profile={"preparedCache":".sources/cache"}
            self.assertIsNone(verified_preparation(profile,"b",root))
            self.assertEqual(verified_preparation(profile,"a",root),cache)
            with self.assertRaises(ValueError):verified_preparation({"preparedCache":"../elsewhere"},"a",root)

    def test_test_engine_dispatches_and_preserves_quality_and_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);job=root/("a"*32);job.mkdir()
            (root/"engine-profile.json").write_text(json.dumps({"engine":PORTRAIT_TEST,"userTestingAuthorized":True}))
            (job/"job.json").write_text(json.dumps({"state":"queued","sha256":"a"}))
            (job/"capture.mp4").write_bytes(b"private capture")
            (job/"portrait.gaussian.ply").write_bytes(b"test result")
            (job/"portrait.view.json").write_text("{}")
            assets={"gaussian":{"file":"portrait.gaussian.ply"},"view":{"file":"portrait.view.json"}}
            with patch.object(worker,"ROOT",root),patch.object(worker,"verify_capture"), \
                 patch("reconstruction_runtime.reconstruct_test",return_value=(assets,{"releaseApproved":False})), \
                 patch.object(worker,"portrait_preview",side_effect=ValueError), \
                 patch.object(worker,"extract_frames") as legacy:
                worker.run_one(job)
            result=json.loads((job/"job.json").read_text())
            self.assertEqual(result["algorithm"],PORTRAIT_TEST)
            self.assertEqual(result["state"],"gaussian_ready")
            self.assertFalse(result["reconstructionQuality"]["releaseApproved"])
            self.assertFalse((job/"capture.mp4").exists())
            legacy.assert_not_called()

    def test_selection_uses_names_not_colmap_ids_and_no_duplicates(self):
        names=[f"frame_{i:04d}.png" for i in range(1,161)]
        result=selected_names(names)
        self.assertEqual(len(result),32);self.assertEqual(len(set(result)),32)
        self.assertEqual(result[0],names[0]);self.assertEqual(result[-1],names[-1])

    def test_worker_rejects_changed_closure_even_if_profile_is_reblessed(self):
        with patch("reconstruction_code_identity.source_identity",
                   return_value={"implementationSha256":"new"}), \
             patch("reconstruction_runtime.engine_profile") as profile:
            status=worker_identity_status(Path("unused"),{"implementationSha256":"loaded"})
        self.assertFalse(status["sourceIdentityVerified"])
        self.assertEqual(status["reason"],"worker_source_changed_restart_required")
        self.assertEqual(status["loadedImplementationSha256"],"loaded")
        self.assertEqual(status["currentImplementationSha256"],"new")
        profile.assert_not_called()

    def test_stale_profile_is_not_ready_with_current_worker(self):
        with patch("reconstruction_code_identity.source_identity",
                   return_value={"implementationSha256":"same"}), \
             patch("reconstruction_runtime.engine_profile",
                   side_effect=ValueError("test_source_hash_changed:dependency_closure")):
            status=worker_identity_status(Path("unused"),{"implementationSha256":"same"})
        self.assertFalse(status["sourceIdentityVerified"])
        self.assertEqual(status["reason"],"test_source_hash_changed:dependency_closure")

    def test_heartbeat_invalidates_cached_ready_without_loading_gpu(self):
        with patch("reconstruction_runtime.worker_identity_status",return_value={
                "sourceIdentityVerified":False,"reason":"worker_source_changed_restart_required"}):
            status=worker.refresh_worker_capability({"ready":True,"engine":PORTRAIT_TEST})
            preflight=worker.preflight()
        self.assertFalse(status["ready"])
        self.assertFalse(preflight["ready"])
        self.assertEqual(status["reason"],"worker_source_changed_restart_required")

    def test_heartbeat_preserves_gpu_failure_after_identity_passes(self):
        identity={"sourceIdentityVerified":True,"engine":PORTRAIT_TEST,
                  "algorithmVersion":"v","executionAdapter":"a"}
        with patch("reconstruction_runtime.worker_identity_status",return_value=identity):
            status=worker.refresh_worker_capability({**identity,"ready":False,"reason":"CUDA unavailable"})
        self.assertFalse(status["ready"])
        self.assertEqual(status["reason"],"CUDA unavailable")

    def test_receipt_records_actual_steps_and_missing_counts_without_guessing(self):
        report={"pointCount":10,"trainings":[{"stage":"local","steps":7,"seconds":.2}],
                "jointSteps":0,"surfaceRefine":False,"resumeKind":"new_optimizer"}
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            receipt=training_execution_receipt(out,report)
            self.assertEqual(receipt["initialization"]["status"],"unrecorded")
            self.assertIsNone(receipt["finalPartCounts"])
            (out/"portrait-import.json").write_text(json.dumps({"pointCount":6,"surfaceCount":4,
                "hairCount":2,"environmentCount":4,"bodyMotion":"reference"}))
            import numpy as np
            np.savez(out/"portrait.components.npz",component=np.asarray([0,0,4,4,1,1,1,1,2,2]))
            import torch
            torch.save({"model":{"environment_parts":torch.tensor([0,0,4,4]),
                                  "portrait.role":torch.tensor([0,0,1,1,2,2])}},out/"local-init.pt")
            receipt=training_execution_receipt(out,report)
        self.assertEqual(receipt["initialization"]["head"],6)
        self.assertEqual(receipt["initialization"]["environmentPartCounts"],{"0":2,"4":2})
        self.assertEqual(receipt["initialization"]["portraitRoleCounts"],{"0":2,"1":2,"2":2})
        self.assertEqual(receipt["finalPartCounts"],{"0":2,"1":4,"2":2,"4":2})
        self.assertEqual(receipt["stages"],[{"name":"local","completedSteps":7,"seconds":.2,"densityEvents":[]}])

    def test_hair_budget_and_dense_dependency(self):
        self.assertEqual(training_profile_options({})['hairCompositeSteps'],0)
        for value in (-1,241,True,2.5,'180'):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'hair_composite_budget'):
                training_profile_options({'denseSurfaces':True,'hairCompositeSteps':value})
        with self.assertRaisesRegex(ValueError,'hair_composite_requires_dense'):
            training_profile_options({'hairCompositeSteps':180})
        with self.assertRaisesRegex(ValueError,'shared_room_requires_dense'):
            training_profile_options({'sharedRoomSurface':True})
        self.assertEqual(training_profile_options({'denseSurfaces':True,'hairCompositeSteps':240})['hairCompositeSteps'],240)

    def test_observed_face_option_is_explicit_and_native_adapter_only(self):
        self.assertFalse(training_profile_options({})['observedFaceDomain'])
        for value in (1,0,'true','false',None):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'requires_boolean'):
                training_profile_options({'observedFaceDomain':value})
        with self.assertRaisesRegex(ValueError,'requires_native_adapter'):
            training_profile_options({'observedFaceDomain':True})
        # Observation masks do not require DA3; the full live profile separately
        # chooses dense surfaces. Do not introduce an artificial dependency.
        r=training_profile_options({'executionAdapter':'native-fullframe','observedFaceDomain':True})
        self.assertTrue(r['observedFaceDomain']);self.assertFalse(r['denseSurfaces'])

    def test_new_stage_arguments_and_progress_are_bounded(self):
        class StopAfterCommand(Exception):pass
        updates=[];called=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def update(*args,**kwargs):updates.append((args,kwargs))
            def command(argv,*args,**kwargs):
                called.extend(argv)
                for step in (0,90,180,181,-1,True):kwargs['progress']({'stage':'hair-composite','step':step})
                raise StopAfterCommand
            with patch('reconstruction_runtime.verified_preparation',return_value=root/'prepared'), \
                 patch('reconstruction_runtime.pipeline_entry',return_value=(root/'pipeline.py',0)):
                with self.assertRaises(StopAfterCommand):
                    reconstruct_test(root,{'sha256':'capture'},
                        {'executionAdapter':'native-fullframe','denseSurfaces':True,'sharedRoomSurface':True,
                         'hairCompositeSteps':180,'observedFaceDomain':True},
                        update,None,None,command,None)
        self.assertIn('--dense-surfaces',called);self.assertIn('--shared-room-surface',called)
        self.assertEqual(called[called.index('--hair-steps')+1],'180')
        self.assertIn('--observed-face-domain',called)
        self.assertNotIn('--face-composite',called);self.assertNotIn('--opaque',called)
        progress=[a[2] for a,k in updates if k.get('stage',{}).get('name')=='hair-composite']
        self.assertEqual(progress,[90,91,92])

    def test_default_route_does_not_enable_observed_face_or_context_trials(self):
        class StopAfterCommand(Exception):pass
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);called=[]
            def command(argv,*args,**kwargs):called.extend(argv);raise StopAfterCommand
            with patch('reconstruction_runtime.verified_preparation',return_value=root/'prepared'), \
                 patch('reconstruction_runtime.pipeline_entry',return_value=(root/'pipeline.py',0)):
                with self.assertRaises(StopAfterCommand):
                    reconstruct_test(root,{'sha256':'capture'},{},lambda *a,**k:None,None,None,command,None)
        self.assertNotIn('--observed-face-domain',called)
        self.assertFalse(any('opaque' in str(x) or 'face-composite' in str(x) for x in called))

    def test_observed_face_receipt_binds_masks_and_actual_prior_bytes(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);prior=out/'observed-face-initial-appearance.npz';prior.write_bytes(b'changed face prior')
            ph=hashlib.sha256(prior.read_bytes()).hexdigest()
            value={'method':'connected_semantic_observation','maskHashes':{'image.png':'a'*64},
                   'appearanceSha256':ph,'oldAppearanceSha256':'b'*64,'heldoutColoursUsed':False,'surfaceCount':12}
            receipt=out/'observed-face-domain.json';receipt.write_text(json.dumps(value))
            report={'appearanceHash':ph,'observedFaceDomain':value,'pointCount':20,'trainings':[]}
            r=training_execution_receipt(out,report)['observedFaceDomain']
            self.assertTrue(r['applied']);self.assertEqual(r['maskHashes'],value['maskHashes'])
            self.assertEqual(r['appearanceSha256'],ph);self.assertEqual(r['surfaceCount'],12)
            self.assertNotIn('appearancePath',r)
            with self.assertRaisesRegex(ValueError,'training_prior_mismatch'):
                observed_face_execution_receipt(out,{**report,'appearanceHash':'c'*64})
            prior.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'prior_missing_or_changed'):
                observed_face_execution_receipt(out,report)
            receipt.write_text('{}')
            with self.assertRaisesRegex(ValueError,'receipt_missing_or_changed'):
                observed_face_execution_receipt(out,report)
        self.assertEqual(observed_face_execution_receipt('unused',{}),{'applied':False})

    def test_observed_face_request_cannot_silently_skip_application(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def command(argv,*args,**kwargs):
                out=root/'portrait-training';out.mkdir()
                (out/'report.json').write_text(json.dumps({'sourceSha256':'capture',
                    'engineVersion':'portrait-native-fullframe-20261002-research','observedFaceDomain':None}))
            with patch('reconstruction_runtime.verified_preparation',return_value=root/'prepared'), \
                 patch('reconstruction_runtime.pipeline_entry',return_value=(root/'pipeline.py',0)):
                with self.assertRaisesRegex(ValueError,'requested_actual_mismatch'):
                    reconstruct_test(root,{'sha256':'capture'},
                        {'executionAdapter':'native-fullframe','observedFaceDomain':True},
                        lambda *a,**k:None,None,None,command,None)
            self.assertFalse((root/'portrait.gaussian.ply').exists())

    def test_hair_receipt_separates_request_from_actual_skipped_stage(self):
        report={'pointCount':12,'hairCompositeSteps':180,
                'denseSurfaces':{'components':{'room':{'typedSupport':True}}},
                'trainings':[{'stage':'hair-composite','steps':0,'status':'insufficient_frozen_background_support',
                              'qualifiedViews':['a','b'],'modelChanged':False,'geometryChanged':False}]}
        with tempfile.TemporaryDirectory() as tmp:r=training_execution_receipt(tmp,report)
        self.assertEqual(r['hairCompositeRequestedSteps'],180);self.assertEqual(r['hairCompositeCompletedSteps'],0)
        self.assertEqual(r['stages'][0]['qualifiedViewCount'],2);self.assertFalse(r['stages'][0]['modelChanged'])
        self.assertEqual(r['stages'][0]['status'],'insufficient_frozen_background_support')
        self.assertTrue(r['sharedRoomSurfaceApplied'])

    def test_dense_tool_check_does_not_call_discovery_when_disabled(self):
        with patch('reconstruction_live_dense.fixed_tool') as fixed:
            self.assertFalse(worker.dense_tool_preflight({})['denseToolVerified'])
            fixed.assert_not_called()

    def test_dense_tool_preflight_uses_existing_pinned_validation(self):
        with patch('reconstruction_live_dense.fixed_tool',return_value=(Path('tool'),Path('source'),
                   {'codeCommit':'code','modelCommit':'model'})) as fixed:
            r=worker.dense_tool_preflight({'denseSurfaces':True})
            self.assertTrue(r['denseToolVerified']);self.assertEqual(r['denseToolCodeCommit'],'code');fixed.assert_called_once_with()

    def test_missing_dense_tool_fails_before_gpu_preflight(self):
        with patch('reconstruction_runtime.worker_identity_status',return_value={'sourceIdentityVerified':True}), \
             patch('reconstruction_runtime.engine_profile',return_value={'engine':PORTRAIT_TEST,'denseSurfaces':True}), \
             patch('reconstruction_live_dense.fixed_tool',side_effect=ValueError('pinned_DA3_BASE_tool_missing')), \
             patch('torch.cuda.is_available') as gpu:
            r=worker.preflight()
        self.assertFalse(r['ready']);self.assertIn('pinned_DA3_BASE_tool_missing',r['reason']);gpu.assert_not_called()

    def test_changed_execution_options_require_fresh_preflight(self):
        identity={'sourceIdentityVerified':True,'engine':PORTRAIT_TEST,'algorithmVersion':'v',
                  'executionAdapter':'a','executionProfileSha256':'new'}
        with patch('reconstruction_runtime.worker_identity_status',return_value=identity):
            r=worker.refresh_worker_capability({**identity,'executionProfileSha256':'old','ready':True})
        self.assertFalse(r['ready']);self.assertEqual(r['reason'],'worker_profile_changed_preflight_required')


if __name__=="__main__":unittest.main()
