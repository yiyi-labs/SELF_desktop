"""CPU contracts protecting native-canvas audit identity and observations."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from audit_live_scene_display import mask_domains, raw_rgba, validate_camera


class LiveSceneDisplayAuditTests(unittest.TestCase):
    def camera(self):
        return dict(sourceHash="a"*64, reference="frame.png", width=6, height=4,
                    K=[[5, 0, 3], [0, 5, 2], [0, 0, 1]], C=np.eye(4).tolist(), near=.01, far=100.)

    def test_camera_uses_measured_orientation_not_face_look_at(self):
        spec = self.camera()
        spec["target"] = [4, 5, 6]
        actual = validate_camera(spec)
        self.assertEqual(actual["target"], [0., 0., 1.])
        self.assertEqual(actual["up"], [-0., -1., -0.])

    def test_wrong_canvas_or_nonrigid_camera_rejected(self):
        spec = self.camera();spec["width"] = 0
        with self.assertRaisesRegex(ValueError, "canvas"):
            validate_camera(spec)
        spec = self.camera();spec["C"][1][1] = 2
        with self.assertRaisesRegex(ValueError, "rigid"):
            validate_camera(spec)

    def test_sift_room_mask_cannot_silently_be_observed_room(self):
        with self.assertRaisesRegex(ValueError, "observed_room"):
            mask_domains(dict(face=np.ones((4, 6)), room=np.ones((4, 6))), 4, 6)

    def test_full_mask_keeps_missing_pixels_and_requires_native_size(self):
        face = np.zeros((4, 6), bool);face[1:3, 2:4] = True
        masks = mask_domains(dict(face=face, observed_room=~face), 4, 6)
        self.assertEqual(int(masks["full"].sum()), 24)
        self.assertEqual(int(masks["room"].sum()), 20)
        with self.assertRaisesRegex(ValueError, "canvas"):
            mask_domains(dict(face=face, observed_room=~face), 8, 12)

    def test_raw_gl_is_flipped_but_not_alpha_multiplied_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"sample.rgba"
            rgba = np.array([[[64, 0, 0, 128]], [[0, 32, 0, 64]]], np.uint8)
            rgba.tofile(path)
            actual = raw_rgba(path, 2, 1)
            self.assertEqual(float(actual[1, 0, 0]), float(np.float32(64)/255))
            self.assertEqual(float(actual[0, 0, 1]), float(np.float32(32)/255))
            with self.assertRaisesRegex(ValueError, "byte_count"):
                raw_rgba(path, 3, 1)

    def test_independent_semantic_conflict_is_kept_not_trimmed(self):
        face = np.zeros((4, 6), bool);face[1:3, 2:4] = True
        room = np.ones((4, 6), bool)
        masks = mask_domains(dict(face=face, observed_room=room), 4, 6)
        np.testing.assert_array_equal(masks['face'],face)
        np.testing.assert_array_equal(masks['room'],room)


if __name__ == "__main__":
    unittest.main()
