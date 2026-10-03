"""CPU contracts for bounded, photographed skin replacement and protection."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from reconstruction_live_face_capacity import (skin_domain, project_footprint, inside_support,
    continuous_patch, replacement_mapping, replace_patch, masked_step, preservation_gate,
    restore_model_topology, capture_rng, source_base_colour, train_capacity)
from test_reconstruction_portrait_model import fixture


class FaceCapacityTest(unittest.TestCase):
    def test_semantic_unknown_hair_and_glasses_are_not_skin_support(self):
        labels = {k:np.zeros((4, 4), bool) for k in ('training_skin', 'hair_visible', 'glasses_visible', 'unknown_or_occluded')}
        labels['training_skin'][:] = True
        for col, key in enumerate(('hair_visible', 'glasses_visible', 'unknown_or_occluded')): labels[key][0, col] = True
        mask = skin_domain(labels)
        self.assertEqual(int(mask.sum()), 13)
        with self.assertRaises(ValueError): skin_domain({})

    def test_native_covariance_not_radius_and_off_axis_projection(self):
        means = np.array([[0, 0, 1.], [.2, -.1, 1.]])
        cov = np.tile(np.eye(3)*.0001, (2, 1, 1)); F = np.eye(4)
        K = np.array([[1000., 0, 700], [0, 1000., 900], [0, 0, 1.]])
        uv, z, sigma, c2 = project_footprint(means, cov, F, K)
        np.testing.assert_allclose(uv, [[700, 900], [900, 800]])
        self.assertAlmostEqual(sigma[0], 10)
        self.assertGreater(sigma[1], sigma[0])
        np.testing.assert_allclose(c2[0], np.eye(2)*100)
        shifted = K.copy(); shifted[0, 2] += 85
        np.testing.assert_allclose(project_footprint(means, cov, F, shifted)[0]-uv, [[85, 0], [85, 0]])

    def test_footprint_not_just_center_and_conditional_depth(self):
        distance = np.full((64, 64), 12.); depth = np.ones_like(distance); q = np.ones_like(distance)
        uv = np.array([[32, 32], [32, 32], [32, 32], [-1, 32.]])
        valid, _, _ = inside_support(uv, np.array([1, 1, 1.1, 1]), np.array([2, 8, 2, 2]),
            distance, depth, q, np.full(4, .001), depth_sigma=np.full(4, .002))
        self.assertEqual(valid.tolist(), [True, False, False, False])

    def test_connected_patch_does_not_jump_to_nearby_other_surface(self):
        xy = np.array([[x, y, 0.] for y in range(4) for x in range(4)], float)*.01
        pts = np.concatenate((xy, xy+[0, 0, .0001]))
        normals = np.tile([0, 0, 1.], (32, 1)); ids = np.r_[np.zeros(16, int), np.ones(16, int)]
        adjacency = np.full((2, 3), -1, int)
        selected, _ = continuous_patch(pts, normals, ids, adjacency, np.ones(32, bool), np.arange(32), max_parents=12)
        self.assertTrue(len(set(ids[selected])) == 1)
        self.assertLessEqual(len(selected), 12)

    def test_mapping_keeps_original_order_hair_tail_and_retires_parents(self):
        mapping, children, chosen = replacement_mapping(6, 4, [0, 2], [True, False])
        self.assertEqual(mapping.tolist(), [1, 2, 3, 0, 0, 4, 5])
        self.assertEqual(children.tolist(), [3, 4]); self.assertEqual(chosen.tolist(), [0])

    def test_replacement_preserves_untouched_prior_lineage_and_restores_without_resplitting(self):
        model, _, _ = fixture(); initial = copy.deepcopy(model)
        class Scene: pass
        scene = Scene(); scene.portrait = model; scene.neck_sh_editable = torch.tensor([False, True, False])
        model.initial_embedding[1] = torch.tensor([.3, .3, .4])
        original_other_prior = model.initial_embedding[1].clone()
        optimizer = torch.optim.Adam([getattr(model, k) for k in ('sh','opacity_logits','log_scales','quats')], lr=.001)
        def evidence(scene, data, plan, ids, bary, parents):
            return torch.ones(len(ids), dtype=torch.bool), np.full((len(ids), 3), .4), np.full(len(ids), 4)
        with patch('reconstruction_live_face_capacity.child_observations', side_effect=evidence):
            event, mapping, children, uid, parent = replace_patch(scene, {}, {}, optimizer, [0], np.arange(3), np.full(3, -1))
        self.assertEqual(event['parentsRetired'], 1); self.assertEqual(uid.tolist(), [1, 3, 4, 2])
        self.assertEqual(parent.tolist(), [-1, 0, 0, -1]); self.assertEqual(scene.neck_sh_editable.tolist(), [True, False, False, False])
        self.assertTrue(torch.equal(model.initial_embedding[0], original_other_prior))
        self.assertTrue(torch.equal(model.hair_base, initial.hair_base))
        # Frozen embedding and normal-offset must not add unmapped Adam keys.
        saved_optimizer = copy.deepcopy(optimizer.state_dict())
        self.assertEqual(len(saved_optimizer['param_groups'][0]['params']), 4)
        state = copy.deepcopy(model.state_dict()); restored = copy.deepcopy(initial)
        receipt = restore_model_topology(restored, state)
        self.assertEqual(receipt['pointCount'], 4)
        for key in state: self.assertTrue(torch.equal(restored.state_dict()[key], state[key]), key)
        bad = copy.deepcopy(state); bad['reference_mesh'][0, 0] += 1
        with self.assertRaisesRegex(ValueError, 'immutable'): restore_model_topology(copy.deepcopy(initial), bad)

    def test_invalid_child_not_painted_from_neighbour_or_background(self):
        model, _, _ = fixture()
        class Scene: pass
        scene = Scene(); scene.portrait = model
        optimizer = torch.optim.Adam(model.parameters(), lr=.001); before = copy.deepcopy(model.state_dict())
        def bad(*args): return torch.tensor([False, True]), np.array([[np.nan]*3, [.2]*3]), np.array([0, 4])
        with patch('reconstruction_live_face_capacity.child_observations', side_effect=bad):
            with self.assertRaisesRegex(ValueError, 'child_observation'): replace_patch(scene, {}, {}, optimizer, [0], np.arange(3), np.full(3, -1))
        for key in before: self.assertTrue(torch.equal(before[key], model.state_dict()[key]))

    def test_adam_momentum_cannot_update_protected_point(self):
        params = {k:torch.nn.Parameter(torch.zeros((3, 4, 3) if k=='sh' else (3, 4) if k=='quats' else (3, 3) if k=='log_scales' else (3,)))
                  for k in ('sh','opacity_logits','log_scales','quats')}
        opt = torch.optim.Adam(list(params.values()), lr=.01)
        sum(p.sum() for p in params.values()).backward(); opt.step(); opt.zero_grad()
        frozen = {k:p.detach().clone() for k,p in params.items()}; allowed = torch.tensor([False, True, False])
        sum(p.sum() for p in params.values()).backward()
        masked_step(opt, params, allowed, frozen)
        for key,p in params.items():
            self.assertTrue(torch.equal(p[~allowed], frozen[key][~allowed]))
            self.assertEqual(float(opt.state[p]['exp_avg'][~allowed].abs().sum()), 0.)
            self.assertFalse(torch.equal(p[allowed], frozen[key][allowed]))

    def test_coverage_and_nonpatch_regression_reject_even_lower_rgb(self):
        row = dict(pixels=100, rgb=.02, oldRgb=.04, hole=.02, oldHole=0., edge=.02, oldEdge=.03,
                   protectedMean=0., protectedMax=0.)
        self.assertFalse(preservation_gate({'view':row})['passed'])
        row['hole'] = 0.; row['protectedMax'] = .08
        self.assertFalse(preservation_gate({'view':row})['passed'])
        row['protectedMax'] = 0.
        self.assertTrue(preservation_gate({'view':row})['passed'])
        self.assertFalse(preservation_gate({'view':row})['releaseApproved'])

    def test_rng_state_is_recoverable_not_printed_repr(self):
        state = capture_rng()
        self.assertEqual(state['numpy']['keys'].numel(), 624)
        self.assertIsInstance(state['python'], tuple)

    def test_child_dc_initialization_does_not_double_direction_colour(self):
        from reconstruction_portrait_model import evaluate_sh1
        from appearance_direction_contract import C0
        points = np.array([[.02, 0, .1], [0, .05, .1]], np.float32)
        F = np.eye(4, dtype=np.float32); F[2, 3] = .7
        coeff = np.random.default_rng(3).normal(0, .12, (2, 4, 3)).astype(np.float32)
        camera = -F[:3, :3].T @ F[:3, 3]
        rgb = evaluate_sh1(torch.from_numpy(coeff), torch.from_numpy(points-camera)).numpy()
        dc_rgb = source_base_colour(rgb, points, F, coeff)
        np.testing.assert_allclose((dc_rgb-.5)/C0, coeff[:, 0], atol=3e-7)

    def test_full_short_stage_checkpoint_and_rollback_cpu(self):
        class TinyScene(torch.nn.Module):
            def __init__(self):
                super().__init__(); self.portrait = fixture()[0]
                self.room = torch.nn.Parameter(torch.tensor([.4]))
                self.register_buffer('neck_sh_editable', torch.tensor([False, True, False]))
            def render(self, frame, stage):
                self.assert_stage = stage
                v = sum(getattr(self.portrait, k).sum() for k in ('sh','opacity_logits','log_scales','quats'))*.0001
                return dict(rgb=torch.ones((4, 4, 3))*(.2+v), q=torch.ones((4, 4, 5))*(.8+v))
        def evidence(scene, data, plan, ids, bary, parents):
            return torch.ones(len(ids), dtype=torch.bool), np.full((len(ids), 3), .4), np.full(len(ids), 4)
        row = dict(pixels=16, rgb=.02, oldRgb=.04, hole=0., oldHole=0., edge=.02, oldEdge=.03,
                   protectedMean=0., protectedMax=0.)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); cache = root/'targets'; cache.mkdir()
            mask = np.zeros((4, 4), bool); mask[1:3, 1:3] = True
            np.savez_compressed(cache/'view.npz', target=mask, rgb=np.full((4, 4, 3), .2, np.float32),
                                skin_q=np.full((4, 4), .8, np.float32))
            for capacity in (False, True):
                scene = TinyScene(); before = copy.deepcopy(scene.state_dict())
                plan = dict(selected=np.array([0]), receipt={'estimatedChildrenFromLocalSpacing':[8]})
                targets = dict(train=['view'], directory=str(cache))
                with patch('reconstruction_live_face_capacity.child_observations', side_effect=evidence), \
                     patch('reconstruction_live_face_capacity.representation_metrics', return_value={}), \
                     patch('reconstruction_live_face_capacity.evaluate_patch', return_value={'view':row}), \
                     patch('reconstruction_portrait_pipeline.make_frame', return_value={'rgb':torch.full((4,4,3), .3)}), \
                     patch('reconstruction_portrait_pipeline.surface_contract', return_value={}):
                    report, rollback = train_capacity(scene, {'sourceHash':'synthetic'}, plan, targets,
                        root/('cap' if capacity else 'ctrl'), steps=24, capacity=capacity, rounds=2)
                self.assertEqual(scene.assert_stage, 'T2'); self.assertEqual(report['steps'], 24)
                path = root/('cap' if capacity else 'ctrl')/'capacity-final.pt'
                checkpoint = torch.load(path, weights_only=True)
                self.assertEqual(checkpoint['sampler']['nextStep'], 24)
                self.assertTrue(checkpoint['optimizer']['state'])
                rollback()
                for key in before: self.assertTrue(torch.equal(scene.state_dict()[key], before[key]), key)


if __name__ == '__main__': unittest.main()
