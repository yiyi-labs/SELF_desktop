import unittest

import numpy as np

from research_face_surface_refinement import PARAMETERS, split_surface


class ParentReplacementTest(unittest.TestCase):
    def test_selected_coarse_basis_is_replaced_and_binding_survives(self):
        n, surface = 32, 30
        bary = np.tile(np.array([[.3, .3, .4]], np.float32), (surface, 1))
        candidate = {
            "surface_count": surface, "roles": np.array([0]*surface+[2, 2]),
            "surface_ids": np.arange(surface, dtype=np.int32),
            "surface_bary": bary.copy(),
            "initial_rgb": np.zeros((n, 3), np.float32),
            "initial_scale": np.ones((n, 3), np.float32),
            "source_index": np.arange(n, dtype=np.int32),
            "origin_index": np.arange(n, dtype=np.int32),
            "confidence": np.full(n, 3, np.uint8),
            "counts": {"skin": surface, "hair": 2},
        }
        params = {key: np.zeros((n, 3), np.float32) for key in PARAMETERS}
        params["opacity_logits"] = np.full(n, -1., np.float32)
        selected = np.arange(25)
        output, expanded, event, picked = split_surface(
            candidate, params, selected, np.arange(n)[::-1], 25,
            replace_parent=True)
        self.assertTrue(event["coarseParentBasisReplaced"])
        self.assertEqual(len(output["roles"]), n+25)
        self.assertFalse(np.array_equal(output["surface_bary"][picked], bary[picked]))
        self.assertFalse(np.array_equal(output["surface_bary"][surface:surface+25],
                                        bary[picked]))
        np.testing.assert_allclose(output["surface_bary"].sum(axis=1), 1., atol=1e-6)
        np.testing.assert_array_equal(output["source_index"][surface:surface+25],
                                      candidate["source_index"][picked])
        self.assertEqual(len(expanded["opacity_logits"]), n+25)
        # The existing historical clone experiment remains reproducible.
        clone, _, clone_event, _ = split_surface(
            candidate, params, selected, np.arange(n)[::-1], 25,
            replace_parent=False)
        self.assertFalse(clone_event["coarseParentBasisReplaced"])
        np.testing.assert_array_equal(clone["surface_bary"][:surface], bary)


if __name__ == "__main__":
    unittest.main()
