"""Offline, fail-closed research export of a fitted local head to standard GS PLY.

This converts the trainer's sigmoid(logit + camera-direction term) color to
degree-one 3DGS SH by fitting *training-view model predictions*, not source
pixels from held views. It is an approximation: the source model is nonlinear,
and the local FLAME portrait changes shape over time. This static reference
PLY is only for a computer renderer consistency gate, never app delivery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from gsplat import export_splats

from appearance_direction_contract import (camera_to_point_in_head,
                                           sh1_head_to_reference, sh1_rgb)
from flame_open_model import FlameOpen, MODEL, STANDARD_MODEL
from probe_flame_hair_hull import local_observations
from probe_flame_open_fit import HELD, INTRINSIC, SOURCE_SHA256, TRAIN
from train_flame_local_appearance import (build_candidates, make_view,
                                          quat_multiply)


C0 = 0.2820947917738781
C1 = 0.48860251190292


def normalize(value: np.ndarray) -> np.ndarray:
    return value / np.maximum(np.linalg.norm(value, axis=-1, keepdims=True), 1e-8)


def sh_basis(direction: np.ndarray) -> np.ndarray:
    """Exact degree-one order used by the installed gsplat 1.5.3 code."""
    direction = normalize(direction)
    return np.stack((np.full(direction.shape[:-1], C0, np.float32),
                     -C1 * direction[..., 1], C1 * direction[..., 2],
                     -C1 * direction[..., 0]), axis=-1)


def sigmoid(value: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(value, -30, 30)))


def means_for_view(view, roles: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    base = view.base.cpu().numpy()
    normal = view.normals.cpu().numpy()
    root = view.root_rotation.cpu().numpy()
    limit = np.where(roles == 0, .006, np.where(roles == 1, .012, .018))
    bounded = np.tanh(offsets) * limit[:, None]
    displacement = np.where((roles != 2)[:, None],
                            normal * bounded[:, :1], bounded @ root.T)
    return base + displacement


def fit_degree_one(directions: np.ndarray,
                   target_colors: np.ndarray) -> tuple[np.ndarray, dict]:
    """Ridge-fit a standard SH approximation; report conversion residuals."""
    # [views, splats, four] and [views, splats, RGB]. A small ridge on the
    # directional bands prevents huge coefficients from near-identical views.
    basis = sh_basis(directions)
    bt = basis.transpose(1, 2, 0)
    gram = bt @ basis.transpose(1, 0, 2)
    ridge = np.diag([1e-5, .004, .004, .004]).astype(np.float32)
    right = bt @ (target_colors - .5).transpose(1, 0, 2)
    coeff = np.linalg.solve(gram + ridge, right).astype(np.float32)
    restored = np.maximum(np.einsum("vni,nic->vnc", basis, coeff) + .5, 0.)
    error = np.abs(restored-target_colors)
    report = {"meanAbsoluteTrainColorError": float(error.mean()),
              "p95AbsoluteTrainColorError": float(np.quantile(error, .95)),
              "maxAbsoluteTrainColorError": float(error.max()),
              "note": "Model-predicted train colors only; held source pixels excluded"}
    return coeff, report


def export(job: Path, parameters_path: Path, variant: str = "open",
           reference_frame: int = 35, allow_research_binding: bool = False) -> dict:
    if variant not in ("open", "standard") or reference_frame not in TRAIN + HELD:
        raise ValueError("unsupported_research_export")
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    model_path = MODEL if variant == "open" else STANDARD_MODEL
    root = job / ("flame_open_e2_20260927" if variant == "open"
                  else "flame_standard_e2_20260927")
    with np.load(parameters_path) as data:
        params = {key: data[key] for key in data.files}
    if str(params["source_sha256"]) != SOURCE_SHA256:
        raise ValueError("optimized_source_mismatch")
    model = FlameOpen(24, 12, model_path=model_path)
    if "model_sha256" in params and str(params["model_sha256"]) != model.model_sha256:
        raise ValueError("optimized_model_mismatch")
    if "model_variant" in params and str(params["model_variant"]) != variant:
        raise ValueError("optimized_variant_mismatch")
    candidate = build_candidates(job, model, torch.device("cpu"), 1., variant)
    if allow_research_binding:
        # A locally split research asset can reorder points, but every new
        # point must retain a source-supported baseline parent.  Never infer
        # a mapping from array order or carry an old edit mask across assets.
        origin = params["origin_index"].astype(np.int64)
        if (len(origin) != len(params["role"]) or len(origin) < len(candidate["roles"])
                or (origin < 0).any() or (origin >= len(candidate["roles"])).any()):
            raise ValueError("research_origin_index_invalid")
        if not np.array_equal(params["role"], candidate["roles"][origin]):
            raise ValueError("research_role_lineage_changed")
        if not np.array_equal(params["source_index"], candidate["source_index"][origin]):
            raise ValueError("research_source_lineage_changed")
        if not np.array_equal(params["source_confidence"], candidate["confidence"][origin]):
            raise ValueError("research_confidence_lineage_changed")
        surface = params["role"] != 2
        if (len(params["surface_ids"]) != int(surface.sum()) or
                len(params["hair_local_points"]) != int((~surface).sum()) or
                not np.array_equal(params["surface_ids"],candidate["surface_ids"][origin[surface]]) or
                not np.array_equal(params["hair_local_points"],candidate["hair_points"][
                    origin[~surface]-candidate["surface_count"]])):
            raise ValueError("research_attachment_binding_changed")
        bary = params["surface_bary"]
        if (not np.isfinite(bary).all() or (bary < 0).any() or
                np.abs(bary.sum(axis=1)-1).max() > 1e-4 or
                np.abs(bary-candidate["surface_bary"][origin[surface]]).max() > .03):
            raise ValueError("research_barycentric_shift_unbounded")
        candidate = dict(candidate)
        candidate["roles"] = params["role"]
        candidate["surface_count"] = int(surface.sum())
        candidate["surface_ids"] = params["surface_ids"]
        candidate["surface_bary"] = bary
        candidate["hair_points"] = params["hair_local_points"]
    else:
        for key, source in (("role", "roles"), ("surface_ids", "surface_ids"),
                            ("surface_bary", "surface_bary"),
                            ("hair_local_points", "hair_points")):
            if not np.array_equal(params[key], candidate[source]):
                raise ValueError(f"optimized_binding_changed:{key}")
        if len(params["role"]) != len(candidate["roles"]):
            raise ValueError("optimized_point_count_mismatch")
    fit = dict(np.load(root / "private-fit-parameters.npz"))
    held = dict(np.load(root / "private-held-local-parameters.npz"))
    observations = local_observations(root)
    views = {frame: make_view(job, model, fit, held, candidate, frame,
                             observations[frame], torch.device("cpu"))
             for frame in TRAIN + (reference_frame,)}
    roles, offsets = params["role"], params["local_offsets"]
    reference = views[reference_frame]
    means = means_for_view(reference, roles, offsets)
    q_local = normalize(params["local_quats"])
    q_root = np.repeat(reference.root_quat.cpu().numpy()[None], len(roles), axis=0)
    quats = quat_multiply(torch.from_numpy(q_root), torch.from_numpy(q_local)).numpy()
    quats = normalize(quats).astype(np.float32)
    reference_root = reference.root_rotation.cpu().numpy()
    color_mode = str(params.get("color_mode", "legacy-camera-sigmoid"))
    if color_mode == "head-local-sh1":
        coeff = sh1_head_to_reference(params["sh_coeff"], reference_root)
        errors = []
        for frame in TRAIN:
            view = views[frame]
            camera_ray = normalize(means_for_view(view, roles, offsets))
            local_ray = camera_to_point_in_head(camera_ray,
                                                view.root_rotation.cpu().numpy())
            reference_ray = local_ray @ reference_root.T
            errors.append(np.abs(sh1_rgb(local_ray, params["sh_coeff"])
                                 - sh1_rgb(reference_ray, coeff)))
        error = np.stack(errors)
        color_report = {"meanAbsoluteTrainColorError": float(error.mean()),
                        "p95AbsoluteTrainColorError": float(np.quantile(error, .95)),
                        "maxAbsoluteTrainColorError": float(error.max()),
                        "conversion": "exact_degree1_linear_basis_rotation"}
    elif color_mode == "legacy-camera-sigmoid":
        basis_directions = []
        target_colors = []
        for frame in TRAIN:
            view = views[frame]
            camera_means = means_for_view(view, roles, offsets)
            camera_to_point = normalize(camera_means)
            local_ray = camera_to_point @ view.root_rotation.cpu().numpy()
            basis_directions.append(local_ray @ reference_root.T)
            raw = params["base_rgb_logits"] + np.einsum(
                "ndc,nd->nc", params["sh1"], -camera_to_point)
            target_colors.append(sigmoid(raw))
        directions = np.stack(basis_directions).astype(np.float32)
        target = np.stack(target_colors).astype(np.float32)
        coeff, color_report = fit_degree_one(directions, target)
    else:
        raise ValueError("unsupported_optimized_color_mode")
    sh0 = coeff[:, :1]
    shN = np.zeros((len(roles), 15, 3), np.float32)
    shN[:, :3] = coeff[:, 1:]
    scales = np.log(np.exp(params["log_scales"]).clip(.00045, .018)).astype(np.float32)
    out = parameters_path.parent / f"private-reference-{reference_frame:04d}-ply-contract"
    out.mkdir(exist_ok=True)
    ply = out / "research-head-only.gaussian.ply"
    export_splats(means=torch.from_numpy(means.astype(np.float32)),
                  scales=torch.from_numpy(scales),
                  quats=torch.from_numpy(quats),
                  opacities=torch.from_numpy(params["opacity_logits"].astype(np.float32)),
                  sh0=torch.from_numpy(sh0), shN=torch.from_numpy(shN),
                  format="ply", save_to=str(ply))
    depth = float(np.median(means[:, 2]))
    fov = math.degrees(2 * math.atan(1920 / (2 * INTRINSIC[1, 1])))
    view_contract = {"schemaVersion": 1, "sourceFrame": f"frame_{reference_frame:04d}.png",
                     "target": [0, 0, depth], "camera": [0, 0, 0], "up": [0, -1, 0],
                     "fovDegrees": fov, "targetFaceFraction": .5,
                     "researchOnly": True}
    if allow_research_binding:
        # The current viewer already honours this prefix bound.  Research
        # splats are ordered skin/detail first, hair search-volume last;
        # excluding the latter prevents a lip lasso from recolouring hair
        # leaking through an incorrect experimental shell.
        view_contract["editableSplats"] = int((roles != 2).sum())
    (out / "portrait.view.json").write_text(json.dumps(view_contract, indent=2),
                                             encoding="utf-8")
    audit = {"status": "research_static_reference_export_not_for_app",
             "sourceSha256": SOURCE_SHA256, "modelSha256": model.model_sha256,
             "variant": variant, "referenceFrame": reference_frame,
             "optimizedParameterSha256": hashlib.sha256(parameters_path.read_bytes()).hexdigest(),
             "plySha256": hashlib.sha256(ply.read_bytes()).hexdigest(),
             "pointCount": len(roles), "plyBytes": ply.stat().st_size,
             "bindingMode": "validated_research_lineage" if allow_research_binding else "unchanged_baseline",
             "colorRepresentation": ("head-local-degree1-SH-exact-rotation" if color_mode == "head-local-sh1"
                                     else "sigmoid-logit-direction-to-degree1-SH-ridge-approximation"),
             "conversion": color_report,
             "limits": ["Reference head only; not a motion-aware full-scene asset",
                        ("Exact SH coefficient rotation still requires a same-camera render gate"
                         if color_mode == "head-local-sh1" else
                         "SH conversion is approximate and requires same-camera render gate"),
                        "Local face F and estimated K do not supply world cameras",
                        "No held source pixels entered SH fit or export color"]}
    (out / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    if allow_research_binding:
        # The display PLY itself has no editable semantics.  This sidecar is
        # versioned by its exact PLY hash; the present viewer's masks use
        # Gaussian array indices and MUST NOT be reused across a re-export.
        np.savez_compressed(out / "private-edit-binding.npz",
            gaussian_index=np.arange(len(roles),dtype=np.int32),
            origin_index=params["origin_index"].astype(np.int32),
            source_index=params["source_index"].astype(np.int32),
            component_role=roles.astype(np.uint8),
            source_confidence=params["source_confidence"].astype(np.uint8),
            surface_ids=params["surface_ids"].astype(np.int32),
            surface_bary=params["surface_bary"].astype(np.float32),
            local_offsets=params["local_offsets"].astype(np.float32),
            hair_local_points=params["hair_local_points"].astype(np.float32))
        binding = {"schemaVersion":1,"assetSha256":audit["plySha256"],
            "sourceSha256":SOURCE_SHA256,"modelSha256":model.model_sha256,
            "parameterSha256":audit["optimizedParameterSha256"],
            "referenceFrame":reference_frame,"colorConvention":audit["colorRepresentation"],
            "gaussianCount":len(roles),
            "componentRoles":{"0":"skin_surface","1":"facial_detail_and_eyewear_mixed",
                              "2":"hair_search_volume"},
            "bindingNpZSha256":hashlib.sha256((out/"private-edit-binding.npz").read_bytes()).hexdigest(),
            "limits":["Research-only head, not an edit-ready full portrait",
                "Mask weights index this exact PLY only; old masks require explicit verified transfer",
                "Triangle normals and SH colors are not measured skin material",
                "Facial-detail role still mixes eyes, lips and eyewear; not a semantic safety boundary"]}
        (out/"private-edit-binding.json").write_text(json.dumps(binding,indent=2),encoding="utf-8")
    print(json.dumps(audit, indent=2))
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("parameters", type=Path)
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    parser.add_argument("--reference", type=int, default=35)
    parser.add_argument("--allow-research-binding", action="store_true")
    args = parser.parse_args()
    export(args.job, args.parameters, args.variant, args.reference,
           args.allow_research_binding)
