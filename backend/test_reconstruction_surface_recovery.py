import json,tempfile,unittest
from pathlib import Path
import numpy as np
from reconstruction_surface_recovery import (digest,retain_surface_initialization,verify_recovery_manifest,
                                              retain_runtime_surface_initialization,resolve_recovery_identity)


class SurfaceRecoveryTest(unittest.TestCase):
    def add_hair_motion(self,manifest):
        meta=json.loads(manifest.read_text());folder=manifest.parent/'hair-inference';folder.mkdir()
        fit=folder/'fit.pt';fit.write_bytes(b'private-fitted-parameters-without-images')
        arrays=folder/'motion.npz';np.savez(arrays,referenceToFrameRootLocal=np.eye(4)[None])
        value=dict(status='reference_relative_joint1_transport',sourceHash='capture',
            checkpointSha256=digest(fit),fitStatePath=str(fit),modelSha256='m'*64,
            referenceName='reference',transformSha256='t'*64,arrayPath=str(arrays),arraySha256=digest(arrays))
        receipt=folder/'motion.json';receipt.write_text(json.dumps(value))
        motion={**value,'path':str(receipt),'sha256':digest(receipt)}
        depth=folder/'depth-manifest.json';depth.write_text(json.dumps(dict(sourceHash='capture',hairMotion=motion)))
        meta['components']['hair'].update(hairMotion=motion,hairDepthManifestPath=str(depth),hairDepthManifestHash=digest(depth))
        manifest.write_text(json.dumps(meta));return receipt,arrays,fit,depth

    def test_hair_motion_retained_with_room_proof_after_inputs_expire(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest,*_=self.proof_fixture(root)
            originals=self.add_hair_motion(manifest);raw={str(p):p.read_bytes() for p in originals}
            hashes={str(p):digest(p) for p in originals};expected=digest(manifest);target=root/'retained'
            result=retain_surface_initialization(manifest,target,expected_manifest_hash=expected,expected_source_hash='capture')
            self.assertIn('room.surface',result['evidenceFiles'])
            for key in ('hair.motion','hair.motionArrays','hair.fitState','hair.depthManifest'):
                self.assertIn(key,result['evidenceFiles'])
            (root/'temporary').rename(root/'expired');(root/'auxiliary').rename(root/'expired-aux');(root/'correction').rename(root/'expired-proof')
            verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)
            for old,content in raw.items():
                resolved=resolve_recovery_identity(target/'recovery-manifest.json',old,expected_manifest_hash=expected,expected_hash=hashes[old])
                self.assertEqual(resolved.read_bytes(),content)
            saved=result['evidenceFiles']['hair.motionArrays'];(target/saved['file']).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'hair_evidence_changed'):
                verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)

    def test_hair_motion_or_fit_tamper_before_retention(self):
        for which in range(4):
            with self.subTest(which=which),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);manifest=self.fixture(root);files=self.add_hair_motion(manifest);expected=digest(manifest)
                files[which].write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError,'hair_dependency_hash'):
                    retain_surface_initialization(manifest,root/'retained',expected_manifest_hash=expected,expected_source_hash='capture')
                self.assertFalse((root/'retained').exists())

    def test_auxiliary_surface_proofs_and_original_base_remain_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m,proof,solver,surface=self.proof_fixture(root)
            meta=json.loads(m.read_text());row=meta['components']['room'];base=dict(row)
            extra=root/'correction/extra.npz'
            np.savez(extra,means=np.ones((2,3)),source_hash=np.asarray('capture'),coordinate_frame=np.asarray('world'))
            ep=root/'correction/extra-proof.json';ev=json.loads(proof.read_text());ev['roomAssetHash']=digest(extra);ep.write_text(json.dumps(ev))
            final=root/'temporary/combined.npz'
            np.savez(final,means=np.r_[np.zeros((3,3)),np.ones((2,3))],source_hash=np.asarray('capture'),coordinate_frame=np.asarray('world'))
            row.update(path=str(final),sha256=digest(final),count=5,
                surfaceBaseComponent={k:base[k] for k in ('path','sha256','count')},
                additionalSurfaceReceipts=[dict(index=1,path=str(ep),sha256=digest(ep),assetPath=str(extra),assetSha256=digest(extra),count=2)])
            m.write_text(json.dumps(meta));expected=digest(m);target=root/'retained'
            receipt=retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
            for label in ('room.surfaceBaseComponent','room.additional1.asset','room.additional1.surfaceCorrectionReceipt',
                          'room.additional1.solverReport','room.additional1.surface'):
                self.assertIn(label,receipt['evidenceFiles'])
            (root/'temporary').rename(root/'expired');(root/'auxiliary').rename(root/'expired-aux');(root/'correction').rename(root/'expired-proof')
            verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)
            (target/receipt['evidenceFiles']['room.additional1.asset']['file']).write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError,'evidence_changed'):
                verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)

    def fixture(self,root):
        source=root/'temporary';source.mkdir();other=root/'auxiliary';other.mkdir()
        rows={}
        for name in ('room','body','hair'):
            p=(other if name=='body' else source)/(name+'-surface.npz')
            np.savez(p,means=np.zeros((3,3)),source_hash=np.asarray('capture'),
                     coordinate_frame=np.asarray('head-local' if name=='hair' else 'world'))
            rows[name]={'count':3,'path':str(p),'sha256':digest(p)}
        manifest=source/'result.json';manifest.write_text(json.dumps({'sourceSha256':'capture','components':rows},indent=3))
        return manifest

    def proof_fixture(self,root,relative=False):
        m=self.fixture(root);meta=json.loads(m.read_text());proof_dir=root/'correction';proof_dir.mkdir()
        solver=proof_dir/'solver-report.json';solver.write_text('{"oneSharedSurface":true}\n')
        surface=proof_dir/'shared-surface.npz';np.savez(surface,xyz=np.zeros((4,3)))
        proof=proof_dir/'proof.json'
        proof.write_text(json.dumps({'kind':'shared-static-track-surface-correction','qualified':True,
            'sourceSha256':'capture','roomAssetHash':meta['components']['room']['sha256'],
            'solverReportPath':solver.name if relative else str(solver),'solverReportSha256':digest(solver),
            'surfacePath':surface.name if relative else str(surface),'surfaceSha256':digest(surface)},indent=4))
        meta['components']['room'].update(typedSupport=True,
            surfaceCorrectionReceipt='../correction/proof.json' if relative else str(proof),
            surfaceCorrectionReceiptSha256=digest(proof))
        m.write_text(json.dumps(meta,indent=3));return m,proof,solver,surface

    def test_original_hash_and_external_component_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=self.fixture(root);raw=manifest.read_bytes();expected=digest(manifest)
            destination=root/'state/surface-initialization'
            receipt=retain_surface_initialization(manifest,destination,expected_manifest_hash=expected,expected_source_hash='capture')
            self.assertEqual((destination/'result.json').read_bytes(),raw)
            self.assertTrue((destination/'components/body.npz').is_file())
            metadata,files=verify_recovery_manifest(destination/'recovery-manifest.json',expected_manifest_hash=expected)
            self.assertEqual(set(files),{'room','body','hair'});self.assertNotEqual(files['body'],Path(metadata['components']['body']['path']))
            self.assertFalse(receipt['recovery']['originalVideoRetained'])
            self.assertFalse(receipt['recovery']['exactTrainingResumeEstablished'])

    def test_checkpoint_manifest_mismatch_not_reblessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m=self.fixture(root)
            with self.assertRaisesRegex(ValueError,'checkpoint_manifest_mismatch'):
                retain_surface_initialization(m,root/'state',expected_manifest_hash='wrong',expected_source_hash='capture')
            self.assertFalse((root/'state').exists())

    def test_component_tamper_detected_before_copy_and_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m=self.fixture(root);expected=digest(m);target=root/'state'
            retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
            (target/'components/body.npz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'retained_component_changed'):
                verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)
            Path(json.loads(m.read_text())['components']['body']['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'component_hash'):
                retain_surface_initialization(m,root/'another',expected_manifest_hash=expected,expected_source_hash='capture')

    def test_relative_recovery_paths_cannot_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m=self.fixture(root);expected=digest(m);target=root/'state'
            retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
            p=target/'recovery-manifest.json';r=json.loads(p.read_text());r['components']['body']['file']='../outside.npz';p.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'relative_path_escape'):verify_recovery_manifest(p,expected_manifest_hash=expected)

    def test_old_absolute_paths_not_required_for_verified_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m=self.fixture(root);expected=digest(m);target=root/'state'
            retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
            # Simulate the recorded cleanup by moving only this test fixture's
            # temporary directory; actual user assets are never touched.
            (root/'temporary').rename(root/'expired-temporary');(root/'auxiliary').rename(root/'expired-auxiliary')
            _,resolved=verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)
            self.assertTrue(all(p.is_file() for p in resolved.values()))

    def test_runtime_uses_final_checkpoint_manifest_contract(self):
        import torch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m=self.fixture(root);expected=digest(m)
            output=root/'training';output.mkdir();state_dir=root/'retained';state_dir.mkdir()
            torch.save({'model':{},'surfaceContract':{'manifestSha256':expected}},output/'trained-state.pt')
            receipt=retain_runtime_surface_initialization(output,state_dir,
                {'sourceSha256':'capture','denseSurfaces':{'manifestPath':str(m)}})
            self.assertEqual(receipt['originalManifestSha256'],expected)
            self.assertEqual(receipt['components']['body']['file'],'components/body.npz')
            self.assertTrue((state_dir/receipt['recoveryManifest']).is_file())

    def test_three_proof_files_retained_byte_exact_and_resolve(self):
        for relative in (False,True):
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);m,proof,solver,surface=self.proof_fixture(root,relative)
                expected=digest(m);target=root/'state'
                receipt=retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
                self.assertEqual(set(receipt['evidenceFiles']),{'room.surfaceCorrectionReceipt','room.solverReport','room.surface'})
                raw_manifest=m.read_bytes();originals={str(f):f.read_bytes() for f in (proof,solver,surface)}
                hashes={str(f):digest(f) for f in (proof,solver,surface)}
                (root/'temporary').rename(root/'expired');(root/'auxiliary').rename(root/'expired-aux');(root/'correction').rename(root/'expired-proof')
                self.assertEqual((target/'result.json').read_bytes(),raw_manifest)
                for old,raw in originals.items():
                    new=resolve_recovery_identity(target/'recovery-manifest.json',old,
                        expected_manifest_hash=expected,expected_hash=hashes[old])
                    self.assertEqual(new.read_bytes(),raw)

    def test_proof_or_dependency_tamper_blocks_retention(self):
        for label in ('receipt','solver','surface'):
            with self.subTest(label=label),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);m,proof,solver,surface=self.proof_fixture(root)
                expected=digest(m);{'receipt':proof,'solver':solver,'surface':surface}[label].write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError,'proof_hash|dependency_hash'):
                    retain_surface_initialization(m,root/'state',expected_manifest_hash=expected,expected_source_hash='capture')
                self.assertFalse((root/'state').exists())

    def test_retained_dependency_tamper_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m,proof,solver,surface=self.proof_fixture(root);expected=digest(m);target=root/'state'
            r=retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
            (target/r['evidenceFiles']['room.surface']['file']).write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'evidence_changed'):
                verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)

    def test_relocation_cannot_bypass_original_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m,*_=self.proof_fixture(root);expected=digest(m);target=root/'state'
            retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
            p=target/'recovery-manifest.json';r=json.loads(p.read_text())
            r['relocations']['/unrelated-private-file']={'file':'components/room.npz','sha256':r['components']['room']['sha256']}
            p.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'relocation_set_changed'):
                verify_recovery_manifest(p,expected_manifest_hash=expected)


if __name__=='__main__':unittest.main()
