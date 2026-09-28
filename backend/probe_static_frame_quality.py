"""Frame-level evidence for two static-camera candidates.

All joins use COLMAP image names. Output is numeric and never embeds pixels.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pycolmap

from probe_static_alignment import best_model


def quality(model: pycolmap.Reconstruction, expected: list[str]) -> dict[str, dict]:
    images = model.images
    by_name = {image.name: image for image in images.values() if image.has_pose}
    if len(by_name) != model.num_reg_images():
        raise ValueError("registered_image_names_not_unique")
    track_cache: dict[int, tuple[int, int, float]] = {}
    for point_id, point in model.points3D.items():
        track = [images[element.image_id] for element in point.track.elements
                 if images[element.image_id].has_pose]
        indices = [int(image.name[6:10]) for image in track]
        if len(track) < 2:
            continue
        center = np.asarray([image.projection_center() for image in track])
        rays = center - np.asarray(point.xyz)
        rays /= np.linalg.norm(rays, axis=1, keepdims=True)
        cosine = np.clip(rays @ rays.T, -1., 1.)
        max_angle = float(np.degrees(np.arccos(cosine.min())))
        track_cache[point_id] = len(track), max(indices) - min(indices), max_angle
    report = {}
    for name in expected:
        image = by_name.get(name)
        if image is None:
            report[name] = {"registered": False, "reason": "not_registered"}
            continue
        camera = model.cameras[image.camera_id]
        pose = np.asarray(image.cam_from_world().matrix())
        points = [(feature, model.points3D[feature.point3D_id])
                  for feature in image.points2D if feature.has_point3D() and
                  feature.point3D_id in track_cache]
        if not points:
            raise ValueError(f"registered_frame_has_no_points:{name}")
        xyz = np.asarray([point.xyz for _, point in points])
        camera_xyz = xyz @ pose[:3, :3].T + pose[:3, 3]
        uv = camera.img_from_cam(camera_xyz)
        measured = np.asarray([feature.xy for feature, _ in points])
        residuals = np.linalg.norm(uv - measured, axis=1)
        cells = {(min(3, int(feature.xy[0] * 4 / camera.width)),
                  min(3, int(feature.xy[1] * 4 / camera.height)))
                 for feature, _ in points}
        tracks = [track_cache[feature.point3D_id] for feature, _ in points]
        good_depth = camera_xyz[:, 2] > 0
        report[name] = {"registered": True, "imageId": int(image.image_id),
                        "staticInliers": len(points), "occupiedGridCells4x4": len(cells),
                        "reprojectionMedianPx": round(float(np.median(residuals)), 3),
                        "reprojectionP90Px": round(float(np.quantile(residuals, .9)), 3),
                        "reprojectionP99Px": round(float(np.quantile(residuals, .99)), 3),
                        "longTracks8Plus": sum(length >= 8 for length, _, _ in tracks),
                        "cross20FrameTracks": sum(span >= 20 for _, span, _ in tracks),
                        "triangulationAngleMedianDegrees": round(float(np.median(
                            [angle for _, _, angle in tracks])), 3),
                        "triangulationAngleP10Degrees": round(float(np.quantile(
                            [angle for _, _, angle in tracks], .1)), 3),
                        "positiveDepthFraction": round(float(np.mean(good_depth)), 5),
                        "medianDepthSceneUnits": round(float(np.median(camera_xyz[:, 2])), 4)}
    return report


def section_stats(rows: dict[str, dict]) -> list[dict]:
    output = []
    for start in range(1, 161, 20):
        active = [rows[f"frame_{index:04d}.png"] for index in range(start, start + 20)
                  if rows[f"frame_{index:04d}.png"]["registered"]]
        output.append({"frameRange": [start, start + 19], "registered": len(active),
                       "medianStaticInliers": round(float(np.median(
                           [row["staticInliers"] for row in active])), 1) if active else 0,
                       "medianGridCells": round(float(np.median(
                           [row["occupiedGridCells4x4"] for row in active])), 1) if active else 0,
                       "medianReprojectionP90Px": round(float(np.median(
                           [row["reprojectionP90Px"] for row in active])), 3) if active else None,
                       "medianLongTracks8Plus": round(float(np.median(
                           [row["longTracks8Plus"] for row in active])), 1) if active else 0,
                       "medianTriangulationAngle": round(float(np.median(
                           [row["triangulationAngleMedianDegrees"] for row in active])), 3)
                       if active else None})
    return output


def run(job: Path) -> dict:
    manifest = json.loads((job / "frame_manifest.audit.json").read_text(encoding="utf-8"))
    names = [item["name"] for item in manifest["frames"]]
    if len(names) != 160 or len(set(names)) != 160:
        raise ValueError("frame_manifest_not_160_unique")
    root = job / "static_sfm_probe_stride1"
    candidates = {"static_incremental": best_model(root / "sparse"),
                  "static_global_estimated_focal": best_model(root / "calibrated_global" / "sparse")}
    all_rows = {label: quality(model, names) for label, model in candidates.items()}
    result = {"coordinateNote": "depth and centers are in each model's arbitrary Sim3 gauge",
              "perFrame": all_rows,
              "sections": {label: section_stats(rows) for label, rows in all_rows.items()}}
    output = root / "frame_quality.json"
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    summary = {"output": str(output), "sections": result["sections"]}
    print(json.dumps(summary), flush=True)
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_static_frame_quality.py JOB_DIR")
    run(Path(sys.argv[1]))
