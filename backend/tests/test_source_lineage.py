"""Exercise gsplat 1.5.3's actual split/clone/prune on frozen source IDs."""

import unittest

import torch
from gsplat.strategy.ops import duplicate, remove, split


class SourceLineageTest(unittest.TestCase):
    def test_origin_and_semantic_follow_split_clone_and_prune(self):
        params = torch.nn.ParameterDict({
            "means": torch.nn.Parameter(torch.tensor([[0., 0., 2.], [.3, 0., 2.]])),
            "scales": torch.nn.Parameter(torch.full((2, 3), -2.)),
            "quats": torch.nn.Parameter(torch.tensor([[1., 0., 0., 0.]] * 2)),
            "opacities": torch.nn.Parameter(torch.zeros(2)),
            "sh0": torch.nn.Parameter(torch.zeros(2, 1, 3)),
            "shN": torch.nn.Parameter(torch.zeros(2, 15, 3)),
            "semantic": torch.nn.Parameter(torch.tensor([[1.], [0.]])),
            "source_index": torch.nn.Parameter(torch.tensor([[7.], [11.]])),
        })
        opts = {key: torch.optim.Adam([{"params": value, "lr": 0.}], eps=1e-15)
                for key, value in params.items()}
        # Initialize Adam moments before topology changes; shape-only tests
        # with empty state would miss stale exp_avg / exp_avg_sq arrays.
        sum(value.square().sum() for value in params.values()).backward()
        for optimizer in opts.values():
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        split(params, opts, {}, torch.tensor([True, False]))
        self.assertEqual(params["source_index"].flatten().tolist(), [11., 7., 7.])
        self.assertEqual(params["semantic"].flatten().tolist(), [0., 1., 1.])
        duplicate(params, opts, {}, torch.tensor([False, True, False]))
        self.assertEqual(params["source_index"].flatten().tolist(), [11., 7., 7., 7.])
        remove(params, opts, {}, torch.tensor([False, False, True, False]))
        self.assertEqual(params["source_index"].flatten().tolist(), [11., 7., 7.])
        self.assertEqual(params["semantic"].flatten().tolist(), [0., 1., 1.])
        for optimizer in opts.values():
            self.assertEqual(len(optimizer.param_groups[0]["params"]), 1)
            self.assertEqual(optimizer.param_groups[0]["params"][0].shape[0], 3)
            parameter = optimizer.param_groups[0]["params"][0]
            self.assertEqual(optimizer.state[parameter]["exp_avg"].shape[0], 3)
            self.assertEqual(optimizer.state[parameter]["exp_avg_sq"].shape[0], 3)


if __name__ == "__main__":
    unittest.main()
