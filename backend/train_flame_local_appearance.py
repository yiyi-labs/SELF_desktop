"""Private source-video multi-view appearance optimization on fitted FLAME.

This is an E2 local-head research trainer, not a production reconstruction.
Skin, source-colored facial detail and a *search-volume* hair group share one
gsplat rasterization and its transmittance. Fixed native-pixel crops use the
upright decoded frames and the same estimated K; no world cameras are made up.
Held frames never contribute colors, losses, exposure, pose or optimizer steps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
from gsplat.rendering import rasterization
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from appearance_direction_contract import C0, C1
from flame_open_model import FlameOpen, MODEL, STANDARD_MODEL
from probe_flame_hair_hull import local_observations, to_camera
from probe_flame_open_fit import HELD, INTRINSIC, SOURCE_SHA256, TRAIN, filename
from probe_flame_real_appearance import bound_points, frame_mesh, project


@dataclass
class View:
    index: int
    name: str
    role: str
    crop: tuple[int, int, int, int]
    K: torch.Tensor
    rgb: torch.Tensor
    foreground: torch.Tensor
    face_region: torch.Tensor
    hair: torch.Tensor
    face_skin: torch.Tensor
    details: torch.Tensor
    empty: torch.Tensor
    base: torch.Tensor
    normals: torch.Tensor
    root_rotation: torch.Tensor
    root_quat: torch.Tensor
    face_width_px: int
    feature_boxes: dict[str, tuple[int, int, int, int]]


def quat_multiply(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    aw, ax, ay, az = a.unbind(-1)
    bw, bx, by, bz = b.unbind(-1)
    return torch.stack((aw*bw-ax*bx-ay*by-az*bz,
                        aw*bx+ax*bw+ay*bz-az*by,
                        aw*by-ax*bz+ay*bw+az*bx,
                        aw*bz+ax*by-ay*bx+az*bw), dim=-1)


def source_label_colors(job: Path, model: FlameOpen, fit: dict,
                        face_ids: np.ndarray, bary: np.ndarray,
                        faces: np.ndarray, device: torch.device
                        ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Use original non-hair feature pixels; never borrow neighbouring skin."""
    counts = np.zeros(len(face_ids), np.uint8)
    rgb = np.zeros((len(face_ids), 3), np.float32)
    for frame in TRAIN:
        name = filename(frame)
        mesh = frame_mesh(model, fit, frame, device)
        points, normals = bound_points(mesh, faces, face_ids, bary)
        xy, depth = project(points)
        x, y = np.rint(xy[:, 0]).astype(np.int32), np.rint(xy[:, 1]).astype(np.int32)
        source = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
        parts = cv2.imread(str(job / "portrait_components_20260927" / f"parts-{name}"),
                           cv2.IMREAD_GRAYSCALE)
        hair = cv2.imread(str(job / "portrait_components_20260927" / f"hair-{name}"),
                          cv2.IMREAD_GRAYSCALE)
        head = cv2.imread(str(job / "face_masks" / (name + ".png")),
                          cv2.IMREAD_GRAYSCALE)
        if any(item is None for item in (source, parts, hair, head)):
            raise ValueError(f"missing_feature_color_source:{name}")
        height, width = parts.shape
        inside = (depth > .04) & (x >= 2) & (y >= 2) & (x < width-2) & (y < height-2)
        xi, yi = x.clip(0, width-1), y.clip(0, height-1)
        half_depth = np.full((height//2, width//2), np.inf, np.float32)
        np.minimum.at(half_depth, (yi[inside]//2, xi[inside]//2), depth[inside])
        visible_depth = depth <= half_depth[yi//2, xi//2] + .0035
        front = (normals * (-points / np.maximum(np.linalg.norm(points, axis=1,
                                                       keepdims=True), 1e-8))).sum(1) > .18
        valid = (inside & front & visible_depth & (parts[yi, xi] == 5) &
                 (hair[yi, xi] == 0) & (head[yi, xi] > 127))
        first = valid & (counts == 0)
        rgb[first] = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)[yi[first], xi[first]] / 255
        counts[valid] += 1
    return rgb, counts, counts >= 1


def build_candidates(job: Path, model: FlameOpen, device: torch.device,
                     footprint_factor: float = 1., variant: str = "open",
                     hair_hull_suffix: str = "") -> dict:
    root = job / ("flame_open_e2_20260927" if variant == "open"
                  else "flame_standard_e2_20260927")
    with np.load(root / "private-real-appearance-semantic_skin-20000" /
                 "private-bound-splats.npz") as skin:
        ids_all = skin["face_ids"]
        bary_all = skin["barycentric"]
        color_all = skin["rgb_from_source"]
        support_all = skin["source_support_count"]
        scale_all = skin["scale"]
    hair_hull_name = "private-hair-hull-20260927" + (
        f"-{hair_hull_suffix}" if hair_hull_suffix else "")
    with np.load(root / hair_hull_name / "private-hair-shell.npz") as hair:
        hair_points = hair["local_points"]
        hair_colors = hair["observed_rgb"]
        hair_support = hair["source_support_count"]
    fit = dict(np.load(root / "private-fit-parameters.npz"))
    faces = model.faces.cpu().numpy()
    detail_rgb, detail_counts, detail_valid = source_label_colors(
        job, model, fit, ids_all, bary_all, faces, device)
    skin_valid = support_all > 0
    # Detail is independently colored from original eyewear/eye/brow pixels.
    # Points with no direct source color are excluded, not skin-filled.
    detail_idx = np.flatnonzero(detail_valid)
    skin_idx = np.flatnonzero(skin_valid & ~detail_valid)
    hair_idx = np.flatnonzero(hair_support > 0)
    if len(skin_idx) < 3000 or len(detail_idx) < 100 or len(hair_idx) < 300:
        raise ValueError(f"candidate_support_insufficient:{len(skin_idx)}:{len(detail_idx)}:{len(hair_idx)}")
    surface_idx = np.concatenate((skin_idx, detail_idx))
    roles = np.concatenate((np.zeros(len(skin_idx), np.int64),
                            np.ones(len(detail_idx), np.int64),
                            np.full(len(hair_idx), 2, np.int64)))
    initial_rgb = np.concatenate((color_all[skin_idx], detail_rgb[detail_idx],
                                  hair_colors[hair_idx]), axis=0).astype(np.float32)
    if not np.isfinite(initial_rgb).all():
        raise ValueError("candidate_color_nonfinite")
    surface_scale = scale_all[surface_idx].copy()
    detail_start = len(skin_idx)
    surface_scale[detail_start:] *= .65
    hair_scale = np.full(len(hair_idx), .0048, np.float32)
    spacing = np.concatenate((surface_scale, hair_scale))
    spacing *= np.where(roles == 2, min(1., footprint_factor * 1.5),
                        footprint_factor).astype(np.float32)
    initial_scale = np.stack((spacing, spacing, spacing * .75), axis=1)
    return {
        "roles": roles,
        "surface_count": len(surface_idx),
        "surface_ids": ids_all[surface_idx],
        "surface_bary": bary_all[surface_idx],
        "hair_points": hair_points[hair_idx],
        "initial_rgb": initial_rgb,
        "initial_scale": initial_scale,
        "source_index": np.concatenate((surface_idx.astype(np.int32),
                                         hair_idx.astype(np.int32))),
        "origin_index": np.arange(len(roles), dtype=np.int32),
        "confidence": np.concatenate((support_all[skin_idx], detail_counts[detail_idx],
                                       hair_support[hair_idx])).astype(np.uint8),
        "counts": {"skin": len(skin_idx), "detail": len(detail_idx),
                   "hair": len(hair_idx), "excludedNoSourceColor":
                   int((~skin_valid & ~detail_valid).sum() + (hair_support == 0).sum())},
        "detail_source_views": int((detail_counts > 0).sum()),
    }


def make_view(job: Path, model: FlameOpen, fit: dict, held: dict,
              candidate: dict, frame: int, F: np.ndarray,
              device: torch.device) -> View:
    name = filename(frame)
    is_held = frame in HELD
    params = held if is_held else fit
    source = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
    head = cv2.imread(str(job / "face_masks" / (name + ".png")), cv2.IMREAD_GRAYSCALE)
    hair = cv2.imread(str(job / "portrait_components_20260927" / f"hair-{name}"),
                      cv2.IMREAD_GRAYSCALE)
    parts = cv2.imread(str(job / "portrait_components_20260927" / f"parts-{name}"),
                       cv2.IMREAD_GRAYSCALE)
    if any(item is None for item in (source, head, hair, parts)):
        raise ValueError(f"missing_native_view:{name}")
    if source.shape[:2] != (1920, 1080) or head.shape != source.shape[:2]:
        raise ValueError(f"inconsistent_upright_frame:{name}")
    region = (head > 127) | (hair > 127)
    ys, xs = np.where(region)
    x0, x1 = max(int(xs.min())-24, 0), min(int(xs.max())+25, 1080)
    y0, y1 = max(int(ys.min())-24, 0), min(int(ys.max())+25, 1920)
    # Native-pixel crop: no resize or hidden mirror. The same x/y subtraction
    # is applied to K's principal point, while focal length is unchanged.
    K = INTRINSIC.copy().astype(np.float32)
    K[0, 2] -= x0
    K[1, 2] -= y0
    c = np.s_[y0:y1, x0:x1]
    rgb = cv2.cvtColor(source[c], cv2.COLOR_BGR2RGB).copy().astype(np.float32) / 255
    fg = region[c].astype(np.uint8)
    skin_mask = (((parts[c] == 2) | (parts[c] == 3)) & (hair[c] == 0) & (head[c] > 127)).astype(np.uint8)
    detail_mask = ((parts[c] == 5) & (hair[c] == 0) & (head[c] > 127)).astype(np.uint8)
    hair_mask = (hair[c] > 127).astype(np.uint8)
    fixed = cv2.erode(fg, np.ones((5, 5), np.uint8)) > 0
    hair_inner = cv2.erode(hair_mask, np.ones((9, 9), np.uint8)) > 0
    face_skin = cv2.erode(skin_mask, np.ones((9, 9), np.uint8)) > 0
    detail_inner = cv2.erode(detail_mask, np.ones((3, 3), np.uint8)) > 0
    safe_empty = cv2.dilate(fg, np.ones((17, 17), np.uint8)) == 0
    # Fixed face region from the original frame, not changing with renderer
    # coverage. Hair has its own fixed region. Both count missing pixels.
    face_region = fixed & (hair_mask == 0)
    mesh = frame_mesh(model, params, frame, device, held=is_held)
    surface, normal = bound_points(mesh, model.faces.cpu().numpy(),
                                   candidate["surface_ids"], candidate["surface_bary"])
    hair_camera = to_camera(candidate["hair_points"], F)
    base = np.concatenate((surface, hair_camera), axis=0).astype(np.float32)
    normals = np.concatenate((normal, np.zeros_like(hair_camera)), axis=0).astype(np.float32)
    quat_xyzw = Rotation.from_matrix(F[:3, :3]).as_quat()
    quat_wxyz = quat_xyzw[[3, 0, 1, 2]].astype(np.float32)
    with np.load(job / "face_landmarks.npz") as landmarks:
        marks = landmarks[name]
    face_width = int(round(float(np.linalg.norm(marks[234] - marks[454]))))
    def feature_box(indices: tuple[int, ...], padx: int, pady: int) -> tuple[int, int, int, int]:
        xx = marks[list(indices), 0] - x0
        yy = marks[list(indices), 1] - y0
        return (max(0, int(np.floor(xx.min()))-padx),
                max(0, int(np.floor(yy.min()))-pady),
                min(x1-x0, int(np.ceil(xx.max()))+padx),
                min(y1-y0, int(np.ceil(yy.max()))+pady))
    hy, hx = np.where(hair_mask > 0)
    hairline = (max(0, int(hx.min())-10), max(0, int(hy.min())-10),
                min(x1-x0, int(hx.max())+11),
                min(y1-y0, int(marks[10, 1]-y0)+45))
    features = {"brow_eye_glasses": feature_box((33, 133, 362, 263, 168, 6), 65, 55),
                "nose": feature_box((1, 2, 4, 5, 98, 327), 35, 35),
                "lips": feature_box((61, 291, 13, 14, 0, 17), 45, 40),
                "hairline": hairline}
    return View(frame, name, "held" if is_held else "train", (x0, y0, x1, y1),
                torch.from_numpy(K).to(device), torch.from_numpy(rgb).to(device),
                torch.from_numpy(fixed).to(device),
                torch.from_numpy(face_region).to(device),
                torch.from_numpy(hair_inner).to(device),
                torch.from_numpy(face_skin).to(device),
                torch.from_numpy(detail_inner).to(device),
                torch.from_numpy(safe_empty).to(device),
                torch.from_numpy(base).to(device),
                torch.from_numpy(normals).to(device),
                torch.from_numpy(F[:3, :3].copy()).to(device),
                torch.from_numpy(quat_wxyz).to(device), face_width, features)


class TrainablePortrait(torch.nn.Module):
    def __init__(self, candidate: dict, device: torch.device,
                 color_mode: str = "legacy-camera-sigmoid",
                 hair_sh_prior: float = 0.):
        super().__init__()
        if color_mode not in ("legacy-camera-sigmoid", "head-local-sh1"):
            raise ValueError("unsupported_color_mode")
        self.color_mode = color_mode
        self.hair_sh_prior = hair_sh_prior
        n = len(candidate["roles"])
        rgb = np.clip(candidate["initial_rgb"], .015, .985)
        self.base_rgb_logits = torch.nn.Parameter(torch.logit(torch.from_numpy(rgb).to(device)))
        self.sh1 = torch.nn.Parameter(torch.zeros(n, 3, 3, device=device))
        coeff = torch.zeros(n, 4, 3, device=device)
        coeff[:, 0] = (torch.from_numpy(rgb).to(device)-.5)/C0
        self.sh_coeff = torch.nn.Parameter(coeff)
        initial_opacity = np.where(candidate["roles"] == 2, .55,
                                   np.where(candidate["roles"] == 1, .67, .76))
        self.opacity_logits = torch.nn.Parameter(torch.logit(
            torch.from_numpy(initial_opacity.astype(np.float32)).to(device)))
        self.log_scales = torch.nn.Parameter(torch.log(torch.from_numpy(
            candidate["initial_scale"]).to(device)))
        quat = torch.zeros((n, 4), device=device)
        quat[:, 0] = 1
        self.local_quats = torch.nn.Parameter(quat)
        self.local_offsets = torch.nn.Parameter(torch.zeros((n, 3), device=device))
        self.register_buffer("role", torch.from_numpy(candidate["roles"]).to(device))
        self.register_buffer("initial_log_scales", self.log_scales.detach().clone())
        self.register_buffer("initial_rgb", self.base_rgb_logits.detach().clone())
        self.register_buffer("initial_opacity", self.opacity_logits.detach().clone())
        self.eye = torch.eye(4, device=device)[None]

    def raster(self, view: View) -> tuple[torch.Tensor, torch.Tensor, dict]:
        role = self.role
        surface = role != 2
        limits = torch.where(role == 0, .006,
                             torch.where(role == 1, .012, .018))
        bounded = torch.tanh(self.local_offsets) * limits[:, None]
        # Optional *research-only* low-dimensional, shared normal field.  It
        # is absent from the production/baseline trainer.  The isolated
        # refinement folds it into local_offsets before export, so the PLY
        # and existing viewer need no new representation.
        if hasattr(self, "research_surface_basis"):
            bounded = bounded.clone()
            bounded[:, 0] = bounded[:, 0] + .0015 * (
                self.research_surface_basis @ torch.tanh(self.research_surface_controls))
        displacement = torch.where(surface[:, None],
                                   view.normals * bounded[:, :1],
                                   bounded @ view.root_rotation.T)
        means = view.base + displacement
        if self.color_mode == "head-local-sh1":
            # gsplat uses camera-to-point rays. F maps head-local to camera,
            # so row directions transform into the fixed head basis by @ R.
            direction = torch.nn.functional.normalize(means, dim=1) @ view.root_rotation
            basis = torch.stack((torch.full_like(direction[:, 0], C0),
                                 -C1*direction[:, 1], C1*direction[:, 2],
                                 -C1*direction[:, 0]), dim=1)
            color = torch.clamp_min(torch.einsum("ni,nic->nc", basis,
                                                self.sh_coeff)+.5, 0.)
        else:
            raw = self.base_rgb_logits + (self.sh1 * torch.nn.functional.normalize(
                -means, dim=1)[:, :, None]).sum(1)
            color = torch.sigmoid(raw)
        labels = torch.nn.functional.one_hot(role, num_classes=3).float()
        features = torch.cat((color, labels), dim=1)
        root_q = view.root_quat[None].expand(len(role), -1)
        quats = quat_multiply(root_q, torch.nn.functional.normalize(self.local_quats, dim=1))
        scales = torch.exp(self.log_scales).clamp(.00045, .018)
        image, alpha, info = rasterization(
            means, quats, scales, torch.sigmoid(self.opacity_logits), features,
            self.eye, view.K[None], view.rgb.shape[1], view.rgb.shape[0],
            sh_degree=None, packed=True, near_plane=.01)
        return image[0], alpha[0, :, :, 0], info

    def regularization(self) -> torch.Tensor:
        role = self.role
        normal_offset = torch.tanh(self.local_offsets[:, 0])
        hair_offset = torch.tanh(self.local_offsets[role == 2])
        offset_penalty = normal_offset[role != 2].square().mean()
        if len(hair_offset):
            offset_penalty += hair_offset.square().mean()
        scale_change = (self.log_scales - self.initial_log_scales).square().mean()
        directional = (self.sh_coeff[:, 1:].square().mean() if self.color_mode == "head-local-sh1"
                       else self.sh1.square().mean())
        extra_hair = (self.hair_sh_prior * self.sh_coeff[role == 2, 1:].square().mean()
                      if self.color_mode == "head-local-sh1" and self.hair_sh_prior else 0.)
        return .002 * offset_penalty + .001 * scale_change + .0005 * directional + extra_hair


def score(model: TrainablePortrait, view: View) -> dict:
    with torch.no_grad():
        image, alpha, _ = model.raster(view)
        rgb = image[:, :, :3]
        fg = view.foreground
        face = view.face_region
        hair = view.hair
        def region_mae(region: torch.Tensor) -> float:
            return float(((rgb-view.rgb).abs().mean(2)*region).sum() /
                         region.sum().clamp_min(1))
        def coverage(region: torch.Tensor) -> float:
            return float(((alpha > .2)&region).sum()/region.sum().clamp_min(1))
        hair_projected = image[:, :, 5] > .2
        overlap = (hair_projected & hair).sum()
        return {"fixedRoiRgbL1IncludingMissing": region_mae(fg),
                "fixedFaceRgbL1IncludingMissing": region_mae(face),
                "fixedHairRgbL1IncludingMissing": region_mae(hair),
                "fixedRoiAlphaCoverage": coverage(fg),
                "hairMaskRecall": float(overlap/hair.sum().clamp_min(1)),
                "hairMaskPrecisionProxy": float(overlap/hair_projected.sum().clamp_min(1)),
                "hairForeheadContribution": float((image[:, :, 5]*view.face_skin).sum() /
                                                     view.face_skin.sum().clamp_min(1)),
                "safeEmptyAlpha": float((alpha*view.empty).sum()/view.empty.sum().clamp_min(1))}


def loss_for(model: TrainablePortrait, view: View) -> tuple[torch.Tensor, dict]:
    image, alpha, _ = model.raster(view)
    rgb = image[:, :, :3]
    error = (rgb-view.rgb).abs().mean(2)
    face = view.face_region
    hair = view.hair
    empty = view.empty
    face_rgb = (error*face).sum()/face.sum().clamp_min(1)
    hair_rgb = (error*hair).sum()/hair.sum().clamp_min(1)
    face_alpha = ((1-alpha).square()*face).sum()/face.sum().clamp_min(1)
    hair_alpha = ((1-alpha).square()*hair).sum()/hair.sum().clamp_min(1)
    empty_alpha = (alpha.square()*empty).sum()/empty.sum().clamp_min(1)
    q_hair = image[:, :, 5]
    forehead = (q_hair.square()*view.face_skin).sum()/view.face_skin.sum().clamp_min(1)
    hair_semantic = ((1-q_hair).square()*hair).sum()/hair.sum().clamp_min(1)
    loss = (1.5*face_rgb + hair_rgb + .06*face_alpha + .06*hair_alpha +
            .08*empty_alpha + .05*forehead + .025*hair_semantic +
            model.regularization())
    return loss, {"faceRgb": float(face_rgb.detach()), "hairRgb": float(hair_rgb.detach()),
                  "faceAlpha": float(face_alpha.detach()),
                  "hairAlpha": float(hair_alpha.detach()),
                  "hairOnFace": float(forehead.detach())}


def sampling_diagnostics(model: TrainablePortrait, view: View,
                         candidate: dict) -> dict:
    with torch.no_grad():
        _, _, info = model.raster(view)
    radii = info.get("radii")
    measured: dict = {"nativeFaceWidthPx": view.face_width_px}
    if isinstance(radii, torch.Tensor):
        visible = radii.detach().float().flatten().cpu().numpy()
        visible = visible[np.isfinite(visible) & (visible > 0)]
        measured["gsplatVisibleRadiiCount"] = int(len(visible))
        if len(visible):
            measured["gsplatProjectedRadiusPxP10P50P90"] = [
                round(float(v), 3) for v in np.quantile(visible, (.1, .5, .9))]
    means = view.base[:candidate["surface_count"]].cpu().numpy()
    K = view.K.cpu().numpy()
    xy = means[:, :2] / np.maximum(means[:, 2:3], 1e-8)
    xy = xy * np.asarray([K[0, 0], K[1, 1]]) + np.asarray([K[0, 2], K[1, 2]])
    valid = ((means[:, 2] > .04) & (xy[:, 0] >= 0) & (xy[:, 0] < view.rgb.shape[1]) &
             (xy[:, 1] >= 0) & (xy[:, 1] < view.rgb.shape[0]))
    if valid.sum() >= 2:
        distance = cKDTree(xy[valid]).query(xy[valid], k=2)[0][:, 1]
        measured["nativeProjectedNearestSurfaceSpacingPxMedian"] = round(float(np.median(distance)), 3)
    return measured


def bounded_split(job: Path, geometry: FlameOpen, fit: dict, held: dict,
                  transforms: dict[int, np.ndarray], candidate: dict,
                  portrait: TrainablePortrait, optimizer: torch.optim.Adam,
                  selected: tuple[int, ...], eval_frames: tuple[int, ...],
                  device: torch.device, seed: int, max_new: int = 2800
                  ) -> tuple[dict, TrainablePortrait, torch.optim.Adam,
                             list[View], list[View], dict]:
    """Split only source-supported high-residual points, preserving lineage.

    Adam first and second moments follow every old point and its child. The
    exact same reindex is applied to roles, confidence, source IDs, binding,
    local hair positions and per-view means/normals. No unsupported source
    pixel gains color by cloning.
    """
    n = len(candidate["roles"])
    old_surface = candidate["surface_count"]
    scores = np.zeros(n, np.float32)
    votes = np.zeros(n, np.uint8)
    role = candidate["roles"]
    with torch.no_grad():
        for frame in selected:
            view = make_view(job, geometry, fit, held, candidate, frame,
                             transforms[frame], device)
            image, _, _ = portrait.raster(view)
            error = (image[:, :, :3]-view.rgb).abs().mean(2).cpu().numpy()
            xyz = view.base.cpu().numpy()
            K = view.K.cpu().numpy()
            z = xyz[:, 2]
            x = np.rint(xyz[:, 0]/np.maximum(z, 1e-8)*K[0, 0]+K[0, 2]).astype(np.int32)
            y = np.rint(xyz[:, 1]/np.maximum(z, 1e-8)*K[1, 1]+K[1, 2]).astype(np.int32)
            height, width = error.shape
            valid = (z > .04) & (x >= 0) & (x < width) & (y >= 0) & (y < height)
            xi, yi = x.clip(0, width-1), y.clip(0, height-1)
            target = np.where(role == 2, view.hair.cpu().numpy()[yi, xi],
                              np.where(role == 1, view.details.cpu().numpy()[yi, xi],
                                       view.face_region.cpu().numpy()[yi, xi]))
            valid &= target & (candidate["confidence"] > 0)
            scores[valid] += error[yi[valid], xi[valid]]
            votes[valid] += 1
    scores /= np.maximum(votes, 1)
    rng = np.random.default_rng(seed)
    quotas = ((0, int(max_new*.72)), (1, int(max_new*.12)),
              (2, max_new-int(max_new*.72)-int(max_new*.12)))
    picked = []
    for part, cap in quotas:
        eligible = np.flatnonzero((role == part) & (votes >= 2) & (scores > .018))
        ordered = eligible[np.argsort(scores[eligible])[::-1]]
        picked.extend(ordered[:cap].tolist())
    chosen = np.asarray(sorted(set(picked)), np.int32)
    surface_children = chosen[chosen < old_surface]
    hair_children = chosen[chosen >= old_surface]
    if len(chosen) < 100:
        raise RuntimeError(f"bounded_split_insufficient_supported_residuals:{len(chosen)}")
    # Old surface, new surface, old hair, new hair keeps bindings contiguous.
    order = np.concatenate((np.arange(old_surface), surface_children,
                            np.arange(old_surface, n), hair_children)).astype(np.int64)
    old = candidate
    new = dict(old)
    new["surface_count"] = old_surface + len(surface_children)
    new["surface_ids"] = np.concatenate((old["surface_ids"],
                                         old["surface_ids"][surface_children]))
    new_bary = old["surface_bary"][surface_children].copy()
    new_bary += rng.normal(0, .085, new_bary.shape).astype(np.float32)
    new_bary = np.clip(new_bary, .015, None)
    new_bary /= new_bary.sum(axis=1, keepdims=True)
    new["surface_bary"] = np.concatenate((old["surface_bary"], new_bary))
    hair_local = old["hair_points"][hair_children-old_surface].copy()
    hair_local += rng.normal(0, .0011, hair_local.shape).astype(np.float32)
    new["hair_points"] = np.concatenate((old["hair_points"], hair_local))
    for key in ("roles", "initial_rgb", "initial_scale", "source_index",
                "origin_index", "confidence"):
        new[key] = old[key][order].copy()
    new["counts"] = {**old["counts"],
                     "skin": int((new["roles"] == 0).sum()),
                     "detail": int((new["roles"] == 1).sum()),
                     "hair": int((new["roles"] == 2).sum())}
    new_portrait = TrainablePortrait(new, device, portrait.color_mode,
                                    portrait.hair_sh_prior).to(device)
    index = torch.from_numpy(order).to(device)
    with torch.no_grad():
        for name, parameter in portrait.named_parameters():
            getattr(new_portrait, name).copy_(parameter.detach().index_select(0, index))
        parent_pos = np.concatenate((surface_children,
                                     new["surface_count"]+hair_children-old_surface))
        child_pos = np.concatenate((old_surface+np.arange(len(surface_children)),
                                    new["surface_count"]+(n-old_surface)+
                                    np.arange(len(hair_children))))
        for positions in (parent_pos, child_pos):
            idx = torch.from_numpy(positions.astype(np.int64)).to(device)
            new_portrait.log_scales[idx] += math.log(.72)
            alpha = torch.sigmoid(new_portrait.opacity_logits[idx])
            new_portrait.opacity_logits[idx] = torch.logit(
                (1-torch.sqrt(1-alpha)).clamp(.001, .999))
        new_portrait.initial_log_scales.copy_(new_portrait.log_scales)
        new_portrait.initial_rgb.copy_(new_portrait.base_rgb_logits)
        new_portrait.initial_opacity.copy_(new_portrait.opacity_logits)
    new_groups = [{"params": [getattr(new_portrait, old_group["name"]
                             if old_group["name"] not in ("color", "alpha", "scale", "orientation", "offset")
                             else {"color": "base_rgb_logits", "alpha": "opacity_logits",
                                   "scale": "log_scales", "orientation": "local_quats",
                                   "offset": "local_offsets"}[old_group["name"]])],
                   "lr": old_group["lr"], "name": old_group["name"]}
                  for old_group in optimizer.param_groups]
    new_optimizer = torch.optim.Adam(new_groups, eps=1e-8)
    for old_group, new_group in zip(optimizer.param_groups, new_optimizer.param_groups):
        old_param = old_group["params"][0]
        new_param = new_group["params"][0]
        if old_param not in optimizer.state:
            continue
        new_optimizer.state[new_param] = {}
        for key, value in optimizer.state[old_param].items():
            new_optimizer.state[new_param][key] = (
                value.index_select(0, index).clone() if isinstance(value, torch.Tensor)
                and value.shape == old_param.shape else
                value.clone() if isinstance(value, torch.Tensor) else value)
    view_by_id = {frame: make_view(job, geometry, fit, held, new, frame,
                                   transforms[frame], device)
                  for frame in set(selected) | set(eval_frames)}
    event = {"oldPointCount": n, "newPointCount": len(order),
             "newSkin": int((role[chosen] == 0).sum()),
             "newDetail": int((role[chosen] == 1).sum()),
             "newHair": int((role[chosen] == 2).sum()),
             "optimizerMomentsReindexed": True,
             "bindingSourceConfidenceReindexed": True,
             "minimumTrainingViewSupport": 2}
    return new, new_portrait, new_optimizer, [view_by_id[i] for i in selected], [view_by_id[i] for i in eval_frames], event


def save_comparison(out: Path, tag: str, model: TrainablePortrait,
                    views: list[View], baseline: dict[int, np.ndarray]) -> None:
    for view in views:
        with torch.no_grad():
            image, alpha, _ = model.raster(view)
        source = (view.rgb.cpu().numpy()*255).round().clip(0, 255).astype(np.uint8)
        current = (image[:, :, :3].cpu().numpy()*255).round().clip(0, 255).astype(np.uint8)
        initial = baseline[view.index]
        row = np.concatenate((source, initial, current), axis=1)
        cv2.imwrite(str(out / f"private-{tag}-{view.role}-{view.index:04d}.jpg"),
                    cv2.cvtColor(row, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
        if view.index in (25, 80, 136, 35, 75, 145) and tag == "final":
            for region, (x0, y0, x1, y1) in view.feature_boxes.items():
                if x1 <= x0 or y1 <= y0:
                    continue
                local = np.concatenate((source[y0:y1, x0:x1],
                                        initial[y0:y1, x0:x1],
                                        current[y0:y1, x0:x1]), axis=1)
                cv2.imwrite(str(out / f"private-{tag}-{view.role}-{view.index:04d}-{region}-100pct.jpg"),
                            cv2.cvtColor(local, cv2.COLOR_RGB2BGR),
                            [cv2.IMWRITE_JPEG_QUALITY, 96])


def train(job: Path, stage: str, steps: int, footprint_factor: float = 1.,
          split_at: tuple[int, ...] = (), variant: str = "open",
          run_id: str = "", hair_hull_suffix: str = "",
          color_mode: str = "legacy-camera-sigmoid",
          hair_sh_prior: float = 0.) -> dict:
    start = time.perf_counter()
    if (variant not in ("open", "standard") or
            stage not in ("single", "three", "subset") or steps < 10 or
            not .2 <= footprint_factor <= 1.2):
        raise ValueError("invalid_training_stage")
    if run_id and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", run_id):
        raise ValueError("invalid_research_run_id")
    if color_mode not in ("legacy-camera-sigmoid", "head-local-sh1"):
        raise ValueError("invalid_color_mode")
    if hair_sh_prior < 0 or hair_sh_prior > .2 or (hair_sh_prior and color_mode != "head-local-sh1"):
        raise ValueError("invalid_hair_sh_prior")
    if hair_hull_suffix and not re.fullmatch(r"s[2-9]-c[0-3]-(?:fill|open)", hair_hull_suffix):
        raise ValueError("invalid_research_hair_hull_suffix")
    if any(step < 1 or step >= steps for step in split_at):
        raise ValueError("split_step_outside_training_range")
    if split_at and stage == "single":
        raise ValueError("bounded_split_requires_at_least_two_training_views")
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    torch.manual_seed(260927)
    np.random.seed(260927)
    if not torch.cuda.is_available():
        raise RuntimeError("cuda_unavailable_for_real_image_optimization")
    torch.cuda.reset_peak_memory_stats()
    device = torch.device("cuda")
    free_start, total_vram = torch.cuda.mem_get_info()
    model_path = MODEL if variant == "open" else STANDARD_MODEL
    model = FlameOpen(24, 12, model_path=model_path).to(device)
    candidate = build_candidates(job, model, device, footprint_factor, variant,
                                 hair_hull_suffix)
    root = job / ("flame_open_e2_20260927" if variant == "open"
                  else "flame_standard_e2_20260927")
    fit = dict(np.load(root / "private-fit-parameters.npz"))
    held = dict(np.load(root / "private-held-local-parameters.npz"))
    if (tuple(fit["train_frame_indices"]) != TRAIN or
            tuple(held["held_frame_indices"]) != HELD):
        raise ValueError("training_holdout_split_changed")
    fit_audit = json.loads((root / "fit.audit.json").read_text(encoding="utf-8"))
    if fit_audit["modelSha256"] != model.model_sha256:
        raise ValueError("fit_model_variant_mismatch")
    observations = local_observations(root)
    if stage == "single":
        selected = (25,)
    elif stage == "three":
        selected = (25, 80, 136)
    else:
        selected = TRAIN
    eval_frames = (25, 80, 136) + HELD
    view_by_id = {frame: make_view(job, model, fit, held, candidate, frame,
                                   observations[frame], device)
                  for frame in set(selected) | set(eval_frames)}
    train_views = [view_by_id[index] for index in selected]
    eval_views = [view_by_id[index] for index in eval_frames]
    portrait = TrainablePortrait(candidate, device, color_mode, hair_sh_prior).to(device)
    initial_count = len(candidate["roles"])
    split_suffix = ("-split-" + "-".join(map(str, split_at))) if split_at else ""
    run_suffix = f"-{run_id}" if run_id else ""
    out = root / f"private-optimized-{stage}-{steps}-footprint-{footprint_factor:.2f}{split_suffix}{run_suffix}"
    if run_id and out.exists() and any(out.iterdir()):
        raise FileExistsError(f"research_run_already_exists:{out}")
    out.mkdir(exist_ok=True)
    baseline_metrics = {str(v.index): score(portrait, v) for v in eval_views}
    baseline = {}
    with torch.no_grad():
        for view in eval_views:
            image, _, _ = portrait.raster(view)
            baseline[view.index] = (image[:, :, :3].cpu().numpy()*255).round().clip(0, 255).astype(np.uint8)
    params_before = {name: p.detach().clone() for name, p in portrait.named_parameters()}
    groups = [
        {"params": [portrait.base_rgb_logits], "lr": .01, "name": "color"},
        {"params": [portrait.opacity_logits], "lr": .02, "name": "alpha"},
        {"params": [portrait.sh1], "lr": 0., "name": "sh1"},
        {"params": [portrait.log_scales], "lr": 0., "name": "scale"},
        {"params": [portrait.local_quats], "lr": 0., "name": "orientation"},
        {"params": [portrait.local_offsets], "lr": 0., "name": "offset"},
        {"params": [portrait.sh_coeff], "lr": .01 if color_mode == "head-local-sh1" else 0.,
         "name": "sh_coeff"},
    ]
    optimizer = torch.optim.Adam(groups, eps=1e-8)
    curve = []
    split_events = []
    optimizer_steps = 0
    snapshot_step = steps // 2
    mid_metrics = None
    for step in range(steps):
        frac = step / steps
        optimizer.param_groups[2]["lr"] = (.002 if frac >= .15 else 0.) if color_mode == "legacy-camera-sigmoid" else 0.
        optimizer.param_groups[3]["lr"] = .0015 if frac >= .15 else 0.
        optimizer.param_groups[4]["lr"] = .0005 if frac >= .25 else 0.
        optimizer.param_groups[5]["lr"] = .00035 if frac >= .4 else 0.
        view = train_views[step % len(train_views)]
        loss, parts = loss_for(portrait, view)
        if not torch.isfinite(loss):
            raise RuntimeError(f"nonfinite_real_image_loss:{step}")
        loss.backward()
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        optimizer_steps += 1
        if step+1 in split_at:
            (candidate, portrait, optimizer, train_views, eval_views,
             event) = bounded_split(job, model, fit, held, observations,
                                    candidate, portrait, optimizer, selected,
                                    eval_frames, device, seed=260927+step)
            event["afterOptimizerStep"] = step+1
            split_events.append(event)
        if step == snapshot_step:
            mid_metrics = {str(v.index): score(portrait, v) for v in eval_views}
            save_comparison(out, "mid", portrait, eval_views, baseline)
        if step % max(steps // 20, 1) == 0 or step == steps-1:
            curve.append({"step": step+1, "frame": view.index,
                          "loss": round(float(loss.detach()), 6),
                          "points": int(len(candidate["roles"])),
                          **{key: round(value, 6) for key, value in parts.items()}})
    final_metrics = {str(v.index): score(portrait, v) for v in eval_views}
    save_comparison(out, "final", portrait, eval_views, baseline)
    origin_index = torch.from_numpy(candidate["origin_index"].astype(np.int64)).to(device)
    parameter_change = {name: round(float((p.detach()-params_before[name].index_select(
                            0, origin_index)).abs().mean()), 8)
                        for name, p in portrait.named_parameters()}
    np.savez_compressed(out / "private-optimized-parameters.npz",
                        source_sha256=np.asarray(SOURCE_SHA256),
                        model_sha256=np.asarray(model.model_sha256),
                        model_variant=np.asarray(variant),
                        role=candidate["roles"], source_index=candidate["source_index"],
                        origin_index=candidate["origin_index"],
                        source_confidence=candidate["confidence"],
                        surface_ids=candidate["surface_ids"],
                        surface_bary=candidate["surface_bary"],
                        hair_local_points=candidate["hair_points"],
                        base_rgb_logits=portrait.base_rgb_logits.detach().cpu().numpy(),
                        sh1=portrait.sh1.detach().cpu().numpy(),
                        sh_coeff=portrait.sh_coeff.detach().cpu().numpy(),
                        color_mode=np.asarray(color_mode),
                        opacity_logits=portrait.opacity_logits.detach().cpu().numpy(),
                        log_scales=portrait.log_scales.detach().cpu().numpy(),
                        local_quats=portrait.local_quats.detach().cpu().numpy(),
                        local_offsets=portrait.local_offsets.detach().cpu().numpy())
    torch.cuda.synchronize()
    free_end, _ = torch.cuda.mem_get_info()
    report = {
        "status": "real_image_optimization_isolated_not_publishable",
        "sourceSha256": SOURCE_SHA256, "modelSha256": model.model_sha256,
        "modelPath": str(model_path), "modelVariant": variant, "runId": run_id,
        "colorMode": color_mode,
        "hairDirectionalPrior": hair_sh_prior,
        "hairHullCandidate": "private-hair-hull-20260927" + (
            f"-{hair_hull_suffix}" if hair_hull_suffix else ""),
        "trainerSourceSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "stage": stage, "actualBackwardCount": optimizer_steps,
        "actualOptimizerStepCount": optimizer_steps,
        "trainFrames": list(selected), "heldColorAndLossExcluded": list(HELD),
        "fixedK": INTRINSIC.tolist(),
        "distortion": "unknown; no invented coefficients or per-frame K",
        "orientation": "decoded upright native PNG; no mirror or resize; crop shifts K principal point",
        "nativePixelViews": {str(v.index): {"role": v.role, "cropXYXY": list(v.crop),
                                             "cropSize": [v.rgb.shape[1], v.rgb.shape[0]],
                                             "faceWidthPxFromLandmarks234To454": v.face_width_px,
                                             "croppedK": v.K.cpu().numpy().tolist()}
                              for v in eval_views},
        "actualSampling": {str(v.index): sampling_diagnostics(portrait, v, candidate)
                           for v in eval_views if v.index in (25, 80, 136, 35, 75, 145)},
        "candidateCounts": candidate["counts"],
        "initialPointCount": initial_count,
        "finalPointCount": int(len(candidate["roles"])),
        "initialFootprintFactor": footprint_factor,
        "pointCountChange": int(len(candidate["roles"])-initial_count),
        "densificationStatus": ("bounded_source_supported_split_with_optimizer_and_binding_reindex"
                                if split_events else "not_run_in_this_bounded_optimization"),
        "splitEvents": split_events,
        "parameterMeanAbsoluteChange": parameter_change,
        "initialMetrics": baseline_metrics, "midMetrics": mid_metrics,
        "finalMetrics": final_metrics,
        "curve": curve,
        "fullElapsedSeconds": round(time.perf_counter()-start, 2),
        "cudaPeakAllocatedMiB": round(torch.cuda.max_memory_allocated()/1024**2, 2),
        "cudaPeakReservedMiB": round(torch.cuda.max_memory_reserved()/1024**2, 2),
        "cudaTotalMiB": round(total_vram/1024**2, 2),
        "cudaFreeStartMiB": round(free_start/1024**2, 2),
        "cudaFreeEndMiB": round(free_end/1024**2, 2),
        "limits": ["Local estimated F and K are fixed; no world camera was invented.",
                   "Eyewear candidates are FLAME-near source-colored points, not validated separate frame geometry.",
                   "Coarse hair hull is a movable search initialization and still fails held silhouette gate.",
                   "No neck/shoulder/clothing/room joint training or app export.",
                   "The initial 2D semantic labels and head mask have uncertain boundaries."]}
    (out / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "status", "stage", "actualOptimizerStepCount", "candidateCounts",
        "parameterMeanAbsoluteChange", "initialMetrics", "finalMetrics",
        "fullElapsedSeconds", "cudaPeakAllocatedMiB", "cudaPeakReservedMiB")}, indent=2), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--stage", choices=("single", "three", "subset"), required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--footprint-factor", type=float, default=1.)
    parser.add_argument("--split-at", type=int, action="append", default=[])
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--hair-hull-suffix", default="")
    parser.add_argument("--color-mode", choices=("legacy-camera-sigmoid", "head-local-sh1"),
                        default="legacy-camera-sigmoid")
    parser.add_argument("--hair-sh-prior", type=float, default=0.)
    args = parser.parse_args()
    train(args.job, args.stage, args.steps, args.footprint_factor,
          tuple(sorted(set(args.split_at))), args.variant, args.run_id,
          args.hair_hull_suffix, args.color_mode, args.hair_sh_prior)
