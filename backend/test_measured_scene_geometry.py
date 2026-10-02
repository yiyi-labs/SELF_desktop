import unittest
import numpy as np
from run_static_depth_calibration import fit_inverse_depth
from run_measured_body_handoff import solve_body_tracks,dedup_measured,geometry_training_pool
from reconstruction_dense_contract import project
from reconstruction_motion_geometry import motion_matrices
from run_locked_body_tracks import coordinate_scale,spatial_seeds,online_chunk


class MeasuredSceneGeometryTest(unittest.TestCase):
    def test_grouped_inverse_depth_calibration_recovers_shared_sensor_bias(self):
        z=np.linspace(2.,8.,300);unit=np.median(1/z);scale=1.13;shift=-.08
        predicted=scale/(1/z-shift*unit);ids=np.arange(len(z))
        # A point observed twice must belong to the same held-out group.
        r=fit_inverse_depth(np.repeat(predicted,2),np.repeat(z,2),np.repeat(ids,2))
        self.assertTrue(r['accepted']);self.assertLess(r['heldoutP90After'],.002)
        self.assertAlmostEqual(r['scale'],scale,places=2)
        self.assertLess(r['heldoutUniquePoints'],r['uniquePoints'])
        self.assertEqual(r['perFrameScales'],0);self.assertEqual(r['cameraChanges'],0)
    def test_bad_or_missing_depth_cannot_enable_transport(self):
        self.assertFalse(fit_inverse_depth(np.ones(20),np.ones(20),np.arange(20))['accepted'])
        self.assertFalse(fit_inverse_depth(np.full(300,np.nan),np.ones(300),np.arange(300))['accepted'])
        rng=np.random.default_rng(2)
        self.assertFalse(fit_inverse_depth(rng.uniform(1,10,300),rng.uniform(1,10,300),np.arange(300))['accepted'])
        with self.assertRaisesRegex(ValueError,'identity'):fit_inverse_depth(np.ones(100),np.ones(99),np.arange(100))
    def test_tracker_coordinate_contract_round_trip(self):
        p=np.array([[0.,0.],[1079.,1919.],[437.3,901.2]])
        network=coordinate_scale(p,[1080,1920],[512,384])
        np.testing.assert_allclose(coordinate_scale(network,[512,384],[1080,1920]),p,atol=1e-12)
        np.testing.assert_allclose(network[1],[511,383],atol=1e-12)
    def test_short_tracker_chunk_executes_updates_and_resets_both_directions(self):
        import torch
        class LockedOnlineContract:
            window_len=16
            def __init__(self):self.resets=0;self.calls=[]
            def init_video_online_processing(self):self.resets+=1
            def __call__(self,video,queries,*,iters,is_online):
                self.calls.append((iters,is_online,video.shape[1]))
                shape=(1,video.shape[1],queries.shape[1])
                return torch.ones((*shape,2)),torch.ones(shape),torch.ones(shape),None
        model=LockedOnlineContract();video=torch.zeros(1,7,3,64,64);queries=torch.zeros(1,8,3)
        online_chunk(model,video,queries);online_chunk(model,video.flip(1),queries)
        self.assertEqual(model.resets,2);self.assertEqual(model.calls,[(6,True,7)]*2)
        with self.assertRaisesRegex(ValueError,'length'):online_chunk(model,torch.zeros(1,17,3,64,64),queries)
    def test_body_motion_solve_preserves_world_cameras_and_reference(self):
        rng=np.random.default_rng(32);names=[str(i) for i in range(6)];times={n:float(i) for i,n in enumerate(names)}
        K=np.array([[900.,0,540],[0,900,960],[0,0,1.]])
        C={n:np.eye(4) for n in names}
        for i,n in enumerate(names):C[n][:3,3]=[.3*np.sin(.6*i),.18*np.cos(.9*i),.15*np.sin(1.1*i)]
        points=np.c_[rng.uniform(-.6,.6,64),rng.uniform(-.6,.6,64),rng.uniform(3.,4.,64)]
        pivot=np.median(points,0);B=motion_matrices(names,times,'2',np.array([.1,-.2,.1,.4,0,.1]),pivot,1.,max_rotation=4.,max_translation=.025)
        tracks=[];initial={}
        for i,p in enumerate(points):
            key='test:'+str(i);tracks.append(dict(id=key,region='upper_left' if i%2 else 'lower_right',observations=[dict(name=n,uv=project(p[None],K,C[n]@B[n])[0][0].tolist(),sigma=.5) for n in names]));initial[key]=p
        frozen={n:c.copy() for n,c in C.items()};r=solve_body_tracks(tracks,C,K,times,'2',1.,initial,max_nfev=80)
        self.assertEqual(r['count'],64);self.assertFalse(r['initialStaticErrorUsedForAdmission'])
        self.assertLess(r['withheldThirdP90'],.25);self.assertTrue(r['motionAccepted'])
        np.testing.assert_allclose(r['B']['2'],np.eye(4),atol=1e-12)
        for n in names:np.testing.assert_array_equal(C[n],frozen[n])
    def test_small_reprojection_error_does_not_prove_motion_depth_observable(self):
        rng=np.random.default_rng(32);names=[str(i) for i in range(6)];times={n:float(i) for i,n in enumerate(names)}
        K=np.array([[900.,0,540],[0,900,960],[0,0,1.]])
        C={n:np.eye(4) for n in names}
        for i,n in enumerate(names):C[n][0,3]=-.12*i
        points=np.c_[rng.uniform(-.6,.6,64),rng.uniform(-.6,.6,64),rng.uniform(3.,4.,64)]
        tracks=[];initial={}
        for i,p in enumerate(points):
            key='test:'+str(i);tracks.append(dict(id=key,region='upper_left' if i%2 else 'lower_right',observations=[dict(name=n,uv=project(p[None],K,C[n])[0][0].tolist(),sigma=.5) for n in names]));initial[key]=p
        r=solve_body_tracks(tracks,C,K,times,'2',1.,initial)
        self.assertLess(r['withheldThirdP90'],.01);self.assertFalse(r['motionDataObservable']);self.assertFalse(r['motionAccepted'])

    def test_temporal_knots_keep_reference_and_cameras_without_free_frame_scale(self):
        rng=np.random.default_rng(43);names=[str(i) for i in range(7)];times={n:float(i) for i,n in enumerate(names)}
        K=np.array([[900.,0,540],[0,900,960],[0,0,1.]])
        C={n:np.eye(4) for n in names}
        for i,n in enumerate(names):C[n][:3,3]=[.4*np.sin(.7*i),.2*np.cos(.9*i),.18*np.sin(1.2*i)]
        points=np.c_[rng.uniform(-.6,.6,48),rng.uniform(-.6,.6,48),rng.uniform(3.,4.,48)]
        tracks=[];initial={}
        for i,p in enumerate(points):
            key='knots:'+str(i);tracks.append(dict(id=key,region='upper_left' if i%2 else 'lower_right',observations=[dict(name=n,uv=project(p[None],K,C[n])[0][0].tolist(),sigma=.5) for n in names]));initial[key]=p
        frozen={n:c.copy() for n,c in C.items()};r=solve_body_tracks(tracks,C,K,times,'3',1.,initial,motion_basis='temporal-knots')
        np.testing.assert_allclose(r['B']['3'],np.eye(4),atol=1e-12)
        self.assertEqual(len(r['velocity']),18);self.assertLess(r['withheldThirdP90'],.01)
        for n in names:
            np.testing.assert_array_equal(C[n],frozen[n]);T=np.asarray(r['B'][n]);self.assertAlmostEqual(np.linalg.det(T[:3,:3]),1.,places=9)
        # Exact reprojection is a diagnostic; admission still requires data-only
        # motion observability rather than priors or a perfect synthetic image.
        if not r['motionDataObservable']:self.assertFalse(r['motionAccepted'])
    def test_auxiliary_geometry_training_does_not_consume_any_holdout(self):
        raw=dict(names=np.array(['a','b','c','d','e','f']),roles=np.array(['train','train','train','development','train','audit']))
        plan=dict(train=['a'],development=['c'],audit=['e'])
        self.assertEqual(geometry_training_pool(raw,plan,{'a','b','c','d','e','f','unknown'}),{'a','b'})
    def test_unknown_or_zero_time_cannot_produce_body_transform(self):
        with self.assertRaisesRegex(ValueError,'timestamps'):solve_body_tracks([],{'x':np.eye(4)},np.eye(3),{'x':0.},'x',1.,{})
        r=solve_body_tracks([],{'x':np.eye(4),'y':np.eye(4)},np.eye(3),{'x':0.,'y':1.},'x',1.,{})
        self.assertFalse(r['motionAccepted']);self.assertNotIn('B',r)
    def test_physical_track_dedup_retains_one_identity(self):
        a=dict(id='a',observations=[dict(name=str(i),uv=[10.,20.]) for i in range(4)])
        b=dict(id='b',observations=[dict(name=str(i),uv=[10.2,20.1]) for i in range(4)])
        kept,duplicates=dedup_measured([a,b]);self.assertEqual(len(kept),1);self.assertEqual(duplicates,[dict(id='b',sameAs='a')])
if __name__=='__main__':unittest.main()