"""Small reversible suppression experiment on one frozen private full scene.

Only points with high visible contribution inside observed head pixels and
very low contribution to visible room in the *same* source views qualify.
This is not an automatic pruning rule or a publishable asset.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from audit_joint_reconstruction_visibility import load_mask, load_upright_rgb, image_u8
from reconstruction_joint_visibility import load_recorded_ply, render_shared
from reconstruction_train import load_scene


def measure(rendered: dict, source: np.ndarray, inside: np.ndarray,
            background: np.ndarray) -> dict:
    alpha = rendered["alpha"].detach().cpu().numpy()
    rgb = rendered["rgb"].detach().cpu().numpy()
    image = np.clip(rgb + (1 - alpha[..., None]) * .08, 0, 1)
    q_room = rendered["q_environment"].detach().cpu().numpy()
    q_person = rendered["q_person"].detach().cpu().numpy()
    return {"faceL1IncludingMissing": float(np.abs(image[inside]-source[inside]).mean()),
            "visibleRoomL1IncludingMissing":
            float(np.abs(image[background]-source[background]).mean()),
            "faceAlphaMean": float(alpha[inside].mean()),
            "faceEnvironmentContributionMean": float(q_room[inside].mean()),
            "facePersonContributionMean": float(q_person[inside].mean()),
            "visibleRoomEnvironmentContributionMean": float(q_room[background].mean())}


def run(job: Path, ply: Path, audit: Path, output: Path,
        ratio_limit: float = .1, factor: float = .25,
        max_candidates: int = 64, min_weight: float = 50) -> dict:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    started = time.perf_counter()
    earlier = json.loads((audit / "audit.json").read_text(encoding="utf-8"))
    if earlier["status"] != "shared_visibility_diagnostic":
        raise ValueError("shared_visibility_audit_required")
    view = json.loads((job / "portrait.view.json").read_text(encoding="utf-8"))
    asset = load_recorded_ply(ply, int(view["editableSplats"]))
    if asset["ply_sha256"] != earlier["plySha256"]:
        raise ValueError("frozen_ply_hash_mismatch")
    if (not 1 <= max_candidates <= 512 or not 0 < factor < 1 or
            not 0 < ratio_limit < 1 or not 0 < min_weight <= 100):
        raise ValueError("counterfactual_bounds_invalid")
    weights_path = audit / "private-point-visible-weights.npz"
    if weights_path.is_file():
        with np.load(weights_path) as weights:
            if str(weights["plySha256"]) != asset["ply_sha256"] or int(
                    weights["editableSplats"]) != asset["person_count"]:
                raise ValueError("point_weight_asset_contract_failed")
            bad = weights["faceIntrusion"]
            good = weights["roomSupport"]
        if len(bad) != len(asset["means"])-asset["person_count"]:
            raise ValueError("point_weight_count_mismatch")
        eligible = np.flatnonzero((bad > min_weight) &
                                 (good / np.maximum(bad, 1e-9) < ratio_limit))
        chosen_ids = eligible[np.argsort(bad[eligible])[::-1]][:max_candidates]
        chosen_indices = (chosen_ids + asset["person_count"]).tolist()
    else:
        chosen_indices = [item["plyIndex"] for item in earlier["suspects"] if
                          item["roomSupportToIntrusionRatio"] < ratio_limit and
                          item["trustedFaceVisibleWeight"] > min_weight][:max_candidates]
    if not chosen_indices:
        raise ValueError("no_source_supported_counterfactual_candidates")
    ids = torch.as_tensor(chosen_indices, device="cuda")
    candidate_opacity = asset["opacity"].clone()
    candidate_opacity[ids] *= factor
    cameras = {entry[0].name: entry for entry in load_scene(job)[0]}
    with np.load(job / "face_camera_poses.npz") as source:
        poses = dict(zip(map(str, source["names"]), source["w2c"]))
    rows = []
    for checked in earlier["checks"]:
        name = checked["name"]
        frame_path, world_pose, K, source_width, source_height = cameras[name]
        width, height = checked["analysisResolution"]
        scale = width / source_width
        K = K.copy(); K[:2, :] *= scale
        source_rgb = load_upright_rgb(frame_path, (width, height))
        inside = load_mask(job / "face_masks" / (name + ".png"),
                           (width, height), erode=max(2, round(12 * scale)))
        background = load_mask(job / "environment_masks" / (name + ".png"),
                               (width, height), erode=max(2, round(8 * scale)))
        with torch.no_grad():
            before = render_shared(asset, world_pose, poses[name], K, width, height)
            after = render_shared(asset, world_pose, poses[name], K, width, height,
                                  opacity_override=candidate_opacity)
        old = measure(before, source_rgb, inside, background)
        new = measure(after, source_rgb, inside, background)
        def display(rendered):
            alpha = rendered["alpha"].detach().cpu().numpy()
            rgb = rendered["rgb"].detach().cpu().numpy()
            return image_u8(np.clip(rgb + (1-alpha[..., None])*.08, 0, 1))
        contact = Image.new("RGB", (width*3, height))
        for i, image in enumerate((image_u8(source_rgb), display(before), display(after))):
            contact.paste(image, (i*width, 0))
        contact.save(output / f"{Path(name).stem}-source-base-clean.png")
        rows.append({"name": name, "base": old, "clean": new,
                     "faceL1Change": new["faceL1IncludingMissing"]-old["faceL1IncludingMissing"],
                     "roomL1Change": new["visibleRoomL1IncludingMissing"]-
                                     old["visibleRoomL1IncludingMissing"]})
    accepted = (all(row["faceL1Change"] < -.003 and row["roomL1Change"] < .002
                    and row["clean"]["faceAlphaMean"] >=
                    row["base"]["faceAlphaMean"] - .01 for row in rows))
    report = {"status": "candidate_not_published", "sourcePlySha256": asset["ply_sha256"],
              "candidateCount": len(chosen_indices), "indices": [int(i) for i in ids.cpu().tolist()],
              "opacityFactor": factor, "ratioLimit": ratio_limit,
              "minimumVisibleWeight": min_weight, "frames": rows,
              "predeclaredMetricScreenPassed": accepted,
              "elapsedSeconds": round(time.perf_counter()-started, 2),
              "limits": ["Opacity suppression is a causal diagnostic, not corrected geometry",
                         "Source masks and COLMAP world cameras still require independent audit",
                         "No PLY exported; full scene, rotating views and neck/collar not yet accepted"]}
    (output / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("ply", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-candidates", type=int, default=64)
    parser.add_argument("--ratio-limit", type=float, default=.1)
    parser.add_argument("--min-weight", type=float, default=50)
    args = parser.parse_args()
    result = run(args.job, args.ply, args.audit, args.output,
                 ratio_limit=args.ratio_limit, max_candidates=args.max_candidates,
                 min_weight=args.min_weight)
    print(json.dumps({key: result[key] for key in
                      ("status", "candidateCount", "predeclaredMetricScreenPassed",
                       "elapsedSeconds")}, ensure_ascii=False))
