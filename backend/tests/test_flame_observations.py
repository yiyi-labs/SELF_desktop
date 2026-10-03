"""Regression for the local FLAME F_t convention and permanent GS binding."""

import unittest

import numpy as np
import torch

from flame_open_model import EMBEDDING, MODEL, STANDARD_MODEL, FlameOpen
from probe_flame_observations import root_neutral_contract
from probe_flame_real_appearance import barycentric_samples, bound_points


@unittest.skipUnless(MODEL.is_file() and EMBEDDING.is_file(),
                     "official local research model is unavailable")
class FlameObservationTest(unittest.TestCase):
    def test_nonzero_shape_neck_jaw_root_once(self):
        model = FlameOpen(8, 4)
        shape = torch.tensor([[.3, -.2, .1, .05, -.03, .06, .02, -.01]])
        expression = torch.tensor([[.25, -.17, .04, .02]])
        pose = torch.zeros(1, 5, 3)
        pose[0, 0] = torch.tensor([.12, -.32, .08])
        pose[0, 1] = torch.tensor([.07, .02, -.04])
        pose[0, 2] = torch.tensor([-.09, .01, .03])
        local, F, error = root_neutral_contract(model, shape, expression, pose,
                                                np.asarray([.08, .14, .6]))
        self.assertLess(error, 2e-6)
        self.assertGreater(float(np.linalg.norm(F[:3, :3] - np.eye(3))), .2)
        self.assertEqual(local.shape, (5023, 3))

    def test_permanent_triangle_binding_survives_pose(self):
        model = FlameOpen(8, 4)
        faces = model.faces.numpy()
        ids, bary, scale = barycentric_samples(model.template.numpy(), faces, 5000)
        neutral, _ = bound_points(model.template.numpy(), faces, ids, bary)
        moved = model.template.numpy().copy()
        moved[:, 2] += np.linspace(0, .01, len(moved))
        changed, _ = bound_points(moved, faces, ids, bary)
        expected = ((moved[faces[ids]] - model.template.numpy()[faces[ids]])
                    * bary[..., None]).sum(axis=1)
        self.assertTrue(np.allclose(changed - neutral, expected, atol=1e-7))
        self.assertTrue(np.isfinite(scale).all())

    @unittest.skipUnless(STANDARD_MODEL.is_file(), "legacy model not downloaded")
    def test_standard_uses_same_topology_not_same_coefficients(self):
        standard = FlameOpen(8, 4, model_path=STANDARD_MODEL)
        opened = FlameOpen(8, 4)
        self.assertTrue(torch.equal(standard.faces, opened.faces))
        self.assertNotEqual(standard.model_sha256, opened.model_sha256)
        self.assertFalse(torch.allclose(standard.directions[..., -4:],
                                        opened.directions[..., -4:]))


if __name__ == "__main__":
    unittest.main()
