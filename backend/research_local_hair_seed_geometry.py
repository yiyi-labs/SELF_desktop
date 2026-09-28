"""Isolated observed-hair-seed refinement of one frozen Open research run.

Only two-view-triangulated training pixels with independent training-view mask
support enter. Original splats stay; parent/child alpha is split to preserve
coverage. This remains a head-only research candidate, never a tablet asset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from scipy.spatial import cKDTree
from gsplat import export_splats

from appearance_direction_contract import sh1_head_to_reference, C0
from export_flame_appearance_research import means_for_view, normalize
from flame_open_model import FlameOpen, MODEL
from probe_flame_hair_hull import local_observations, pixels
from probe_flame_open_fit import HELD, SOURCE_SHA256, TRAIN, filename
from train_flame_local_appearance import (TrainablePortrait, build_candidates,
                                          loss_for, make_view, quat_multiply,
                                          save_comparison, score)


def choose_seeds(job: Path, root: Path, candidate: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    source = root / "private-component-tracks/private-hair-seeds.npz"
    with np.load(source) as data:
        positions = data["local_points"]
        colors = data["source_rgb"]
        pair = data["source_pair"]
        if str(data["source_sha256"]) != SOURCE_SHA256:
            raise ValueError("hair_seed_source_mismatch")
    transforms = local_observations(root)
    independent_hits = np.zeros(len(positions), np.int32)
    contradictions = np.zeros(len(positions), np.int32)
    for frame in TRAIN:
        hair = cv2.imread(str(job / "portrait_components_20260927" /
                              f"hair-{filename(frame)}"), cv2.IMREAD_GRAYSCALE)
        if hair is None:
            raise FileNotFoundError(frame)
        x, y, z = pixels(positions, transforms[frame])
        good = (z > .03) & (x >= 0) & (x < hair.shape[1]) & (y >= 0) & (y < hair.shape[0])
        observed = good & (hair[y.clip(0, hair.shape[0]-1),
                                x.clip(0, hair.shape[1]-1)] > 127)
        independent_hits += observed & (pair[:, 0] != frame) & (pair[:, 1] != frame)
        contradictions += good & ~observed
    distance, nearest = cKDTree(candidate["hair_points"]).query(positions)
    admissible = ((independent_hits >= 8) & (contradictions <= 3) &
                  (distance >= .003) & (distance <= .014))
    # One actual training-observed seed per parent prevents stacking copies.
    selected = []
    used = set()
    for index in np.flatnonzero(admissible)[np.argsort(distance[admissible])[::-1]]:
        parent = int(nearest[index])
        if parent not in used:
            selected.append(int(index))
            used.add(parent)
    selected = np.asarray(selected, np.int32)
    evidence = {"allTriangulatedSeeds": len(positions),
                "independentlySupportedBeforeDedup": int(admissible.sum()),
                "selectedSeedCount": len(selected),
                "selection": "at least 8 other training hair masks, at most 3 contradictions, 3-14 mm from hull, unique parent",
                "selectedDisplacementMmP50P90":
                    [float(v*1000) for v in np.quantile(distance[selected], [.5, .9])] if len(selected) else [],
                "selectedSourcePairs": pair[selected].tolist(),
                "heldImagesUsedForSelection": False,
                "limits": "2D hair-mask support does not independently prove depth or occlusion ordering"}
    if len(selected) < 12:
        raise RuntimeError(f"insufficient_supported_hair_seed_geometry:{len(selected)}")
    return positions[selected], colors[selected], {
        **evidence, "selectedOriginalSeedIndex": selected.tolist(),
        "parentHairIndex": nearest[selected].astype(int).tolist(),
        "independentTrainingMaskHits": independent_hits[selected].tolist(),
        "sourceTrainingPairs": pair[selected].tolist()}


def run(job: Path, baseline: Path, run_id: str, steps: int = 180) -> dict:
    if not run_id or not run_id.replace("-", "").isalnum() or steps < 1 or steps > 300:
        raise ValueError("invalid_bounded_geometry_run")
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    root = job / "flame_open_e2_20260927"
    out = root / f"private-observed-hair-geometry-{run_id}"
    if out.exists():
        raise FileExistsError(out)
    out.mkdir()
    start = time.perf_counter()
    with np.load(baseline) as data:
        params = {key: data[key] for key in data.files}
    if (str(params["color_mode"]) != "head-local-sh1" or
            str(params["model_sha256"]) != FlameOpen(24, 12, model_path=MODEL).model_sha256):
        raise ValueError("unsupported_frozen_baseline")
    device = torch.device("cuda")
    torch.cuda.reset_peak_memory_stats()
    free_before, total = torch.cuda.mem_get_info()
    geometry = FlameOpen(24, 12, model_path=MODEL).to(device)
    initial = build_candidates(job, geometry, device)
    for key, source in (("roles", "role"), ("surface_ids", "surface_ids"),
                        ("surface_bary", "surface_bary"), ("hair_points", "hair_local_points")):
        if not np.array_equal(initial[key], params[source]):
            raise ValueError(f"baseline_geometry_binding_changed:{key}")
    seeds, rgb, evidence = choose_seeds(job, root, initial)
    fit = dict(np.load(root / "private-fit-parameters.npz"))
    held = dict(np.load(root / "private-held-local-parameters.npz"))
    transforms = local_observations(root)
    selected = tuple(evidence["selectedOriginalSeedIndex"])
    parent_hair = np.asarray(evidence["parentHairIndex"], np.int64)
    parent = initial["surface_count"]+parent_hair
    device_baseline = TrainablePortrait(initial, device, "head-local-sh1").to(device)
    with torch.no_grad():
        for name, param in device_baseline.named_parameters():
            param.copy_(torch.from_numpy(params[name]).to(device))
    updated = dict(initial)
    n_old = len(initial["roles"])
    updated["hair_points"] = np.concatenate((initial["hair_points"], seeds))
    updated["roles"] = np.concatenate((initial["roles"], np.full(len(seeds), 2, np.int64)))
    updated["initial_rgb"] = np.concatenate((initial["initial_rgb"], rgb))
    updated["initial_scale"] = np.concatenate((initial["initial_scale"],
                                                initial["initial_scale"][parent]*.72))
    updated["source_index"] = np.concatenate((initial["source_index"], -np.asarray(selected)-1))
    updated["origin_index"] = np.concatenate((initial["origin_index"], parent.astype(np.int32)))
    updated["confidence"] = np.concatenate((initial["confidence"],
                                            np.asarray(evidence["independentTrainingMaskHits"], np.uint8)))
    updated["counts"] = {**initial["counts"], "hair": initial["counts"]["hair"]+len(seeds)}
    model = TrainablePortrait(updated, device, "head-local-sh1").to(device)
    with torch.no_grad():
        for name, parameter in model.named_parameters():
            previous = getattr(device_baseline, name).detach()
            parameter[:n_old].copy_(previous)
            parameter[n_old:].copy_(previous[torch.from_numpy(parent).to(device)])
        model.sh_coeff[n_old:, 0] = (torch.from_numpy(rgb).to(device)-.5)/C0
        model.local_offsets[n_old:] = 0.
        # Two co-located equal-alpha splats have exactly their original
        # transmittance; moving the child is then explicitly coverage-tested.
        all_split = torch.cat((torch.from_numpy(parent).to(device),
                               torch.arange(n_old, n_old+len(seeds), device=device)))
        original_alpha = torch.sigmoid(model.opacity_logits[torch.from_numpy(parent).to(device)])
        split_logit = torch.logit((1-torch.sqrt(1-original_alpha)).clamp(.001, .999))
        model.opacity_logits[all_split] = split_logit.repeat(2)
        model.log_scales[all_split] += math.log(.72)
        model.initial_log_scales.copy_(model.log_scales)
        model.initial_opacity.copy_(model.opacity_logits)
        model.initial_rgb.copy_(model.base_rgb_logits)
    view_ids = TRAIN + HELD
    old_views = {i: make_view(job, geometry, fit, held, initial, i,
                             transforms[i], device) for i in view_ids}
    new_views = {i: make_view(job, geometry, fit, held, updated, i,
                             transforms[i], device) for i in view_ids}
    reference = {}
    with torch.no_grad():
        for i in view_ids:
            image, _, _ = device_baseline.raster(old_views[i])
            reference[i] = (image[:, :, :3].cpu().numpy()*255).round().clip(0, 255).astype(np.uint8)
    before = {str(i): score(device_baseline, old_views[i]) for i in HELD}
    geometry_only = {str(i): score(model, new_views[i]) for i in HELD}
    save_comparison(out, "geometry", model, [new_views[i] for i in (35, 75, 145)], reference)
    active = np.unique(np.r_[parent, np.arange(n_old, n_old+len(seeds))])
    gradient_mask = torch.zeros((len(updated["roles"]), 1), device=device)
    gradient_mask[torch.from_numpy(active).to(device)] = 1
    for name, param in model.named_parameters():
        param.register_hook(lambda grad, mask=gradient_mask: grad*mask.view(
            (len(mask),)+(1,)*(grad.ndim-1)))
    opt = torch.optim.Adam([
        {"params": [model.sh_coeff], "lr": .002},
        {"params": [model.opacity_logits], "lr": .003},
        {"params": [model.log_scales], "lr": .0008},
        {"params": [model.local_offsets], "lr": .00015},
    ])
    loss_curve = []
    for step in range(steps):
        frame = TRAIN[step % len(TRAIN)]
        loss, components = loss_for(model, new_views[frame])
        if not torch.isfinite(loss):
            raise RuntimeError(f"nonfinite_hair_geometry_loss:{step}")
        loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        if step in (0, steps//2, steps-1):
            loss_curve.append({"step": step+1, "frame": frame,
                               "loss": float(loss.detach()), **components})
    after = {str(i): score(model, new_views[i]) for i in HELD}
    save_comparison(out, "final", model, [new_views[i] for i in (35, 75, 145)], reference)
    reference_view = new_views[35]
    means = means_for_view(reference_view, updated["roles"],
                           model.local_offsets.detach().cpu().numpy())
    reference_root = reference_view.root_rotation.cpu().numpy()
    coeff = sh1_head_to_reference(model.sh_coeff.detach().cpu().numpy(), reference_root)
    shN = np.zeros((len(coeff), 15, 3), np.float32)
    shN[:, :3] = coeff[:, 1:]
    root_quat = reference_view.root_quat.cpu().numpy()
    local_quats = normalize(model.local_quats.detach().cpu().numpy())
    quats = quat_multiply(torch.from_numpy(np.tile(root_quat, (len(coeff), 1))),
                          torch.from_numpy(local_quats)).numpy()
    exported = out / "private-reference-0035-ply-contract"
    exported.mkdir()
    ply = exported / "research-head-only.gaussian.ply"
    export_splats(means=torch.from_numpy(means.astype(np.float32)),
                  scales=torch.from_numpy(torch.clamp(model.log_scales.exp(), .00045, .018).log().detach().cpu().numpy()),
                  quats=torch.from_numpy(normalize(quats).astype(np.float32)),
                  opacities=model.opacity_logits.detach().cpu(),
                  sh0=torch.from_numpy(coeff[:, :1].astype(np.float32)),
                  shN=torch.from_numpy(shN), format="ply", save_to=str(ply))
    old_view = baseline.parent / "private-reference-0035-ply-contract/portrait.view.json"
    (exported / "portrait.view.json").write_bytes(old_view.read_bytes())
    torch.cuda.synchronize()
    report = {"status": "isolated_observed_hair_geometry_candidate_not_for_app",
              "sourceSha256": SOURCE_SHA256,
              "baselineParameterSha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
              "hairSeedSha256": hashlib.sha256((root / "private-component-tracks/private-hair-seeds.npz").read_bytes()).hexdigest(),
              "plySha256": hashlib.sha256(ply.read_bytes()).hexdigest(),
              "pointCountBeforeAfter": [n_old, len(coeff)], "seedEvidence": evidence,
              "localOptimizerSteps": steps, "lossCurve": loss_curve,
              "heldBaseline": before, "heldGeometryOnly": geometry_only,
              "heldRefined": after,
              "seconds": round(time.perf_counter()-start, 2),
              "cudaPeakAllocatedMiB": round(torch.cuda.max_memory_allocated()/1024**2, 1),
              "cudaPeakReservedMiB": round(torch.cuda.max_memory_reserved()/1024**2, 1),
              "cudaTotalMiB": round(total/1024**2, 1),
              "cudaFreeStartMiB": round(free_before/1024**2, 1),
              "limits": ["Head-only black-background research sample",
                         "Sparse seed constraints do not establish full hair volume",
                         "No neck, shoulder, clothing or room joint result",
                         "No tablet transfer and no release assertion"]}
    (out / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "pointCountBeforeAfter",
                        "localOptimizerSteps", "seconds", "cudaPeakAllocatedMiB", "plySha256")}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--steps", type=int, default=180)
    args = parser.parse_args()
    run(args.job, args.baseline, args.run_id, args.steps)
