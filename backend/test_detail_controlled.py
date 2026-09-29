import unittest
import torch
from reconstruction_detail_controlled import pixel_structure,NativeStaticStrategy
from reconstruction_reference_static import StaticGaussians

class DetailContracts(unittest.TestCase):
    def test_signed_structure_counts_missing_but_no_mask_edge(self):
        target=torch.zeros(8,8,3);target[:,4:]=1
        pred=torch.full_like(target,.5,requires_grad=True);mask=torch.ones(8,8,dtype=torch.bool)
        loss=pixel_structure(pred,target,mask);self.assertGreater(float(loss),0);loss.backward();self.assertGreater(float(pred.grad.abs().sum()),0)
        mask[:,3:5]=False
        self.assertEqual(float(pixel_structure(pred.detach(),target,mask)),0.)
        self.assertEqual(float(pixel_structure(pred.detach(),target,torch.zeros_like(mask))),0.)
    def test_native_strategy_uses_absolute_gradient_and_stops(self):
        s=NativeStaticStrategy(start=120,stop=600,every=100,max_growth=2,max_points=10,reset_steps=(300,))
        self.assertTrue(s.absgrad);self.assertEqual(s.grow_grad2d,.0008);self.assertEqual(s.refine_stop_iter,601)
        s.step_post_backward({}, {}, {}, 900, {})
    def test_projected_large_point_split_retains_lineage(self):
        n=3;v={'means':torch.zeros(n,3),'scales':torch.full((n,3),-6.),'quats':torch.tensor([[1.,0,0,0]]).repeat(n,1),
            'opacities':torch.zeros(n),'sh':torch.zeros(n,4,3)}
        r=StaticGaussians(v,{'id':torch.arange(n),'kind':torch.ones(n)},torch.ones(n));ops=r.optimizers(1.)
        for k,p in r.params.items():p.sum().backward();ops[k].step();ops[k].zero_grad(set_to_none=True)
        s=NativeStaticStrategy(start=0,stop=600,every=100,max_growth=1,max_points=10,reset_steps=())
        state=s.initialize_for(r,1.);state['grad2d']=torch.tensor([.02,0.,0.]);state['count']=torch.tensor([10.,10.,10.]);state['radii']=torch.tensor([.05,0.,0.])
        nd,ns=s._grow_gs(r.params,ops,state,200);self.assertEqual((nd,ns),(0,1));self.assertEqual(len(r.params['means']),4)
        self.assertEqual(int((state['source_id']==0).sum()),2);self.assertEqual(len(state['point_uid'].unique()),4)
        for key in ('initial_means','initial_scales','source_id','generation'):self.assertEqual(len(state[key]),4)
        s.check_sanity(r.params,ops)
        for k,p in r.params.items():
            for a in ('exp_avg','exp_avg_sq'):self.assertEqual(ops[k].state[p][a].shape,p.shape)

if __name__=='__main__':unittest.main()
