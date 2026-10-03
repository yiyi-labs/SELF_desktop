import copy
from types import SimpleNamespace
import unittest
import tempfile
import numpy as np
from pathlib import Path
import torch
from flame_open_model import axis_angle_matrix
from reconstruction_portrait_model import GaussianState,evaluate_sh1
from reconstruction_live_hair_motion import (build_hair_motion,joint1_root_neutral_transform,
    transport_hair,legacy_hair_motion,write_motion_contract,verify_motion_receipt)


def fixture():
    dtype=torch.float64
    template=torch.tensor([[0.,-.1,0.],[0.,.04,0.],[.06,.12,.01],[-.05,.1,.02],[0.,.02,.05]],dtype=dtype)
    directions=torch.arange(5*3*4,dtype=dtype).reshape(5,3,4)*.00001
    model=SimpleNamespace(template=template,directions=directions,joint_regressor=torch.eye(5,dtype=dtype),
        parents=(-1,0,1,1,1),shape_count=2,expression_count=2,model_sha256='a'*64)
    pose=torch.tensor([[[.2,-.1,.3],[.03,-.08,.02],[.1,0.,0.],[0.,0.,0.],[0.,0.,0.]],
        [[-.1,.3,-.2],[.1,.04,-.03],[.04,0.,0.],[0.,0.,0.],[0.,0.,0.]],
        [[.2,.1,-.1],[-.05,.12,.07],[.2,0.,0.],[0.,0.,0.],[0.,0.,0.]]],dtype=dtype)
    state={'names':['left','reference','right'],'shape':torch.tensor([[.6,-.2]],dtype=dtype),
        'expression':torch.tensor([[.2,.4],[-.2,.1],[.6,-.4]],dtype=dtype),'pose':pose,
        'modelSha256':model.model_sha256,'sourceHash':'b'*64}
    return model,state


class HairMotionContracts(unittest.TestCase):
    def test_saved_inference_transport_survives_only_numerical_reduction_roundoff(self):
        model,fit=fixture();original=build_hair_motion(model,fit,'reference',checkpoint_sha256='c'*64)
        with tempfile.TemporaryDirectory() as tmp:
            record=write_motion_contract(original,tmp)
            rebuilt=build_hair_motion(model,fit,'reference',checkpoint_sha256='c'*64)
            rebuilt.transforms[0,0,3]+=1e-15
            rebuilt.metadata['transformSha256']='roundoff_recomputed_digest'
            verify_motion_receipt(record,rebuilt)
            self.assertTrue(torch.equal(rebuilt.transforms,original.transforms))
            self.assertEqual(rebuilt.metadata['transformSha256'],original.metadata['transformSha256'])
            rebuilt.transforms[0,0,3]+=.0001
            with self.assertRaises(AssertionError):verify_motion_receipt(record,rebuilt)

    def test_dense_camera_and_scene_share_exact_reference_transport(self):
        from reconstruction_live_dense import dense_camera
        from reconstruction_portrait_pipeline import SceneAssembly
        model,fit=fixture();binding=build_hair_motion(model,fit,'reference',checkpoint_sha256='c'*64)
        F=torch.eye(4,dtype=torch.float64);F[:3,:3]=axis_angle_matrix(torch.tensor([[.3,-.2,.1]],dtype=F.dtype))[0]
        F[:3,3]=torch.tensor([.01,-.02,.7],dtype=F.dtype)
        xyz=torch.tensor([[0.,.01,0.],[.03,.1,.02]],dtype=F.dtype)
        state=GaussianState(xyz,torch.tensor([[1.,0,0,0],[1.,0,0,0]],dtype=F.dtype),
            torch.ones(2,3,dtype=F.dtype)*.003,torch.ones(2,dtype=F.dtype)*.5,
            torch.zeros(2,4,3,dtype=F.dtype),torch.tensor([1,2]))
        scene=SimpleNamespace(portrait=SimpleNamespace(local_state=lambda mesh:state,surface_count=1),hair_motion=binding)
        moved=SceneAssembly.portrait_state(scene,{'name':'left','mesh':None})
        expected=dense_camera({'local':{'left':F.numpy()},'world':{}},'left','head-local',binding)
        camera=moved.means[1:]@F[:3,:3].T+F[:3,3]
        np.testing.assert_allclose(camera.numpy(),xyz[1:].numpy()@expected[:3,:3].T+expected[:3,3],atol=1e-12)
        self.assertTrue(torch.equal(moved.means[:1],xyz[:1]))
        self.assertIs(SceneAssembly.portrait_state(scene,{'name':'reference','mesh':None}),state)

    def test_recorded_motion_and_array_tamper_rejected(self):
        model,state=fixture();binding=build_hair_motion(model,state,'reference',checkpoint_sha256='c'*64)
        with tempfile.TemporaryDirectory() as tmp:
            record=write_motion_contract(binding,tmp);verify_motion_receipt(record,binding)
            with self.assertRaisesRegex(ValueError,'reinfer_required'):verify_motion_receipt(None,binding)
            other=build_hair_motion(model,state,'left',checkpoint_sha256='c'*64)
            with self.assertRaisesRegex(ValueError,'contract_mismatch'):verify_motion_receipt(record,other)
            (Path(tmp)/'hair-motion.npz').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'arrays_changed'):verify_motion_receipt(record,binding)

    def test_nonzero_shape_neck_reference_and_root_match_exact_joint_chain(self):
        model,state=fixture();binding=build_hair_motion(model,state,'reference',checkpoint_sha256='c'*64)
        beta=torch.cat((state['shape'],state['expression'][1:2]),1)
        shaped=model.template+torch.einsum('vci,bi->bvc',model.directions,beta)[0]
        J0,J1=shaped[0],shaped[1]
        G=joint1_root_neutral_transform(J1,state['pose'][:,1])
        marker=shaped[2];reference_marker=G[1,:3,:3]@marker+G[1,:3,3]
        for i,name in enumerate(state['names']):
            root=axis_angle_matrix(state['pose'][i:i+1,0])[0];neck=G[i,:3,:3]
            translation=torch.tensor([.02,-.03,.8],dtype=root.dtype)
            F=torch.eye(4,dtype=root.dtype);F[:3,:3]=root;F[:3,3]=translation+J0-root@J0
            actual=binding.camera(name,F)@torch.cat((reference_marker,torch.ones(1,dtype=root.dtype)))
            # Full FLAME parent chain for a marker with pure joint-1 weight.
            chain_rotation=root@neck;chain_origin=root@(J1-J0)+J0
            expected=chain_rotation@marker+chain_origin-chain_rotation@J1+translation
            torch.testing.assert_close(actual[:3],expected,atol=1e-12,rtol=0)
        self.assertTrue(torch.equal(binding.transforms[1],torch.eye(4,dtype=torch.float64)))

    def test_root_jaw_and_nonreference_expression_do_not_drag_hair(self):
        model,state=fixture();first=build_hair_motion(model,state,'reference',checkpoint_sha256='c'*64)
        changed=copy.deepcopy(state);changed['pose'][:,0]+=.4;changed['pose'][:,2:]+=.3
        changed['expression'][0]+=2;changed['expression'][2]-=2
        second=build_hair_motion(model,changed,'reference',checkpoint_sha256='d'*64)
        self.assertTrue(torch.equal(first.transforms,second.transforms))
        self.assertFalse(first.receipt()['perFrameExpressionApplied']);self.assertFalse(first.receipt()['jawApplied'])
        changed['shape']+=1
        third=build_hair_motion(model,changed,'reference',checkpoint_sha256='e'*64)
        self.assertGreater(float((first.transforms-third.transforms).abs().max()),0.)

    def test_hair_covariance_sh_gradients_and_skin_prefix_preserved(self):
        model,fit=fixture();binding=build_hair_motion(model,fit,'reference',checkpoint_sha256='c'*64)
        means=torch.tensor([[.1,.2,.3],[.3,.2,.1],[-.1,.3,.1]],dtype=torch.float64,requires_grad=True)
        scales=torch.tensor([[.01,.02,.03],[.02,.008,.003],[.007,.025,.004]],dtype=torch.float64,requires_grad=True)
        quats=torch.tensor([[1.,0.,0.,0.],[.9,.1,.2,.1],[.9,.1,-.2,.1]],dtype=torch.float64)
        sh=torch.arange(36,dtype=torch.float64).reshape(3,4,3)*.001;sh.requires_grad_()
        state=GaussianState(means,quats,scales,torch.tensor([.4,.5,.6],dtype=torch.float64),sh,torch.tensor([1,2,2]))
        moved=binding.deform('right',state,1);D=binding.matrix('right',means);R=D[:3,:3]
        for field in ('means','quats','scales','opacity','sh','parts'):
            self.assertTrue(torch.equal(getattr(moved,field)[:1],getattr(state,field)[:1]))
        torch.testing.assert_close(moved.covariance()[1:],R@state.covariance()[1:]@R.T,atol=1e-13,rtol=0)
        exported=GaussianState(moved.means,moved.quats,moved.scales,moved.opacity,moved.sh,moved.parts)
        torch.testing.assert_close(exported.covariance(),moved.covariance(),atol=1e-12,rtol=0)
        rays=torch.tensor([[.1,.2,.3],[-.3,.2,.1]],dtype=torch.float64)
        torch.testing.assert_close(evaluate_sh1(moved.sh[1:],rays@R.T),evaluate_sh1(state.sh[1:],rays),atol=1e-12,rtol=0)
        (moved.means.square().sum()+moved.covariance().square().sum()+moved.sh.square().sum()).backward()
        for value in (means,scales,sh):self.assertTrue(torch.isfinite(value.grad).all());self.assertGreater(float(value.grad.abs().sum()),0)
        self.assertIs(binding.deform('reference',state,1),state)

    def test_identity_and_legacy_are_explicit_and_bad_names_fail(self):
        model,state=fixture();binding=build_hair_motion(model,state,'reference',checkpoint_sha256='c'*64)
        with self.assertRaises(ValueError):binding.camera('missing',torch.eye(4))
        bad=copy.deepcopy(state);bad['names'][0]='reference'
        with self.assertRaises(ValueError):build_hair_motion(model,bad,'reference',checkpoint_sha256='c'*64)
        old=legacy_hair_motion(state['names'],'reference')
        self.assertEqual(old.receipt()['status'],'explicit_legacy_root_local');self.assertFalse(old.receipt()['motionCorrected'])
        self.assertTrue(binding.receipt()['newHairDepthInferenceRequired'])
        self.assertFalse(binding.receipt()['oldRootLocalDepthCacheCompatible'])


if __name__=='__main__':unittest.main()
