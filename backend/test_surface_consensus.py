import unittest
import numpy as np
from reconstruction_surface_consensus import contract_compatible,consensus_status,representative_samples,covered_retirement

class SurfaceConsensusTests(unittest.TestCase):
    def test_different_checkpoint_cannot_merge(self):
        a=dict(sourceHash='s',cameraFrame='head-local',restoredCompleteCheckpointHash='a',fullK=np.eye(3).tolist(),names=[],contract=dict(cameras={}))
        with self.assertRaisesRegex(ValueError,'CheckpointHash'):contract_compatible(a,dict(a,restoredCompleteCheckpointHash='b'))
    def test_overlap_agreement_conflict_unknown_are_distinct(self):
        x=np.array([[0,0,0],[.001,0,0],[1,0,0],[1.001,0,0],[8,0,0.]])
        n=np.array([[0,0,1],[0,0,-1],[0,0,1],[1,0,0],[0,0,1.]])
        s=consensus_status(x,n,np.full(5,.001),[0,1,0,1,0])
        np.testing.assert_array_equal(s['agreement'][:2],[1,1]);np.testing.assert_array_equal(s['conflict'][2:4],[1,1]);self.assertTrue(s['unknown'][4])
    def test_representatives_keep_original_geometry_and_source(self):
        x=np.array([[0,0,1],[0,0,1.0001],[.02,0,1.]])
        n=np.tile([0,0,1.],(3,1));keep,info=representative_samples(x,n,np.full(3,.01),[1,2,1],np.array([10,20,30]),budget=10)
        self.assertIn(1,keep);self.assertNotIn(0,keep);self.assertFalse(info['positionsAveraged'])
    def test_one_uncovered_observation_blocks_retirement(self):
        total=np.full((4,2),10.);covered=total.copy();covered[3,0]=8
        ok,frac=covered_retirement(total,covered)
        np.testing.assert_array_equal(ok,[False,True]);self.assertAlmostEqual(frac[3,0],.8)
    def test_unknown_noncontributing_view_does_not_refute(self):
        total=np.array([[10.],[10.],[10.],[0.]]);covered=total.copy()
        self.assertTrue(covered_retirement(total,covered)[0][0])
    def test_invalid_contribution_cannot_pass(self):
        with self.assertRaises(ValueError):covered_retirement([[1.]],[[2.]])

if __name__=='__main__':unittest.main()