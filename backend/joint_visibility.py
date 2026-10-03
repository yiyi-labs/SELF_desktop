"""Shared-visibility diagnostics for a recorded person and environment GS.

The legacy trainer fitted the head under a pose-compensated camera while
hiding the environment.  For a recorded frame this module instead moves only
the head into that frame's world pose and rasterizes *all* points together.
It is an isolated diagnostic, never a viewer-time occlusion override.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from gsplat.cuda._wrapper import spherical_harmonics
from gsplat.rendering import rasterization
from scipy.spatial.transform import Rotation

from probe_gs_contract import read_float_ply


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_recorded_ply(path: Path, editable_splats: int, device: str = "cuda") -> dict:
    data = read_float_ply(path)
    count = len(data["x"])
    if not 0 < editable_splats < count:
        raise ValueError("editable_splat_partition_invalid")
    field = lambda names: np.stack([data[name] for name in names], axis=1)
    dc = field([f"f_dc_{axis}" for axis in range(3)])[:, None]
    rest = field([f"f_rest_{axis}" for axis in range(45)]).reshape(count, 3, 15).transpose(0, 2, 1)
    person_mask = torch.arange(count, device=device) < editable_splats
    return {
        "means": torch.from_numpy(field(("x", "y", "z"))).to(device),
        "quats": torch.from_numpy(field([f"rot_{axis}" for axis in range(4)])).to(device),
        "scales": torch.from_numpy(np.exp(field([f"scale_{axis}" for axis in range(3)]))).to(device),
        "opacity": torch.from_numpy(1 / (1 + np.exp(-data["opacity"]))).to(device),
        "sh": torch.from_numpy(np.concatenate((dc, rest), axis=1).copy()).to(device),
        "person_count": editable_splats,
        "person_mask": person_mask,
        "ply_sha256": sha256_file(path),
    }


def quaternion_multiply(left: torch.Tensor, right: torch.Tensor) -> torch.Tensor:
    aw, ax, ay, az = left.unbind(-1)
    bw, bx, by, bz = right.unbind(-1)
    return torch.stack((aw*bw-ax*bx-ay*by-az*bz,
                        aw*bx+ax*bw+ay*bz-az*by,
                        aw*by-ax*bz+ay*bw+az*bx,
                        aw*bz+ax*by-ay*bx+az*bw), dim=-1)


def posed_points(asset: dict, world_w2c: np.ndarray,
                 corrected_face_w2c: np.ndarray) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Return current-world means/quats and per-point camera-to-point rays.

    The corrected training camera equals C_t @ H_t @ inverse(H_reference).
    Therefore inverse(C_t) @ corrected_camera is the relative head transform.
    It becomes identity at the recorded reference, without assuming the
    absolute head matrix is identity.  Static scene splats are not moved.
    """
    world_w2c = np.asarray(world_w2c, dtype=np.float64)
    corrected_face_w2c = np.asarray(corrected_face_w2c, dtype=np.float64)
    if world_w2c.shape != (4, 4) or corrected_face_w2c.shape != (4, 4):
        raise ValueError("pose_shape_invalid")
    if not (np.isfinite(world_w2c).all() and np.isfinite(corrected_face_w2c).all()):
        raise ValueError("pose_nonfinite")
    relative = np.linalg.inv(world_w2c) @ corrected_face_w2c
    if np.linalg.det(relative[:3, :3]) < .99 or np.linalg.det(relative[:3, :3]) > 1.01:
        raise ValueError("relative_head_rotation_invalid")
    means = asset["means"]
    mask = asset["person_mask"]
    if mask.shape != (len(means),) or mask.dtype != torch.bool:
        raise ValueError("person_motion_mask_invalid")
    transform = torch.as_tensor(relative, device=means.device, dtype=means.dtype)
    moved_means = means @ transform[:3, :3].T + transform[:3, 3]
    current_means = torch.where(mask[:, None], moved_means, means)
    xyzw = Rotation.from_matrix(relative[:3, :3]).as_quat()
    rotation = torch.as_tensor(xyzw[[3, 0, 1, 2]].copy(), device=means.device,
                               dtype=means.dtype)
    moved_quats = quaternion_multiply(rotation, asset["quats"])
    current_quats = torch.where(mask[:, None], moved_quats, asset["quats"])
    # Head SH was fitted in the reference axes.  Evaluate it against the
    # corrected head camera, while room SH uses the actual world camera.
    face_center = np.linalg.inv(corrected_face_w2c)[:3, 3]
    room_center = np.linalg.inv(world_w2c)[:3, 3]
    face_center = torch.as_tensor(face_center, device=means.device, dtype=means.dtype)
    room_center = torch.as_tensor(room_center, device=means.device, dtype=means.dtype)
    rays = torch.where(mask[:, None], means-face_center, means-room_center)
    return current_means, current_quats, rays


def render_shared(asset: dict, world_w2c: np.ndarray, corrected_face_w2c: np.ndarray,
                  K: np.ndarray, width: int, height: int,
                  opacity_override: torch.Tensor | None = None,
                  point_probe: bool = False, degree: int = 3,
                  antialiased: bool = False) -> dict:
    means, quats, rays = posed_points(asset, world_w2c, corrected_face_w2c)
    mask = asset["person_mask"]
    rgb = torch.clamp_min(spherical_harmonics(degree, rays, asset["sh"]) + .5, 0.)
    groups = torch.zeros((len(means), 2), device=means.device, dtype=means.dtype)
    groups[:, 0] = mask.to(means.dtype)
    groups[:, 1] = (~mask).to(means.dtype)
    features = torch.cat((rgb, groups), dim=1)
    probe = None
    if point_probe:
        probe = torch.zeros((len(means), 1), device=means.device,
                            dtype=means.dtype, requires_grad=True)
        features = torch.cat((features, probe), dim=1)
    opacity = asset["opacity"] if opacity_override is None else opacity_override
    if opacity.shape != asset["opacity"].shape:
        raise ValueError("opacity_override_shape_invalid")
    frame, alpha, info = rasterization(
        means, quats, asset["scales"], opacity, features,
        torch.as_tensor(world_w2c, device=means.device, dtype=means.dtype)[None],
        torch.as_tensor(K, device=means.device, dtype=means.dtype)[None],
        width, height, packed=True, sh_degree=None, near_plane=.01,
        rasterize_mode="antialiased" if antialiased else "classic")
    return {"rgb": frame[0, :, :, :3], "q_person": frame[0, :, :, 3],
            "q_environment": frame[0, :, :, 4], "alpha": alpha[0, :, :, 0],
            "point_probe": probe, "probe_image": frame[0, :, :, 5] if point_probe else None,
            "projection": info}


def visible_point_scores(rendered: dict, pixel_weights: torch.Tensor,
                         retain_graph: bool = False) -> torch.Tensor:
    """d(sum W*Y_b)/db gives visible per-point contribution, no N*H*W map."""
    probe = rendered["point_probe"]
    image = rendered["probe_image"]
    if probe is None or image is None or image.shape != pixel_weights.shape:
        raise ValueError("point_probe_or_weight_shape_invalid")
    score, = torch.autograd.grad((image * pixel_weights.detach()).sum(), probe,
                                 retain_graph=retain_graph)
    return score[:, 0].detach()


def conservation_error(rendered: dict) -> float:
    return float((rendered["q_person"] + rendered["q_environment"] -
                  rendered["alpha"]).abs().max().detach())


COMPONENTS = ("room_static", "skin_face_head", "hair", "glasses",
              "neck_shoulder_cloth")


def render_components(means, quats, scales, opacity, sh, component,
                      viewmat, K, width, height, *, degree=1, absgrad=False,
                      antialiased=False, point_probe=False):
    """One common sort/transmittance for RGB, five contributions and depths.

    Inputs must already be posed in a common world frame. SH is evaluated in
    that frame; callers rotate head-local coefficients with the actual head.
    Per-component accumulated depth is diagnostic, not a surface z-buffer.
    """
    if component.shape != (len(means),) or (component<0).any() or (component>=5).any():
        raise ValueError("five_component_labels_invalid")
    center = torch.linalg.inv(viewmat)[:3,3]
    rgb = torch.clamp_min(spherical_harmonics(degree,means-center,sh)+.5,0.)
    groups = torch.nn.functional.one_hot(component.long(),5).to(means.dtype)
    depth = (means @ viewmat[:3,:3].T + viewmat[:3,3])[:,2]
    features = torch.cat((rgb,groups,groups*depth[:,None]),dim=1)
    probe = None
    if point_probe:
        probe = torch.zeros((len(means),1),device=means.device,
                            dtype=means.dtype,requires_grad=True)
        features = torch.cat((features,probe),dim=1)
    image, alpha, info = rasterization(means,quats,scales,opacity,features,
        viewmat[None],K[None],width,height,packed=True,sh_degree=None,
        absgrad=absgrad,rasterize_mode="antialiased" if antialiased else "classic",
        render_mode="RGB+D",near_plane=.01)
    q=image[0,:,:,3:8]
    q_depth=image[0,:,:,8:13]
    accumulated=image[0,:,:,-1]
    return {"rgb":image[0,:,:,:3],"alpha":alpha[0,:,:,0],"q":q,
            "component_accumulated_depth":q_depth,
            "component_expected_depth":q_depth/q.clamp_min(1e-8),
            "accumulated_depth":accumulated,
            "expected_depth":accumulated/alpha[0,:,:,0].clamp_min(1e-8),
            "projection":info,"point_probe":probe,
            "probe_image":image[0,:,:,13] if point_probe else None}


def component_conservation_error(rendered):
    return float((rendered["q"].sum(-1)-rendered["alpha"]).abs().max().detach())
