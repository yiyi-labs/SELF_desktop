"""Contracts for movable portrait geometry and reversible topology changes."""
import copy
import unittest

import numpy as np
import torch
from scipy.spatial.transform import Rotation

from portrait_model import (LocalPortraitModel, CandidateTransaction,
    GaussianState, evaluate_sh1, mesh_adjacency, walk_embeddings)


def fixture():
    vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [1., 1., 0.]], np.float32)*.1
    faces = np.array([[0, 1, 2], [1, 3, 2]])
    rng = np.random.default_rng(28)
    prior = dict(color_mode="head-local-sh1", source_sha256="source", model_sha256="model",
        role=np.array([0, 1, 2]), surface_ids=np.array([0, 1]),
        surface_bary=np.array([[.2, .4, .4], [.2, .4, .4]], np.float32),
        hair_local_points=np.array([[.01, .08, .01]], np.float32),
        source_index=np.array([6, 19, 7]), origin_index=np.array([0, 1, 2]),
        source_confidence=np.array([5, 3, 8]), local_offsets=np.full((3, 3), .1, np.float32),
        sh_coeff=rng.normal(size=(3, 4, 3)).astype(np.float32)*.1,
        opacity_logits=np.full(3, .5, np.float32), log_scales=np.log(np.full((3, 3), .004, np.float32)),
        local_quats=np.tile(np.array([1, 0, 0, 0], np.float32), (3, 1)))
    model = LocalPortraitModel(prior, faces, vertices, native_metric_per_pixel=.0005)
    return model, prior, torch.from_numpy(vertices)


class PortraitModelTest(unittest.TestCase):
    def test_import_does_not_filter_or_recolor(self):
        model, prior, mesh = fixture()
        state = model.local_state(mesh)
        self.assertEqual(len(state.means), len(prior["role"]))
        np.testing.assert_array_equal(model.source_index.numpy(), prior["source_index"])
        np.testing.assert_array_equal(state.sh.detach().numpy(), prior["sh_coeff"])
        np.testing.assert_allclose(state.scales.detach(), np.exp(prior["log_scales"]), atol=1e-9)
        np.testing.assert_allclose(state.means[-1].detach(), prior["hair_local_points"][0]+np.tanh(.1)*.018, atol=1e-8)

    def test_world_projection_covariance_and_direction_preserved(self):
        model, _, mesh = fixture()
        state = model.local_state(mesh)
        F, C = torch.eye(4), torch.eye(4)
        F[:3, :3] = torch.from_numpy(Rotation.from_rotvec([.3, -.6, .1]).as_matrix()).float()
        C[:3, :3] = torch.from_numpy(Rotation.from_rotvec([-.2, .4, .2]).as_matrix()).float()
        F[:3, 3] = torch.tensor([.02, -.03, .7]); C[:3, 3] = torch.tensor([2., -.3, 1.])
        for scale in (.3, 1., 13.354):
            world = state.to_world(C, F, scale)
            local_camera = state.means@F[:3, :3].T+F[:3, 3]
            world_camera = world.means@C[:3, :3].T+C[:3, 3]
            torch.testing.assert_close(world_camera/scale, local_camera, atol=2e-6, rtol=2e-6)
            sigma_local = F[:3, :3]@state.covariance()@F[:3, :3].T
            sigma_world = C[:3, :3]@world.covariance()@C[:3, :3].T/scale**2
            torch.testing.assert_close(sigma_world, sigma_local, atol=1e-10, rtol=2e-5)
            local_center = -F[:3, :3].T@F[:3, 3]
            world_center = -C[:3, :3].T@C[:3, 3]
            torch.testing.assert_close(evaluate_sh1(state.sh, state.means-local_center),
                                       evaluate_sh1(world.sh, world.means-world_center), atol=2e-6, rtol=2e-6)
            self.assertIs(world.opacity, state.opacity)

    def test_connected_walk_and_semantic_barrier(self):
        model, _, mesh = fixture(); vertices = mesh.numpy(); faces = model.faces.numpy()
        bary = np.array([[-.2, .6, .6]])
        target = bary@vertices[faces[0]]
        ids, moved, changed, blocked = walk_embeddings(vertices, faces, model.adjacency, np.array([0]), bary)
        self.assertEqual(ids[0], 1); self.assertTrue(changed[0]); self.assertEqual(blocked, 0)
        np.testing.assert_allclose(moved@vertices[faces[1]], target, atol=1e-8)
        barrier = mesh_adjacency(vertices, faces, np.array([0, 1]))
        ids, moved, _, blocked = walk_embeddings(vertices, faces, barrier, np.array([0]), bary)
        self.assertEqual(ids[0], 0); self.assertGreater(blocked, 0); self.assertGreaterEqual(moved.min(), 0)

    def test_soft_band_has_scale_gradient_but_no_hair_pressure(self):
        model, _, mesh = fixture()
        loss = model.soft_regularization(mesh)["skinSoftBand"]
        loss.backward()
        self.assertGreater(float(model.log_scales.grad[0].abs().sum()), 0)
        self.assertEqual(float(model.log_scales.grad[1:].abs().sum()), 0)
        self.assertIsNone(model.hair_delta.grad)

    def test_shared_surface_receives_multiview_geometry_gradient(self):
        model, _, mesh = fixture()
        target = model.local_state(mesh).means.detach().clone(); target[0, 2] += .001
        optimizer = torch.optim.Adam([model.surface_residual], lr=.0001)
        before = model.surface_residual.detach().clone()
        (model.local_state(mesh).means-target).square().sum().backward(); optimizer.step()
        self.assertGreater(float((model.surface_residual.detach()-before).abs().sum()), 0)
        # A second expression shares that exact same residual tensor.
        mesh2 = mesh+torch.tensor([0., .002, 0.])
        torch.testing.assert_close(model.local_state(mesh2).means[:2]-model.local_state(mesh).means[:2],
                                   torch.tensor([[0., .002, 0.]]*2), atol=1e-8, rtol=1e-5)

    def test_parent_replacement_and_complete_adam_rollback(self):
        model, _, _ = fixture(); optimizer = torch.optim.Adam(model.parameters(), lr=.001)
        sum(p.square().sum() for p in model.parameters()).backward(); optimizer.step(); optimizer.zero_grad()
        original = copy.deepcopy(model.state_dict()); old_opt = copy.deepcopy(optimizer.state_dict())
        calls = []
        with CandidateTransaction(model, optimizer) as tx:
            def mutate():
                return model.replace_skin_parents([0], optimizer, lambda ids, bary: torch.ones(len(ids), dtype=torch.bool))
            def audit():
                # A small initial coverage drop is allowed recovery; recovered
                # RGB remains wrong and must reject every parameter/state.
                return {"development": {"hole": .1 if len(model.role) == 3 else .11,
                                         "rgb": .1 if len(model.role) == 3 else .2}}
            result = tx.run(mutate, lambda i: calls.append(i), audit, recovery_steps=3)
        self.assertFalse(result["accepted"]); self.assertEqual(len(calls), 3)
        for key, value in original.items(): torch.testing.assert_close(model.state_dict()[key], value, rtol=0, atol=0)
        new_opt = optimizer.state_dict()
        for key, state in old_opt["state"].items():
            for field, value in state.items(): torch.testing.assert_close(new_opt["state"][key][field], value, rtol=0, atol=0)
        for group in optimizer.param_groups:
            self.assertTrue(all(any(p is actual for actual in model.parameters()) for p in group["params"]))

    def test_accepted_children_retire_parent_and_keep_lineage(self):
        model, _, _ = fixture(); optimizer = torch.optim.Adam(model.parameters(), lr=.001)
        model.replace_skin_parents([0], optimizer, lambda ids, bary: torch.ones(len(ids), dtype=torch.bool))
        self.assertEqual(len(model.role), 4); self.assertEqual(model.surface_count, 3)
        self.assertEqual(model.origin_index.tolist(), [1, 0, 0, 2])
        self.assertEqual(model.generation.tolist(), [0, 1, 1, 0])
        self.assertEqual(model.source_index.tolist(), [19, 6, 6, 7])
        self.assertEqual(model.embedding.shape, (3, 3))
        self.assertEqual(model.hair_base.shape, (1, 3))

    def test_one_invalid_child_keeps_its_parent(self):
        model, _, _ = fixture(); model.role[1]=0
        optimizer = torch.optim.Adam(model.parameters(), lr=.001)
        event=model.replace_skin_parents([0,1], optimizer,
            lambda ids,bary:torch.tensor([True,True,True,False]))
        self.assertEqual(event["parentsRetired"],1)
        self.assertEqual(event["rejectedChildEvidence"],1)
        self.assertEqual(model.source_index.tolist(),[19,6,6,7])
        self.assertEqual(model.generation.tolist(),[0,1,1,0])

    def test_invalid_parent_index_and_incomplete_child_evidence(self):
        model, _, _ = fixture(); optimizer = torch.optim.Adam(model.parameters())
        with self.assertRaises(ValueError):
            model.replace_skin_parents([-1],optimizer,lambda ids,bary:None)
        with self.assertRaises(ValueError):
            model.replace_skin_parents([0],optimizer,lambda ids,bary:torch.ones(1,dtype=torch.bool))


if __name__ == "__main__": unittest.main()
