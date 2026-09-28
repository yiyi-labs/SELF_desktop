"""Measure face motion against the room camera path before fitting one GS scene.

MediaPipe's 468-vertex canonical face is used only for pose constraints. The
output remains one room-and-person Gaussian asset; a face-view camera is used
while fitting the face so ordinary hand/head motion does not duplicate eyes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def refit_local_pose_same_camera(local_vertices, local_landmarks, observed,
                                camera_K, distortion, initial_F):
    """Fixed shape/expression, one local rigid PnP in the actual camera model.

    It does not change or invent a world camera. Every fifth landmark is
    excluded from fitting and reported separately as development geometry.
    """
    import cv2
    import numpy as np
    selected=np.arange(len(observed))%5!=0
    rvec=cv2.Rodrigues(np.asarray(initial_F[:3,:3],np.float64))[0]
    tvec=np.asarray(initial_F[:3,3],np.float64).reshape(3,1).copy()
    rvec,tvec=cv2.solvePnPRefineLM(np.asarray(local_landmarks[selected],np.float64),
        np.asarray(observed[selected],np.float64),camera_K,distortion,rvec,tvec)
    result=np.eye(4);result[:3,:3]=cv2.Rodrigues(rvec)[0];result[:3,3]=tvec[:,0]
    pred=cv2.projectPoints(local_landmarks.astype(np.float64),rvec,tvec,
                           camera_K,distortion)[0][:,0]
    error=np.linalg.norm(pred-observed,axis=1)
    change=cv2.Rodrigues(result[:3,:3]@initial_F[:3,:3].T)[0]
    report={"fitMedianPixels":float(np.median(error[selected])),
            "developmentLandmarkMedianPixels":float(np.median(error[~selected])),
            "rotationChangeDegrees":float(np.linalg.norm(change)*180/np.pi),
            "translationChangeModelUnits":float(np.linalg.norm(result[:3,3]-initial_F[:3,3])),
            "worldCameraChanged":False,"sharedShapeChanged":False}
    return result,report

import cv2
import numpy as np
import pycolmap
from scipy.spatial.transform import Rotation


HERE = Path(__file__).resolve().parent
CANONICAL_FACE = HERE / "models" / "canonical_face_model.obj"
CANONICAL_SHA256 = "8bac80443397e113f41a8b565ea72c59390bc031d9defab289dba7bc0c54e618"


def canonical_vertices() -> np.ndarray:
    if not CANONICAL_FACE.is_file() or hashlib.sha256(CANONICAL_FACE.read_bytes()).hexdigest() != CANONICAL_SHA256:
        raise RuntimeError("canonical_face_geometry_missing_or_changed")
    vertices = np.asarray([
        [float(value) for value in line.split()[1:4]]
        for line in CANONICAL_FACE.read_text(encoding="utf-8").splitlines()
        if line.startswith("v ")
    ], dtype=np.float64)
    if vertices.shape != (468, 3):
        raise RuntimeError("canonical_face_topology_changed")
    return vertices


def pose_from_landmarks(vertices: np.ndarray, points: np.ndarray,
                        intrinsic: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, int]:
    ok, rvec, tvec, inliers = cv2.solvePnPRansac(
        vertices, points, intrinsic, np.zeros(4),
        iterationsCount=160, reprojectionError=12.0, confidence=.99,
        flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok or inliers is None or len(inliers) < 160:
        raise RuntimeError("face_pose_insufficient_landmarks")
    selected = inliers[:, 0]
    rvec, tvec = cv2.solvePnPRefineLM(vertices[selected], points[selected],
                                      intrinsic, np.zeros(4), rvec, tvec)
    projection, _ = cv2.projectPoints(vertices[selected], rvec, tvec,
                                      intrinsic, np.zeros(4))
    error = projection.reshape(-1, 2) - points[selected]
    rmse = float(np.sqrt(np.mean(np.sum(error * error, axis=1))))
    if not np.isfinite(rmse) or rmse > 12:
        raise RuntimeError("face_pose_reprojection_unreliable")
    return cv2.Rodrigues(rvec)[0], tvec.reshape(3), rmse, len(selected)


def prepare_face_views(path: Path) -> dict:
    """Align only face training views; keep original cameras for the room."""
    vertices = canonical_vertices()
    model = pycolmap.Reconstruction(path / "sparse" / "0")
    observations = np.load(path / "face_landmarks.npz")
    records = []
    for image in sorted(model.images.values(), key=lambda item: item.name):
        if not image.has_pose or image.name not in observations:
            continue
        points = observations[image.name].astype(np.float64)
        intrinsic = np.asarray(model.cameras[image.camera_id].calibration_matrix(), dtype=np.float64)
        try:
            face_rotation, face_translation, rmse, inliers = pose_from_landmarks(
                vertices, points, intrinsic)
        except RuntimeError:
            continue
        w2c = np.eye(4, dtype=np.float64)
        w2c[:3, :] = np.asarray(image.cam_from_world().matrix())
        c2w = np.linalg.inv(w2c)
        world_rotation = c2w[:3, :3] @ face_rotation
        camera_center = c2w[:3, 3]
        face_ray = c2w[:3, :3] @ face_translation
        records.append((image.name, w2c, world_rotation, camera_center, face_ray,
                        rmse, inliers, face_rotation, face_translation))
    if len(records) < max(16, round(len(observations.files) * .75)):
        raise RuntimeError("face_pose_coverage_insufficient")
    camera_centers = np.stack([item[3] for item in records])
    face_rays = np.stack([item[4] for item in records])
    centered_cameras = camera_centers - np.median(camera_centers, axis=0)
    centered_rays = face_rays - np.median(face_rays, axis=0)
    scale = -float(np.sum(centered_cameras * centered_rays)) / float(np.sum(centered_rays ** 2))
    if not np.isfinite(scale) or scale <= 0:
        raise RuntimeError("face_pose_metric_scale_unreliable")
    face_centers = camera_centers + scale * face_rays
    rotations = Rotation.from_matrix(np.stack([item[2] for item in records]))
    center_median = np.median(face_centers, axis=0)
    rotation_med = rotations.mean().as_matrix()
    distances = np.linalg.norm(face_centers - center_median, axis=1) / (14 * scale)
    rotation_distances = (Rotation.from_matrix(rotation_med.T @ rotations.as_matrix()).magnitude()
                          * 180 / np.pi)
    medoid = int(np.argmin(distances + rotation_distances / 90))
    reference = np.eye(4)
    reference[:3, :3] = records[medoid][2]
    reference[:3, 3] = face_centers[medoid]
    inverse_reference = np.linalg.inv(reference)
    corrected = []
    for record, face_center in zip(records, face_centers):
        current = np.eye(4)
        current[:3, :3] = record[2]
        current[:3, 3] = face_center
        corrected.append(record[1] @ current @ inverse_reference)
    names = np.asarray([item[0] for item in records])
    np.savez_compressed(path / "face_camera_poses.npz", names=names,
                        w2c=np.asarray(corrected, dtype=np.float32))
    local_poses = []
    for record in records:
        head_to_camera = np.eye(4, dtype=np.float64)
        head_to_camera[:3, :3] = record[7]
        head_to_camera[:3, 3] = record[8] * scale
        local_poses.append(head_to_camera)
    np.savez_compressed(path / "face_head_to_camera.npz", names=names,
                        head_to_camera=np.asarray(local_poses, dtype=np.float32))
    report = {
        "registeredFaceViews": len(records),
        "facialLandmarkReprojectionMedianPx": round(float(np.median([item[5] for item in records])), 2),
        "facialLandmarkInliersMin": int(min(item[6] for item in records)),
        "worldFaceRotationDriftMedianDegrees": round(float(np.median(rotation_distances)), 2),
        "worldFaceRotationDriftMaxDegrees": round(float(np.max(rotation_distances)), 2),
        "worldFaceCenterDriftMedianFaceWidths": round(float(np.median(distances)), 3),
        "worldFaceCenterDriftMaxFaceWidths": round(float(np.max(distances)), 3),
        "referenceFrame": records[medoid][0],
        "faceOnlyPoseCompensation": True,
        "localHeadPoseMethod": "canonical_mediapipe_pnp_with_estimated_colmap_scale",
        "localHeadPoseScaleStatus": "estimated_not_independently_calibrated",
    }
    (path / "face_pose_quality.json").write_text(json.dumps(report, separators=(",", ":")))
    return report
