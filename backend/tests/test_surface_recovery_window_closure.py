"""Room-window proof recovery is byte preserving and independent of job paths."""
import json
import tempfile
import unittest
from pathlib import Path
import numpy as np

from surface_recovery import digest,retain_surface_initialization,verify_recovery_manifest,resolve_recovery_identity
import test_surface_recovery as fixtures


def save(path,value):
    path.write_text(json.dumps(value));return str(path),digest(path)


class WindowClosureContract(unittest.TestCase):
    def test_second_reference_selection_and_failed_first_attempt_remain_after_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=fixtures.SurfaceRecoveryTest().fixture(root)
            parent=manifest.parent
            prior,prior_hash=save(parent/'prior-attempt.json',{'sourceSha256':'capture','status':'independent_validation_failed'})
            selection,selection_hash=save(parent/'selection.json',{'sourceSha256':'capture','candidates':[]})
            decision,decision_hash=save(parent/'retry-decision.json',dict(kind='one-second-reference-research',maxAttemptsPerWindow=2,
                maxEvaluations=40,priorAttemptPath=prior,priorAttemptSha256=prior_hash,selectionPath=selection,selectionSha256=selection_hash))
            meta=json.loads(manifest.read_text());meta['roomWindowSecondReference']=dict(decisionPath=decision,decisionSha256=decision_hash)
            manifest.write_text(json.dumps(meta));expected=digest(manifest);target=root/'retained'
            receipt=retain_surface_initialization(manifest,target,expected_manifest_hash=expected,expected_source_hash='capture')
            self.assertTrue({'roomSecondReference.decision','roomSecondReference.priorAttempt','roomSecondReference.selection'}<=set(receipt['evidenceFiles']))
            (root/'temporary').rename(root/'expired');(root/'auxiliary').rename(root/'expired-aux')
            verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)
            kept=resolve_recovery_identity(target/'recovery-manifest.json',decision,expected_manifest_hash=expected,expected_hash=decision_hash)
            self.assertEqual(json.loads(kept.read_text())['maxAttemptsPerWindow'],2)

    def fixture(self,root,*,linked=False,relative=False):
        manifest,proof,solver,surface=fixtures.SurfaceRecoveryTest().proof_fixture(root,relative)
        data=json.loads(proof.read_text());folder=proof.parent
        leaves={}
        for name in ('depthManifest','originalDecision','parentManifest'):
            value={'sourceHash':'capture'} if name=='depthManifest' else {'sourceSha256':'capture'}
            # Untrusted paths in provenance must not trigger arbitrary copying.
            value['sourceVideo']=str(root/'private.mp4');value['secretPath']=str(root/'credentials.json')
            leaves[name]=save(folder/(name+'.json'),value)
        proposal=dict(kind='rejected-fixed-camera-window-proposal',sourceSha256='capture',permitsSolveOnly=True)
        for key,(path,sha) in leaves.items():
            proposal[key+'Path']=Path(path).name if relative else path;proposal[key+'Sha256']=sha
        proposal_path,proposal_hash=save(folder/'proposal.json',proposal)
        points=folder/'point-evidence.npz';np.savez(points,uid=np.arange(3),kept=np.ones(3,bool))
        parent_room=Path(json.loads(manifest.read_text())['components']['room']['path'])
        overlap=dict(kind='recovered-room-unrepresented-observation',qualified=True,sourceSha256='capture',
            surfacePath=surface.name if relative else str(surface),surfaceSha256=digest(surface),
            pointEvidencePath=points.name if relative else str(points),pointEvidenceSha256=digest(points),
            parentRoomPath='../temporary/'+parent_room.name if relative else str(parent_room),parentRoomSha256=digest(parent_room))
        overlap_path,overlap_hash=save(folder/'local-overlap.json',overlap)
        recovery=dict(proposalPath=Path(proposal_path).name if relative else proposal_path,proposalSha256=proposal_hash,
            overlapPath=Path(overlap_path).name if relative else overlap_path,overlapSha256=overlap_hash)
        data['windowRecovery']=recovery
        if linked:
            linked_path,linked_hash=save(folder/'linked-proof.json',data.copy())
            broad=dict(kind='recovered-room-mutual-surface-overlap',qualified=True,sourceSha256='capture',
                surfacePath=surface.name if relative else str(surface),surfaceSha256=digest(surface),
                pairs=[dict(receiptPath=Path(linked_path).name if relative else linked_path,receiptSha256=linked_hash)])
            bp,bh=save(folder/'broad-overlap.json',broad)
            data['windowRecovery']={**recovery,'overlapPath':Path(bp).name if relative else bp,'overlapSha256':bh}
        proof.write_text(json.dumps(data))
        meta=json.loads(manifest.read_text());meta['components']['room']['surfaceCorrectionReceiptSha256']=digest(proof)
        manifest.write_text(json.dumps(meta))
        (root/'private.mp4').write_bytes(b'video-must-not-be-retained')
        (root/'credentials.json').write_text('{"secret":"must-not-copy"}')
        return manifest,points,Path(proposal_path),Path(overlap_path)

    def test_recursive_dependencies_survive_expiry_without_rewriting_hashes(self):
        for linked in (False,True):
            for relative in (False,True):
                with self.subTest(linked=linked,relative=relative),tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp);m,points,proposal,overlap=self.fixture(root,linked=linked,relative=relative)
                    expected=digest(m);target=root/'retained'
                    result=retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
                    old=str(points);raw=points.read_bytes();wanted=digest(points)
                    self.assertTrue(any('windowRecovery' in k for k in result['evidenceFiles']))
                    self.assertFalse(any(p.suffix.lower()=='.mp4' or 'credentials' in p.name for p in target.rglob('*')))
                    (root/'temporary').rename(root/'expired');(root/'auxiliary').rename(root/'expired-aux');(root/'correction').rename(root/'expired-proof')
                    verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)
                    relocated=resolve_recovery_identity(target/'recovery-manifest.json',old,expected_manifest_hash=expected,expected_hash=wanted)
                    self.assertEqual(relocated.read_bytes(),raw)
                    self.assertEqual(digest(target/'result.json'),expected)

    def test_window_dependency_tamper_detected_before_and_after_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m,points,proposal,overlap=self.fixture(root);expected=digest(m);target=root/'retained'
            index=retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
            entry=index['relocations'][str(points)];(target/entry['file']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'evidence_changed'):
                verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)
            points.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'dependency_hash'):
                retain_surface_initialization(m,root/'other',expected_manifest_hash=expected,expected_source_hash='capture')
            self.assertFalse((root/'other').exists())

    def test_missing_recursive_entry_cannot_pass_complete_index_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m,*_=self.fixture(root,linked=True);expected=digest(m);target=root/'retained'
            result=retain_surface_initialization(m,target,expected_manifest_hash=expected,expected_source_hash='capture')
            key=next(k for k in result['evidenceFiles'] if 'link0.windowRecovery.overlap.pointEvidence' in k)
            del result['evidenceFiles'][key]
            (target/'recovery-manifest.json').write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError,'evidence_missing'):
                verify_recovery_manifest(target/'recovery-manifest.json',expected_manifest_hash=expected)

    def test_video_cannot_be_smuggled_as_point_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);m,points,proposal,overlap=self.fixture(root)
            value=json.loads(overlap.read_text());value['pointEvidencePath']=str(root/'private.mp4');value['pointEvidenceSha256']=digest(root/'private.mp4')
            overlap.write_text(json.dumps(value));meta=json.loads(m.read_text());proof=Path(meta['components']['room']['surfaceCorrectionReceipt'])
            p=json.loads(proof.read_text());p['windowRecovery']['overlapSha256']=digest(overlap);proof.write_text(json.dumps(p))
            meta['components']['room']['surfaceCorrectionReceiptSha256']=digest(proof);m.write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError,'dependency_type'):
                retain_surface_initialization(m,root/'retained',expected_manifest_hash=digest(m),expected_source_hash='capture')


if __name__=='__main__':unittest.main()
