"""Find tentative side views with two graph-perturbation checks.

Consistency is not ground truth; views unsupported by room texture remain
tentative and cannot authorize a published ±60 degree result.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pycolmap
from scipy.spatial.transform import Rotation

from probe_static_alignment import best_model


def aligned_residuals(reference: pycolmap.Reconstruction,
                      test: pycolmap.Reconstruction) -> dict[str, tuple[float, float]]:
    transform = pycolmap.align_reconstructions_via_proj_centers(test, reference, .05)
    if transform is None:
        raise ValueError("static_candidate_alignment_failed")
    rotation = np.asarray(transform.rotation.matrix())
    reference_images = {image.name: image for image in reference.images.values() if image.has_pose}
    result = {}
    for image in test.images.values():
        if not image.has_pose or image.name not in reference_images:
            continue
        old = reference_images[image.name]
        center = transform.scale * rotation @ np.asarray(image.projection_center()) + np.asarray(transform.translation)
        delta = float(np.linalg.norm(center - np.asarray(old.projection_center())))
        old_c2w = np.asarray(old.cam_from_world().matrix())[:3, :3].T
        new_c2w = np.asarray(image.cam_from_world().matrix())[:3, :3].T
        degrees = math.degrees(Rotation.from_matrix(old_c2w.T @ rotation @ new_c2w).magnitude())
        result[image.name] = (delta, degrees)
    return result


def run(job: Path) -> dict:
    root = job / "static_sfm_probe_stride1"
    reference = best_model(root / "targeted_global" / "sparse")
    variations = [best_model(root / f"targeted_global_graph_perturb_seed{seed}" / "sparse")
                  for seed in (260926, 260927)]
    residuals = [aligned_residuals(reference, variation) for variation in variations]
    quality = json.loads((root / "targeted_global" / "frame_quality.json").read_text(encoding="utf-8"))["perFrame"]
    yaw = {row["name"]: row["faceYawPnpDiagnosticDegrees"] for row in
           json.loads((root / "trusted_views.audit.json").read_text(encoding="utf-8"))["frames"]}
    rows = []
    for number in range(1, 161):
        name = f"frame_{number:04d}.png"
        evidence = quality[name]
        perturb = [check.get(name) for check in residuals]
        reasons = []
        if not evidence["registered"] or None in perturb:
            reasons.append("unregistered_after_graph_perturbation")
        else:
            if evidence["staticInliers"] < 60:
                reasons.append("few_static_inliers")
            if evidence["occupiedGridCells4x4"] < 4:
                reasons.append("concentrated_static_inliers")
            if evidence["longTracks8Plus"] < 40:
                reasons.append("few_long_tracks")
            if evidence["reprojectionP90Px"] > 2.5:
                reasons.append("reprojection_tail")
            if any(center > .1 or angle > 1 for center, angle in perturb):
                reasons.append("camera_unstable_under_static_graph_perturbation")
        rows.append({"name": name, "pnpYawDiagnostic": yaw[name],
                     "staticInliers": evidence.get("staticInliers", 0),
                     "gridCells": evidence.get("occupiedGridCells4x4", 0),
                     "perturbResiduals": perturb, "tentativeResearchView": not reasons,
                     "reasons": reasons})
    selected = [item for item in rows if item["tentativeResearchView"]]
    report = {"tentativeResearchViews": len(selected),
              "tentativeMiddle61To100": sum(61 <= int(item["name"][6:10]) <= 100 for item in selected),
              "yawMin": min(item["pnpYawDiagnostic"] for item in selected),
              "yawMax": max(item["pnpYawDiagnostic"] for item in selected),
              "note": "two perturbations are correlated to the same source video, features and estimated focal; no independent ground truth",
              "frames": rows}
    (root / "targeted_consensus.audit.json").write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "frames"}), flush=True)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_targeted_consensus.py JOB_DIR")
    run(Path(sys.argv[1]))
