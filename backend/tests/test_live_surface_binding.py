import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np
from reconstruction_live_surface_binding import load_component,environment_from_components,replace_hair_prior,verify_room_completion,file_hash


def component(n=3):
    return dict(means=np.ones((n,3),np.float32),scales=np.tile([.01,.02,.003],(n,1)).astype(np.float32),
        quats=np.tile([1.,0,0,0],(n,1)).astype(np.float32),opacity=np.full(n,.55,np.float32),
        sh=np.zeros((n,4,3),np.float32),support=np.full(n,3),confidence=np.ones(n,np.float32),
        uid=np.arange(n,dtype=np.int64)+100,source_hash=np.asarray('source'),coordinate_frame=np.asarray('world'))


class BindingContract(unittest.TestCase):
    def test_auxiliary_surface_cannot_modify_original_or_borrow_its_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);parts=[]
            for i,n in enumerate((3,2)):
                c=component(n);c['uid']+=i*100;c['support'][:]=1
                c.update(evidence_type=np.full(n,'conditional_shared_surface'),static_image_support=np.full(n,3),
                         colour_support=np.full(n,3),depth_free=np.zeros(n,int))
                np.savez(folder/f'{i}.npz',**c);parts.append(c)
            final={k:np.concatenate([c[k] for c in parts]) for k,v in parts[0].items() if v.ndim}
            final['source_receipt_index']=np.array([0,0,0,1,1])
            row={'sha256':'combined','surfaceBaseComponent':{'path':'0.npz','sha256':file_hash(folder/'0.npz'),'count':3},
                 'additionalSurfaceReceipts':[{'index':1,'path':'proof1.json','sha256':'proof1','assetPath':'1.npz',
                    'assetSha256':file_hash(folder/'1.npz'),'count':2}]}
            with patch('reconstruction_live_surface_binding.verify_room_correction') as verify:
                verify_room_completion(row,{}, {'sourceHash':'source'},folder/'result.json',final)
                self.assertEqual(verify.call_count,2)
                self.assertEqual(verify.call_args_list[0].kwargs['expected_asset_hash'],file_hash(folder/'0.npz'))
                self.assertEqual(verify.call_args_list[1].args[0]['sha256'],file_hash(folder/'1.npz'))
                final['means'][0,0]+=.001
                with self.assertRaisesRegex(ValueError,'parameters_changed:means'):
                    verify_room_completion(row,{}, {'sourceHash':'source'},folder/'result.json',final)
                final['means'][0,0]-=.001;final['source_receipt_index'][-1]=3
                with self.assertRaisesRegex(ValueError,'unknown_point_proof'):
                    verify_room_completion(row,{}, {'sourceHash':'source'},folder/'result.json',final)

    def test_conditional_surface_does_not_forge_three_depth_votes(self):
        with tempfile.TemporaryDirectory() as folder:
            p=component();p['support'][0]=1
            p.update(evidence_type=np.array(['conditional_shared_surface','original_depth_consistent','depth_consistent_shared_surface']),
                     static_image_support=np.array([4,3,3]),colour_support=np.array([3,3,3]),depth_free=np.zeros(3,int))
            path=Path(folder)/'room.npz';np.savez(path,**p)
            with self.assertRaisesRegex(ValueError,'distinct'):load_component(path,'source','world')
            loaded=load_component(path,'source','world',conditional_room=True)
            self.assertEqual(loaded['support'][0],1)
            p['depth_free'][0]=2;np.savez(path,**p)
            with self.assertRaisesRegex(ValueError,'evidence_invalid'):load_component(path,'source','world',conditional_room=True)

    def test_camera_frame_source_and_support_cannot_be_silently_repaired(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'part.npz';p=component();np.savez(path,**p)
            self.assertEqual(len(load_component(path,'source','world')['means']),3)
            with self.assertRaisesRegex(ValueError,'source_mismatch'):load_component(path,'other','world')
            with self.assertRaisesRegex(ValueError,'coordinate'):load_component(path,'source','head-local')
            p['support'][1]=2;np.savez(path,**p)
            with self.assertRaisesRegex(ValueError,'distinct'):load_component(path,'source','world')

    def test_surface_covariance_and_source_identity_survive_handoff(self):
        p=component();env,origin,layers=environment_from_components({'room':p},'cpu')
        np.testing.assert_allclose(env['scales'].exp(),p['scales'],rtol=1e-6)
        np.testing.assert_array_equal(origin['id'],p['uid'])
        self.assertTrue((env['part']==0).all());self.assertTrue((layers=='room').all())

    def test_hair_replacement_cannot_change_any_face_parameter(self):
        h=component();s=2;n=4
        p=dict(role=np.array([0,1,2,2]),surface_ids=np.array([5,7]),surface_bary=np.array([[.2,.3,.5],[.1,.7,.2]]),
            hair_local_points=np.zeros((2,3)),source_index=np.arange(n),origin_index=np.arange(n),
            source_confidence=np.ones(n),local_offsets=np.zeros((n,3)),log_scales=np.zeros((n,3)),
            local_quats=np.tile([1.,0,0,0],(n,1)),opacity_logits=np.zeros(n),sh_coeff=np.zeros((n,4,3)),
            base_rgb_logits=np.zeros((n,3)),sh1=np.zeros((n,3,3)))
        q=replace_hair_prior(p,h)
        for k in ('local_offsets','log_scales','local_quats','opacity_logits','sh_coeff','source_index','source_confidence'):
            np.testing.assert_array_equal(q[k][:s],p[k][:s])
        self.assertEqual(len(q['role']),5);self.assertEqual(len(q['sh1']),5)
        np.testing.assert_array_equal(q['hair_local_points'],h['means'])


if __name__=='__main__':unittest.main()
