import unittest
import numpy as np
import torch
from live_opaque_person import (prepare_opaque_interiors, person_rgb_features,
    conditional_person_colour, observed_structure_error, opaque_person_loss, DEFAULT_CONFIG)


class OpaquePersonContract(unittest.TestCase):
    def frame(self, value=.4):
        z=torch.zeros((9,9),dtype=torch.bool);m=z.clone();m[2:7,2:7]=True
        return {'rgb':torch.full((9,9,3),value), 'masks':{
            'opaque_skin':m, 'opaque_cloth':z.clone(), 'opaque_body_skin':z.clone()}}

    def render(self, frame, person=.5, room=.5):
        p=torch.tensor(float(person),requires_grad=True)
        rgb=frame['rgb']*p
        q=torch.zeros((*frame['rgb'].shape[:2],5));q[...,0]=room;q[...,1]=p
        return {'q':q,'person_rgb':rgb,'alpha':q.sum(-1),'rgb':rgb+room*.8},p

    def test_room_total_alpha_cannot_satisfy_person_opacity(self):
        f=self.frame();r,p=self.render(f)
        self.assertTrue(torch.equal(r['alpha'],torch.ones(9,9)))
        loss,record=opaque_person_loss(r,f);loss.backward()
        self.assertGreater(float(loss),.1);self.assertLess(float(p.grad),0)
        self.assertEqual(record['skin']['meanPersonContribution'],.5)
        r,_=self.render(f,person=1,room=0)
        loss,_=opaque_person_loss(r,f)
        self.assertLess(float(loss),1e-7)

    def test_normalized_colour_does_not_trade_alpha_against_brightness(self):
        f=self.frame();r,p=self.render(f,person=.3,room=.7)
        conditional,q=conditional_person_colour(r)
        self.assertTrue(torch.allclose(conditional,f['rgb'],atol=1e-7))
        conditional.sum().backward();self.assertLess(abs(float(p.grad)),1e-4)
        self.assertGreater(float((r['rgb']-f['rgb']).abs().mean()),.2)

    def test_part_mapping_retains_skin_and_body_but_not_room_hair_lens(self):
        rgb=torch.arange(15,dtype=torch.float32).reshape(5,3)
        out=person_rgb_features(rgb,torch.arange(5))
        self.assertTrue(torch.equal(out[[1,4]],rgb[[1,4]]))
        self.assertEqual(float(out[[0,2,3]].abs().sum()),0)

    def test_neck_skin_and_body_common_coverage_is_allowed(self):
        f=self.frame();f['masks']['opaque_body_skin']=f['masks']['opaque_skin'].clone()
        f['masks']['opaque_skin'].zero_();q=torch.zeros(9,9,5)
        q[...,1]=.6;q[...,4]=.4
        r={'q':q,'person_rgb':f['rgb'].clone()}
        loss,record=opaque_person_loss(r,f,scope='body')
        self.assertLess(float(loss),1e-7)
        self.assertEqual(record['body_skin']['meanPersonContribution'],1)

    def test_masks_exclude_unknown_hair_glasses_and_record_native_erosion(self):
        z=np.zeros((80,100),bool);skin=z.copy();skin[10:70,10:90]=True
        labels={k:z.copy() for k in ('hair_visible','glasses_visible','unknown_or_occluded')}
        labels['training_skin']=skin;labels['hair_visible'][10:20]=True
        labels['glasses_visible'][25:35,20:80]=True;labels['unknown_or_occluded'][60:70]=True
        masks,receipt=prepare_opaque_interiors(labels)
        m=masks['opaque_skin'];self.assertTrue(m[45,50])
        self.assertFalse(m[29,50]);self.assertFalse(m[14,50]);self.assertFalse(m[64,50])
        self.assertFalse(m[45,10]);self.assertTrue(m[45,12])
        self.assertEqual(receipt['regions']['skin']['erosionRadiusNativePixels'],1)
        self.assertFalse(masks['opaque_cloth'].any());self.assertFalse(masks['opaque_body_skin'].any())

    def test_missing_pixels_in_main_transmission_and_zero_finite(self):
        f=self.frame();r,p=self.render(f,person=0,room=1)
        loss,record=opaque_person_loss(r,f);loss.backward()
        self.assertTrue(torch.isfinite(loss));self.assertTrue(torch.isfinite(p.grad))
        self.assertLess(float(p.grad),0)
        self.assertEqual(record['skin']['pixels'],25)
        self.assertEqual(record['skin']['conditionalPixels'],0)

    def test_native_structure_uses_original_edges_not_mask_edges(self):
        target=torch.zeros(7,7,3);target[:,4:]=1;pred=target.clone()
        mask=torch.zeros(7,7,dtype=torch.bool);mask[2:5,1:6]=True
        self.assertEqual(float(observed_structure_error(pred,target,mask)),0)
        pred[~mask]=9
        self.assertEqual(float(observed_structure_error(pred,target,mask)),0)
        pred[mask]=.5
        self.assertGreater(float(observed_structure_error(pred,target,mask)),0)

    def test_contract_does_not_silently_use_full_scene_rgb(self):
        f=self.frame();r,_=self.render(f);del r['person_rgb']
        with self.assertRaises(ValueError):opaque_person_loss(r,f)
        r,_=self.render(f);del f['masks']['opaque_skin']
        with self.assertRaises(ValueError):opaque_person_loss(r,f)

    def test_empty_regions_no_fabricated_supervision(self):
        f=self.frame();f['masks']['opaque_skin'].zero_();r,p=self.render(f)
        loss,record=opaque_person_loss(r,f,scope='person');loss.backward()
        self.assertEqual(float(loss),0);self.assertEqual(float(p.grad),0)
        self.assertTrue(all(row['pixels']==0 for row in record.values()))

    def test_body_stage_does_not_supervise_frozen_face(self):
        f=self.frame();r,_=self.render(f)
        loss,record=opaque_person_loss(r,f,scope='body')
        self.assertEqual(float(loss.detach()),0)
        self.assertNotIn('skin',record)
        with self.assertRaises(ValueError):opaque_person_loss(r,f,scope='unknown')


if __name__=='__main__':unittest.main()
