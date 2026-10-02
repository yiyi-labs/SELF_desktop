"""Fit shared FLAME 2023 Open identity to existing private video landmarks.

Research-only E2 probe. Camera poses here are head-to-camera *local* fits;
they are not world camera estimates and cannot enter full-scene training.
Outputs remain under the ignored .sources directory and never replace works.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as functional

from flame_open_model import (EMBEDDING, MODEL, MODEL_SHA256, STANDARD_MODEL,
                              STANDARD_SHA256, FlameOpen)


TRAIN = (5, 12, 25, 40, 50, 60, 70, 80, 90, 100, 110, 120, 136, 150)
HELD = (15, 35, 55, 75, 95, 115, 130, 145)
INTRINSIC = np.asarray([[1181.055, 0, 540], [0, 1181.055, 960], [0, 0, 1]],
                       dtype=np.float64)  # Estimated for this video, not calibrated.
SOURCE_SHA256 = "7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf"


def filename(index: int) -> str:
    return f"frame_{index:04d}.png"


def project(landmarks: torch.Tensor, translation: torch.Tensor) -> torch.Tensor:
    point = landmarks + translation[:, None]
    z = point[..., 2].clamp_min(0.05)
    return torch.stack((1181.055 * point[..., 0] / z + 540,
                        1181.055 * point[..., 1] / z + 960), -1)


def reprojection(pred: np.ndarray, observed: np.ndarray) -> dict:
    residual = np.linalg.norm(pred - observed, axis=-1)
    return {"medianPx": round(float(np.median(residual)), 3),
            "p90Px": round(float(np.percentile(residual, 90)), 3),
            "rmsePx": round(float(np.sqrt(np.mean(residual ** 2))), 3)}


def initialize_pose(neutral: np.ndarray, observed: np.ndarray,
                    fit_landmarks: np.ndarray, root_joint: np.ndarray
                    ) -> tuple[np.ndarray, np.ndarray, dict]:
    object_points = neutral[fit_landmarks].astype(np.float64)
    image_points = observed[fit_landmarks].astype(np.float64)
    ok, rotation, translation, inliers = cv2.solvePnPRansac(
        object_points, image_points, INTRINSIC, np.zeros(4),
        iterationsCount=400, reprojectionError=18., confidence=.999,
        flags=cv2.SOLVEPNP_EPNP)
    if not ok or inliers is None or len(inliers) < 45:
        raise RuntimeError("flame_open_pnp_insufficient_static_landmarks")
    rotation, translation = cv2.solvePnPRefineLM(
        object_points[inliers[:, 0]], image_points[inliers[:, 0]], INTRINSIC,
        np.zeros(4), rotation, translation)
    prediction, _ = cv2.projectPoints(neutral.astype(np.float64), rotation,
                                      translation, INTRINSIC, np.zeros(4))
    prediction = prediction.reshape(-1, 2)
    # OpenCV rotates model points around the coordinate origin. FLAME's root
    # LBS rotates around its regressed root joint, adding (I - R) @ J_root.
    # Account for this *once* when using the OpenCV t as model initialization.
    rotation_matrix = cv2.Rodrigues(rotation)[0]
    flame_translation = translation.reshape(3) + rotation_matrix @ root_joint - root_joint
    return rotation.reshape(3).astype(np.float32), flame_translation.astype(np.float32), {
        "inliers": len(inliers),
        "fittedLandmarks": reprojection(prediction[fit_landmarks], image_points),
        "withheldLandmarks": reprojection(prediction[~fit_landmarks], observed[~fit_landmarks]),
    }


def run(job: Path, steps: int = 260, variant: str = "open") -> dict:
    started = time.perf_counter()
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    if variant not in ("open", "standard"):
        raise ValueError("unsupported_flame_variant")
    model_path = MODEL if variant == "open" else STANDARD_MODEL
    model_hash = MODEL_SHA256 if variant == "open" else STANDARD_SHA256
    out = job / ("flame_open_e2_20260927" if variant == "open"
                 else "flame_standard_e2_20260927")
    out.mkdir(exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    model = FlameOpen(shape_count=24, expression_count=12,
                      model_path=model_path).to(device)
    zeros = torch.zeros(1, 5, 3, device=device)
    with torch.no_grad():
        _, neutral = model(torch.zeros(1, 24, device=device),
                           torch.zeros(1, 12, device=device), zeros)
    neutral_np = neutral[0].cpu().numpy()
    fit_landmarks = np.arange(105) % 5 != 0
    root_joint = (model.joint_regressor @ model.template)[0].cpu().numpy().astype(np.float64)
    records = {}
    with np.load(job / "face_landmarks.npz") as all_landmarks:
        for index in TRAIN + HELD:
            name = filename(index)
            if name not in all_landmarks or not (job / "frames" / name).is_file():
                raise ValueError(f"missing_frame_or_landmarks:{name}")
            detected = np.asarray(all_landmarks[name], dtype=np.float32)
            if detected.shape != (468, 2):
                raise ValueError(f"unexpected_landmark_shape:{name}")
            observed = detected[model.landmark_indices.cpu().numpy()]
            rotation, translation, pnp = initialize_pose(neutral_np, observed, fit_landmarks,
                                                         root_joint)
            records[index] = {"observed": observed, "rotation": rotation,
                              "translation": translation, "pnp": pnp}
    train = [records[index] for index in TRAIN]
    count = len(train)
    observed = torch.from_numpy(np.stack([item["observed"] for item in train])).to(device)
    fit_indices = torch.from_numpy(fit_landmarks).to(device)
    shape = torch.nn.Parameter(torch.zeros(1, 24, device=device))
    expression = torch.nn.Parameter(torch.zeros(count, 12, device=device))
    pose = torch.nn.Parameter(torch.zeros(count, 5, 3, device=device))
    translation = torch.nn.Parameter(torch.from_numpy(np.stack(
        [item["translation"] for item in train])).to(device))
    with torch.no_grad():
        pose[:, 0] = torch.from_numpy(np.stack([item["rotation"] for item in train])).to(device)
    initial_pose = pose.detach().clone()
    initial_translation = translation.detach().clone()
    optimizer = torch.optim.Adam([
        {"params": [shape], "lr": .012}, {"params": [expression], "lr": .018},
        {"params": [pose], "lr": .0012}, {"params": [translation], "lr": .0007},
    ])
    history = []
    for step in range(steps):
        _, points = model(shape.expand(count, -1), expression, pose)
        predicted = project(points, translation)
        residual = torch.linalg.vector_norm(predicted[:, fit_indices] -
                                            observed[:, fit_indices], dim=-1)
        loss = (functional.smooth_l1_loss(residual, torch.zeros_like(residual), beta=4.)
                + .12 * shape.square().mean()
                + .08 * expression.square().mean()
                + .4 * pose[:, 1:].square().mean()
                + .04 * (pose[:, 0] - initial_pose[:, 0]).square().mean()
                + 10. * (translation - initial_translation).square().mean())
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        if step % 25 == 0 or step == steps - 1:
            history.append({"step": step, "loss": round(float(loss.detach()), 4),
                            "fitMedianPx": round(float(residual.detach().median()), 3)})
    with torch.no_grad():
        fitted_vertices, fitted_points = model(shape.expand(count, -1), expression, pose)
        training_prediction = project(fitted_points, translation).cpu().numpy()
        projected_mesh = project(fitted_vertices, translation).cpu().numpy()
    np.savez_compressed(out / "private-fit-parameters.npz",
                        source_sha256=np.asarray(SOURCE_SHA256),
                        model_sha256=np.asarray(model_hash),
                        train_frame_indices=np.asarray(TRAIN),
                        shared_shape=shape.detach().cpu().numpy(),
                        expressions=expression.detach().cpu().numpy(),
                        joint_axis_angles=pose.detach().cpu().numpy(),
                        camera_translations=translation.detach().cpu().numpy())
    train_results = {}
    for position, index in enumerate(TRAIN):
        target = records[index]["observed"]
        pred = training_prediction[position]
        train_results[str(index)] = {
            "neutralPnP": records[index]["pnp"],
            "fittedLandmarks": reprojection(pred[fit_landmarks], target[fit_landmarks]),
            "withheldLandmarks": reprojection(pred[~fit_landmarks], target[~fit_landmarks]),
        }
    # Withheld video frames never update the shared identity. Their local pose
    # and expression can be fitted from the 84 non-withheld landmarks only.
    held_results = {}
    held_poses = []
    held_expressions = []
    held_translations = []
    held_shape = shape.detach()
    for index in HELD:
        item = records[index]
        obs = torch.from_numpy(item["observed"])[None].to(device)
        local_pose = torch.nn.Parameter(torch.zeros(1, 5, 3, device=device))
        local_translation = torch.nn.Parameter(torch.from_numpy(item["translation"])[None].to(device))
        local_expression = torch.nn.Parameter(torch.zeros(1, 12, device=device))
        with torch.no_grad():
            local_pose[0, 0] = torch.from_numpy(item["rotation"]).to(device)
        local_optimizer = torch.optim.Adam([
            {"params": [local_pose], "lr": .001},
            {"params": [local_translation], "lr": .0005},
            {"params": [local_expression], "lr": .01},
        ])
        for _ in range(90):
            _, points = model(held_shape, local_expression, local_pose)
            predicted = project(points, local_translation)
            error = torch.linalg.vector_norm(predicted[:, fit_indices] -
                                             obs[:, fit_indices], dim=-1)
            loss = (functional.smooth_l1_loss(error, torch.zeros_like(error), beta=4.)
                    + .1 * local_expression.square().mean()
                    + .3 * local_pose[:, 1:].square().mean())
            local_optimizer.zero_grad(set_to_none=True)
            loss.backward()
            local_optimizer.step()
        with torch.no_grad():
            _, final_points = model(held_shape, local_expression, local_pose)
            final = project(final_points, local_translation)[0].cpu().numpy()
        target = item["observed"]
        held_poses.append(local_pose.detach().cpu().numpy()[0])
        held_expressions.append(local_expression.detach().cpu().numpy()[0])
        held_translations.append(local_translation.detach().cpu().numpy()[0])
        held_results[str(index)] = {
            "neutralPnP": item["pnp"],
            "fittedLandmarks": reprojection(final[fit_landmarks], target[fit_landmarks]),
            "withheldLandmarks": reprojection(final[~fit_landmarks], target[~fit_landmarks]),
        }
    np.savez_compressed(out / "private-held-local-parameters.npz",
                        source_sha256=np.asarray(SOURCE_SHA256),
                        model_sha256=np.asarray(model_hash),
                        held_frame_indices=np.asarray(HELD),
                        shared_shape=shape.detach().cpu().numpy(),
                        expressions=np.asarray(held_expressions),
                        joint_axis_angles=np.asarray(held_poses),
                        camera_translations=np.asarray(held_translations),
                        fitting_landmark_count=np.asarray(int(fit_landmarks.sum())),
                        color_training_eligible=np.asarray(False))
    # Direct visual check: show the model's 105 predictions on actual frames.
    for index in (25, 80, 136):
        position = TRAIN.index(index)
        image = cv2.imread(str(job / "frames" / filename(index)), cv2.IMREAD_COLOR)
        mesh_pixels = np.round(projected_mesh[position]).astype(np.int32)
        silhouette = np.zeros(image.shape[:2], dtype=np.uint8)
        for face in model.faces.cpu().numpy():
            triangle = mesh_pixels[face]
            if (triangle[:, 0].min() > -2000 and triangle[:, 0].max() < image.shape[1] + 2000
                    and triangle[:, 1].min() > -2000 and triangle[:, 1].max() < image.shape[0] + 2000):
                cv2.fillConvexPoly(silhouette, triangle, 255)
        contours, _ = cv2.findContours(silhouette, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(image, contours, -1, (228, 160, 56), 2)
        for xy in records[index]["observed"]:
            cv2.circle(image, tuple(np.round(xy).astype(int)), 2, (68, 220, 102), -1)
        for xy in training_prediction[position]:
            cv2.circle(image, tuple(np.round(xy).astype(int)), 2, (220, 100, 226), -1)
        cv2.imwrite(str(out / f"private-landmark-overlay-{index:04d}.jpg"),
                    cv2.resize(image, (540, 960), interpolation=cv2.INTER_AREA),
                    [cv2.IMWRITE_JPEG_QUALITY, 90])
    result = {"sourceSha256": SOURCE_SHA256, "modelSha256": model_hash,
              "modelVariant": model.model_variant,
              "embeddingSha256": hashlib.sha256(EMBEDDING.read_bytes()).hexdigest(),
              "expressionSpaceMetadata": model.expression_metadata,
              "cameraIntrinsicSource": "same-video COLMAP estimate; not independent calibration",
              "worldCameraUsed": False, "shapeComponents": 24, "expressionComponents": 12,
              "poseJoints": ["root", "neck", "jaw", "leftEye", "rightEye"],
              "sharedShape": True, "perFrameScale": False,
              "fitLandmarkCount": int(fit_landmarks.sum()),
              "withheldLandmarkCount": int((~fit_landmarks).sum()),
              "trainFrames": list(TRAIN), "heldFrames": list(HELD),
              "train": train_results, "held": held_results, "curve": history,
              "shapeCoefficientAbsMax": round(float(shape.detach().abs().max()), 3),
              "expressionCoefficientAbsMax": round(float(expression.detach().abs().max()), 3),
              "elapsedSeconds": round(time.perf_counter() - started, 2),
              "peakAllocatedMiB": (round(torch.cuda.max_memory_allocated() / 1024 ** 2, 1)
                                   if device.type == "cuda" else None),
              "status": "isolated_local_geometry_probe_only"}
    (out / "fit.audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("sourceSha256", "modelSha256", "trainFrames",
                "heldFrames", "shapeCoefficientAbsMax", "expressionCoefficientAbsMax",
                "elapsedSeconds", "peakAllocatedMiB", "status")}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--steps", type=int, default=260)
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    arguments = parser.parse_args()
    run(arguments.job, arguments.steps, arguments.variant)
