"""Numerical contract for the locally downloaded FLAME 2023 Open model."""

import unittest

import torch

from flame_open_model import EMBEDDING, MODEL, FlameOpen, axis_angle_matrix


@unittest.skipUnless(MODEL.is_file() and EMBEDDING.is_file(),
                     "official FLAME Open research assets are not installed")
class FlameOpenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = FlameOpen(shape_count=8, expression_count=4)

    def test_neutral_matches_template_and_embedding(self):
        zeros = torch.zeros(1, 5, 3)
        vertices, landmarks = self.model(torch.zeros(1, 8), torch.zeros(1, 4), zeros)
        self.assertTrue(torch.allclose(vertices[0], self.model.template, atol=2e-6))
        expected = (self.model.template[self.model.faces[self.model.landmark_faces]]
                    * self.model.barycentric[..., None]).sum(dim=1)
        self.assertTrue(torch.allclose(landmarks[0], expected, atol=2e-6))

    def test_root_rotation_preserves_geometry(self):
        pose = torch.zeros(1, 5, 3)
        pose[0, 0, 1] = 0.47
        vertices, landmarks = self.model(torch.zeros(1, 8), torch.zeros(1, 4), pose)
        rotation = axis_angle_matrix(pose[:, 0])[0]
        joint = self.model.joint_regressor @ self.model.template
        expected = (self.model.template - joint[0]) @ rotation.T + joint[0]
        self.assertTrue(torch.allclose(vertices[0], expected, atol=2e-6))
        self.assertTrue(torch.isfinite(landmarks).all())

    def test_shape_expression_jaw_gradients(self):
        shape = torch.zeros(1, 8, requires_grad=True)
        expression = torch.zeros(1, 4, requires_grad=True)
        pose = torch.zeros(1, 5, 3)
        pose[0, 2, 0] = 0.1
        pose.requires_grad_()
        _, landmarks = self.model(shape, expression, pose)
        landmarks.square().sum().backward()
        for tensor in (shape, expression, pose):
            self.assertTrue(torch.isfinite(tensor.grad).all())
        self.assertGreater(float(shape.grad.abs().sum()), 0)
        self.assertGreater(float(expression.grad.abs().sum()), 0)
        self.assertGreater(float(pose.grad[:, 2].abs().sum()), 0)


if __name__ == "__main__":
    unittest.main()
