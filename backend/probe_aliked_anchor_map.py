"""Build a tiny ALIKED-only local 3D map from trusted fixed COLMAP cameras.

This is an E1 query-localization research test. No SIFT index is reused and
the untrusted query never updates anchor poses, intrinsics or world scale.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from probe_static_alignment import best_model


ANCHOR_PAIRS = ((45, 53), (48, 53), (50, 53), (52, 53))
QUERY = (53, 54)
SOURCE_SHA256 = "7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf"


def name(index: int) -> str:
    return f"frame_{index:04d}.png"


def stats(values: np.ndarray) -> dict:
    if not len(values):
        return {"median": None, "p90": None}
    return {"median": round(float(np.median(values)), 4),
            "p90": round(float(np.percentile(values, 90)), 4)}


def grid(points: np.ndarray) -> int:
    return len({(min(3, int(x * 4 / 1080)), min(3, int(y * 4 / 1920)))
                for x, y in points})


def camera(model, index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    image = next((image for image in model.images.values() if image.name == name(index)
                  and image.has_pose), None)
    if image is None:
        raise ValueError(f"trusted_anchor_camera_missing:{index}")
    K = np.asarray(model.cameras[image.camera_id].calibration_matrix(), dtype=np.float64)
    w2c = np.asarray(image.cam_from_world().matrix(), dtype=np.float64)
    center = -w2c[:3, :3].T @ w2c[:3, 3]
    return K, w2c, center


def run(job: Path) -> dict:
    root = job / "static_sfm_probe_stride1"
    pair_root = root / "aliked_lightglue_local_20260927"
    trust = {row["name"]: row for row in json.loads(
        (root / "trusted_views.audit.json").read_text(encoding="utf-8"))["frames"]}
    for index in (45, 48, 50, 52, 53):
        if not trust[name(index)]["researchTrusted"]:
            raise ValueError(f"anchor_not_trusted:{index}")
    model = best_model(root / "targeted_global/sparse")
    all_maps = {}
    for first, second in ANCHOR_PAIRS:
        with np.load(pair_root / f"pair_{first:04d}_{second:04d}.matches.npz") as data:
            matches = data["matches"][data["static_fundamental_inliers"]]
            points0 = data["keypoints0"][matches[:, 0]].astype(np.float64)
            points1 = data["keypoints1"][matches[:, 1]].astype(np.float64)
        K0, pose0, center0 = camera(model, first)
        K1, pose1, center1 = camera(model, second)
        homogeneous = cv2.triangulatePoints(K0 @ pose0, K1 @ pose1,
                                            points0.T, points1.T)
        world = (homogeneous[:3] / homogeneous[3]).T
        cam0 = (pose0[:, :3] @ world.T + pose0[:, 3, None]).T
        cam1 = (pose1[:, :3] @ world.T + pose1[:, 3, None]).T
        projected0 = (K0 @ cam0.T).T
        projected1 = (K1 @ cam1.T).T
        projected0 = projected0[:, :2] / projected0[:, 2, None]
        projected1 = projected1[:, :2] / projected1[:, 2, None]
        error = np.maximum(np.linalg.norm(projected0 - points0, axis=1),
                           np.linalg.norm(projected1 - points1, axis=1))
        rays0 = world - center0
        rays1 = world - center1
        rays0 /= np.linalg.norm(rays0, axis=1)[:, None].clip(1e-10)
        rays1 /= np.linalg.norm(rays1, axis=1)[:, None].clip(1e-10)
        angles = np.degrees(np.arccos(np.clip((rays0 * rays1).sum(axis=1), -1, 1)))
        supported = (np.isfinite(world).all(axis=1) & (cam0[:, 2] > 0)
                     & (cam1[:, 2] > 0) & (error <= 2.5))
        valid = supported & (angles >= 1.5) & (angles <= 80)
        all_maps[f"{first}_{second}"] = {
            "feature_ids_in_53": matches[valid, 1],
            "points_world": world[valid], "points_in_53": points1[valid],
            "summary": {"pairMatches": len(matches),
                        "positiveDepthAndReprojection": int(supported.sum()),
                        "angleBeforeThresholdDegrees": stats(angles[supported]),
                        "triangulatedValid": int(valid.sum()),
                        "triangulationAngleDegrees": stats(angles[valid]),
                        "twoViewReprojectionPx": stats(error[valid]),
                        "gridCells4x4": grid(points1[valid])}}
    with np.load(pair_root / "pair_0053_0054.matches.npz") as data:
        query_matches = data["matches"][data["static_fundamental_inliers"]]
        query_points = data["keypoints1"]
    query = {}
    K, _, _ = camera(model, 53)
    for key, local in all_maps.items():
        lookup = {int(fid): world for fid, world in zip(
            local["feature_ids_in_53"], local["points_world"])}
        correspondences = [(lookup[int(a)], query_points[int(b)])
                           for a, b in query_matches if int(a) in lookup]
        if len(correspondences) < 12:
            query[key] = {"mapCorrespondences": len(correspondences),
                          "localized": False, "reason": "too_few_anchored_2d3d_matches"}
            continue
        points3d = np.asarray([pair[0] for pair in correspondences], dtype=np.float64)
        points2d = np.asarray([pair[1] for pair in correspondences], dtype=np.float64)
        held = np.arange(len(points3d)) % 5 == 0
        ok, rvec, tvec, inlier_rows = cv2.solvePnPRansac(
            points3d[~held], points2d[~held], K, np.zeros(4),
            iterationsCount=1000, reprojectionError=3., confidence=.999,
            flags=cv2.SOLVEPNP_EPNP)
        if not ok or inlier_rows is None or len(inlier_rows) < 10:
            query[key] = {"mapCorrespondences": len(correspondences),
                          "localized": False, "reason": "anchored_pnp_failed"}
            continue
        prediction, _ = cv2.projectPoints(points3d[held], rvec, tvec, K, np.zeros(4))
        held_error = np.linalg.norm(prediction.reshape(-1, 2) - points2d[held], axis=1)
        query[key] = {"mapCorrespondences": len(correspondences),
                      "pnpInliers": len(inlier_rows),
                      "queryGridCells4x4": grid(points2d[~held][inlier_rows[:, 0]]),
                      "heldoutReprojectionPx": stats(held_error),
                      "localized": bool(len(inlier_rows) >= 15
                                        and grid(points2d[~held][inlier_rows[:, 0]]) >= 5
                                        and np.median(held_error) <= 3.),
                      "worldCameraNotGroundTruth": True}
    report = {"sourceSha256": SOURCE_SHA256,
              "queryImage": name(54), "trustedAnchors": [name(i) for i in (45, 48, 50, 52, 53)],
              "fixedWorldCameras": True,
              "newFeatureIndicesOnly": True,
              "map": {key: value["summary"] for key, value in all_maps.items()},
              "queryLocalization": query}
    (pair_root / "anchored_local_map.audit.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    run(parser.parse_args().job)
