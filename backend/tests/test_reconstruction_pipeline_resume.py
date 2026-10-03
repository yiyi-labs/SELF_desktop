"""Mock the real pipeline orchestration; no GPU, training or rasterization."""
import copy
import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import torch
import reconstruction_portrait_pipeline as pipeline
from reconstruction_live_opaque_person import prepare_opaque_interiors


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value));return digest(path)


class PipelineResumeTest(unittest.TestCase):
    def fixture(self,root,*,opaque=True,footprint=True,recovery=True):
        parent=root/'parent';parent.mkdir();prepared=root/'prepared';prepared.mkdir()
        (prepared/'cloth_supported_seeds.npz').write_bytes(b'cloth fixture')
        prior=parent/'observed-face-initial-appearance.npz';np.savez(prior,complete_prior=np.arange(6))
        labels={k:np.zeros((16,18),bool) for k in
                ('hair_visible','glasses_visible','unknown_or_occluded','training_skin','observed_cloth','observed_body_skin')}
        labels['training_skin'][3:12,4:13]=True
        domain={'appearanceSha256':digest(prior),'oldAppearanceSha256':'old','maskHashes':{'ref':'mask'}}
        cfg={'engineVersion':pipeline.ENGINE_VERSION,'sourceSha256':'source','appearanceHash':digest(prior),
             'soft':True,'antialiased':False,'opaquePerson':opaque,'opaqueBody':False,
             'observedFaceDomain':domain,'observedEmptySpace':False,'surfaceRefine':False,
             'surfaceFootprint':None,'roomWindowRecovery':recovery}
        if footprint:
            cfg['surfaceFootprint']={'method':'fixture','changedCount':1}
            domain['surfaceFootprintSha256']=write(parent/'surface-footprint.json',cfg['surfaceFootprint'])
            np.savez(parent/'surface-footprint-diagnostics.npz',changed=np.array([True]))
        write(parent/'observed-face-domain.json',domain)
        if opaque:
            _,receipt=prepare_opaque_interiors(labels)
            cfg['opaqueInteriorsReceiptSha256']=write(parent/'opaque-interiors.json',{'ref':receipt})
        manifest=parent/'dense.json';dense={'manifestPath':str(manifest),'sourceSha256':'source'}
        if recovery:dense['roomWindowRecovery']={'status':'retained','addedCount':0}
        write(manifest,dense);cfg['denseSurfaces']=dense
        if recovery:
            cfg['roomWindowRecoveryReceipt']={'manifestPath':str(manifest),'manifestSha256':digest(manifest),
                                              'result':dense['roomWindowRecovery']}
            write(parent/'room-window-recovery.json',cfg['roomWindowRecoveryReceipt'])
        write(parent/'config.json',cfg)
        contract={'reference':'ref','manifestSha256':digest(manifest)}
        state={'engineVersion':pipeline.ENGINE_VERSION,'sourceSha256':'source','surfaceContract':contract,
               'model':{'frozen_field':torch.tensor([3.])},'personSupervision':
               {'opaqueHead':opaque,'opaqueBody':False,'appearanceSha256':digest(prior)}}
        torch.save(state,parent/'trained-state.pt')
        marks=np.zeros((478,2));marks[454,0]=20;marks[152,1]=20
        data={'prepared':prepared,'sourceHash':'source','appearanceHash':'old','prior':{'legacy':True},
              'train':['ref'],'local':{'ref':{'marks':marks}},'worlds':{'ref':np.eye(4)},
              'labels':{'ref':labels}}
        args=SimpleNamespace(prepared=prepared,output=root/'output',resume_state=parent/'trained-state.pt',
            portrait_state=None,portrait_manifest=None,observed_face_domain=False,observed_empty_space=False,
            surface_footprint=False,opaque_person=False,opaque_body=False,dense_surfaces=False,dense_manifest=None,
            room_window_recovery=False,surface_refine=False,soft=False,antialiased=False,
            local_steps=0,room_steps=0,joint_steps=0,hair_steps=0,skin_steps=0)
        scene=SimpleNamespace(dense_surface=True,dense_metadata=dense,
            portrait=SimpleNamespace(sh=torch.zeros(2,4,3),role=torch.zeros(2,dtype=torch.long)),
            environment_parts=torch.zeros(3),load_state_dict=lambda model,strict:None)
        return args,data,scene,cfg,contract

    def invoke(self,args,data,scene,cfg,contract):
        def restore(data,parent,config):
            data['appearanceHash']=config['appearanceHash'];data['face_domain_receipt']=copy.deepcopy(config['observedFaceDomain'])
            data['prior']={'complete_restored':True}
        def initialize(actual,out):
            self.assertEqual(actual['prior'],{'complete_restored':True})
            self.assertEqual(actual['reference'],'ref')
            return scene
        with ExitStack() as stack:
            def patcher(target,**kw):return stack.enter_context(patch(target,**kw))
            patcher('torch.cuda.is_available',return_value=True)
            for name in ('reset_peak_memory_stats','synchronize'):patcher('torch.cuda.'+name,return_value=None)
            for name in ('max_memory_allocated','max_memory_reserved'):patcher('torch.cuda.'+name,return_value=0)
            patcher('reconstruction_portrait_pipeline.load_prepared',return_value=data)
            patcher('reconstruction_portrait_pipeline.initialize_scene',side_effect=initialize)
            patcher('reconstruction_live_face_domain.restore_recorded',side_effect=restore)
            activate=patcher('reconstruction_live_face_domain.activate',side_effect=AssertionError('must not reinitialize'))
            patcher('reconstruction_live_surface_footprint.adapt_observed_surface_footprints',side_effect=AssertionError('must not readapt'))
            patcher('reconstruction_capture_reference.choose_capture_reference',side_effect=AssertionError('must keep reference'))
            patcher('reconstruction_live_room_window_recovery.recover_static_window_surfaces',side_effect=AssertionError('must not recover again'))
            patcher('reconstruction_portrait_pipeline.surface_contract',return_value=contract)
            patcher('reconstruction_code_identity.source_identity',return_value={'sourceFiles':{},'implementationSha256':'source'})
            patcher('reconstruction_portrait_pipeline.audit_stages',return_value={})
            patcher('reconstruction_portrait_pipeline.audit_full_scene',return_value={})
            patcher('reconstruction_portrait_pipeline.export_candidate',return_value='asset')
            patcher('reconstruction_portrait_pipeline.train_stage',side_effect=AssertionError('zero steps'))
            portrait_start=patcher('reconstruction_portrait_pipeline.warm_start_portrait',
                                  return_value={'kind':'complete_head_model_warm_start_new_Adam'})
            pipeline.run(args);activate.assert_not_called()
            self.assertEqual(portrait_start.call_count,int(args.portrait_state is not None))

    def test_default_false_restores_original_flags_prior_and_no_prepare(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,data,scene,cfg,contract=self.fixture(Path(tmp))
            self.invoke(args,data,scene,cfg,contract)
            result=json.loads((args.output/'config.json').read_text())
            self.assertTrue(result['opaquePerson']);self.assertFalse(result['opaqueBody'])
            self.assertTrue(args.soft);self.assertTrue(scene.opaque_person)
            self.assertEqual(result['surfaceFootprint'],cfg['surfaceFootprint'])
            self.assertEqual(result['roomWindowRecoveryReceipt'],cfg['roomWindowRecoveryReceipt'])
            self.assertEqual(result['resumeKind'],'model_only_warm_start')
            for name in ('surface-footprint.json','opaque-interiors.json','room-window-recovery.json'):
                self.assertEqual((args.output/name).read_bytes(),(args.resume_state.parent/name).read_bytes())

    def test_explicit_new_opaque_flag_is_not_warm_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,data,scene,cfg,contract=self.fixture(Path(tmp),opaque=False)
            args.opaque_person=True
            with self.assertRaisesRegex(ValueError,'resume_cannot_change_recorded_flag:opaquePerson'):
                self.invoke(args,data,scene,cfg,contract)

    def test_missing_config_and_changed_room_proof_rejected(self):
        for kind in ('missing','proof'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                args,data,scene,cfg,contract=self.fixture(Path(tmp))
                if kind=='missing':(args.resume_state.parent/'config.json').unlink()
                else:(args.resume_state.parent/'room-window-recovery.json').write_text('{}')
                with self.assertRaisesRegex(ValueError,'resume_complete_config_required|resume_room_window_recovery_receipt_changed'):
                    self.invoke(args,data,scene,cfg,contract)

    def test_checkpoint_supervision_mismatch_cannot_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            args,data,scene,cfg,contract=self.fixture(Path(tmp))
            state=torch.load(args.resume_state,weights_only=True);state['personSupervision']['opaqueHead']=False
            torch.save(state,args.resume_state)
            with self.assertRaisesRegex(ValueError,'checkpoint_contract_mismatch'):
                self.invoke(args,data,scene,cfg,contract)
            self.assertFalse((args.output/'report.json').exists())

    def test_head_only_warm_start_restores_prior_but_keeps_new_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args,data,scene,cfg,contract=self.fixture(root)
            args.portrait_state=args.resume_state;args.resume_state=None
            args.portrait_manifest=Path(cfg['denseSurfaces']['manifestPath'])
            new_manifest=root/'new-room.json';new_dense={'manifestPath':str(new_manifest),
                'sourceSha256':'source','newRoomOnly':True}
            write(new_manifest,new_dense);args.dense_manifest=new_manifest
            scene.dense_metadata=new_dense
            def forbidden(*a,**k):raise AssertionError('must not load old full environment')
            scene.load_state_dict=forbidden
            self.invoke(args,data,scene,cfg,contract)
            result=json.loads((args.output/'config.json').read_text())
            self.assertTrue(result['opaquePerson']);self.assertEqual(result['surfaceFootprint'],cfg['surfaceFootprint'])
            self.assertEqual(result['denseSurfaces'],new_dense)
            self.assertEqual(result['resumeKind'],'complete_head_model_warm_start_new_Adam')
            self.assertFalse(result['roomWindowRecovery'])
            self.assertFalse((args.output/'room-window-recovery.json').exists())

    def test_head_warm_start_original_manifest_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args,data,scene,cfg,contract=self.fixture(root)
            args.portrait_state=args.resume_state;args.resume_state=None
            args.portrait_manifest=root/'wrong.json';write(args.portrait_manifest,{})
            args.dense_manifest=args.portrait_manifest
            with self.assertRaisesRegex(ValueError,'original_manifest_required'):
                self.invoke(args,data,scene,cfg,contract)


if __name__=='__main__':unittest.main()
