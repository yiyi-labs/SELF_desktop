import copy
from dataclasses import replace
import unittest
import numpy as np
from scipy.spatial.transform import Rotation

from reconstruction_live_surface_footprint import (FootprintConfig, adapt_surface_footprints,
    adapt_observed_surface_footprints, observed_skin_semantics, _covariance)


def plane(size=13, dx=.002, dy=.002):
    x, y = np.meshgrid(np.arange(size)*dx, np.arange(size)*dy)
    vertices = np.stack((x-x.mean(), y-y.mean(), np.ones_like(x)), -1).reshape(-1, 3)
    faces = []
    for j in range(size-1):
        for i in range(size-1):
            a = j*size+i
            faces.extend(((a, a+size, a+1), (a+1, a+size, a+size+1)))
    faces = np.asarray(faces, np.int32); s = len(faces)
    prior = dict(source_sha256=np.asarray('test-source'), model_sha256=np.asarray('test-model'),
        color_mode=np.asarray('head-local-sh1'), role=np.zeros(s, np.int64),
        surface_ids=np.arange(s, dtype=np.int32), surface_bary=np.full((s, 3), 1/3, np.float64),
        local_quats=np.tile([1., 0, 0, 0], (s, 1)), log_scales=np.tile(np.log([.007, .007, .0018]), (s, 1)),
        opacity_logits=np.full(s, 1.), local_offsets=np.zeros((s, 3)),
        sh_coeff=np.random.default_rng(3).normal(size=(s, 4, 3)), source_index=np.arange(s),
        origin_index=np.arange(s), source_confidence=np.full(s, 6), hair_local_points=np.empty((0, 3)))
    return prior, vertices, faces


def adapt(prior, mesh, faces, **kwargs):
    return adapt_surface_footprints(prior, mesh, faces, triangle_regions=kwargs.pop('regions', np.zeros(len(faces), np.int32)),
        point_eligible=kwargs.pop('eligible', np.ones(len(prior['role']), bool)), prior_stage=kwargs.pop('prior_stage', 'fresh_initialization'), **kwargs)


def data_for(prior, mesh, shape=(128, 128)):
    zero = np.zeros(shape, bool); one = ~zero
    labels = {k: zero.copy() for k in ('hair_visible', 'glasses_visible', 'unknown_or_occluded')}
    labels.update(training_skin=one.copy(), training_face=one.copy())
    names = ['first', 'second', 'third']
    return dict(sourceHash='test-source', reference='first', K=np.array([[1000., 0, 64], [0, 1000., 64], [0, 0, 1]]),
        local={name: dict(mesh=mesh.copy(), F=np.eye(4), role='train') for name in names},
        labels={name: copy.deepcopy(labels) for name in names})


def plane_depth(mesh, F, K, w, h):
    return np.full((h, w), (mesh[0]@F[:3, :3].T+F[:3, 3])[:, 2].min(), np.float32)


class SurfaceFootprintTests(unittest.TestCase):
    def test_actual_adaptation_preserves_every_other_field_and_normal_variance(self):
        p, mesh, faces = plane(); original = copy.deepcopy(p)
        output, receipt, diag = adapt(p, mesh, faces)
        self.assertGreater(receipt['changedCount'], 20)
        self.assertGreater(receipt['reasons'].get('bounded_scale_ratio_fallback', 0), 0)
        for key in p:
            np.testing.assert_array_equal(p[key], original[key])
            if key not in ('log_scales', 'local_quats'): np.testing.assert_array_equal(output[key], p[key])
        changed = diag['changed']
        new_cov = _covariance(np.exp(output['log_scales']), output['local_quats'])
        old_cov = _covariance(np.exp(p['log_scales']), p['local_quats'])
        np.testing.assert_allclose(new_cov[changed, 2, 2], old_cov[changed, 2, 2], rtol=1e-10)
        self.assertLess(np.median(diag['proposed_tangent_sigma'][changed]), .007)
        required = np.minimum(.8, np.maximum(0, diag['local_proxy_before'][changed]-.15))
        self.assertTrue((diag['local_proxy_after'][changed] >= required).all())

    def test_non_skin_roles_and_unproven_semantics_are_bitwise_untouched(self):
        p, mesh, faces = plane(); p['role'][20:35] = 1
        eligible = np.ones(len(p['role']), bool); eligible[70:90] = False
        regions = np.zeros(len(faces), np.int32); regions[100:130] = -1
        output, _, diag = adapt(p, mesh, faces, eligible=eligible, regions=regions)
        protected = (p['role'] != 0) | ~eligible | (regions < 0)
        self.assertFalse(diag['changed'][protected].any())
        for key in ('local_quats', 'log_scales'): np.testing.assert_array_equal(output[key][protected], p[key][protected])

    def test_appended_hair_is_not_reoriented_or_rescaled(self):
        p, mesh, faces = plane(); s = len(p['role'])
        for key in ('role', 'local_quats', 'log_scales', 'opacity_logits', 'local_offsets', 'sh_coeff',
                    'source_index', 'origin_index', 'source_confidence'):
            p[key] = np.concatenate((p[key], p[key][-1:]))
        p['role'][-1] = 2; p['hair_local_points'] = np.array([[.05, .01, 1.01]])
        output, receipt, diag = adapt(p, mesh, faces)
        self.assertGreater(receipt['changedCount'], 0); self.assertFalse(diag['changed'][-1])
        for key in ('role', 'local_quats', 'log_scales', 'opacity_logits', 'local_offsets', 'sh_coeff'):
            np.testing.assert_array_equal(output[key][s:], p[key][s:])

    def test_degenerate_triangle_does_not_produce_fake_covariance(self):
        p, mesh, faces = plane(); p['surface_ids'][0] = len(faces)
        faces = np.concatenate((faces, np.array([[0, 0, 0]])))
        output, _, diag = adapt(p, mesh, faces)
        self.assertEqual(diag['reason'][0], 'degenerate_surface')
        for key in ('local_quats', 'log_scales'): np.testing.assert_array_equal(output[key][0], p[key][0])

    def test_disconnected_nearby_surface_never_enters_neighbourhood(self):
        p, mesh, faces = plane(); n = len(p['role']); nv = len(mesh)
        mesh2 = mesh.copy(); mesh2[:, 2] += .00002
        joined = {k: np.concatenate((v, v)) if v.ndim and k not in ('hair_local_points',) else v.copy() for k, v in p.items()}
        joined['surface_ids'] = np.arange(n*2); joined['origin_index'] = np.arange(n*2)
        vertices = np.concatenate((mesh, mesh2)); triangles = np.concatenate((faces, faces+nv))
        _, receipt, diag = adapt(joined, vertices, triangles)
        self.assertGreater(receipt['changedCount'], 0)
        for index, neighbours in enumerate(diag['neighbour_indices']):
            neighbours = neighbours[neighbours >= 0]
            self.assertTrue(((neighbours < n) == (index < n)).all())

    def test_semantic_barrier_blocks_adjacent_triangles(self):
        p, mesh, faces = plane(); regions = (mesh[faces].mean(1)[:, 0] > 0).astype(np.int32)
        _, _, diag = adapt(p, mesh, faces, regions=regions)
        for point, near in enumerate(diag['neighbour_indices']):
            near = near[near >= 0]
            self.assertTrue((regions[near] == regions[point]).all())

    def test_rotation_equivariance(self):
        p, mesh, faces = plane(); out, _, diag = adapt(p, mesh, faces)
        R = Rotation.from_rotvec([.31, -.42, .12]).as_matrix(); rotated = copy.deepcopy(p)
        rotated['local_quats'] = Rotation.from_matrix(np.tile(R, (len(p['role']), 1, 1))).as_quat()[:, [3, 0, 1, 2]]
        result, _, rotated_diag = adapt(rotated, mesh@R.T, faces)
        shared = diag['changed'] & rotated_diag['changed']; self.assertGreater(shared.sum(), 20)
        c = _covariance(np.exp(out['log_scales']), out['local_quats'])
        rc = _covariance(np.exp(result['log_scales']), result['local_quats'])
        # Equidistant lattice-neighbour ties can rotate a weak anisotropic axis;
        # compare invariant tangent area/normal variance rather than tie identity.
        np.testing.assert_allclose(np.linalg.det(rc[shared]), np.linalg.det(c[shared]), rtol=.10)
        normal = R[:, 2]
        np.testing.assert_allclose(np.einsum('i,nij,j->n', normal, rc[shared], normal), .0018**2, rtol=1e-10)

    def test_unit_scale_equivariance(self):
        p, mesh, faces = plane(); out, _, diag = adapt(p, mesh, faces)
        ratio = 1000.; scaled = copy.deepcopy(p); scaled['log_scales'] += np.log(ratio)
        c = replace(FootprintConfig(), activation_scale_floor=.00045*ratio, activation_scale_ceiling=.018*ratio)
        result, _, scaled_diag = adapt(scaled, mesh*ratio, faces, config=c)
        both = diag['changed'] & scaled_diag['changed']; self.assertGreater(both.sum(), 20)
        a = _covariance(np.exp(out['log_scales']), out['local_quats'])
        b = _covariance(np.exp(result['log_scales']), result['local_quats'])/ratio**2
        np.testing.assert_allclose(np.linalg.det(a[both]), np.linalg.det(b[both]), rtol=.10)

    def test_sparse_unknown_and_activation_floor_fallback(self):
        p, mesh, faces = plane()
        out, receipt, _ = adapt(p, mesh, faces, regions=np.full(len(faces), -1))
        self.assertEqual(receipt['changedCount'], 0)
        np.testing.assert_array_equal(out['log_scales'], p['log_scales'])
        p['log_scales'][:] = np.log(.0001)
        _, receipt, diag = adapt(p, mesh, faces)
        self.assertEqual(receipt['changedCount'], 0)
        self.assertTrue((diag['reason'] == 'input_activation_range_fallback').all())

    def test_reject_trained_checkpoint_and_malformed_binding(self):
        p, mesh, faces = plane()
        with self.assertRaisesRegex(ValueError, 'only_fresh'): adapt(p, mesh, faces, prior_stage='trained')
        p['surface_bary'][0] = [-.2, .6, .6]
        with self.assertRaisesRegex(ValueError, 'binding_contract'): adapt(p, mesh, faces)

    def test_semantic_adapter_uses_three_train_observations_not_dev(self):
        p, mesh, faces = plane(); data = data_for(p, mesh)
        # An unusable development row is deliberately never inspected.
        data['local']['held'] = dict(role='development'); data['labels']['held'] = None
        proof = observed_skin_semantics(p, data, faces, depth_function=plane_depth)
        self.assertTrue(proof['point_eligible'].all()); self.assertTrue((proof['triangle_support'] == 3).all())
        data['local']['third']['role'] = 'development'
        proof = observed_skin_semantics(p, data, faces, depth_function=plane_depth)
        self.assertFalse(proof['point_eligible'].any())

    def test_hair_unknown_detail_and_prior_occlusion_exclude_that_view(self):
        p, mesh, faces = plane(); data = data_for(p, mesh)
        for key in ('hair_visible', 'glasses_visible', 'unknown_or_occluded'):
            candidate = copy.deepcopy(data); candidate['labels']['second'][key][:] = True
            proof = observed_skin_semantics(p, candidate, faces, depth_function=plane_depth)
            self.assertFalse(proof['point_eligible'].any())
        candidate = copy.deepcopy(data); candidate['labels']['second']['training_skin'][:] = False
        proof = observed_skin_semantics(p, candidate, faces, depth_function=plane_depth)
        self.assertFalse(proof['point_eligible'].any())
        proof = observed_skin_semantics(p, data, faces, depth_function=lambda m, F, K, w, h: np.full((h, w), .5))
        self.assertFalse(proof['point_eligible'].any())
        # Three other valid observations still support the same physical skin.
        candidate['local']['fourth'] = copy.deepcopy(data['local']['first'])
        candidate['labels']['fourth'] = copy.deepcopy(data['labels']['first'])
        proof = observed_skin_semantics(p, candidate, faces, depth_function=plane_depth)
        self.assertTrue(proof['point_eligible'].all())

    def test_native_sigma_receipt_and_anisotropic_density(self):
        p, mesh, faces = plane(dy=.0035); data = data_for(p, mesh)
        output, receipt, diag = adapt_observed_surface_footprints(p, data, faces,
            prior_stage='fresh_initialization', depth_function=plane_depth)
        changed = diag['changed']; self.assertGreater(changed.sum(), 20)
        self.assertLess(receipt['nativeSigmaAfter']['median'], receipt['nativeSigmaBefore']['median'])
        self.assertGreater(np.max(diag['proposed_tangent_sigma'][changed, 1]/diag['proposed_tangent_sigma'][changed, 0]), 1.01)
        self.assertFalse(receipt['acceptedQuality']); self.assertFalse(receipt['proxyIsActualRasterCoverage'])
        self.assertFalse(receipt['semantics']['heldoutImagesRead'])


if __name__ == '__main__': unittest.main()
