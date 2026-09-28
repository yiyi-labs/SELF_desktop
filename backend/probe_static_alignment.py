"""Compare isolated masked room cameras with the current mixed-person SfM."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pycolmap
from scipy.spatial.transform import Rotation


def best_model(root: Path) -> pycolmap.Reconstruction:
    models = [pycolmap.Reconstruction(directory) for directory in root.iterdir()
              if directory.is_dir() and (directory / "cameras.bin").exists()]
    if not models:
        raise ValueError("no_sparse_model")
    return max(models, key=lambda value: (value.num_reg_images(), value.num_points3D()))


def run(job: Path, stride: int, source: str = "incremental",
        reference: str = "mixed") -> dict:
    probe_root = job / f"static_sfm_probe_stride{stride}"
    original = (pycolmap.Reconstruction(job / "sparse" / "0") if reference == "mixed"
                else best_model(probe_root / "sparse"))
    folder = {"incremental": "sparse", "global": "global_sparse",
              "calibrated": "calibrated_global/sparse"}[source]
    sparse_root = probe_root / folder
    static = best_model(sparse_root)
    transform = pycolmap.align_reconstructions_via_proj_centers(static, original, .05)
    if transform is None:
        raise ValueError("static_camera_alignment_failed")
    rotation = np.asarray(transform.rotation.matrix())
    translation = np.asarray(transform.translation)
    old = {image.name: image for image in original.images.values() if image.has_pose}
    residuals, angular = [], []
    for image in static.images.values():
        if not image.has_pose or image.name not in old:
            continue
        old_image = old[image.name]
        new_center = transform.scale * rotation @ np.asarray(image.projection_center()) + translation
        residuals.append(float(np.linalg.norm(new_center - np.asarray(old_image.projection_center()))))
        new_c2w = np.asarray(image.cam_from_world().matrix())[:3, :3].T
        old_c2w = np.asarray(old_image.cam_from_world().matrix())[:3, :3].T
        angular.append(float(Rotation.from_matrix(old_c2w.T @ rotation @ new_c2w).magnitude() * 180 / math.pi))
    static_names = sorted(image.name for image in static.images.values() if image.has_pose)
    registered = {int(name.removeprefix("frame_").removesuffix(".png")) for name in static_names}
    number_of_source_frames = len(list((job / "frames").glob("frame_*.png")))
    sections = [sum(start <= number <= start + 19 for number in registered)
                for start in range(1, number_of_source_frames + 1, 20)]
    run = longest_missing_run = 0
    for number in range(1, number_of_source_frames + 1, stride):
        run = 0 if number in registered else run + 1
        longest_missing_run = max(run, longest_missing_run)
    model_sizes = sorted((candidate.num_reg_images() for directory in sparse_root.iterdir()
                          if directory.is_dir() and (directory / "cameras.bin").exists()
                          for candidate in [pycolmap.Reconstruction(directory)]), reverse=True)
    report = {"source": source, "reference": reference,
              "commonViews": len(residuals), "staticRegisteredViews": len(static_names),
              "firstRegistered": static_names[0], "lastRegistered": static_names[-1],
              "registeredPer20FrameSection": sections, "longestMissingRun": longest_missing_run,
              "connectedModelSizes": model_sizes,
              "centerResidualMedianSceneUnits": round(float(np.median(residuals)), 4),
              "centerResidualP90SceneUnits": round(float(np.quantile(residuals, .9)), 4),
              "orientationResidualMedianDegrees": round(float(np.median(angular)), 3),
              "orientationResidualP90Degrees": round(float(np.quantile(angular, .9)), 3),
              "commonSceneScale": round(float(transform.scale), 5)}
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--source", choices=("incremental", "global", "calibrated"),
                        default="incremental")
    parser.add_argument("--reference", choices=("mixed", "static_incremental"), default="mixed")
    args = parser.parse_args()
    run(args.job, args.stride, args.source, args.reference)
