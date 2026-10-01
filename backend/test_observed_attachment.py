import unittest,numpy as np
from reconstruction_observed_attachment import rebind_hair,contact_pairs,exterior_patch
class AttachmentContract(unittest.TestCase):
    def observations(self):
        K=np.array([[100.,0,20],[0,100.,20],[0,0,1]])
        return [dict(role='train',K=K,F=np.eye(4),hair=np.ones((40,40),bool)) for _ in range(3)]
    def surface(self):
        return dict(means=np.array([[0.,0.,2.]]),support=np.array([3]))
    def test_bounded_hair_proposal(self):
        ids,ix,report=rebind_hair(np.array([[.02,0,2.],[2.,0,2.]]),self.observations(),self.surface())
        np.testing.assert_array_equal(ids,[0]);np.testing.assert_array_equal(ix,[0])
        self.assertFalse(report['independentDepthTruth'])
    def test_observation_boundary_not_clamped(self):
        obs=self.observations()
        for o in obs:o['hair'][:]=False
        ids,_,_=rebind_hair(np.array([[0.,0,2.]]),obs,self.surface())
        self.assertEqual(len(ids),0)
    def test_unknown_insufficient_views_kept(self):
        obs=self.observations();obs[0]['hair'][:]=False
        ids,_,_=rebind_hair(np.array([[0.,0,2.]]),obs,self.surface())
        self.assertEqual(len(ids),0)
    def test_dev_data_rejected(self):
        obs=self.observations();obs[0]['role']='development'
        with self.assertRaises(ValueError):rebind_hair(np.array([[0.,0,2.]]),obs,self.surface())
    def test_neck_contacts_limited_to_same_skin_top(self):
        neck=np.array([[0,0,0],[0,1,0],[0,2,0],[0,3,0.]])
        head=np.array([[0,0,.01],[0,3,.01]])
        i,j=contact_pairs(neck,head,.01,neck[:,1])
        np.testing.assert_array_equal(i,[0]);np.testing.assert_array_equal(j,[0])
    def test_distant_contact_not_forced(self):
        i,_=contact_pairs(np.array([[0.,0,0]]),np.array([[1.,0,0]]),.01,np.array([0.]))
        self.assertEqual(len(i),0)
class ExteriorPatchContract(unittest.TestCase):
    observations=AttachmentContract.observations
    def test_patch_uses_unique_real_indices_and_lineage(self):
        a=dict(means=np.array([[0.,0.,2.],[.01,0,2.],[.03,0,2.],[2.,0,2.]]),support=np.array([3,3,3,3]))
        i,parent,report=exterior_patch(np.array([[0.,0.,2.],[.02,0,2.]]),self.observations(),a,[0,1],[0,1],neighbors=4)
        self.assertEqual(set(i),{0,1,2});self.assertEqual(len(i),len(set(i)))
        self.assertTrue(set(parent)<=set([0,1]));self.assertFalse(report['independentDepthTruth'])
    def test_patch_cannot_use_unknown_or_nontraining_colour(self):
        a=dict(means=np.array([[0.,0.,2.],[.01,0,2.]]),support=np.array([3,2]))
        i,_,_=exterior_patch(np.array([[0.,0.,2.]]),self.observations(),a,[0],[0],neighbors=2)
        np.testing.assert_array_equal(i,[0])
        o=self.observations();o[1]['role']='development'
        with self.assertRaises(ValueError):exterior_patch(a['means'],o,a,[0],[0])
    def test_budget_does_not_remove_first_proposals(self):
        a=dict(means=np.array([[0.,0.,2.],[.1,0,2.],[.01,0,2.],[.11,0,2.]]),support=np.full(4,3))
        i,_,_=exterior_patch(a['means'][:2],self.observations(),a,[0,1],[0,1],neighbors=4,maximum_points=2)
        self.assertEqual(set(i),{0,1})
        with self.assertRaises(ValueError):exterior_patch(a['means'],self.observations(),a,[0,1],[0,1],maximum_points=1)
if __name__=='__main__':unittest.main()