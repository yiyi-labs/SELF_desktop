"""CPU contracts for physical neck-only motion and exact covariance gradients."""
import unittest
import numpy as np
import torch
from portrait_model import GaussianState, evaluate_sh1
from live_neck_motion import build_neck_binding, joined_covariant


def fixture():
    dtype=torch.float64
    means=torch.tensor([[0.,-.1,2.],[.01,-.05,2.],[0.,0.,2.],[-.01,.05,2.],
                        [0.,.1,2.],[.2,.1,2.],[.4,0.,3.]],dtype=dtype)
    layers=np.array(['neck_skin']*5+['cloth','room'])
    C=torch.eye(4,dtype=dtype);F=torch.eye(4,dtype=dtype)
    # Nonidentity absolute head pose: relative reference must still be exact.
    F[:3,3]=torch.tensor([.05,.02,.5],dtype=dtype)
    binding=build_neck_binding(means,layers,C,F,2.)
    sh=torch.arange(7*4*3,dtype=dtype).reshape(7,4,3)/1000
    state=GaussianState(means,torch.tensor([[1.,0,0,0]],dtype=dtype).repeat(7,1),
        torch.tensor([[.006,.004,.002]],dtype=dtype).repeat(7,1),torch.ones(7,dtype=dtype)*.6,
        sh,torch.tensor([4,4,4,4,4,4,0]))
    return state,binding,C,F,layers


class NeckMotionTest(unittest.TestCase):
    def test_reference_is_exact_even_with_nonidentity_absolute_head(self):
        state,binding,C,F,_=fixture()
        self.assertIs(binding.deform(state,C,F),state)
        torch.testing.assert_close(binding.relative_head(C,F),torch.eye(4,dtype=C.dtype),atol=0,rtol=0)

    def test_cloth_room_alpha_and_bottom_neck_are_exactly_unchanged(self):
        state,binding,C,F,_=fixture();other=F.clone();other[0,3]+=.005
        result=binding.deform(state,C,other)
        self.assertGreater(float((result.means[:4]-state.means[:4]).abs().max()),0)
        for name in GaussianState.__dataclass_fields__:
            torch.testing.assert_close(getattr(result,name)[4:],getattr(state,name)[4:],atol=0,rtol=0)
        self.assertIs(result.opacity,state.opacity);self.assertIs(result.parts,state.parts)

    def test_full_jacobian_matches_finite_difference_of_reference_field(self):
        state,binding,C,F,_=fixture();other=F.clone();other[0,3]+=.005
        moved,J=binding.transforms(state,C,other)
        H=binding.relative_head(C,other);neck=2;point=state.means[neck]
        def mapping(p):
            cam=p@C[:3,:3].T+C[:3,3]
            y=cam[1]/cam[2];u=((y+.05)/.1).clamp(0,1);w=1-u*u*(3-2*u)
            return p+w*(p@H[:3,:3].T+H[:3,3]-p)
        numeric=torch.autograd.functional.jacobian(mapping,point)
        torch.testing.assert_close(J[neck],numeric,atol=1e-10,rtol=1e-10)
        torch.testing.assert_close(moved[neck],mapping(point),atol=1e-12,rtol=1e-12)

    def test_covariance_and_export_factors_match_full_transport(self):
        state,binding,C,F,_=fixture();other=F.clone();other[0,3]+=.005
        result=binding.deform(state,C,other);_,J=binding.transforms(state,C,other)
        expected=J@state.covariance()@J.transpose(-1,-2)
        torch.testing.assert_close(result.covariance(),expected,atol=1e-14,rtol=1e-10)
        # A vanilla state represents exactly the same numeric exported PLY.
        exported=GaussianState(**{k:getattr(result,k) for k in GaussianState.__dataclass_fields__})
        torch.testing.assert_close(exported.covariance(),expected,atol=1e-14,rtol=1e-10)

    def test_covariance_training_gradients_are_not_lost_in_eigen_factorization(self):
        state,binding,C,F,_=fixture();other=F.clone();other[0,3]+=.005
        state.quats=state.quats.clone().requires_grad_();state.scales=state.scales.clone().requires_grad_()
        result=binding.deform(state,C,other)
        weights=torch.arange(63,dtype=F.dtype).reshape(7,3,3)/63
        actual=torch.autograd.grad((result.covariance()*weights).sum(),(state.quats,state.scales),retain_graph=True)
        _,J=binding.transforms(state,C,other)
        truth=J@state.covariance()@J.transpose(-1,-2)
        expected=torch.autograd.grad((truth*weights).sum(),(state.quats,state.scales))
        for a,b in zip(actual,expected):
            self.assertTrue(torch.isfinite(a).all());self.assertGreater(float(a.abs().sum()),0)
            torch.testing.assert_close(a,b,atol=1e-12,rtol=1e-10)

    def test_absent_or_single_neck_does_not_create_geometry(self):
        state,_,C,F,layers=fixture();layers[:]='cloth'
        binding=build_neck_binding(state.means,layers,C,F,2.)
        other=F.clone();other[0,3]+=.05
        self.assertIs(binding.deform(state,C,other),state)
        layers[0]='neck_skin';binding=build_neck_binding(state.means,layers,C,F,2.)
        self.assertIs(binding.deform(state,C,other),state)
        self.assertFalse(binding.receipt()['geometryCreated'])

    def test_binding_checkpoint_restores_material_field_and_reference(self):
        state,binding,C,F,layers=fixture()
        other=build_neck_binding(state.means+torch.tensor([.01,0,0]),layers,C,F,2.)
        other.load_state_dict(binding.state_dict(),strict=True)
        shifted=F.clone();shifted[0,3]+=.005
        a=binding.deform(state,C,shifted);b=other.deform(state,C,shifted)
        for key in GaussianState.__dataclass_fields__:
            torch.testing.assert_close(getattr(a,key),getattr(b,key),atol=0,rtol=0)

    def test_sh_uses_same_polar_rotation_as_deformation(self):
        state,binding,C,F,_=fixture();other=F.clone();other[0,3]+=.005
        result=binding.deform(state,C,other);_,J=binding.transforms(state,C,other)
        U,_,Vh=torch.linalg.svd(J);R=U@Vh
        rays=torch.tensor([[.4,.2,1.]],dtype=F.dtype).repeat(len(state.means),1)
        moved=torch.einsum('nij,nj->ni',R,rays)
        torch.testing.assert_close(evaluate_sh1(result.sh,moved),evaluate_sh1(state.sh,rays),atol=1e-12,rtol=1e-10)

    def test_invalid_frames_and_topology_are_rejected(self):
        state,binding,C,F,layers=fixture()
        with self.assertRaisesRegex(ValueError,'neck_layer_count'):
            build_neck_binding(state.means,layers[:-1],C,F,2.)
        bad=C.clone();bad[0,0]=2
        with self.assertRaisesRegex(ValueError,'neck_nonrigid_transform'):
            build_neck_binding(state.means,layers,bad,F,2.)
        state.means=state.means[:-1]
        with self.assertRaisesRegex(ValueError,'neck_topology_changed'):binding.deform(state,C,F)

    def test_scene_join_preserves_exact_covariance_and_both_source_gradients(self):
        head,_,_,_,_=fixture();body,binding,C,F,_=fixture()
        head.scales=head.scales.clone().requires_grad_()
        body.quats=body.quats.clone().requires_grad_()
        other=F.clone();other[0,3]+=.005
        moved=binding.deform(body,C,other)
        joint=joined_covariant(head,moved)
        torch.testing.assert_close(joint.covariance(),torch.cat((head.covariance(),moved.covariance())),atol=0,rtol=0)
        weights=torch.arange(126,dtype=C.dtype).reshape(14,3,3)/126
        gradients=torch.autograd.grad((joint.covariance()*weights).sum(),(head.scales,body.quats))
        for gradient in gradients:
            self.assertTrue(torch.isfinite(gradient).all())
            self.assertGreater(float(gradient.abs().sum()),0)
        self.assertEqual(len(joint.means),14)


if __name__=='__main__':unittest.main()
