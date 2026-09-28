import tempfile,unittest
from pathlib import Path
import numpy as np
import torch
from reconstruction_components_v3 import FreeComponent,StageStatus,authorize_joint_training,export_identity
from reconstruction_portrait_model import GaussianState
from reconstruction_compose_v3 import classify_front_conflicts

class V3Contracts(unittest.TestCase):
    def test_front_support_unknown_and_world_evidence_are_all_required(self):
        result=classify_front_conflicts([4,4,4,4,1],[0,3,0,0,0],[0,0,1,0,0],[4,4,4,0,4])
        np.testing.assert_array_equal(result,[True,False,False,False,False])
    @unittest.skipUnless(torch.cuda.is_available(),'actual CUDA required')
    def test_off_center_gaussian_is_seen_in_actual_face_footprint(self):
        from reconstruction_compose_v3 import footprint_scores
        s=GaussianState(torch.tensor([[.12,0,1.]],device='cuda'),torch.tensor([[1.,0,0,0]],device='cuda'),
            torch.full((1,3),.07,device='cuda'),torch.tensor([.7],device='cuda'),torch.zeros(1,4,3,device='cuda'),torch.zeros(1,dtype=torch.long,device='cuda'))
        C=torch.eye(4,device='cuda');K=torch.tensor([[32.,0,16],[0,32,16],[0,0,1]],device='cuda')
        safe=torch.zeros(32,32,device='cuda',dtype=torch.bool);safe[14:18,14:18]=True
        center=(s.means@K.T)[0];self.assertFalse(bool(safe[round(float(center[1])),round(float(center[0]))]))
        scores,depth,unknown=footprint_scores(s,C,K,32,32,safe,torch.ones(32,32,device='cuda')*2,torch.zeros_like(safe))
        self.assertGreater(float(scores[0]),1.);self.assertAlmostEqual(float(depth[0]),2.,places=5)
        self.assertEqual(float(unknown[0]),0.)
    def test_partial_or_different_source_cannot_enter_joint(self):
        keys=('face','hair','accessory','neck_cloth','static_scene','world_camera')
        s={k:StageStatus('evidence',True,'same') for k in keys}
        self.assertTrue(authorize_joint_training(s,'same'))
        s['hair']=StageStatus('low_RGB_but_shell',False,'same')
        with self.assertRaisesRegex(ValueError,'hair'):authorize_joint_training(s,'same')
        s['hair']=StageStatus('other_video',True,'different')
        with self.assertRaises(ValueError):authorize_joint_training(s,'same')
    def test_component_has_actual_bounded_geometry_gradient(self):
        n=2
        state=GaussianState(torch.zeros(n,3),torch.tensor([[1.,0,0,0]]*n),torch.full((n,3),.002),torch.full((n,),.4),torch.zeros(n,4,3),torch.full((n,),2))
        block=FreeComponent(state,np.array([10,90]),np.array([3,4]),'head-local',.006)
        optimizer=torch.optim.Adam(block.parameters(),lr=.1)
        for _ in range(3):
            optimizer.zero_grad();loss=(block.state().means-.003).square().sum();loss.backward();optimizer.step()
        self.assertGreater(float(block.state().means.abs().sum().detach()),0)
        self.assertLess(float(block.state().means.abs().max().detach()),.006)
        np.testing.assert_array_equal(block.source_ids,[10,90])
    def test_misaligned_export_identity_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            ply=Path(d)/'a.ply';ply.write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError,'point_field_length'):
                export_identity(Path(d)/'a.npz',ply,{'point_id':np.arange(2),'component':np.array([1])},source_hash='x',reference='r',editable_count=1)
            with self.assertRaisesRegex(ValueError,'editable_prefix'):
                export_identity(Path(d)/'a.npz',ply,{'point_id':np.arange(2),'component':np.array([0,1])},source_hash='x',reference='r',editable_count=1)
if __name__=='__main__':unittest.main()
