import unittest

import torch

from reconstruction_train_joint import source_edge_alignment


class SourceDetailLossTest(unittest.TestCase):
    def test_signed_source_edges_and_mask_boundary(self):
        source = torch.tensor([[[[0., 0., 0.], [1., 1., 1.], [0., 0., 0.]],
                                [[0., 0., 0.], [1., 1., 1.], [0., 0., 0.]]]])
        inside = torch.ones((1, 2, 3, 1))
        self.assertEqual(float(source_edge_alignment(source, source, inside)), 0.)
        flat = torch.zeros_like(source, requires_grad=True)
        loss = source_edge_alignment(flat, source, inside)
        self.assertGreater(float(loss.detach()), .1)
        loss.backward()
        self.assertGreater(float(flat.grad.abs().sum()), 0.)
        # The changed last column is outside the source observation and may
        # not create an artificial target at its cut-out boundary.
        sparse = inside.clone()
        sparse[:, :, -1] = 0
        changed = source.clone()
        changed[:, :, -1] = 20
        self.assertEqual(float(source_edge_alignment(changed, source, sparse)), 0.)


if __name__ == "__main__":
    unittest.main()
