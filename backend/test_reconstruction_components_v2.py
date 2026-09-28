"""Meaningful component, coordinate and live optimizer regressions."""
import unittest
from types import SimpleNamespace

import numpy as np
import torch
from scipy.spatial.transform import Rotation

from appearance_direction_contract import sh1_head_to_reference
from reconstruction_joint_visibility import render_components,component_conservation_error
from reconstruction_shared_v2 import torch_sh_rotate,ComponentStrategy


class ComponentContractTest(unittest.TestCase):
    def test_head_sh_rotation_matches_exact_export(self):
        rng=np.random.default_rng(28)
        coeff=rng.normal(size=(9,4,3)).astype(np.float32)
        R=Rotation.from_rotvec([.3,-.2,.1]).as_matrix().astype(np.float32)
        actual=torch_sh_rotate(torch.from_numpy(coeff),torch.from_numpy(R)).numpy()
        np.testing.assert_allclose(actual,sh1_head_to_reference(coeff,R),atol=3e-7)

    @unittest.skipUnless(torch.cuda.is_available(),"CUDA rasterization requires current GPU")
    def test_five_group_conservation_depth_and_actual_gradients(self):
        means=torch.tensor([[0.,0.,2.],[0.,0.,2.1],[0.,0.,2.2],[0.,0.,2.3],[0.,0.,2.4]],device="cuda",requires_grad=True)
        opacity=torch.full((5,),.35,device="cuda",requires_grad=True)
        coeff=torch.zeros((5,4,3),device="cuda",requires_grad=True)
        output=render_components(means,torch.tensor([[1.,0.,0.,0.]]*5,device="cuda"),
            torch.full((5,3),.09,device="cuda"),opacity,coeff,torch.arange(5,device="cuda"),
            torch.eye(4,device="cuda"),torch.tensor([[80.,0.,32.],[0.,80.,32.],[0.,0.,1.]],device="cuda"),64,64,absgrad=True,antialiased=True)
        self.assertLess(component_conservation_error(output),2e-6)
        self.assertLess(float((output["component_accumulated_depth"].sum(-1)-output["accumulated_depth"]).abs().max()),3e-6)
        output["projection"]["means2d"].retain_grad()
        loss=(output["rgb"]-.2).square().mean()+output["q"][:,:,0].mean()
        loss.backward()
        self.assertTrue(torch.isfinite(means.grad).all())
        self.assertTrue((opacity.grad.abs()>0).all())
        self.assertTrue((coeff.grad.abs().sum((1,2))>0).all())
        self.assertTrue(hasattr(output["projection"]["means2d"],"absgrad"))

    def test_real_parent_replacement_preserves_binding_and_adam(self):
        device="cuda" if torch.cuda.is_available() else "cpu"
        data={"reference":"a","local":{"a":{"mesh":np.array([[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]],np.float32)}},
              "geometry":SimpleNamespace(faces=torch.tensor([[0,1,2]])),"scale":1.}
        values={"means":[[.33,.33,0.]],"base_xyz":[[.33,.33,0.]],"scales":[[-2.,-2.,-3.]],
            "quats":[[1.,0.,0.,0.]],"opacities":[0.],"sh":np.zeros((1,4,3)),
            "part":[[1.]],"tri_id":[[0.]],"bary":[[.34,.33,.33]],"normal_offset":[[0.]],
            "support":[[5.]],"source_index":[[11.]],"family_id":[[7.]],"generation":[[0.]],"initial_scales":[[-2.,-2.,-3.]]}
        params=torch.nn.ParameterDict({key:torch.nn.Parameter(torch.as_tensor(value,dtype=torch.float32,device=device)) for key,value in values.items()})
        opts={key:torch.optim.Adam([value],lr=0.) for key,value in params.items()}
        sum(value.square().sum() for value in params.values()).backward()
        for optimizer in opts.values():optimizer.step();optimizer.zero_grad()
        strategy=ComponentStrategy(data,600)
        strategy.child_support=lambda child:torch.ones(len(child["means"]),dtype=torch.bool,device=device)
        state={"grad2d":torch.tensor([.02],device=device),"count":torch.tensor([5.],device=device),"radii":torch.tensor([.03],device=device),"scene_scale":1.,
            "native_radii":torch.tensor([20.],device=device),"residual_sum":torch.tensor([.25],device=device),"residual_count":torch.tensor([5.],device=device)}
        strategy._grow_gs(params,opts,state,240)
        self.assertEqual(len(params["means"]),2)
        self.assertEqual(params["source_index"][:,0].tolist(),[11.,11.])
        self.assertEqual(params["generation"][:,0].tolist(),[1.,1.])
        self.assertFalse(torch.any(torch.all(params["bary"]==torch.tensor([.34,.33,.33],device=device),dim=1)))
        self.assertTrue(torch.allclose(params["bary"].sum(1),torch.ones(2,device=device)))
        for key,optimizer in opts.items():
            parameter=optimizer.param_groups[0]["params"][0]
            self.assertIs(parameter,params[key])
            self.assertEqual(optimizer.state[parameter]["exp_avg"].shape,parameter.shape)


if __name__=="__main__":unittest.main()
