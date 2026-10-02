import unittest
from types import SimpleNamespace
import numpy as np
import torch
from reconstruction_observation_domains import observation_domains
from reconstruction_static_planes import fit_plane_groups, finite_plane_support
from reconstruction_complete_room import CompleteRoomReplacement, structure, plane_source_members, target_plane_groups
from reconstruction_portrait_model import GaussianState


class PhysicalSupportTests(unittest.TestCase):
    def scene(self, colors=None):
        grid=np.mgrid[-.5:.51:.2,-.5:.51:.2].reshape(2,-1).T
        xyz=np.c_[grid,np.ones(len(grid))*2].astype(np.float32)
        room=dict(xyz=xyz,source_kind=np.zeros(len(xyz),np.uint8),source_id=np.arange(len(xyz)))
        K=np.array([[80,0,50],[0,80,50],[0,0,1.]])
        views={};masks={};images={}
        for i in range(4):
            C=np.eye(4);C[0,3]=(i-1.5)*.03
            views[str(i)]=(C,K);masks[str(i)]=np.ones((100,100),bool)
            images[str(i)]=np.ones((100,100,3),np.float32)*(colors[i] if colors else .6)
        return room,views,masks,images

    def test_low_texture_room_not_limited_to_feature_mask(self):
        classes=np.zeros((6,8),np.uint8);confidence=np.ones_like(classes,dtype=float)
        feature_mask=np.zeros_like(classes,dtype=bool)
        result=observation_domains(classes,confidence,feature_mask,{'room_visible':feature_mask})
        self.assertTrue(result['observed_room'].all())
        self.assertFalse(result['room_visible'].any())

    def test_unknown_and_outside_not_supervised(self):
        cls=np.array([[0,0,4,2,1]]);confidence=np.array([[1.,.5,1.,1.,1.]])
        result=observation_domains(cls,confidence,np.array([[True,False,False,False,False]]),{})
        self.assertFalse(result['observed_room'].any())
        self.assertEqual(result['observed_neck_cloth'].tolist(),[[False,False,True,True,False]])

    def test_finite_plane_from_distributed_real_tracks(self):
        room,views,masks,images=self.scene();groups=fit_plane_groups(room['xyz'],1.)
        self.assertEqual(len(groups),1)
        proposal,report=finite_plane_support(room,views,masks,images,1.,budget=80,stride=5,
            plane_groups=groups,grow_observed=False)
        self.assertIsNotNone(proposal)
        self.assertTrue(np.all(proposal['support']>=3))
        self.assertTrue(np.all(np.abs(proposal['xyz'][:,:2])<=.501))
        np.testing.assert_allclose(proposal['xyz'][:,2],2,atol=1e-6)
        self.assertEqual(report['planes'][0]['domain'],'measured_plane_inlier_hull_only')
        self.assertFalse(report['planes'][0]['independentDenseTruth'])

    def test_true_color_conflicts_not_turned_into_unknown(self):
        room,views,masks,images=self.scene([.2,.2,.8,.8])
        proposal,_=finite_plane_support(room,views,masks,images,1.,budget=80,stride=5,grow_observed=False)
        self.assertIsNone(proposal)

    def test_sampled_descendants_need_all_measured_parents_on_plane(self):
        room=dict(source_kind=np.array([0,1,1]),source_id=np.array([11,99,100]),
            triangle_sources=np.array([[11,11,11],[11,12,13],[11,12,20]]))
        result=plane_source_members(room,np.array([11,99,99,100,404]),
            np.array([0,1,1,1,1]),np.array([11,12,13]))
        self.assertEqual(result.tolist(),[True,True,True,False,False])

    def test_old_seed_outside_plane_needs_multiple_finite_projection_supports(self):
        room,views,masks,images=self.scene()
        room={**room,'xyz':np.vstack(([0,0,2.08],room['xyz'])),
            'source_id':np.arange(len(room['xyz'])+1),'source_kind':np.zeros(len(room['xyz'])+1,np.uint8)}
        room['triangle_sources']=np.repeat(room['source_id'][:,None],3,1)
        groups,records=target_plane_groups(room,[],np.array([0]),np.array([0]),[(0,.1)],1.,views=views,masks=masks)
        self.assertTrue(groups)
        self.assertFalse(groups[0]['oldSeedOnPlane'])
        self.assertGreaterEqual(groups[0]['trainHullOverlap'],3)
        unknown={n:np.zeros_like(mask) for n,mask in masks.items()}
        groups,_=target_plane_groups(room,[],np.array([0]),np.array([0]),[(0,.1)],1.,views=views,masks=unknown)
        self.assertFalse(groups)

    def test_edge_structure_does_not_cross_invalid_mask(self):
        target=torch.zeros(3,3,3);pred=target.clone();pred[0]=1
        mask=torch.ones(3,3,dtype=torch.bool);mask[0]=False
        self.assertEqual(float(structure(pred,target,mask)),0)


@unittest.skipUnless(torch.cuda.is_available(),'CUDA unavailable')
class CompleteTransactionTests(unittest.TestCase):
    def test_consolidated_draw_preserves_pixels_and_source_gradients(self):
        from reconstruction_portrait_pipeline import draw as historical_draw
        from reconstruction_render_contract import draw as common_draw
        torch.manual_seed(7);device='cuda';n=8
        values=[torch.cat((torch.rand(n,2,device=device)*.3-.15,torch.ones(n,1,device=device)*2),1),
            torch.tensor([[1.,0,0,0]],device=device).repeat(n,1),torch.ones(n,3,device=device)*.055,
            torch.ones(n,device=device)*.6,torch.randn(n,4,3,device=device)*.06]
        def run(function):
            params=[v.detach().clone().requires_grad_() for v in values]
            state=GaussianState(*params,torch.arange(n,device=device)%5)
            C=torch.eye(4,device=device);K=torch.tensor([[90.,0,44],[0,85.,36],[0,0,1]],device=device)
            rendered=function(state,C,K,88,72)
            loss=rendered['rgb'].square().mean()+rendered['q'].square().mean()
            loss.backward()
            return rendered,[p.grad for p in params]
        historical,a=run(historical_draw);current,b=run(common_draw)
        for key in ('rgb','alpha','q','q_depth','depth'):
            torch.testing.assert_close(historical[key],current[key],rtol=0,atol=1e-7)
        for ga,gb in zip(a,b):torch.testing.assert_close(ga,gb,rtol=0,atol=1e-7)

    def test_all_components_kept_and_patch_geometry_frozen(self):
        dev='cuda';n=10
        state=GaussianState(torch.rand(n,3,device=dev),torch.tensor([[1.,0,0,0]],device=dev).repeat(n,1),
            torch.ones(n,3,device=dev)*.03,torch.ones(n,device=dev)*.7,
            torch.zeros(n,4,3,device=dev),torch.arange(n,device=dev)%5)
        class Base(torch.nn.Module):
            def __init__(self):
                super().__init__();self.scale=1.;self.baseline=SimpleNamespace(adjusted_frame=lambda f:f)
            def state(self,frame):return state
        base=Base();rgb=np.zeros((4,4,3),np.float32);name='test'
        data=dict(rgb={name:rgb},labels={name:{}},K=np.eye(3),worlds={name:np.eye(4)},
            local={name:dict(mesh=np.zeros((3,3)),F=np.eye(4))})
        proposal=dict(xyz=np.array([[0,0,2],[.1,0,2],[0,.1,2],[.1,.1,2]],np.float32),
            surface_normal=np.tile([0,0,1.],(4,1)),rgb=np.ones((4,3),np.float32)*.6,
            support=np.ones(4)*3,triangle_sources=np.tile([1,2,3],(4,1)))
        replacement=CompleteRoomReplacement(base,data,name,torch.tensor([0],device=dev),proposal)
        self.assertTrue(all(not p.requires_grad for p in replacement.patch.parameters()))
        after=replacement.state({})
        self.assertEqual(len(after.means),13)
        torch.testing.assert_close(after.means[:9],state.means[1:],rtol=0,atol=0)
        torch.testing.assert_close(after.sh[:9],state.sh[1:],rtol=0,atol=0)
        torch.testing.assert_close(after.parts[:9],state.parts[1:],rtol=0,atol=0)


if __name__=='__main__':unittest.main()
