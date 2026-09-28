import unittest

from reconstruction_train_joint import check_export_policy, fidelity_warnings


class ReconstructionQualityPolicyTest(unittest.TestCase):
    def setUp(self):
        self.metrics = {
            'gaussians': 130000,
            'editableSplats': 43000,
            'roomSplats': 87000,
            'headPsnrDb': 23.1,
            'roomPsnrDb': 22.1,
            'roomAlpha': .991,
        }

    def test_valid_personal_model_survives_soft_fidelity_miss(self):
        self.assertEqual(fidelity_warnings(self.metrics),
                         ['head_detail_below_review_target'])
        self.assertEqual(check_export_policy(self.metrics, best_effort=True),
                         ['head_detail_below_review_target'])
        with self.assertRaisesRegex(RuntimeError, 'joint_scene_fidelity_gate_failed'):
            check_export_policy(self.metrics, best_effort=False)

    def test_absent_personal_geometry_never_becomes_a_fake_portrait(self):
        self.metrics['editableSplats'] = 0
        with self.assertRaisesRegex(RuntimeError, 'personal_gaussian_geometry_invalid'):
            check_export_policy(self.metrics, best_effort=True)

    def test_invalid_numeric_output_never_reaches_viewer(self):
        self.metrics['roomAlpha'] = float('nan')
        with self.assertRaisesRegex(RuntimeError, 'personal_gaussian_geometry_invalid'):
            check_export_policy(self.metrics, best_effort=True)


if __name__ == '__main__':
    unittest.main()
