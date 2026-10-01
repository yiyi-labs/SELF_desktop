import unittest,torch
from reconstruction_observation_protection import extra_foreground_loss
class ObservationProtectionTests(unittest.TestCase):
    def test_unknown_is_not_empty_and_original_does_not_train(self):
        a=torch.tensor([.7,.9,.2],requires_grad=True);b=torch.tensor([.2,.1,.4],requires_grad=True)
        loss=extra_foreground_loss(a,b,torch.tensor([True,False,True]));loss.backward()
        self.assertGreater(a.grad[0],0);self.assertEqual(float(a.grad[1]),0);self.assertEqual(float(a.grad[2]),0);self.assertIsNone(b.grad)
    def test_all_unknown_finite_zero(self):
        a=torch.tensor([.7],requires_grad=True);loss=extra_foreground_loss(a,a.detach(),torch.tensor([False]));loss.backward()
        self.assertEqual(float(loss),0);self.assertEqual(float(a.grad[0]),0)
    def test_mismatch_rejected(self):
        with self.assertRaises(ValueError):extra_foreground_loss(torch.zeros(2),torch.zeros(1),torch.tensor([True,True]))
if __name__=='__main__':unittest.main()