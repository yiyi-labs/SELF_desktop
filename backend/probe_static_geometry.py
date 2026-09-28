"""Evaluate whether a fully registered static camera model has real geometry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pycolmap

from probe_static_alignment import best_model


def run(job: Path, source: str) -> dict:
    root = job / "static_sfm_probe_stride1"
    folder = {"incremental": "sparse", "global": "global_sparse",
              "calibrated": "calibrated_global/sparse"}[source]
    model = best_model(root / folder)
    images = model.images
    cameras = model.cameras
    posed = [image for image in images.values() if image.has_pose]
    posed.sort(key=lambda image: image.name)
    centers = np.asarray([image.projection_center() for image in posed])
    singular = np.linalg.svd(centers - centers.mean(axis=0), compute_uv=False)
    increments = np.linalg.norm(np.diff(centers, axis=0), axis=1)
    step_sections = [round(float(np.median(increments[i:i + 20])), 4)
                     for i in range(0, len(increments), 20) if len(increments[i:i + 20])]
    angles, tracks = [], []
    for point in model.points3D.values():
        observations = [images[element.image_id] for element in point.track.elements
                        if images[element.image_id].has_pose]
        if len(observations) < 2:
            continue
        xyz = np.asarray(point.xyz)
        rays = np.asarray([np.asarray(image.projection_center()) - xyz for image in observations])
        rays /= np.linalg.norm(rays, axis=1, keepdims=True)
        # The maximal span is enough to reject a low-parallax point; sample
        # first/last observation in time without assuming camera yaw=face yaw.
        cosine = float(np.clip(rays[0] @ rays[-1], -1, 1))
        angles.append(np.degrees(np.arccos(cosine)))
        tracks.append(len(observations))
    focal = sorted({round(float(camera.calibration_matrix()[0, 0]), 3)
                    for camera in cameras.values()})
    radial = sorted({round(float(camera.params[-1]), 6) for camera in cameras.values()})
    report = {"source": source, "registered": len(posed), "points": len(angles),
              "cameraCount": len(cameras), "focalPixels": focal, "lastCameraParams": radial,
              "centerSpanSingularValues": [round(float(value), 4) for value in singular],
              "adjacentCenterStepMedian": round(float(np.median(increments)), 4),
              "adjacentCenterStepP90": round(float(np.quantile(increments, .9)), 4),
              "adjacentStepMedianPer20Registered": step_sections,
              "trackLengthMedian": float(np.median(tracks)),
              "triangulationAngleMedianDegrees": round(float(np.median(angles)), 3),
              "triangulationAngleP10Degrees": round(float(np.quantile(angles, .1)), 3),
              "pointsAtLeast3Degrees": int(sum(angle >= 3 for angle in angles)),
              "pointsAtLeast5Degrees": int(sum(angle >= 5 for angle in angles))}
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--source", choices=("global", "incremental", "calibrated"), default="global")
    args = parser.parse_args()
    run(args.job, args.source)
