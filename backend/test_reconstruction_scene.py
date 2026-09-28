"""Geometry checks for room visibility and optional clothing continuity."""

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from reconstruction_scene import foreground_clearance, make_environment_masks


class RecordedSceneTest(unittest.TestCase):
    def test_room_splats_cannot_cross_head_from_front_or_sixty_five_degrees(self):
        # Camera is on +Z. A rear point survives; a near-left point that
        # would cross the face at an oblique view is rejected.
        points = np.array([[0, 0, -3], [0, 0, 2], [-2, 0, 1], [7, 0, 1]])
        keep = foreground_clearance(points, [0, 0, 0], [0, 0, 1], [0, 1, 0],
                                    [1, 1.5, .5], splat_radius=.1)
        self.assertEqual(keep.tolist(), [True, False, False, True])

    def test_clothing_area_can_remain_in_room_mask_below_head(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scene_exclusions").mkdir()
            excluded = np.zeros((300, 300), dtype=np.uint8)
            cv2.circle(excluded, (150, 90), 30, 255, -1)
            cv2.imwrite(str(root / "scene_exclusions" / "frame.png.png"), excluded)
            output = make_environment_masks(root, ["frame.png"])
            mask = cv2.imread(str(output / "frame.png.png"), cv2.IMREAD_GRAYSCALE)
            self.assertEqual(int(mask[90, 150]), 0)
            self.assertEqual(int(mask[125, 150]), 255)
            self.assertEqual(int(mask[230, 150]), 255)


if __name__ == "__main__":
    unittest.main()
