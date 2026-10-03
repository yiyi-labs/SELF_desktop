import unittest
import numpy as np
from reconstruction_live_face_domain import observed_face_domain,observed_empty_domain


class FaceDomainTest(unittest.TestCase):
    def test_observed_empty_excludes_low_confidence_and_positive_conflicts(self):
        c=np.zeros((5,6),np.uint8);q=np.ones_like(c,float);outside=np.zeros_like(c,bool)
        q[0,0]=.84;c[0,1]=3;outside[0,2]=True
        empty=np.zeros_like(c,bool)
        m=dict(training_face=empty.copy(),hair_visible=empty.copy(),glasses_visible=empty.copy(),
               observed_room=~empty,unknown_or_occluded=~empty)
        m['training_face'][1,0]=True;m['hair_visible'][1,1]=True;m['glasses_visible'][1,2]=True
        m['observed_room'][1,3]=False
        r=observed_empty_domain(c,q,outside,m)
        self.assertFalse(r[0,:3].any());self.assertFalse(r[1,:4].any())
        # A known room pixel may have been legacy-unknown, but uncertainty by
        # itself is never used to classify a pixel as room.
        self.assertTrue(r[3,3]);self.assertTrue(m['unknown_or_occluded'].all())

    def test_head_loss_uses_only_explicit_empty_mask_otherwise_legacy(self):
        import torch
        from reconstruction_portrait_pipeline import head_loss
        z=torch.zeros((3,3),dtype=torch.bool);rgb=torch.zeros((3,3,3))
        masks=dict(face_core=z,face_boundary=z,glasses_visible=z,hair_visible=z,
                   room_visible=z,unknown_or_occluded=~z)
        rendered=dict(rgb=rgb,alpha=torch.ones((3,3)))
        loss0,r0=head_loss(rendered,dict(rgb=rgb,masks=masks))
        self.assertEqual(float(loss0),0);self.assertEqual(r0['reliableEmpty'],0)
        explicit=z.clone();explicit[1,1]=True
        loss1,r1=head_loss(rendered,dict(rgb=rgb,masks={**masks,'training_empty':explicit}))
        self.assertAlmostEqual(float(loss1),.03,places=6);self.assertEqual(r1['reliableEmpty'],1)
        # The explicit mask also supersedes the old broad mask, not its union.
        loss2,_=head_loss(rendered,dict(rgb=rgb,masks={**masks,'room_visible':~z,
            'unknown_or_occluded':z,'training_empty':z}))
        self.assertEqual(float(loss2),0)

    def test_empty_flag_requires_face_domain_before_side_effects(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from reconstruction_portrait_pipeline import run
        with patch('torch.cuda.is_available') as gpu:
            with self.assertRaisesRegex(ValueError,'requires_observed_face_domain'):
                run(SimpleNamespace(observed_empty_space=True,observed_face_domain=False))
        gpu.assert_not_called()

    def test_restore_replays_empty_flag_and_rejects_changed_hash_or_flag(self):
        import tempfile,json,hashlib
        from pathlib import Path
        from unittest.mock import patch
        from reconstruction_live_face_domain import restore_recorded
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);prior=root/'observed-face-initial-appearance.npz'
            np.savez(prior,source=np.asarray([1]));ph=hashlib.sha256(prior.read_bytes()).hexdigest()
            receipt=dict(oldAppearanceSha256='old',appearanceSha256=ph,maskHashes={'a':'face'},
                skinMaskHashes={'a':'skin'},observedEmptySpace=True,emptyMaskHashes={'a':'negative'})
            data=dict(appearanceHash='old')
            with patch('reconstruction_live_face_domain.activate',return_value=receipt) as activate:
                restore_recorded(data,root,dict(observedFaceDomain=receipt,observedEmptySpace=True))
                activate.assert_called_once_with(data,root,regenerate_prior=False,write_receipt=False,observed_empty_space=True)
            self.assertEqual(data['appearanceHash'],ph)
            with patch('reconstruction_live_face_domain.activate',return_value={**receipt,'emptyMaskHashes':{'a':'changed'}}):
                with self.assertRaisesRegex(ValueError,'empty_observations_changed'):
                    restore_recorded(dict(appearanceHash='old'),root,dict(observedFaceDomain=receipt))
            with self.assertRaisesRegex(ValueError,'empty_recorded_contract_mismatch'):
                restore_recorded(dict(appearanceHash='old'),root,dict(observedFaceDomain=receipt,observedEmptySpace=False))

    def test_missing_development_skin_does_not_fill_pixels_or_abort_training(self):
        import tempfile,json,cv2
        from pathlib import Path
        from reconstruction_live_face_domain import activate
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'labels').mkdir();(root/'confidence').mkdir()
            (root/'preparation.json').write_text(json.dumps({'masks':str(root),'sourceDistortion':[0,0,0,0]}))
            data={'prepared':root,'appearanceHash':'unchanged','K':np.array([[10.,0,5],[0,10.,5],[0,0,1.]]),'labels':{},'local':{}}
            for i,role in enumerate(['train','train','train','development']):
                name=f'observation-{i}.png';classes=np.zeros((12,12),np.uint8)
                if role=='train':classes[3:9,3:9]=3;classes[5,5]=5
                cv2.imwrite(str(root/'labels'/(name+'.png')),classes)
                np.savez_compressed(root/'confidence'/(name+'.npz'),confidence=np.ones_like(classes,np.float32))
                a=np.ones_like(classes,bool)
                data['labels'][name]={'face_core':a,'face_boundary':~a,'glasses_visible':~a,'hair_visible':~a}
                data['local'][name]={'role':role}
            receipt=activate(data,root,regenerate_prior=False,write_receipt=False)
            self.assertFalse(data['labels']['observation-3.png']['training_face'].any())
            self.assertTrue(data['labels']['observation-0.png']['training_face'][5,5])
            self.assertFalse(data['labels']['observation-0.png']['training_skin'][5,5])
            self.assertTrue(data['labels']['observation-0.png']['training_skin'][4,4])
            self.assertEqual(receipt['oldAppearanceSha256'],'unchanged')
            self.assertEqual(len(receipt['skinMaskHashes']),4)
            self.assertFalse(receipt['observedEmptySpace']);self.assertEqual(receipt['emptyMaskHashes'],{})
            self.assertTrue(all('training_empty' not in m for m in data['labels'].values()))
            r=activate(data,root,regenerate_prior=False,write_receipt=False,observed_empty_space=True)
            self.assertTrue(r['observedEmptySpace']);self.assertEqual(len(r['emptyMaskHashes']),4)
            self.assertTrue(all('training_empty' in m for m in data['labels'].values()))
            r=activate(data,root,regenerate_prior=False,write_receipt=False)
            self.assertTrue(all('training_empty' not in m for m in data['labels'].values()))

    def test_saved_surface_contract_only_tolerates_pivot_roundoff(self):
        import copy
        from reconstruction_portrait_pipeline import surface_contract_matches
        a=dict(hairMotion=dict(pivotRootLocal=[.001,-.008,-.05],transformSha256='frozen'),
               hairReferenceTransforms=[np.eye(4).tolist()],scale=23.,reference='actual-source')
        b=copy.deepcopy(a);b['hairMotion']['pivotRootLocal'][0]+=1e-17
        self.assertTrue(surface_contract_matches(a,b))
        b['hairReferenceTransforms'][0][0][3]=1e-10
        self.assertFalse(surface_contract_matches(a,b))
        b=copy.deepcopy(a);b['hairMotion']['pivotRootLocal'][0]+=.001
        self.assertFalse(surface_contract_matches(a,b))
        b=copy.deepcopy(a);b['hairMotion']['transformSha256']='changed'
        self.assertFalse(surface_contract_matches(a,b))

    def test_connected_forehead_is_kept_without_colouring_background_or_neck(self):
        classes=np.zeros((14,16),np.uint8);classes[2:11,5:11]=3;classes[11:,5:11]=2
        classes[1,14]=3;classes[6,7]=5
        core=np.zeros_like(classes,bool);core[5:9,6:10]=True
        boundary=np.zeros_like(core);boundary[4:12,4:12]=True
        hair=np.zeros_like(core);hair[2,5:11]=True
        masks=dict(face_core=core,face_boundary=boundary,hair_visible=hair)
        copies={k:v.copy() for k,v in masks.items()}
        result=observed_face_domain(classes,np.ones_like(classes,float),np.zeros_like(core),masks)
        self.assertTrue(result[3,7]);self.assertTrue(result[6,7]);self.assertFalse(result[1,14])
        self.assertFalse(result[11,7]);self.assertFalse(result[5,4]);self.assertFalse(result[2,7])
        for k in masks:np.testing.assert_array_equal(masks[k],copies[k])

    def test_unknown_and_invalid_pixels_never_become_face(self):
        c=np.full((5,5),3,np.uint8);q=np.ones_like(c,float);o=np.zeros_like(c,bool)
        q[1,1]=.69;o[2,2]=True
        a=np.ones_like(c,bool);m=dict(face_core=a,face_boundary=a,hair_visible=~a)
        r=observed_face_domain(c,q,o,m)
        self.assertFalse(r[1,1]);self.assertFalse(r[2,2]);self.assertTrue(r[3,3])


if __name__=='__main__':unittest.main()
