import unittest
import numpy as np
from reconstruction_surface_handoff import move_observation_points,plane_rays,plane_samples,finite_plane,observation_layers,select_room_transaction
from reconstruction_dense_contract import project

class SurfaceHandoffTest(unittest.TestCase):
    def test_body_motion_matches_camera_projection(self):
        C=np.eye(4);K=np.array([[100.,0,50],[0,100,50],[0,0,1]])
        B=np.eye(4);B[0,3]=.2;points=np.array([[0.,0.,2.],[.3,.1,3.]])
        moved=move_observation_points(points,'a','b',{'a':C,'b':B})
        uv,z=project(moved,K,C)
        np.testing.assert_allclose(uv,[[60,50],[100*.5/3+50,100*.1/3+50]])
        np.testing.assert_array_equal(move_observation_points(points,'a','a',{'a':B}),points)
        np.testing.assert_allclose(move_observation_points(moved,'b','a',{'a':C,'b':B}),points)
    def test_missing_motion_is_unknown(self):
        with self.assertRaisesRegex(ValueError,'missing_observed'):
            move_observation_points(np.ones((1,3)),'a','b',{'a':np.eye(4)})
    def test_motion_world_unit_invariance(self):
        p=np.array([[.1,.4,2.]]);B=np.eye(4);B[:3,3]=[.2,-.1,.05]
        a=move_observation_points(p,'a','b',{'a':np.eye(4),'b':B})
        scaled=B.copy();scaled[:3,3]*=7
        b=move_observation_points(p*7,'a','b',{'a':np.eye(4),'b':scaled})
        np.testing.assert_allclose(a*7,b)
    def test_plane_is_3d_surface_not_screen_paste(self):
        K=np.array([[100.,0,50],[0,120,40],[0,0,1.]])
        C=np.eye(4);C[0,3]=.1;u=np.array([[10.,20],[50,40],[80,60]])
        n=np.array([.3,0,1.]);n/=np.linalg.norm(n);centre=np.array([0.,0,2.])
        p,z=plane_rays(u,K,C,centre,n)
        np.testing.assert_allclose((p-centre)@n,0,atol=1e-12)
        np.testing.assert_allclose(project(p,K,C)[0],u,atol=1e-10)
        _,basis,scales,valid=plane_samples(u,K,C,centre,n)
        self.assertTrue(valid.all());np.testing.assert_allclose(np.linalg.det(basis),1,atol=1e-12)
        self.assertTrue((scales[:,2]<scales[:,:2].min(1)).all())
    def test_nonplanar_and_line_support_rejected(self):
        x,y=np.mgrid[-1:1:15j,-1:1:15j]
        p=np.c_[x.ravel(),y.ravel(),(2+x*x+y*y).ravel()]
        self.assertIsNone(finite_plane(p,p[:,2]))
        line=np.c_[np.linspace(0,1,100),np.zeros(100),np.full(100,2)]
        self.assertIsNone(finite_plane(line,line[:,2]))
    def test_finite_planar_domain_preserves_samples(self):
        x,y=np.mgrid[-1:1:15j,-1:1:15j];p=np.c_[x.ravel(),y.ravel(),np.full(x.size,2)]
        centre,n,active=finite_plane(p,p[:,2]);self.assertTrue(active.all())
        np.testing.assert_allclose((p-centre)@n,0,atol=1e-12)

    def test_unknown_motion_omits_depth_without_omitting_rgb(self):
        self.assertEqual(observation_layers('a',['a'],None,False),['room'])
        self.assertEqual(observation_layers('a',['a'],{'a':np.eye(4)},False),['room'])
        self.assertEqual(observation_layers('a',['a'],{'a':np.eye(4)},True),['room','cloth'])
        self.assertEqual(observation_layers('b',['b'],{'a':np.eye(4)},True),['room'])
        with self.assertRaisesRegex(ValueError,'verified_motion_missing'):observation_layers('a',['a'],None,True)
    def test_projection_support_can_replace_wrong_depth_not_human(self):
        import torch
        from reconstruction_portrait_model import GaussianState
        state=GaussianState(torch.tensor([[0.,0.,2.]]),torch.tensor([[1.,0.,0.,0.]]),torch.tensor([[.05,.05,.01]]),
            torch.tensor([.5]),torch.zeros(1,4,3),torch.tensor([0]))
        x,y=np.mgrid[-.1:.1:20j,-.1:.1:20j]
        pool=dict(means=np.c_[x.ravel(),y.ravel(),np.full(x.size,4)],scales=np.full((x.size,3),.01),uid=np.arange(x.size))
        K=np.array([[100.,0,50],[0,100,50],[0,0,1]])
        evidence=dict(imageName='a',C=np.eye(4),K=K,room=np.ones((100,100),bool),gaussian_ids=np.array([0]),means2d=np.array([[50.,50.]]),conics=np.array([[.01,0,.01]]))
        with self.assertRaisesRegex(ValueError,'no_bounded'):select_room_transaction(state,pool)
        ids,a,r=select_room_transaction(state,pool,projection_evidence=[evidence,dict(evidence,imageName='b')],contribution=np.array([.02]),budget=500)
        np.testing.assert_array_equal(ids,[0]);self.assertEqual(len(a['means']),400)
        with self.assertRaisesRegex(ValueError,'duplicate_projection'):select_room_transaction(state,pool,projection_evidence=[evidence,evidence],contribution=np.array([.02]),budget=500)
        with self.assertRaisesRegex(ValueError,'no_bounded'):select_room_transaction(state,pool,projection_evidence=[evidence],contribution=np.array([.02]),budget=500)
        with self.assertRaisesRegex(ValueError,'no_bounded'):select_room_transaction(state,pool,projection_evidence=[evidence,dict(evidence,imageName='b')],contribution=np.array([.02]),budget=200)
        state.parts[:]=1
        with self.assertRaisesRegex(ValueError,'no_bounded'):select_room_transaction(state,pool,projection_evidence=[evidence,dict(evidence,imageName='b')],contribution=np.array([.02]),budget=500)
if __name__=='__main__':unittest.main()
