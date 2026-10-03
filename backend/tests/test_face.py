"""Small geometric checks; run with the WSL reconstruction Python."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image

from face import head_box, make_head_mask, make_static_feature_mask
from train import observed_head_splats


class HeadMaskTest(unittest.TestCase):
    def test_envelope_preserves_profile_margin(self):
        landmarks = [SimpleNamespace(x=x, y=y) for x, y in
                     ((.4, .2), (.6, .2), (.4, .6), (.6, .6))]
        x, y, w, h = head_box(landmarks, 1000, 1000)
        self.assertLess(x, 400)
        self.assertGreater(x + w, 600)
        self.assertLess(y, 200)
        self.assertGreater(y + h, 600)

    def test_mask_rejects_distant_background(self):
        layers = [np.zeros((100, 100), dtype=np.float32) for _ in range(6)]
        cv2.circle(layers[3], (50, 45), 13, 1, -1)
        cv2.circle(layers[1], (50, 30), 11, 1, -1)
        cv2.circle(layers[3], (5, 5), 4, 1, -1)
        mask, fraction = make_head_mask(layers, (20, 15, 60, 70), 100, 100)
        self.assertEqual(int(mask[45, 50]), 255)
        self.assertEqual(int(mask[5, 5]), 0)
        self.assertLess(fraction, .4)

    def test_static_camera_shadow_mask_excludes_accessory(self):
        layers = [np.zeros((64, 64), dtype=np.float32) for _ in range(6)]
        layers[0][:] = .1
        layers[5][27:37, 27:37] = .9
        static = make_static_feature_mask(layers, np.zeros((64, 64), np.uint8))
        self.assertEqual(int(static[32, 32]), 0)
        self.assertEqual(int(static[0, 0]), 255)

    def test_splat_support_keeps_only_observed_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "face_masks").mkdir()
            mask = np.zeros((100, 100), dtype=np.uint8)
            mask[25:75, 25:75] = 255
            Image.fromarray(mask).save(root / "face_masks" / "frame.png.png")
            k = np.asarray([[50, 0, 50], [0, 50, 50], [0, 0, 1]], dtype=np.float32)
            cameras = [(Path("frame.png"), np.eye(4, dtype=np.float32), k, 100, 100)]
            means = np.asarray([[0, 0, 2], [1.8, 0, 2], [0, 0, -2]], dtype=np.float32)
            self.assertEqual(observed_head_splats(root, cameras, means).tolist(),
                             [True, False, False])


if __name__ == "__main__":
    unittest.main()
