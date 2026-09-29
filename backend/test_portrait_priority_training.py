"""Research contracts. Synthetic CPU updates are NOT portrait training evidence."""
import copy,tempfile,unittest
from pathlib import Path
import numpy as np
import torch
from test_reconstruction_portrait_model import fixture
from reconstruction_research_state import (FrameSampler,BoundedHeadPose,save_checkpoint,
    restore_checkpoint,validate_research_manifest,rigid_component_state,ensure_point_lineage,replace_face_with_lineage)
from reconstruction_reference_static import (StaticGaussians,BudgetedStaticStrategy,valid_window_structure,
    valid_static_mask,static_loss)

class TrainingStateTests(unittest.TestCase):
    def test_full_topology_adam_rng_sampler_restore_next_update(self):
        torch.manual_seed(17)
        model,_,mesh=fixture();optimizer=torch.optim.Adam(model.parameters(),lr=.001)
        sum(p.square().sum() for p in model.parameters()).backward();optimizer.step();optimizer.zero_grad()
        model.replace_skin_parents([0],optimizer,lambda ids,bary:torch.ones(len(ids),dtype=torch.bool))
        sampler=FrameSampler(['a','b','c'],8);sampler.next()
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'state.pt';contract={'input':'unchanged'}
            save_checkpoint(path,model,{'face':optimizer},{'face':sampler},stage='face',step=10,contract=contract)
            with self.assertRaises(FileExistsError):save_checkpoint(path,model,{'face':optimizer},{'face':sampler},stage='face',step=10,contract=contract)
            expected_random=torch.rand(5);expected_sample=sampler.next()
            sum(p.square().sum() for p in model.parameters()).backward();optimizer.step()
            expected=copy.deepcopy(model.state_dict())
            other,_,_=fixture();other_opt=torch.optim.Adam(other.parameters(),lr=.001);other_sample=FrameSampler(['a','b','c'],8)
            restore_checkpoint(path,other,{'face':other_opt},{'face':other_sample},contract=contract)
            torch.testing.assert_close(torch.rand(5),expected_random,atol=0,rtol=0)
            self.assertEqual(other_sample.next(),expected_sample)
            sum(p.square().sum() for p in other.parameters()).backward();other_opt.step()
            for k,v in expected.items():torch.testing.assert_close(other.state_dict()[k],v,atol=0,rtol=0)
            payload=torch.load(path,weights_only=False);del payload['model']['surface_residual'];broken=Path(root)/'broken.pt';torch.save(payload,broken)
            with self.assertRaisesRegex(ValueError,'fields_missing'):restore_checkpoint(broken,other,{'face':other_opt},{'face':other_sample},contract=contract)
    def test_stable_ids_follow_actual_parent_replacement(self):
        model,_,_=fixture();ensure_point_lineage(model)
        optimizer=torch.optim.Adam(model.parameters(),lr=.001)
        event=replace_face_with_lineage(model,optimizer,[0],lambda ids,bary:torch.ones(len(ids),dtype=torch.bool))
        self.assertEqual(event['retiredStableUIDs'],[0]);self.assertEqual(event['childStableUIDs'],[3,4])
        self.assertEqual(model.stable_uid.tolist(),[1,3,4,2]);self.assertEqual(model.parent_uid.tolist(),[-1,0,0,-1])
        self.assertEqual(len(model.stable_uid.unique()),len(model.role))

    def test_pose_bounds_reference_and_unknown_preserved(self):
        pose=BoundedHeadPose(['ref','train'],'ref');pose.delta.data.fill_(100)
        F=torch.eye(4);F[:3,3]=torch.tensor([.1,.2,.8])
        self.assertIs(pose('ref',F),F);self.assertIs(pose('held',F),F)
        result=pose('train',F)
        self.assertLessEqual(float(torch.linalg.norm(result[:3,3]-F[:3,3]).detach()),.001501)
        angle=torch.acos(((torch.trace(result[:3,:3])-1)/2).clamp(-1,1))
        self.assertLessEqual(float((angle*180/torch.pi).detach()),1.001)
    def test_body_rotation_covariance_has_gradient_and_reference_value(self):
        model,_,mesh=fixture();state=model.local_state(mesh)
        state.scales=state.scales*torch.tensor([1.,2.,3.])
        angles=torch.zeros(3,requires_grad=True);translation=torch.zeros(3,requires_grad=True)
        moved=rigid_component_state(state,angles,translation,torch.zeros(3))
        torch.testing.assert_close(moved.covariance(),state.covariance())
        loss=moved.covariance()[:,0,1].sum()+moved.means[:,0].sum()
        loss.backward();self.assertTrue(torch.isfinite(angles.grad).all())
        self.assertGreater(float(angles.grad.abs().sum()),0.);self.assertGreater(float(translation.grad.abs().sum()),0.)

    def test_research_valid_not_release_and_no_default_C(self):
        C=np.eye(4);F=np.eye(4);F[2,3]=.8
        data={'scale':13.,'K':np.diag([100.,100.,1.]),'worlds':{'x':C},'local':{'x':{'F':F}}}
        self.assertFalse(validate_research_manifest(data,'x',['x'])['releaseQualityPassed'])
        with self.assertRaisesRegex(ValueError,'observation_missing'):validate_research_manifest(data,'x',['absent'])

class StaticAdapterTests(unittest.TestCase):
    def room(self):
        n=6
        values={'means':torch.randn(n,3),'scales':torch.tensor([[.001]*3]*3+[[.03]*3]*3).log(),
            'quats':torch.tensor([[1.,0,0,0]]*n),'opacities':torch.zeros(n),'sh':torch.randn(n,4,3)}
        return StaticGaussians(values,{'id':np.arange(10,10+n),'kind':np.zeros(n)},np.ones(n)*3)
    def test_actual_upstream_ops_sync_metadata_optimizer_and_budget(self):
        room=self.room();strategy=BudgetedStaticStrategy(max_points=9,max_growth=3)
        optim=room.optimizers(1);strategy.check_sanity(room.params,optim)
        sum(p.square().sum() for p in room.params.values()).backward()
        for op in optim.values():op.step();op.zero_grad()
        state=strategy.initialize_for(room,1);state['grad2d']=torch.tensor([6.,0,0,5.,4.,0]);state['count']=torch.ones(6)*4
        nd,ns=strategy._grow_gs(room.params,optim,state,200)
        self.assertEqual((nd,ns),(1,2));self.assertEqual(len(room.params['means']),9)
        self.assertEqual(len(state['point_uid'].unique()),9)
        self.assertTrue(set(state['source_id'].tolist())<=set(range(10,16)))
        for key,v in state.items():
            if isinstance(v,torch.Tensor):self.assertEqual(len(v),9,key)
        for key,param in room.params.items():
            self.assertIs(optim[key].param_groups[0]['params'][0],param)
            self.assertEqual(optim[key].state[param]['exp_avg'].shape,param.shape)
        self.assertGreater(int((state['generation']>0).sum()),0)
    def test_real_pre_post_callbacks_reset_and_recovery_schedule(self):
        room=self.room();strategy=BudgetedStaticStrategy(max_points=10,max_growth=1)
        optim=room.optimizers(1);state=strategy.initialize_for(room,1)
        for step in (1,2,3,200,201,202,300,301,302,400,401,402,600,700):
            n=len(room.params['means']);means2d=torch.ones(n,2,requires_grad=True)*2
            info={'width':16,'height':16,'n_cameras':1,'radii':torch.ones(n,2),
                'gaussian_ids':torch.arange(n),'means2d':means2d}
            strategy.step_pre_backward(room.params,optim,state,step,info)
            means2d.sum().backward()
            strategy.step_post_backward(room.params,optim,state,step,info,packed=True)
            if step==300:self.assertLessEqual(float(room.params['opacities'].detach().sigmoid().max()),.100001)
        self.assertEqual([e['step'] for e in state['events'] if e['type']=='opacity_reset'],[300])
        self.assertEqual([e['step'] for e in state['events'] if e['type']=='topology'],[200,400,600])
        self.assertTrue(any(e.get('duplicates',0)+e.get('splitParents',0)>0 for e in state['events']))
        self.assertLessEqual(len(room.params['means']),10)

    def test_structure_never_crosses_invalid_pixel_windows(self):
        target=torch.zeros(15,15,3);pred=target.clone();pred[0]=1
        mask=torch.ones(15,15,dtype=torch.bool);mask[0]=False
        self.assertEqual(float(valid_window_structure(pred,target,mask)),0.)
        pred[8,8]=1;self.assertGreater(float(valid_window_structure(pred,target,mask)),0.)
    def test_missing_flat_background_in_denominator_and_no_person_black_target(self):
        h=w=15;mask=torch.ones(h,w,dtype=torch.bool);mask[:3]=False
        frame={'rgb':torch.ones(h,w,3)*.7,'masks':{'room_visible':mask,'unknown_or_occluded':torch.zeros_like(mask)}}
        output={'rgb':torch.zeros(h,w,3),'alpha':torch.zeros(h,w),'q':torch.zeros(h,w,5)}
        _,row=static_loss(output,frame);self.assertEqual(row['validPixels'],180);self.assertAlmostEqual(row['rgb'],.7,places=5)
        frame['rgb'][:3]=.1
        _,same=static_loss(output,frame);self.assertAlmostEqual(same['rgb'],row['rgb'],places=6)
        self.assertEqual(row['holeAlpha08'],1.)

if __name__=='__main__':unittest.main()
