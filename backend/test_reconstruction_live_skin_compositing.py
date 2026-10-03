import unittest
import numpy as np
import torch
from reconstruction_live_skin_compositing import opaque_observation_mask,backdrop_consistency,preservation_decision,protected_observation_mask

class SkinContract(unittest.TestCase):
    def test_backdrops_disambiguate_colour_opacity(self):
        target=torch.full((3,3,3),.4);mask=torch.ones((3,3),dtype=torch.bool)
        rgb=target.clone().requires_grad_();alpha=torch.full((3,3),.5,requires_grad=True)
        loss=backdrop_consistency(rgb,alpha,target,mask);loss.backward()
        self.assertGreater(float(loss.detach()),0);self.assertTrue((alpha.grad<0).all())
        self.assertLess(float(backdrop_consistency(target,torch.ones_like(alpha),target,mask)),1e-7)
    def test_unknown_hair_and_lenses_excluded(self):
        ones=np.ones((80,80),bool);zeros=np.zeros_like(ones)
        labels=dict(training_skin=ones,face_core=ones,glasses_visible=zeros.copy(),hair_visible=zeros.copy(),unknown_or_occluded=zeros.copy())
        labels['glasses_visible'][30:35,30:35]=True;labels['hair_visible'][:10]=True;labels['unknown_or_occluded'][:,70:]=True
        m=opaque_observation_mask(labels)
        self.assertTrue(m[40,40]);self.assertFalse(m[32,32]);self.assertFalse(m[4,40]);self.assertFalse(m[40,75])
    def test_empty_observation_no_fake_coverage(self):
        z=torch.zeros((2,2),dtype=torch.bool)
        self.assertEqual(float(backdrop_consistency(torch.zeros(2,2,3),torch.zeros(2,2),torch.ones(2,2,3),z)),0)
    def test_regression_in_one_angle_cannot_hide_in_average(self):
        old={'a':dict(rgb=.03,hole=0),'b':dict(rgb=.04,hole=0)}
        new={'a':dict(rgb=.01,hole=0),'b':dict(rgb=.042,hole=0)}
        self.assertFalse(preservation_decision(old,new)[0])
        self.assertTrue(preservation_decision(old,old)[0])
        self.assertFalse(preservation_decision(old,{'a':old['a']})[0])
        self.assertFalse(preservation_decision({'a':dict(rgb=float('nan'),hole=0)}, {'a':old['a']})[0])
        self.assertFalse(preservation_decision({'a':old['a']}, {'a':dict(rgb=.03,hole=float('inf'))})[0])
    def test_hair_inside_oval_and_unsupervised_face_are_protected(self):
        zero=np.zeros((6,6),bool);one=~zero
        labels={k:zero.copy() for k in ('face_boundary','neck_cloth_visible','observed_room','hair_visible','glasses_visible','unknown_or_occluded')}
        labels.update(face_core=one.copy(),training_face=one.copy())
        labels['hair_visible'][1,1]=True;labels['unknown_or_occluded'][4,4]=True
        opaque=one.copy();opaque[2,3]=False
        p=protected_observation_mask(labels,opaque)
        self.assertTrue(p[1,1]);self.assertTrue(p[4,4]);self.assertTrue(p[2,3]);self.assertFalse(p[3,3])

if __name__=='__main__':unittest.main()
