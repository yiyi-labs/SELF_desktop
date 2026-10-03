"""Geometry and real CUDA visibility checks for one shared rasterization."""

import unittest

import numpy as np
import torch

from joint_visibility import (conservation_error, posed_points,
                                             render_shared, visible_point_scores)


def synthetic_asset(device: str):
    return {"means": torch.tensor([[0., 0., 1.8], [0., 0., 2.4]], device=device),
            "quats": torch.tensor([[1., 0., 0., 0.]] * 2, device=device),
            "scales": torch.tensor([[.2, .2, .04]] * 2, device=device),
            "opacity": torch.tensor([.9, .9], device=device),
            "sh": torch.zeros(2, 16, 3, device=device), "person_count": 1,
            "person_mask": torch.tensor([True, False], device=device)}


class SharedVisibilityTest(unittest.TestCase):
    def test_head_moves_but_room_stays_in_world(self):
        asset = synthetic_asset("cpu")
        world = np.eye(4)
        corrected = np.eye(4)
        corrected[0, 3] = -.3
        means, quats, rays = posed_points(asset, world, corrected)
        self.assertAlmostEqual(float(means[0, 0]), -.3, places=5)
        self.assertAlmostEqual(float(means[1, 0]), 0., places=5)
        self.assertEqual(tuple(quats.shape), (2, 4))
        self.assertEqual(tuple(rays.shape), (2, 3))
        identity_means, _, _ = posed_points(asset, world, world)
        torch.testing.assert_close(identity_means, asset["means"])

    @unittest.skipUnless(torch.cuda.is_available(), "CUDA not exposed by this host")
    def test_sorted_source_contribution_and_point_gradient(self):
        asset = synthetic_asset("cuda")
        K = np.array([[100., 0., 32.], [0., 100., 32.], [0., 0., 1.]])
        identity = np.eye(4)
        image = render_shared(asset, identity, identity, K, 64, 64, point_probe=True)
        self.assertLess(conservation_error(image), 2e-5)
        self.assertGreater(float(image["q_person"][32, 32].detach()),
                           float(image["q_environment"][32, 32].detach()))
        weights = torch.zeros(64, 64, device="cuda")
        weights[30:34, 30:34] = 1
        scores = visible_point_scores(image, weights)
        self.assertGreater(float(scores[0]), float(scores[1]))
        self.assertTrue(torch.isfinite(scores).all())


if __name__ == "__main__":
    unittest.main()
