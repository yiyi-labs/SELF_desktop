import unittest
import json
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
import numpy as np
from reconstruction_live_dense import (selected_names, windows, native_uv,
    physical_masks, surface_samples, support_samples, overlap_check,
    select_budget, choose_reference, validate_request, continuous_world_windows,plan_dense_windows,training_name_scopes,
    verify_tool_source_lock,CODE_COMMIT,static_track_names,validate_world_observation_sources)
from reconstruction_live_dense_contract import resized_camera, project, digest
from reconstruction_live_depth_scale import fit_window_scale


class DenseLiveContract(unittest.TestCase):
    def test_source_lock_checks_version_bytes_and_unlisted_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo='Depth-Anything-3-'+CODE_COMMIT
            file=root/'source'/repo/'src/model.py';file.parent.mkdir(parents=True);file.write_text('fixed source')
            name=file.relative_to(root/'source').as_posix()
            lock=root/'source-lock.json';lock.write_text(json.dumps(dict(codeCommit=CODE_COMMIT,files={name:digest(file)})))
            self.assertEqual(verify_tool_source_lock(root)['verifiedFiles'],1)
            file.write_text('changed')
            with self.assertRaisesRegex(ValueError,'source_changed'):verify_tool_source_lock(root)
            file.write_text('fixed source');other=file.with_name('shadow.py');other.write_text('extra import')
            with self.assertRaisesRegex(ValueError,'unlocked_python'):verify_tool_source_lock(root)
            lock.write_text(json.dumps(dict(codeCommit='wrong',files={name:digest(file)})))
            with self.assertRaisesRegex(ValueError,'source_version'):verify_tool_source_lock(root)

    def test_source_lock_rejects_empty_or_escape_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lock=root/'source-lock.json'
            self.assertIsNone(verify_tool_source_lock(root))
            lock.write_text(json.dumps(dict(codeCommit=CODE_COMMIT,files={})))
            with self.assertRaisesRegex(ValueError,'lock_empty'):verify_tool_source_lock(root)
            lock.write_text(json.dumps(dict(codeCommit=CODE_COMMIT,files={'../outside.py':'123'})))
            with self.assertRaisesRegex(ValueError,'source_path_invalid'):verify_tool_source_lock(root)

    def test_registered_images_without_map_tracks_are_not_fabricated_or_dropped(self):
        C=np.eye(4);names=['map','pnp','unregistered']
        image=SimpleNamespace(has_pose=True,cam_from_world=lambda:SimpleNamespace(matrix=lambda:C[:3]))
        lookup=dict(map=image,unregistered=SimpleNamespace(has_pose=False))
        world={n:C.copy() for n in names}
        self.assertEqual(static_track_names(names,lookup,world),['map'])
        self.assertEqual(list(world),names)
        world['map'][0,3]=1
        with self.assertRaises(AssertionError):static_track_names(names,lookup,world)

    def test_added_world_camera_requires_accepted_fixed_map_evidence(self):
        C=np.eye(4);extra=C.copy();extra[0,3]=.2
        image=SimpleNamespace(name='map',has_pose=True,cam_from_world=lambda:SimpleNamespace(matrix=lambda:C[:3]))
        model=SimpleNamespace(images={1:image});world={'map':C,'pnp':extra}
        quality=dict(count=40,positiveDepthFraction=1.,medianPx=.5,p90Px=1.,gridCells4x4=8,imageHullFraction=.1)
        with tempfile.TemporaryDirectory() as tmp,patch('pycolmap.Reconstruction',return_value=model),patch('reconstruction_capture_registration.immutable_map_hash',return_value='same-map'):
            p=Path(tmp);meta=dict(staticMap=str(p/'map'),sourceHash='capture')
            with self.assertRaisesRegex(ValueError,'evidence_missing'):validate_world_observation_sources(p,meta,world)
            root=p/'short-window-registration';root.mkdir();fit=np.arange(40);held=np.arange(40,50)
            row=dict(name='pnp',status='accepted_fixed_map_localization',fit=quality,held={**quality,'count':10},inliers=35,fitPoint3DIDs=fit.tolist(),heldPoint3DIDs=held.tolist())
            report=dict(sourceSha256='capture',fixedMapUnchanged=True,mapBeforeSha256='same-map',mapAfterSha256='same-map',cameraRefinement=False,mapBundleAdjustment=False,accepted=['pnp'],queries=[row])
            (root/'report.json').write_text(json.dumps(report));np.savez(root/'world-additions.npz',names=['pnp'],C=extra[None])
            np.savez(root/'pnp.correspondences.npz',point3D_ids=np.r_[fit,held],fit=np.arange(50)<40,held=np.arange(50)>=40,pose=extra,accepted=True)
            self.assertEqual(validate_world_observation_sources(p,meta,world)['localizedImageNames'],['pnp'])
            world['pnp']=C
            with self.assertRaises(AssertionError):validate_world_observation_sources(p,meta,world)
            world['pnp']=extra;report['fixedMapUnchanged']=False;(root/'report.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'map_changed'):validate_world_observation_sources(p,meta,world)

    def fixture(self):
        K=np.array([[20.,0,10],[0,20.,10],[0,0,1]])
        depth=np.ones((21,21),np.float32)*2
        return dict(depth=depth,confidence=np.ones_like(depth),K=K,W2C=np.eye(4),nativeToProcessed=np.eye(3))

    def test_reference_preserved_and_missing_rejected(self):
        names=list('abcdefghijkl')
        self.assertIn('f',selected_names(names,4,'f'))
        self.assertEqual(selected_names(names,4,'f'),sorted(selected_names(names,4,'f')))
        with self.assertRaises(ValueError):selected_names(names,4,'z')

    def test_reference_body_window_never_uses_far_frames(self):
        names=list('abcdef');times={n:i for i,n in enumerate(names)}
        value=windows(names,8,'c',times,body=True)
        self.assertEqual(value,[['b','c','d']])
        self.assertEqual(windows(['a','f'],8,'a',times,body=True),[])

    def test_live_no_split_preserves_near_time_body_and_native_validation_boundary(self):
        names=[f'n{i}' for i in range(20)]
        data=dict(train=names,forbidden=['n8','n12'],world={n:np.eye(4) for n in names},
            frameRows={n:dict(timestampSeconds=i*.4) for i,n in enumerate(names)})
        before=list(data['train']);plan=plan_dense_windows(data,'n10',max_views=4)
        body=plan['windows']['body-world'][0]
        self.assertIn('n10',body);self.assertIn('n9',body);self.assertIn('n11',body)
        self.assertNotIn('n8',plan['names']);self.assertNotIn('n12',plan['names'])
        self.assertEqual(before,data['train'])
        self.assertGreater(len(body),len(set(body)&set(plan['windows']['head-local'][0])))

    def test_study_split_narrows_head_but_keeps_declared_train_body_neighbours(self):
        names=[f'n{i}' for i in range(20)]
        data=dict(train=names,forbidden=['n12'],world={n:np.eye(4) for n in names},
            frameRows={n:dict(timestampSeconds=i*.4) for i,n in enumerate(names)})
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'split.json';p.write_text(json.dumps(dict(train=['n0','n5','n10','n15','n19'],development=['n8'],audit=[])))
            plan=plan_dense_windows(data,'n10',max_views=8,split=p)
            self.assertIn('n9',plan['windows']['body-world'][0])
            self.assertNotIn('n9',plan['windows']['head-local'][0])
            self.assertNotIn('n8',plan['names']);self.assertNotIn('n12',plan['names'])
            old=digest(p);p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'split_changed'):training_name_scopes(data,p,expected_split_hash=old)

    def test_static_windows_use_continuous_real_cameras_not_sparse_colour_train(self):
        names=[str(i) for i in range(20)];times={n:int(n)*.4+(10 if int(n)>=10 else 0) for n in names}
        cameras={n:np.eye(4) for n in names}
        for n in names:cameras[n][0,3]=int(n)*.02
        value=continuous_world_windows(names,6,'13',times,cameras,18)
        self.assertIn('13',value[0]);self.assertLessEqual(len(value),3)
        for window in value:self.assertTrue(all(times[b]-times[a]<3 for a,b in zip(window,window[1:])))
        self.assertTrue(any(int(n)<10 for w in value for n in w))

    def test_one_window_scale_has_disjoint_physical_anchor_ids(self):
        rows=[dict(pointId=i,imageName=n,measuredDepth=2+i*.01,predictedDepth=(2+i*.01)*1.1)
            for i in range(160) for n in ('a','b','c')]
        fit=fit_window_scale(rows)
        self.assertTrue(fit['accepted']);self.assertAlmostEqual(fit['scale'],1/1.1)
        self.assertFalse(set(fit['trainPointIds'])&set(fit['validationPointIds']))
        self.assertFalse(fit['perFrameScale']);self.assertFalse(fit['cameraChanged'])
        for row in rows:
            if row['pointId'] in fit['validationPointIds']:row['predictedDepth']*=1.3
        self.assertFalse(fit_window_scale(rows)['accepted'])

    def test_half_pixel_crop_returns_native_coordinates(self):
        K=self.fixture()['K'];new,A=resized_camera(K,[2,3,18,19],(21,21),(32,32))
        xy=np.array([[5.2,7.6],[15.1,14.2]])
        processed=(np.c_[xy,np.ones(2)]@A.T)[:,:2]
        np.testing.assert_allclose(native_uv(processed,A),xy,atol=1e-12)
        np.testing.assert_allclose(new,A@K)

    def test_plane_orientation_and_pixel_footprint(self):
        a=self.fixture();uv,xyz,basis,scales,valid=surface_samples(a['depth'],a['K'],a['W2C'])
        self.assertTrue(valid.all())
        np.testing.assert_allclose(xyz[:,2],2)
        np.testing.assert_allclose(np.linalg.det(basis),1,atol=1e-10)
        np.testing.assert_allclose(scales[:,0],.15,atol=1e-8)
        self.assertTrue(np.all(scales[:,2]<scales[:,0]))

    def test_depth_edge_does_not_create_wide_surface(self):
        a=self.fixture();a['depth'][:,10:]=4
        uv,_,_,_,valid=surface_samples(a['depth'],a['K'],a['W2C'])
        self.assertFalse(valid[uv[:,0]==9].any())

    def test_distinct_views_and_occlusion_are_separate(self):
        a=self.fixture();targets=[({'imageName':n},a) for n in ['a','b','c','c']]
        masks={n:np.ones((21,21),bool) for n in ['a','b','c']}
        xyz=np.array([[0.,0,2],[0,0,1],[0,0,3]])
        support,free,occluded=support_samples(xyz,targets,masks)
        np.testing.assert_array_equal(support,[3,0,0])
        np.testing.assert_array_equal(free,[0,3,0])
        np.testing.assert_array_equal(occluded,[0,0,3])

    def test_low_confidence_room_requires_real_depth_and_mask_support(self):
        a=self.fixture();a['confidence'][:]=5;a['confidence'][7:14,7:14]=1
        targets=[({'imageName':n},a) for n in 'abc'];masks={n:np.ones((21,21),bool) for n in 'abc'}
        xyz=np.array([[0.,0,2],[0.,0,1]])
        original=support_samples(xyz,targets,masks)
        revised=support_samples(xyz,targets,masks,confidence_gate=False,return_weights=True)
        np.testing.assert_array_equal(original[0],[0,0])
        np.testing.assert_array_equal(revised[0],[3,0]);np.testing.assert_array_equal(revised[1],[0,3])
        self.assertTrue(0<revised[3][0]<3)
        masks['c'][:]=False
        self.assertEqual(support_samples(xyz,targets,masks,confidence_gate=False)[0][0],2)

    def test_cross_window_conflict_is_not_averaged(self):
        a=self.fixture();a['depth']=np.ones((64,64))*2;a['confidence']=np.ones((64,64))
        b={**a,'depth':a['depth']*1.25};mask=np.ones((64,64),bool)
        self.assertTrue(overlap_check(a,a,mask)['accepted'])
        self.assertFalse(overlap_check(a,b,mask)['accepted'])

    def test_physical_skin_is_not_all_neck(self):
        z=np.zeros((100,100),bool);face=z.copy();face[10:40,35:65]=True
        skin=z.copy();skin[39:60,44:56]=True;skin[60:90,3:15]=True
        cloth=z.copy();cloth[61:95,25:75]=True
        labels=dict(face_core=face,face_boundary=z,hair_visible=z,unknown_or_occluded=z,
            room_visible=~(face|skin|cloth),neck_cloth_visible=skin|cloth,
            observed_neck_cloth=skin|cloth,observed_body_skin=skin)
        m=physical_masks(labels)
        self.assertTrue(m['neck'][44,49]);self.assertFalse(m['neck'][70,10])
        self.assertTrue(m['other_body_skin'][70,10])

    def test_budget_does_not_blend_or_change_footprints(self):
        arr=dict(means=np.array([[0,0,1],[0,0,1],[1,0,1],[2,0,1]],float),
            scales=np.ones((4,3))*.1,layer=np.array(['cloth','neck_skin','cloth','cloth']),
            uid=np.arange(4),confidence=np.ones(4),support=np.full(4,3))
        copy=arr['scales'].copy();indices=select_budget(arr,4)
        self.assertEqual(len(indices),4)
        np.testing.assert_array_equal(copy,arr['scales'])

    def test_choose_reference_matches_existing_frontal_rule(self):
        a=np.zeros((468,2));b=a.copy()
        for m in (a,b):m[152]=[0,10]
        a[454]=[4,0];b[454]=[8,0]
        data=dict(train=['a','b'],worlds={'a':np.eye(4),'b':np.eye(4)},local={'a':{'marks':a},'b':{'marks':b}})
        self.assertEqual(choose_reference(data),'b')

    def test_request_rejects_changed_geometry_and_audit_colours(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for n in ('preparation.json','local_geometry.npz'):(p/n).write_text('frozen')
            split=p/'split.json';split.write_text(json.dumps(dict(train=['a','b','c'],development=['d'],audit=['e'])))
            data=dict(prepared=p,metadata=dict(sourceHash='source'),train=list('abcde'),
                world={n:np.eye(4) for n in 'abcde'},frameRows={n:dict(timestampSeconds=i*.1) for i,n in enumerate('abcde')})
            request=dict(sourceHash='source',preparedSha256=digest(p/'preparation.json'),
                localGeometrySha256=digest(p/'local_geometry.npz'),splitPath=str(split),splitHash=digest(split),
                names=list('abc'),windows={'head-local':[list('abc')]},reference='b')
            validate_request(request,data)
            with self.assertRaisesRegex(ValueError,'training_role_leak'):
                validate_request({**request,'names':list('abe'),'windows':{'head-local':[list('abe')]}},data)
            (p/'local_geometry.npz').write_text('changed')
            with self.assertRaisesRegex(ValueError,'geometry_changed'):validate_request(request,data)

    def test_auxiliary_body_accepts_original_train_but_no_long_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for n in ('preparation.json','local_geometry.npz'):(p/n).write_text('frozen')
            split=p/'split.json';split.write_text(json.dumps(dict(train=['a','b','c'],development=['e'],audit=[])))
            data=dict(prepared=p,metadata=dict(sourceHash='source'),train=list('abcde'),
                world={n:np.eye(4) for n in 'abcde'},frameRows={n:dict(timestampSeconds=i*.1) for i,n in enumerate('abcde')})
            request=dict(sourceHash='source',preparedSha256=digest(p/'preparation.json'),
                localGeometrySha256=digest(p/'local_geometry.npz'),splitPath=str(split),splitHash=digest(split),
                names=list('bcd'),windows={'body-world':[list('bcd')]},reference='b')
            validate_request(request,data)
            with self.assertRaisesRegex(ValueError,'colour_role_leak'):
                validate_request({**request,'windows':{'head-local':[list('bcd')]}},data)
            data['frameRows']['d']['timestampSeconds']=10
            with self.assertRaisesRegex(ValueError,'body_time_extrapolation'):validate_request(request,data)


if __name__=='__main__':unittest.main()
