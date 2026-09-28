"""Eyewear absence, occlusion and false eye-edge positives stay distinct."""
import unittest

from reconstruction_accessories import EyewearObservation, eyewear_policy, candidate_policy


def observations(state, provenance="audited_semantics", visible=True):
    return [EyewearObservation(str(i), "source", state, provenance, visible, .96) for i in range(3)]


class AccessoriesTest(unittest.TestCase):
    def test_bare_eyes_need_no_accessory_geometry(self):
        result = eyewear_policy(observations("absent"), source_hash="source")
        self.assertEqual(result["state"], "absent_observed")
        self.assertFalse(result["createIndependentAccessory"])
        self.assertEqual(result["eyeSurfacePolicy"], "retain_observed_eye_brow_skin_pixels")

    def test_brows_edges_and_reflections_do_not_establish_glasses(self):
        result = eyewear_policy(observations("present", "edge_candidate"),
                                source_hash="source", geometry_views=["0", "1", "2"])
        self.assertEqual(result["state"], "unknown")
        self.assertFalse(result["createIndependentAccessory"])

    def test_glasses_need_semantics_and_real_depth_support(self):
        obs = observations("present")
        self.assertFalse(eyewear_policy(obs, source_hash="source")["createIndependentAccessory"])
        self.assertTrue(eyewear_policy(obs, source_hash="source",
                        geometry_views=["0", "1", "2"])["createIndependentAccessory"])

    def test_occlusion_is_not_absence(self):
        result = eyewear_policy(observations("absent", visible=False), source_hash="source")
        self.assertEqual(result["state"], "unknown")

    def test_removing_glasses_during_capture_does_not_merge_states(self):
        obs = observations("present") + [EyewearObservation("3", "source", "absent", "audited_semantics", True, .99)]
        result = eyewear_policy(obs, source_hash="source", geometry_views=["0", "1", "2"])
        self.assertEqual(result["state"], "mixed_or_uncertain")
        self.assertFalse(result["createIndependentAccessory"])

    def test_duplicate_frames_and_foreign_sources_are_not_votes(self):
        with self.assertRaises(ValueError):
            eyewear_policy(observations("present")*2, source_hash="source")
        with self.assertRaises(ValueError):
            eyewear_policy(observations("present"), source_hash="other")

    def test_empty_component_is_valid_and_preserves_unknown(self):
        result = candidate_policy({"sourceHash":"source", "local":{}}, [])
        self.assertEqual(result["candidateSegments"], 0)
        self.assertFalse(result["automaticPromotion"])
        self.assertEqual(result["state"], "unknown")


if __name__ == "__main__": unittest.main()
