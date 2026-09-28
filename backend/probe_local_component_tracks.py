"""Triangulate *observed* hair and eyewear features in the fitted head frame.

The result is a conservative research seed candidate, never a completed hair
or eyewear model. Only TRAIN frame pixels and already fitted F_t/K participate.
Each pair must pass forward/backward optical flow, two-view triangulation,
depth, angle and reprojection gates. Held images are not read here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from scipy.spatial import cKDTree

from flame_open_model import FlameOpen, MODEL, STANDARD_MODEL
from probe_flame_hair_hull import local_observations
from probe_flame_observations import root_neutral_contract
from probe_flame_open_fit import INTRINSIC, SOURCE_SHA256, TRAIN, filename


def source_frame(job: Path, frame: int, component: str) -> tuple[np.ndarray, np.ndarray]:
    name = filename(frame)
    image = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
    parts = cv2.imread(str(job / "portrait_components_20260927" / f"parts-{name}"),
                       cv2.IMREAD_GRAYSCALE)
    hair = cv2.imread(str(job / "portrait_components_20260927" / f"hair-{name}"),
                      cv2.IMREAD_GRAYSCALE)
    if any(item is None for item in (image, parts, hair)):
        raise ValueError(f"missing_component_frame:{name}")
    if component == "hair":
        mask = cv2.erode((hair > 127).astype(np.uint8),
                         np.ones((3, 3), np.uint8)) * 255
    else:
        with np.load(job / "face_landmarks.npz") as landmarks:
            marks = landmarks[name]
        eyes = marks[[33, 133, 362, 263, 168, 6]]
        x0, x1 = max(0, int(eyes[:, 0].min())-85), min(1080, int(eyes[:, 0].max())+85)
        y0, y1 = max(0, int(eyes[:, 1].min())-75), min(1920, int(eyes[:, 1].max())+70)
        roi = np.zeros(parts.shape, np.uint8)
        roi[y0:y1, x0:x1] = 255
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.dilate(cv2.Canny(gray, 55, 125), np.ones((3, 3), np.uint8))
        # The "others" class includes more than glasses. These are only
        # candidate line features, not an asserted eyewear segmentation.
        mask = cv2.bitwise_and(roi, edges)
        mask[parts != 5] = 0
    return image, mask


def pair_tracks(job: Path, frame_a: int, frame_b: int, component: str,
                F_a: np.ndarray, F_b: np.ndarray) -> tuple[dict, np.ndarray, np.ndarray]:
    image_a, mask_a = source_frame(job, frame_a, component)
    image_b, mask_b = source_frame(job, frame_b, component)
    gray_a = cv2.cvtColor(image_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(image_b, cv2.COLOR_BGR2GRAY)
    max_corners = 1100 if component == "hair" else 430
    pts = cv2.goodFeaturesToTrack(gray_a, max_corners, .008, 4,
                                  mask=mask_a, blockSize=5)
    if pts is None or len(pts) < 8:
        return {"pair": [frame_a, frame_b], "component": component,
                "detected": 0 if pts is None else len(pts), "flowValid": 0,
                "triangulated": 0, "accepted": 0}, np.empty((0, 3), np.float32), np.empty((0, 3), np.float32)
    next_pts, status, _ = cv2.calcOpticalFlowPyrLK(
        gray_a, gray_b, pts, None, winSize=(31, 31), maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT, 35, .01))
    back_pts, back_status, _ = cv2.calcOpticalFlowPyrLK(
        gray_b, gray_a, next_pts, None, winSize=(31, 31), maxLevel=4,
        criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT, 35, .01))
    a, b = pts.reshape(-1, 2), next_pts.reshape(-1, 2)
    width, height = image_a.shape[1], image_a.shape[0]
    bx = np.rint(b[:, 0]).astype(np.int32).clip(0, width-1)
    by = np.rint(b[:, 1]).astype(np.int32).clip(0, height-1)
    good = ((status[:, 0] > 0) & (back_status[:, 0] > 0) &
            (np.linalg.norm(back_pts.reshape(-1, 2)-a, axis=1) < 1.25) &
            (b[:, 0] >= 2) & (b[:, 0] < width-2) &
            (b[:, 1] >= 2) & (b[:, 1] < height-2) &
            (mask_b[by, bx] > 0))
    a, b = a[good], b[good]
    row = {"pair": [frame_a, frame_b], "component": component,
           "detected": int(len(pts)), "flowValid": int(len(a))}
    if len(a) < 6:
        return {**row, "triangulated": 0, "accepted": 0}, np.empty((0, 3), np.float32), np.empty((0, 3), np.float32)
    P_a = (INTRINSIC @ F_a[:3]).astype(np.float64)
    P_b = (INTRINSIC @ F_b[:3]).astype(np.float64)
    homog = cv2.triangulatePoints(P_a, P_b, a.T.astype(np.float64), b.T.astype(np.float64))
    w = homog[3]
    valid_w = np.abs(w) > 1e-8
    xyz = (homog[:3] / np.where(valid_w, w, 1.)).T
    local = np.concatenate((xyz, np.ones((len(xyz), 1))), axis=1)
    project_a, project_b = (P_a @ local.T).T, (P_b @ local.T).T
    z_a, z_b = project_a[:, 2], project_b[:, 2]
    xy_a = project_a[:, :2] / np.maximum(z_a[:, None], 1e-8)
    xy_b = project_b[:, :2] / np.maximum(z_b[:, None], 1e-8)
    residual = np.maximum(np.linalg.norm(xy_a-a, axis=1),
                          np.linalg.norm(xy_b-b, axis=1))
    camera_a = -F_a[:3, :3].T @ F_a[:3, 3]
    camera_b = -F_b[:3, :3].T @ F_b[:3, 3]
    ray_a = xyz-camera_a
    ray_b = xyz-camera_b
    ray_a /= np.maximum(np.linalg.norm(ray_a, axis=1, keepdims=True), 1e-9)
    ray_b /= np.maximum(np.linalg.norm(ray_b, axis=1, keepdims=True), 1e-9)
    angles = np.degrees(np.arccos(np.clip((ray_a*ray_b).sum(axis=1), -1, 1)))
    box = ((np.abs(xyz[:, 0]) < .21) & (xyz[:, 1] > -.09) & (xyz[:, 1] < .26)
           & (xyz[:, 2] > -.27) & (xyz[:, 2] < .22))
    keep = (valid_w & np.isfinite(xyz).all(axis=1) & (z_a > .04) &
            (z_b > .04) & (residual < 2.5) & (angles >= 1.5) & box)
    ax = np.rint(a[:, 0]).astype(np.int32).clip(0, width-1)
    ay = np.rint(a[:, 1]).astype(np.int32).clip(0, height-1)
    color = cv2.cvtColor(image_a, cv2.COLOR_BGR2RGB)[ay, ax].astype(np.float32)/255
    row.update({"triangulated": int(len(xyz)), "accepted": int(keep.sum()),
                "angleDegMedianAccepted": float(np.median(angles[keep])) if keep.any() else None,
                "reprojectionPxP90Accepted": float(np.quantile(residual[keep], .9)) if keep.any() else None})
    return row, xyz[keep].astype(np.float32), color[keep]


def run(job: Path, variant: str = "open") -> dict:
    if variant not in ("open", "standard"):
        raise ValueError("unsupported_variant")
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    root = job / ("flame_open_e2_20260927" if variant == "open"
                  else "flame_standard_e2_20260927")
    out = root / "private-component-tracks"
    out.mkdir(exist_ok=True)
    transforms = local_observations(root)
    fit = dict(np.load(root / "private-fit-parameters.npz"))
    model = FlameOpen(24, 12, model_path=MODEL if variant == "open" else STANDARD_MODEL)
    ref = TRAIN.index(25)
    shape = torch.from_numpy(fit["shared_shape"])
    expression = torch.from_numpy(fit["expressions"][ref:ref+1])
    pose = torch.from_numpy(fit["joint_axis_angles"][ref:ref+1])
    local_mesh, _, root_error = root_neutral_contract(
        model, shape, expression, pose, fit["camera_translations"][ref])
    nearest_skin = cKDTree(local_mesh)
    report = {"status": "triangulated_component_seed_research_only",
              "sourceSha256": SOURCE_SHA256, "modelSha256": model.model_sha256,
              "variant": variant, "referenceRootError": root_error, "components": {}}
    for component in ("hair", "eyewear_candidates"):
        label = "hair" if component == "hair" else "eyewear"
        rows, points, colors, lineage = [], [], [], []
        for a, b in zip(TRAIN[:-1], TRAIN[1:]):
            row, xyz, rgb = pair_tracks(job, a, b, label,
                                        transforms[a], transforms[b])
            rows.append(row)
            points.append(xyz)
            colors.append(rgb)
            lineage.extend([(a, b)]*len(xyz))
        positions = np.concatenate(points) if points else np.empty((0, 3), np.float32)
        sampled_rgb = np.concatenate(colors) if colors else np.empty((0, 3), np.float32)
        if len(positions):
            # Spatial deduplication only; no observed color or point is invented.
            tree = cKDTree(positions)
            seen = np.zeros(len(positions), bool)
            picked = []
            for i in range(len(positions)):
                if seen[i]:
                    continue
                picked.append(i)
                seen[tree.query_ball_point(positions[i], .0015)] = True
            positions = positions[picked]
            sampled_rgb = sampled_rgb[picked]
            lineage = np.asarray(lineage, np.int32)[picked]
            distance, _ = nearest_skin.query(positions)
        else:
            lineage = np.empty((0, 2), np.int32)
            distance = np.empty(0, np.float32)
        np.savez_compressed(out / f"private-{label}-seeds.npz",
                            local_points=positions, source_rgb=sampled_rgb,
                            source_pair=lineage, source_sha256=np.asarray(SOURCE_SHA256),
                            model_sha256=np.asarray(model.model_sha256))
        report["components"][label] = {
            "detected": int(sum(row["detected"] for row in rows)),
            "flowValid": int(sum(row["flowValid"] for row in rows)),
            "twoViewGeometryAcceptedBeforeDedup": int(sum(row["accepted"] for row in rows)),
            "deduplicatedSeedCount": int(len(positions)),
            "distanceToFlameSurfaceMmP50": float(np.median(distance)*1000) if len(distance) else None,
            "distanceToFlameSurfaceMmP90": float(np.quantile(distance, .9)*1000) if len(distance) else None,
            "pairs": rows,
            "limits": ["Only 14 fitted training views; held source pixels excluded",
                       "Pairwise optical-flow triangulation is not joint geometry training",
                       "Hair unknown/occluded volume is not inferred from this sparse set"]}
    (out / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "variant": variant,
                      "components": {key: {metric: value for metric, value in part.items()
                                           if metric not in ("pairs", "limits")}
                                     for key, part in report["components"].items()}}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    args = parser.parse_args()
    run(args.job, args.variant)
