"""Minimal, isolated FLAME 2023 Open forward model for reconstruction research.

This implements linear blend skinning from the model's own topology, weights,
shape/expression bases and pose correctives. It does not include texture data,
SMPL-X code, image fitting, or any product publishing path.
"""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path

import numpy as np
import torch


MODEL_SHA256 = "e75a0990728ba038c7da2a420ae4396f7ddd7781366c13026066c5b24f127623"
MODEL = Path(__file__).resolve().parent / ".sources/third_party/flame2023_open/flame2023_Open.pkl"
STANDARD_MODEL = (Path(__file__).resolve().parent /
                  ".sources/third_party/flame2023_standard/flame2023.pkl")
STANDARD_SHA256 = "8fb1af0db1abb51053ead8fd1f2624a63d01c9602f4a4fb4ea23bd2c82017fa0"
EMBEDDING = Path(__file__).resolve().parent / ".sources/third_party/flame2023_open/mediapipe_landmark_embedding.npz"


class _StoredChumpyArray:
    """Read the official legacy pickle's stored ndarray without Chumpy runtime."""

    def __setstate__(self, state: dict) -> None:
        self.value = state["x"]


class _LegacyModelUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if (module, name) == ("chumpy.ch", "Ch"):
            return _StoredChumpyArray
        return super().find_class(module, name)


def axis_angle_matrix(angles: torch.Tensor) -> torch.Tensor:
    """Differentiable Rodrigues map, including the zero-angle limit."""
    x, y, z = angles.unbind(-1)
    zeros = torch.zeros_like(x)
    skew = torch.stack((zeros, -z, y, z, zeros, -x, -y, x, zeros), -1)
    skew = skew.reshape(*angles.shape[:-1], 3, 3)
    theta = torch.linalg.vector_norm(angles, dim=-1)
    a = torch.sinc(theta / torch.pi)[..., None, None]
    b = (0.5 * torch.sinc(theta / (2 * torch.pi)) ** 2)[..., None, None]
    identity = torch.eye(3, dtype=angles.dtype, device=angles.device)
    return identity + a * skew + b * (skew @ skew)


class FlameOpen(torch.nn.Module):
    def __init__(self, shape_count: int = 20, expression_count: int = 10,
                 model_path: Path = MODEL, embedding_path: Path = EMBEDDING):
        super().__init__()
        if not 1 <= shape_count <= 300 or not 0 <= expression_count <= 100:
            raise ValueError("unsupported_flame_component_count")
        expected_hash = (MODEL_SHA256 if model_path == MODEL else
                         STANDARD_SHA256 if model_path == STANDARD_MODEL else None)
        if expected_hash is None or hashlib.sha256(model_path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError("flame_model_hash_mismatch")
        with model_path.open("rb") as source:
            model = (_LegacyModelUnpickler(source, encoding="latin1").load()
                     if model_path == STANDARD_MODEL else pickle.load(source, encoding="latin1"))
        expression_metadata = model.get("supr_expression_metadata", {})
        if model_path == MODEL and (expression_metadata.get("expr_components") != "last_100"
                                    or expression_metadata.get("n_expr") != 100):
            raise ValueError("flame_open_expression_basis_layout_changed")
        if model_path == STANDARD_MODEL:
            expression_metadata = {"expr_source": "FLAME2023_legacy_basis",
                                   "supr_gender": "not_recorded",
                                   "expr_components": "last_100",
                                   "n_expr": 100}
        faces = np.asarray(model["f"], dtype=np.int64)
        vertices = np.asarray(model["v_template"], dtype=np.float32)
        stored_directions = model["shapedirs"]
        directions = np.asarray(stored_directions.value if isinstance(
            stored_directions, _StoredChumpyArray) else stored_directions, dtype=np.float32)
        posedirs = np.asarray(model["posedirs"], dtype=np.float32)
        weights = np.asarray(model["weights"], dtype=np.float32)
        joint_regressor = np.asarray(model["J_regressor"].toarray(), dtype=np.float32)
        parents = np.asarray(model["kintree_table"][0], dtype=np.int64)
        parents[0] = -1
        if (faces.shape != (9976, 3) or vertices.shape != (5023, 3)
                or directions.shape != (5023, 3, 400)
                or posedirs.shape != (5023, 3, 36)
                or weights.shape != (5023, 5)
                or joint_regressor.shape != (5, 5023)
                or parents.tolist() != [-1, 0, 1, 1, 1]
                or faces.min() < 0 or faces.max() >= len(vertices)
                or not np.allclose(weights.sum(axis=1), 1, atol=1e-5)):
            raise ValueError("flame_open_topology_changed")
        selected = np.concatenate((np.arange(shape_count),
                                   np.arange(300, 300 + expression_count)))
        with np.load(embedding_path) as landmarks:
            landmark_faces = np.asarray(landmarks["lmk_face_idx"], dtype=np.int64)
            barycentric = np.asarray(landmarks["lmk_b_coords"], dtype=np.float32)
            landmark_indices = np.asarray(landmarks["landmark_indices"], dtype=np.int64)
        if (landmark_faces.shape != (105,) or barycentric.shape != (105, 3)
                or landmark_indices.shape != (105,)
                or landmark_faces.min() < 0 or landmark_faces.max() >= len(faces)
                or landmark_indices.min() < 0 or landmark_indices.max() >= 468
                or not np.allclose(barycentric.sum(axis=1), 1, atol=1e-5)):
            raise ValueError("flame_mediapipe_embedding_changed")
        self.shape_count = shape_count
        self.expression_count = expression_count
        self.model_sha256 = expected_hash
        self.model_variant = "FLAME2023Open" if model_path == MODEL else "FLAME2023_standard"
        self.expression_metadata = {key: str(expression_metadata[key])
                                    for key in ("expr_source", "supr_gender",
                                                "expr_components", "n_expr")}
        self.register_buffer("template", torch.from_numpy(vertices))
        self.register_buffer("directions", torch.from_numpy(directions[..., selected]))
        self.register_buffer("pose_directions", torch.from_numpy(posedirs))
        self.register_buffer("joint_regressor", torch.from_numpy(joint_regressor))
        self.register_buffer("skinning_weights", torch.from_numpy(weights))
        self.register_buffer("faces", torch.from_numpy(faces))
        self.register_buffer("landmark_faces", torch.from_numpy(landmark_faces))
        self.register_buffer("barycentric", torch.from_numpy(barycentric))
        self.register_buffer("landmark_indices", torch.from_numpy(landmark_indices))
        self.parents = tuple(int(parent) for parent in parents)

    def forward(self, shape: torch.Tensor, expression: torch.Tensor,
                pose: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Return posed vertices and the 105 MediaPipe-corresponding points.

        pose order is root, neck, jaw, left eye, right eye; each is axis-angle.
        Root pose does not alter identity shape or the fixed world scale.
        """
        batch = shape.shape[0]
        if (shape.shape != (batch, self.shape_count)
                or expression.shape != (batch, self.expression_count)
                or pose.shape != (batch, 5, 3)):
            raise ValueError("flame_parameter_shape_mismatch")
        betas = torch.cat((shape, expression), dim=1)
        shaped = self.template[None] + torch.einsum("vci,bi->bvc", self.directions, betas)
        joints = torch.einsum("jv,bvc->bjc", self.joint_regressor, shaped)
        rotations = axis_angle_matrix(pose)
        pose_feature = (rotations[:, 1:] - torch.eye(3, device=pose.device,
                                                     dtype=pose.dtype)).reshape(batch, 36)
        posed = shaped + torch.einsum("vci,bi->bvc", self.pose_directions, pose_feature)
        global_rotations: list[torch.Tensor] = []
        global_translations: list[torch.Tensor] = []
        for joint, parent in enumerate(self.parents):
            rotation = rotations[:, joint]
            offset = joints[:, joint] if parent == -1 else joints[:, joint] - joints[:, parent]
            if parent != -1:
                rotation = global_rotations[parent] @ rotation
                offset = (global_rotations[parent] @ offset[..., None])[..., 0] + global_translations[parent]
            global_rotations.append(rotation)
            global_translations.append(offset)
        rotations_all = torch.stack(global_rotations, dim=1)
        translations_all = torch.stack(global_translations, dim=1)
        rest_corrected = translations_all - (rotations_all @ joints[..., None])[..., 0]
        vertex_rotation = torch.einsum("vj,bjkl->bvkl", self.skinning_weights, rotations_all)
        vertex_translation = torch.einsum("vj,bjk->bvk", self.skinning_weights, rest_corrected)
        vertices = (vertex_rotation @ posed[..., None])[..., 0] + vertex_translation
        triangles = vertices[:, self.faces[self.landmark_faces]]
        landmarks = (triangles * self.barycentric[None, :, :, None]).sum(dim=2)
        return vertices, landmarks
