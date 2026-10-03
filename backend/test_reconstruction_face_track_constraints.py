import unittest
import numpy as np
from reconstruction_face_pose_reliability import project
from reconstruction_face_track_constraints import texture_pose_candidate,shared_surface_candidate,triangle_basis,unique_physical_tracks


class TrackConstraints(unittest.TestCase):
    def test_descriptor_orientations_are_not_independent_physical_tracks(self):
        rows=[{'sourceKeypoint':i,'measured':(np.ones((3,2))*delta).tolist()} for i,delta in [(4,0),(2,0),(8,1)]]
        kept,duplicates=unique_physical_tracks(rows)
        self.assertEqual([r['sourceKeypoint'] for r in kept],[2,8])
        self.assertEqual(duplicates,[{'sourceKeypoint':4,'representativeSourceKeypoint':2}])

    def setup_scene(self):
        K=np.array([[1100.,0,540],[0,1100,960],[0,0,1]])
        F=np.eye(4);F[2,3]=.55
        return K,F

    def test_pose_reserved_tracks_not_fit_and_reference_immutable(self):
        K,F=self.setup_scene();x,y=np.meshgrid(np.linspace(-.05,.05,7),np.linspace(-.07,.07,7))
        p=np.stack([x.ravel(),y.ravel(),.007*np.sin(x.ravel()*60)],axis=1)
        true=F.copy();true[0,3]+=.0005;u=project(p,true,K)[0]
        fit=np.arange(len(p))%3!=0
        a,ra=texture_pose_candidate(p,u,F,K,fit)
        corrupted=u.copy();corrupted[~fit]+=55
        b,rb=texture_pose_candidate(p,corrupted,F,K,fit)
        np.testing.assert_array_equal(a,b)
        # Finite pose regularization intentionally prevents an exact fit.
        self.assertLess(np.median(np.asarray(ra['newErrors'])[~fit]),
            .2*np.median(np.asarray(ra['oldErrors'])[~fit]))
        c,_=texture_pose_candidate(p,u,F,K,fit,fixed=True);np.testing.assert_array_equal(c,F)

    def test_surface_third_is_not_used_and_offset_is_shared(self):
        K,F=self.setup_scene();Fs=np.stack([F.copy() for _ in range(3)])
        Fs[1,0,3]=.03;Fs[2,0,3]=-.04
        p=np.repeat([[.01,.01,.005]],3,0);bases=np.repeat(np.eye(3)[None],3,0)
        true=p+np.array([.0005,.0002,.0006]);uv=np.stack([project(v[None],f,K)[0][0] for v,f in zip(true,Fs)])
        a,ra=shared_surface_candidate(p,bases,uv,Fs,K,.2)
        changed=uv.copy();changed[2]+=20;b,rb=shared_surface_candidate(p,bases,changed,Fs,K,.2)
        np.testing.assert_array_equal(a,b);np.testing.assert_allclose(a-p,np.repeat((a[0]-p[0])[None],3,0))
        self.assertLess(ra['newErrors'][2],ra['oldErrors'][2])
        self.assertLessEqual(np.linalg.norm(ra['offsetModelUnits']),ra['boundModelUnits']+1e-12)

    def test_degenerate_camera_does_not_gain_depth_from_prior(self):
        K,F=self.setup_scene();Fs=np.repeat(F[None],3,0)
        p=np.repeat([[0.,0.,.0]],3,0);uv=np.stack([project(v[None],f,K)[0][0] for v,f in zip(p,Fs)])
        uv[1,0]+=.5
        new,r=shared_surface_candidate(p,np.repeat(np.eye(3)[None],3,0),uv,Fs,K,.2)
        self.assertEqual(r['observableModes'],2)
        self.assertAlmostEqual(new[0,2],0.)

    def test_triangle_basis_is_orthonormal(self):
        b=triangle_basis(np.array([[0,0,0],[1,1,0],[0,1,2.]]))
        np.testing.assert_allclose(b.T@b,np.eye(3),atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(b),1.)


if __name__=='__main__':unittest.main()
