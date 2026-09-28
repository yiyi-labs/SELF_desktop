"""Coordinate contract for degree-one head-local color and a static GS PLY.

F maps head-local column points to camera points. Arrays of directions below
are row vectors. gsplat evaluates SH with camera-to-point directions and adds
0.5 before clamping; no sigmoid is part of its SH path.
"""

from __future__ import annotations

import numpy as np

C0 = 0.2820947917738781
C1 = 0.48860251190292


def unit(v: np.ndarray) -> np.ndarray:
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-8)


def camera_to_point_in_head(camera_points: np.ndarray, head_to_camera: np.ndarray) -> np.ndarray:
    """For p_c=R p_h+t, return normalized camera-to-point rays in head space."""
    return unit(camera_points) @ head_to_camera


def sh1_basis(direction: np.ndarray) -> np.ndarray:
    d = unit(direction)
    return np.stack((np.full(d.shape[:-1], C0, np.float32),
                     -C1*d[..., 1], C1*d[..., 2], -C1*d[..., 0]), axis=-1)


def sh1_head_to_reference(coeff_head: np.ndarray, head_to_reference: np.ndarray) -> np.ndarray:
    """Rotate degree-one SH exactly from head axes to one frozen PLY frame."""
    result = coeff_head.copy()
    # SH linear contribution is v dot d where v=C1*(-c3,-c1,c2).
    vector_head = C1*np.stack((-coeff_head[:, 3], -coeff_head[:, 1],
                               coeff_head[:, 2]), axis=1)
    vector_reference = np.einsum("ij,njc->nic", head_to_reference, vector_head)
    result[:, 1] = -vector_reference[:, 1]/C1
    result[:, 2] = vector_reference[:, 2]/C1
    result[:, 3] = -vector_reference[:, 0]/C1
    return result


def sh1_rgb(direction: np.ndarray, coeff: np.ndarray) -> np.ndarray:
    return np.maximum(np.einsum("...i,...ic->...c", sh1_basis(direction), coeff)+.5, 0.)
