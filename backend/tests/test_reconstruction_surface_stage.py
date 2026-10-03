"""Observation, measured-surface and complete split-transaction contracts."""
import unittest
from types import SimpleNamespace
import numpy as np
import torch
from reconstruction_scene import surface_barycentrics,surface_sample_identity
from reconstruction_observed_surface import observation_domains,finite_triangle_samples
from reconstruction_surface_density import split_surface_parameters


class SurfaceStageTest(unittest.TestCase):
    def test_d2_centroid_identity_matches_d3_without_changing_larger_grid(self):
        np.testing.assert_allclose(surface_barycentrics(2),[[1/3]*3])
        for d in (3,4,6,10):
            old=[(a/d,b/d,1-(a+b)/d) for a in range(1,d) for b in range(1,d-a)]
            np.testing.assert_allclose(surface_barycentrics(d),old)
        self.assertEqual(surface_sample_identity([7,8,9],[1/3]*3),surface_sample_identity([9,7,8],[1/3]*3))

    def test_safety_moat_does_not_remove_real_observed_clothes_or_room(self):
        cls=np.array([[0,4,2,3,1,5]],np.uint8);certainty=np.ones(cls.shape,np.float32)
        existing={"room_visible":np.zeros_like(cls,bool)}
        domain=observation_domains(cls,certainty,np.zeros_like(cls,bool),existing)
        self.assertEqual(domain["observed_room"].tolist(),[[True,False,False,False,False,False]])
        self.assertEqual(domain["observed_cloth"].tolist(),[[False,True,False,False,False,False]])
        self.assertEqual(domain["observed_body_skin"].tolist(),[[False,False,True,False,False,False]])
        self.assertFalse(domain["room_visible"].any())
        bad=observation_domains(cls,certainty*.5,np.zeros_like(cls,bool),existing)
        self.assertFalse(bad["observed_room"].any())

    def test_true_3d_surface_with_three_observations_and_rejection(self):
        xyz=np.array([(x,y,2.) for x in (-.30,0,.30) for y in (-.30,0,.30)])
        K=np.array([[120.,0,64.],[0,120.,64.],[0,0,1.]])
        views={};masks={};rgb={}
        for i in range(3):
            C=np.eye(4);C[0,3]=(i-1)*.04;n=str(i);views[n]=(C,K)
            masks[n]=np.ones((128,128),bool);rgb[n]=np.full((128,128,3),.4,np.float32)
        result,report=finite_triangle_samples(xyz,np.arange(9),views,masks,rgb,budget=300)
        self.assertIsNotNone(result);self.assertTrue((result["support"]>=3).all())
        np.testing.assert_allclose(result["xyz"][:,2],2.)
        self.assertTrue((result["sample_bary"]>0).all())
        np.testing.assert_allclose(result["sample_bary"].sum(1),1.)
        rgb["2"]=rgb["2"]+.4
        denied,_=finite_triangle_samples(xyz,np.arange(9),views,masks,rgb,budget=300)
        self.assertIsNone(denied)

    def test_split_retires_parent_and_syncs_adam_and_provenance(self):
        p=torch.nn.ParameterDict({"means":torch.nn.Parameter(torch.tensor([[0.,0,2.],[1.,0,2.]])),
            "scales":torch.nn.Parameter(torch.tensor([[.1,.08,.005],[.2,.1,.01]]).log()),
            "quats":torch.nn.Parameter(torch.tensor([[1.,0,0,0]]*2)),
            "opacities":torch.nn.Parameter(torch.zeros(2)),"sh":torch.nn.Parameter(torch.zeros(2,4,3))})
        optim=torch.optim.Adam([{"params":[v],"name":k} for k,v in p.items()],lr=.001)
        sum(v.square().sum() for v in p.values()).backward();optim.step()
        scene=SimpleNamespace(environment=p,environment_parts=torch.zeros(2,dtype=torch.long),
            environment_initial_means=p["means"].detach().clone(),environment_initial_scales=p["scales"].detach().clone(),
            environment_uid=torch.tensor([0,1]),environment_parent_uid=torch.tensor([-1,-1]),
            environment_generation=torch.zeros(2,dtype=torch.long),environment_sources={"id":np.array([10,20]),"kind":np.array([1,1])})
        old=p["means"].detach().clone();report=split_surface_parameters(scene,optim,[0])
        self.assertEqual(report["parentsRetired"],1);self.assertEqual(report["after"],3)
        self.assertEqual(scene.environment_uid.tolist(),[1,2,3]);self.assertEqual(scene.environment_parent_uid.tolist(),[-1,0,0])
        self.assertEqual(scene.environment_sources["id"].tolist(),[20,10,10])
        np.testing.assert_allclose(p["means"][1:].detach().mean(0),old[0],atol=1e-7)
        for group in optim.param_groups:
            v=p[group["name"]];self.assertIs(group["params"][0],v)
            self.assertEqual(optim.state[v]["exp_avg"].shape,v.shape)
            self.assertEqual(float(optim.state[v]["exp_avg"][1:].abs().sum()),0.)
        optim.zero_grad();sum(v.square().sum() for v in p.values()).backward();optim.step()


if __name__=="__main__":unittest.main()
