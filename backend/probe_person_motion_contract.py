"""Audit fixed-room cameras and one shared portrait scale on real frames.

The generic MediaPipe canonical face is an initialization only. No unseen
neck, clothes, identity geometry, or metric distance is inferred by this test.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from probe_static_alignment import best_model
from reconstruction_pose import canonical_vertices


def shared_scale(centers: np.ndarray, rays: np.ndarray) -> float:
    c = centers - centers.mean(axis=0)
    r = rays - rays.mean(axis=0)
    denominator = float(np.square(r).sum())
    if denominator < 1e-6:
        raise ValueError("relative_person_scale_unobservable")
    value = -float((c * r).sum()) / denominator
    if not math.isfinite(value) or value <= 0:
        raise ValueError("relative_person_scale_nonpositive")
    return value


def run(job: Path) -> dict:
    started = time.perf_counter()
    root = job / "static_sfm_probe_stride1"
    trusted = json.loads((root / "trusted_views.audit.json").read_text(encoding="utf-8"))
    names = [item["name"] for item in trusted["frames"] if item["researchTrusted"]]
    model = best_model(root / "targeted_global" / "sparse")
    images = {image.name: image for image in model.images.values() if image.has_pose}
    canonical = canonical_vertices()
    centers, rays, head_rotations, details = [], [], [], []
    train_indices = np.asarray([index for index in range(468) if index % 5 != 0])
    held_indices = np.asarray([index for index in range(468) if index % 5 == 0])
    with np.load(job / "face_landmarks.npz") as source:
        for name in names:
            image = images[name]
            points = source[name].astype(np.float64)
            K = np.asarray(model.cameras[image.camera_id].calibration_matrix(), dtype=np.float64)
            success, rvec, tvec, inliers = cv2.solvePnPRansac(
                canonical[train_indices], points[train_indices], K,
                np.zeros(4), iterationsCount=160, reprojectionError=12,
                confidence=.99, flags=cv2.SOLVEPNP_ITERATIVE)
            if not success or inliers is None or len(inliers) < 150:
                continue
            selected = train_indices[inliers[:, 0]]
            rvec, tvec = cv2.solvePnPRefineLM(canonical[selected], points[selected],
                                              K, np.zeros(4), rvec, tvec)
            predicted, _ = cv2.projectPoints(canonical[held_indices], rvec, tvec,
                                             K, np.zeros(4))
            hold_error = np.linalg.norm(predicted.reshape(-1, 2) - points[held_indices], axis=1)
            w2c = np.eye(4)
            w2c[:3, :] = np.asarray(image.cam_from_world().matrix())
            c2w = np.linalg.inv(w2c)
            ray = c2w[:3, :3] @ tvec.reshape(3)
            face_rotation = c2w[:3, :3] @ cv2.Rodrigues(rvec)[0]
            centers.append(c2w[:3, 3])
            rays.append(ray)
            head_rotations.append(face_rotation)
            details.append({"name": name, "heldLandmarkMedianPx": round(float(np.median(hold_error)), 2),
                            "heldLandmarkP90Px": round(float(np.quantile(hold_error, .9)), 2),
                            "landmarkInliers": len(selected)})
    if len(details) < 70:
        raise ValueError(f"person_pose_research_coverage_insufficient:{len(details)}")
    centers, rays = np.asarray(centers), np.asarray(rays)
    scale = shared_scale(centers, rays)
    left_scale = shared_scale(centers[:len(centers)//2], rays[:len(rays)//2])
    right_scale = shared_scale(centers[len(centers)//2:], rays[len(rays)//2:])
    head_centers = centers + scale * rays
    common_center = np.median(head_centers, axis=0)
    width = float(np.ptp(canonical[:, 0])) * scale
    drift_face_widths = np.linalg.norm(head_centers - common_center, axis=1) / width
    reference = details.index(next(item for item in details if item["name"] == "frame_0012.png"))
    absolute = np.eye(4)
    absolute[:3, :3] = head_rotations[reference]
    absolute[:3, 3] = head_centers[reference]
    relative = absolute @ np.linalg.inv(absolute)
    if not np.allclose(relative, np.eye(4), atol=1e-9):
        raise AssertionError("reference_relative_transform_not_identity")
    fixed_face_world = (absolute[:3, :3] @ (canonical[held_indices] * scale).T).T + absolute[:3, 3]
    fixed_errors = []
    with np.load(job / "face_landmarks.npz") as source:
        for item in details:
            image = images[item["name"]]
            K = np.asarray(model.cameras[image.camera_id].calibration_matrix(), dtype=np.float64)
            w2c = np.eye(4)
            w2c[:3, :] = np.asarray(image.cam_from_world().matrix())
            camera_xyz = (w2c[:3, :3] @ fixed_face_world.T).T + w2c[:3, 3]
            if (camera_xyz[:, 2] <= 0).any():
                raise ValueError("reference_head_behind_camera")
            projected = (K @ camera_xyz.T).T
            projected = projected[:, :2] / projected[:, 2, None]
            error = np.linalg.norm(projected - source[item["name"]][held_indices], axis=1)
            fixed_errors.append(float(np.median(error)))
    yaw = Rotation.from_matrix(np.asarray(head_rotations)).as_euler("yxz", degrees=True)[:, 0]
    report = {"cameraCandidate": "targeted_global_fixed", "trustedInput": len(names),
              "headPnPViews": len(details), "sharedScaleSceneUnitsPerCanonicalUnit": round(scale, 5),
              "firstHalfScale": round(left_scale, 5), "secondHalfScale": round(right_scale, 5),
              "scaleHalfRatio": round(max(left_scale, right_scale) / min(left_scale, right_scale), 3),
              "headCenterDriftMedianFaceWidths": round(float(np.median(drift_face_widths)), 3),
              "headCenterDriftP90FaceWidths": round(float(np.quantile(drift_face_widths, .9)), 3),
              "heldLandmarkMedianPx": round(float(np.median([row["heldLandmarkMedianPx"] for row in details])), 2),
              "heldLandmarkP90Px": round(float(np.quantile([row["heldLandmarkP90Px"] for row in details], .9)), 2),
              "fixedReferenceHeadHeldLandmarkMedianPx": round(float(np.median(fixed_errors)), 2),
              "fixedReferenceHeadHeldLandmarkP90Px": round(float(np.quantile(fixed_errors, .9)), 2),
              "referenceFrame": details[reference]["name"],
              "referenceAbsoluteHeadIsIdentity": bool(np.allclose(absolute, np.eye(4), atol=1e-6)),
              "referenceRelativeHeadIsIdentity": True,
              "headWorldYawSpanDiagnostic": [round(float(yaw.min()), 2), round(float(yaw.max()), 2)],
              "bodyMotionFit": None, "neckShoulderContinuity": "not_tested",
              "relativeDepthIsIndependentTruth": False,
              "warning": "dynamic-vs-fixed comparison uses detected 2D landmarks, not rendered ghosting or true body motion; monocular person-room scale remains a prior",
              "elapsedSeconds": round(time.perf_counter() - started, 2), "perFrame": details}
    output = root / "person_motion_contract.audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "perFrame"}), flush=True)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_person_motion_contract.py JOB_DIR")
    run(Path(sys.argv[1]))
