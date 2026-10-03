"""Non-GPU restoration checks for head/body flags and observation evidence."""
from pathlib import Path
from types import SimpleNamespace
import ast
import copy
import hashlib
import json
import tempfile
import unittest
import numpy as np

from reconstruction_live_opaque_person import prepare_opaque_interiors
from reconstruction_person_supervision_state import (restore_person_supervision,
                                                     copy_person_supervision_files)


def write(path,value):
    path.write_text(json.dumps(value));return hashlib.sha256(path.read_bytes()).hexdigest()


class PersonRestoreTest(unittest.TestCase):
    def fixture(self,parent,*,head=True,body=False,footprint=False):
        labels={key:np.zeros((20,24),bool) for key in
                ('hair_visible','glasses_visible','unknown_or_occluded','training_skin','observed_cloth','observed_body_skin')}
        labels['training_skin'][3:13,5:17]=True
        labels['observed_cloth'][15:,3:21]=True
        prior=parent/'observed-face-initial-appearance.npz';np.savez(prior,field=np.arange(4))
        sha=hashlib.sha256(prior.read_bytes()).hexdigest()
        domain={'appearanceSha256':sha,'oldAppearanceSha256':'old','maskHashes':{'name.png':'original-evidence'}}
        config={'sourceSha256':'source','appearanceHash':sha,'opaquePerson':head,'opaqueBody':body,'observedFaceDomain':domain}
        if footprint:
            value={'method':'test_footprint','changedCount':1}
            domain['surfaceFootprintSha256']=write(parent/'surface-footprint.json',value)
            np.savez(parent/'surface-footprint-diagnostics.npz',changed=np.array([True]))
            config['surfaceFootprint']=value
        write(parent/'observed-face-domain.json',domain)
        _,receipt=prepare_opaque_interiors(labels)
        if head:config['opaqueInteriorsReceiptSha256']=write(parent/'opaque-interiors.json',{'name.png':receipt})
        data={'sourceHash':'source','appearanceHash':sha,'face_domain_receipt':copy.deepcopy(domain),'labels':{'name.png':labels}}
        state={'sourceSha256':'source','personSupervision':{'opaqueHead':head,'opaqueBody':body,'appearanceSha256':sha}}
        return SimpleNamespace(opaque_person=not head,opaque_body=not body),data,config,state

    def test_legacy_nonopaque_state_and_stale_masks(self):
        scene=SimpleNamespace(opaque_person=True,opaque_body=True)
        data={'sourceHash':'source','appearanceHash':'a','labels':{'x':{'opaque_skin':np.ones((2,2),bool)}}}
        result=restore_person_supervision(scene,data,'unused',{}, {'sourceSha256':'source'})
        self.assertFalse(scene.opaque_person);self.assertFalse(scene.opaque_body)
        self.assertTrue(result['legacyCheckpointContract']);self.assertNotIn('opaque_skin',data['labels']['x'])

    def test_head_only_and_explicit_body_both_restore(self):
        for head,body in ((False,False),(True,False),(True,True)):
            with self.subTest(head=head,body=body),tempfile.TemporaryDirectory() as tmp:
                scene,data,config,state=self.fixture(Path(tmp),head=head,body=body)
                result=restore_person_supervision(scene,data,tmp,config,state)
                self.assertEqual(scene.opaque_person,head);self.assertEqual(scene.opaque_body,body)
                self.assertEqual(result['opaqueBody'],body)
                self.assertEqual('opaque_skin' in data['labels']['name.png'],head)
                if head:self.assertGreater(data['labels']['name.png']['opaque_skin'].sum(),0)

    def test_missing_or_different_checkpoint_flags_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            scene,data,config,state=self.fixture(Path(tmp))
            for value in (None,{'opaqueHead':False,'opaqueBody':False,'appearanceSha256':data['appearanceHash']},
                          {'opaqueHead':True,'opaqueBody':False,'appearanceSha256':'wrong'}):
                check={**state,'personSupervision':value}
                with self.subTest(value=value),self.assertRaisesRegex(ValueError,'checkpoint_contract'):
                    restore_person_supervision(scene,data,tmp,config,check)
            self.assertFalse(scene.opaque_person);self.assertNotIn('opaque_skin',data['labels']['name.png'])

    def test_prior_receipt_and_recomputed_masks_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scene,data,config,state=self.fixture(root)
            data['labels']['name.png']['hair_visible'][6:9,8:11]=True
            with self.assertRaisesRegex(ValueError,'masks_changed'):
                restore_person_supervision(scene,data,root,config,state)
            data['labels']['name.png']['hair_visible'][:]=False
            (root/'observed-face-initial-appearance.npz').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'prior_not_restored'):
                restore_person_supervision(scene,data,root,config,state)

    def test_mask_receipt_rewrite_and_observation_identity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scene,data,config,state=self.fixture(root)
            data['labels']['other.png']=data['labels'].pop('name.png')
            with self.assertRaisesRegex(ValueError,'observation_names_changed'):
                restore_person_supervision(scene,data,root,config,state)
            data['labels']['name.png']=data['labels'].pop('other.png')
            (root/'opaque-interiors.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'opaque_receipt_changed'):
                restore_person_supervision(scene,data,root,config,state)

    def test_footprint_prior_restoration_keeps_evidence_and_rejects_changed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);scene,data,config,state=self.fixture(root,footprint=True)
            restore_person_supervision(scene,data,root,config,state)
            files=copy_person_supervision_files(root,root/'next',config)
            self.assertIn('surface-footprint.json',files)
            self.assertIn('surface-footprint-diagnostics.npz',files)
            self.assertEqual((root/'next'/'opaque-interiors.json').read_bytes(),(root/'opaque-interiors.json').read_bytes())
            (root/'surface-footprint.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'footprint_identity_changed'):
                restore_person_supervision(scene,data,root,config,state)

    def test_failed_copy_does_not_overwrite_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);_,_,config,_=self.fixture(root)
            target=root/'next';target.mkdir();(target/'observed-face-domain.json').write_text('other')
            with self.assertRaisesRegex(ValueError,'destination_conflict'):
                copy_person_supervision_files(root,target,config)
            self.assertEqual((target/'observed-face-domain.json').read_text(),'other')

    def test_all_three_diagnostic_runners_restore_flags_before_audit(self):
        for name in ('run_live_skin_compositing_trial.py','run_live_face_capacity_trial.py','run_live_body_appearance_trial.py'):
            with self.subTest(name=name):
                tree=ast.parse((Path(__file__).resolve().parents[1]/name).read_text())
                calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and
                       isinstance(node.func,ast.Name) and node.func.id=='restore_person_supervision']
                self.assertEqual(len(calls),1)
                audits=[node.lineno for node in ast.walk(tree) if isinstance(node,ast.Call) and
                        isinstance(node.func,ast.Name) and node.func.id in ('audit_full_scene','select_patch')]
                self.assertLess(calls[0].lineno,min(audits))


if __name__=='__main__':unittest.main()
