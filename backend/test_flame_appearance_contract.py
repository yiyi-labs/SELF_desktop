"""Small CPU regressions for the research A/B and PLY color boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch
from gsplat.cuda._wrapper import spherical_harmonics

from compare_flame_appearance_ab import compare
from appearance_direction_contract import (camera_to_point_in_head,
                                           sh1_head_to_reference, sh1_rgb)
from export_flame_appearance_research import C0, C1, fit_degree_one, sh_basis
from probe_flame_hair_hull import classify_projection


class AppearanceContractTest(unittest.TestCase):
    def test_head_direction_changes_with_orbit_but_not_camera_roll(self) -> None:
        from scipy.spatial.transform import Rotation
        point = np.asarray([[0., 0., 1.]], np.float32)
        identity = np.eye(3, dtype=np.float32)
        yaw = Rotation.from_euler('y', 55, degrees=True).as_matrix().astype(np.float32)
        front = camera_to_point_in_head(point, identity)
        side = camera_to_point_in_head(point, yaw)
        self.assertGreater(np.linalg.norm(front-side), .8)
        # Rotate the camera axes, with camera and object positions unchanged.
        roll = Rotation.from_euler('z', 72, degrees=True).as_matrix().astype(np.float32)
        np.testing.assert_allclose(camera_to_point_in_head(point @ roll.T, roll),
                                   front, atol=1e-6)

    def test_exact_head_to_reference_sh1_rotation(self) -> None:
        from scipy.spatial.transform import Rotation
        rng = np.random.default_rng(927)
        coeff = rng.normal(0., .17, (19, 4, 3)).astype(np.float32)
        camera_dirs = rng.normal(size=(19, 3)).astype(np.float32)
        head_to_camera = Rotation.from_euler('xyz', [14., -32., 27.],
                                             degrees=True).as_matrix().astype(np.float32)
        head_dirs = camera_to_point_in_head(camera_dirs, head_to_camera)
        export_coeff = sh1_head_to_reference(coeff, head_to_camera)
        np.testing.assert_allclose(sh1_rgb(head_dirs, coeff),
                                   sh1_rgb(camera_dirs, export_coeff), atol=2e-7)

    def test_degree_one_rgb_matches_installed_gsplat_evaluator(self) -> None:
        if not torch.cuda.is_available():
            self.skipTest("installed gsplat evaluator requires CUDA")
        rng = np.random.default_rng(260928)
        direction = rng.normal(size=(12, 3)).astype(np.float32)
        coeff = rng.normal(0., .1, size=(12, 4, 3)).astype(np.float32)
        observed = spherical_harmonics(1, torch.from_numpy(direction).cuda(),
                                       torch.from_numpy(coeff).cuda()).cpu().numpy()
        expected = np.einsum("ni,nic->nc", sh_basis(direction), coeff)
        np.testing.assert_allclose(observed, expected, atol=2e-7)

    def test_degree_one_basis_order_matches_gsplat(self) -> None:
        sample = sh_basis(np.asarray([[[1., 0., 0.]]], np.float32))
        np.testing.assert_allclose(sample[0, 0], [C0, 0., 0., -C1], atol=1e-7)

    def test_direction_color_conversion_reports_roundtrip_error(self) -> None:
        rng = np.random.default_rng(260927)
        directions = rng.normal(size=(20, 12, 3)).astype(np.float32)
        truth = rng.normal(0, .06, size=(12, 4, 3)).astype(np.float32)
        truth[:, 0] = rng.normal(0, .4, size=(12, 3))
        colors = np.maximum(np.einsum('vni,nic->vnc', sh_basis(directions), truth)+.5, 0.)
        _, report = fit_degree_one(directions, colors)
        self.assertLess(report['meanAbsoluteTrainColorError'], .003)
        self.assertLess(report['p95AbsoluteTrainColorError'], .01)

    def test_ab_rejects_missing_training_result(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(FileNotFoundError, 'completed_900_step_ab_missing'):
                compare(Path(folder))

    def test_face_occluded_hair_projection_is_unknown_not_positive(self) -> None:
        hair = np.zeros((1920, 1080), np.uint8)
        hair[960, 540] = 255
        parts = np.ones_like(hair)
        face_depth = np.full((960, 540), .9, np.float32)
        F = np.eye(4, dtype=np.float32)
        points = np.asarray([[0., 0., 1.], [0., 0., .8]], np.float32)
        positive, empty, unknown = classify_projection(
            points, F, hair, parts, face_depth, visible_positive_only=True)
        np.testing.assert_array_equal(positive, [False, True])
        np.testing.assert_array_equal(empty, [False, False])
        np.testing.assert_array_equal(unknown, [True, False])


if __name__ == '__main__':
    unittest.main()
