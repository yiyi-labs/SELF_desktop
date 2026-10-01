import unittest,numpy as np,torch
from scipy.spatial.transform import Rotation
from reconstruction_room_surface_repair import surface_domain,projected_surface_domain,validate_mvs_roles
from reconstruction_surface_continuity import matrix_quaternion
from reconstruction_portrait_model import quaternion_matrix
class RoomSurfaceTests(unittest.TestCase):
    def test_finite_old_domain_is_not_an_infinite_plane(self):
        good,parent=surface_domain(np.array([[0,0,0],[.5,0,0],[4,0,0]]),np.zeros((1,3)),np.array([[1,0,0,0]]),np.ones((1,3)))
        self.assertEqual(good.tolist(),[True,True,False]);self.assertEqual(parent.tolist(),[0,0,0])
    def test_rotated_covariance_domain(self):
        q=Rotation.from_euler('z',90,degrees=True).as_quat()[[3,0,1,2]]
        good,_=surface_domain(np.array([[0,2,0],[2,0,0]]),np.zeros((1,3)),q[None],np.array([[1,.1,.1]]))
        self.assertEqual(good.tolist(),[True,False])
    def test_quaternion_chart_roundtrip_and_gradient(self):
        r=torch.tensor(Rotation.from_rotvec([[.1,.2,.3],[2.8,.1,0],[0,0,3.]]).as_matrix(),dtype=torch.float32,requires_grad=True)
        q=matrix_quaternion(r);torch.testing.assert_close(quaternion_matrix(q),r,rtol=1e-5,atol=1e-6)
        q.sum().backward();self.assertTrue(torch.isfinite(r.grad).all())
    def test_true_rear_surface_not_bounded_by_wrong_parent_depth(self):
        points=np.array([[0,0,8],[2,0,8],[100,0,8.]])
        parents=(np.array([[0,0,2.]]),np.array([[1,0,0,0.]]),np.array([[.2,.2,.01]]))
        names=['a','b','c'];cameras={n:np.eye(4) for n in names};K=np.diag([100.,100.,1.])
        domain,parent=projected_surface_domain(points,[[0,1,2]]*3,names,cameras,K,parents)
        self.assertEqual(domain.tolist(),[True,True,False]);self.assertEqual(parent.tolist(),[0,0,0])
        original,_=surface_domain(points,*parents);self.assertFalse(original.any())
    def test_unsupported_view_is_not_geometric_support(self):
        domain,_=projected_surface_domain(np.array([[0,0,8.]]),[[0,1]],['a','b','c'],{n:np.eye(4) for n in ['a','b','c']},np.diag([100.,100.,1.]),
            (np.array([[0,0,2.]]),np.array([[1,0,0,0.]]),np.ones((1,3))*.1))
        self.assertFalse(domain[0])
    def test_prepared_training_is_valid_but_development_never_proposal(self):
        data={'train':['real-train','dev'],'worlds':{'real-train':0,'dev':0},'local':{'real-train':{'role':'train'},'dev':{'role':'train'}}}
        plan={'train':[],'development':['dev'],'audit':[]}
        validate_mvs_roles(data,plan,['real-train'])
        with self.assertRaises(ValueError):validate_mvs_roles(data,plan,['dev'])
        data['worlds'].pop('real-train')
        with self.assertRaises(ValueError):validate_mvs_roles(data,plan,['real-train'])
if __name__=='__main__':unittest.main()
