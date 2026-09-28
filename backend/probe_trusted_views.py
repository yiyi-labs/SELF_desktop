"""Pick an E1 research subset with explicit camera evidence and face coverage.

MediaPipe/PnP angles are *diagnostics* for coverage, not ground-truth head
pose. This selection cannot be used as a production publication gate.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pycolmap
from scipy.spatial.transform import Rotation

from probe_static_alignment import best_model
from reconstruction_pose import canonical_vertices, pose_from_landmarks


def run(job: Path) -> dict:
    manifest = json.loads((job / "frame_manifest.audit.json").read_text(encoding="utf-8"))
    quality = json.loads((job / "static_sfm_probe_stride1" / "frame_quality.json").read_text(encoding="utf-8"))
    root = job / "static_sfm_probe_stride1"
    incremental = best_model(root / "sparse")
    global_model = best_model(root / "calibrated_global" / "sparse")
    transform = pycolmap.align_reconstructions_via_proj_centers(global_model, incremental, .05)
    if transform is None:
        raise ValueError("candidate_alignment_failed")
    rotation = np.asarray(transform.rotation.matrix())
    inc_images = {image.name: image for image in incremental.images.values() if image.has_pose}
    global_images = {image.name: image for image in global_model.images.values() if image.has_pose}
    vertices = canonical_vertices()
    with np.load(job / "face_landmarks.npz") as landmarks:
        records = []
        for frame in manifest["frames"]:
            name = frame["name"]
            candidate = frame["candidates"]["static_global_estimated_focal"]
            if not candidate["registered"]:
                raise ValueError(f"global_camera_missing:{name}")
            K = np.asarray(candidate["K"])
            try:
                face_R, _, rmse, _ = pose_from_landmarks(vertices, landmarks[name], K)
                face_yaw = math.degrees(math.atan2(float(face_R[0, 2]), float(face_R[2, 2])))
            except RuntimeError:
                rmse, face_yaw = None, None
            inc = quality["perFrame"]["static_incremental"][name]
            global_quality = quality["perFrame"]["static_global_estimated_focal"][name]
            reasons = []
            center_residual = orientation_residual = None
            if not inc["registered"]:
                reasons.append("not_registered_by_incremental_static")
            else:
                old_image = inc_images[name]
                new_image = global_images[name]
                center = transform.scale * rotation @ np.asarray(new_image.projection_center()) + np.asarray(transform.translation)
                center_residual = float(np.linalg.norm(center - np.asarray(old_image.projection_center())))
                inc_c2w = np.asarray(old_image.cam_from_world().matrix())[:3, :3].T
                glob_c2w = np.asarray(new_image.cam_from_world().matrix())[:3, :3].T
                orientation_residual = float(Rotation.from_matrix(
                    inc_c2w.T @ rotation @ glob_c2w).magnitude() * 180 / math.pi)
                if inc["staticInliers"] < 60:
                    reasons.append("too_few_static_inliers")
                if inc["occupiedGridCells4x4"] < 4:
                    reasons.append("static_inliers_spatially_concentrated")
                if inc["longTracks8Plus"] < 40:
                    reasons.append("too_few_long_static_tracks")
                if inc["reprojectionP90Px"] > 2.5:
                    reasons.append("high_reprojection_tail")
                if center_residual > .1 or orientation_residual > 1.:
                    reasons.append("static_camera_candidates_disagree")
            if face_yaw is None:
                reasons.append("face_orientation_unavailable")
            records.append({"name": name, "timeSeconds": frame["timestampSeconds"],
                            "faceYawPnpDiagnosticDegrees": None if face_yaw is None else round(face_yaw, 2),
                            "facePnpRmsePx": None if rmse is None else round(rmse, 2),
                            "incrementalStaticInliers": inc.get("staticInliers", 0),
                            "globalStaticInliers": global_quality.get("staticInliers", 0),
                            "cameraCenterAgreementSceneUnits": None if center_residual is None else round(center_residual, 4),
                            "cameraOrientationAgreementDegrees": None if orientation_residual is None else round(orientation_residual, 3),
                            "researchTrusted": not reasons, "reasons": reasons})
    reference_yaw = next(item["faceYawPnpDiagnosticDegrees"] for item in records
                         if item["name"] == "frame_0012.png")
    if reference_yaw is None:
        raise ValueError("opening_face_direction_unavailable")
    for item in records:
        angle = item["faceYawPnpDiagnosticDegrees"]
        if angle is not None:
            item["faceYawPnpDiagnosticDegrees"] = round((angle - reference_yaw + 180) % 360 - 180, 2)
    trusted = [item for item in records if item["researchTrusted"]]
    bins = sorted({round(item["faceYawPnpDiagnosticDegrees"] / 10) * 10 for item in trusted})
    report = {"researchTrustedCount": len(trusted), "referenceFrame": "frame_0012.png",
              "coveragePnpTenDegreeBins": bins,
              "minPnpYaw": min(item["faceYawPnpDiagnosticDegrees"] for item in trusted),
              "maxPnpYaw": max(item["faceYawPnpDiagnosticDegrees"] for item in trusted),
              "note": "These are research-only cameras; PnP yaw and COLMAP are not independent ground truth",
              "frames": records}
    output = root / "trusted_views.audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "frames"}), flush=True)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_trusted_views.py JOB_DIR")
    run(Path(sys.argv[1]))
