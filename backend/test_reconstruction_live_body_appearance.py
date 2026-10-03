import copy
import unittest
import torch
import random
import numpy as np
from reconstruction_live_body_appearance import (body_preservation_decision,snapshot_body_transaction,reject_body_transaction)


class BodyAppearanceTransaction(unittest.TestCase):
    def observed(self):
        return {str(i):{name:dict(pixels=100,premultRgbL1=.02,nativeGradientL1=.004,qPersonMean=.99)
                       for name in ('opaque_cloth','opaque_body_skin')} for i in range(5)}

    def test_one_neck_regression_cannot_hide_in_average(self):
        a=self.observed();b=copy.deepcopy(a)
        for rows in b.values():rows['opaque_body_skin']['premultRgbL1']=.01
        b['2']['opaque_body_skin']['premultRgbL1']=.023
        result=body_preservation_decision(a,b)
        self.assertFalse(result['accepted']);self.assertIn('2:opaque_body_skin:rgb_regression',result['failures'])

    def test_native_structure_and_domain_are_gated_separately(self):
        a=self.observed();b=copy.deepcopy(a);b['0']['opaque_cloth']['nativeGradientL1']=.0042
        self.assertIn('0:opaque_cloth:native_structure_regression',body_preservation_decision(a,b)['failures'])
        b=copy.deepcopy(a);b['0']['opaque_cloth']['pixels']=99
        self.assertFalse(body_preservation_decision(a,b)['accepted'])
        b=copy.deepcopy(a);b['0']['opaque_cloth']['premultRgbL1']=float('nan')
        self.assertFalse(body_preservation_decision(a,b)['accepted'])
        self.assertTrue(body_preservation_decision(a,a)['accepted'])

    def test_rejected_candidate_restores_full_model_and_Adam(self):
        model=torch.nn.Linear(2,2);opt=torch.optim.Adam(model.parameters(),lr=.01)
        opt.zero_grad();model(torch.ones(1,2)).sum().backward();opt.step()
        snapshot=snapshot_body_transaction(model,opt)
        expected=(random.random(),np.random.random(),torch.rand(1))
        opt.zero_grad();model(torch.ones(1,2)*3).sum().backward();opt.step()
        model.bias.requires_grad_(False)
        self.assertTrue(reject_body_transaction(model,snapshot,{'accepted':False},opt))
        self.assertTrue(model.bias.requires_grad)
        self.assertEqual(random.random(),expected[0]);self.assertEqual(np.random.random(),expected[1])
        self.assertTrue(torch.equal(torch.rand(1),expected[2]))
        for key,value in model.state_dict().items():self.assertTrue(torch.equal(value,snapshot['model'][key]))
        for key,value in opt.state_dict()['state'].items():
            for field,tensor in value.items():self.assertTrue(torch.equal(tensor,snapshot['optimizer']['state'][key][field]))


if __name__=='__main__':unittest.main()
