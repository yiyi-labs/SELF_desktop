import unittest
import torch
from reconstruction_live_hair_composite import masked_parameter_step


class HairCompositeContract(unittest.TestCase):
    def test_real_background_breaks_black_backdrop_opacity_ambiguity(self):
        logit=torch.tensor([0.],requires_grad=True)
        foreground=torch.tensor([.1]);background=torch.tensor([.8]);target=torch.tensor([.1])
        alpha=logit.sigmoid();((alpha*foreground+(1-alpha)*background-target).square()).backward()
        self.assertLess(float(logit.grad),0.)

    def test_adam_cannot_change_nonhair_parameter_rows(self):
        parameters={'sh':torch.nn.Parameter(torch.randn(5,4,3)),
                    'opacity':torch.nn.Parameter(torch.randn(5))}
        frozen={k:v.detach().clone() for k,v in parameters.items()};hair=torch.tensor([False,False,True,True,False])
        optimizer=torch.optim.Adam(list(parameters.values()),lr=.01)
        for _ in range(4):
            optimizer.zero_grad();sum(v.square().sum() for v in parameters.values()).backward()
            masked_parameter_step(optimizer,parameters,hair,frozen)
        for name,value in parameters.items():
            self.assertTrue(torch.equal(value[~hair],frozen[name][~hair]))
            self.assertFalse(torch.equal(value[hair],frozen[name][hair]))


if __name__=='__main__':unittest.main()
