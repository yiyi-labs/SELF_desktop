"""Measure camera sensitivity to a fixed, small view-graph perturbation.

The calibrated graph is copied before any row is changed. This tests
repeatability under fewer static matches, not accuracy against ground truth.
"""

from __future__ import annotations

import json
import math
import random
import shutil
import sqlite3
import time
from pathlib import Path

import numpy as np
import pycolmap
from scipy.spatial.transform import Rotation

from probe_static_alignment import best_model


def run(job: Path, seed: int = 260926, removed_fraction: float = .1,
        source: str = "calibrated_global") -> dict:
    if source not in ("calibrated_global", "targeted_global"):
        raise ValueError("unknown_static_camera_candidate")
    start = time.perf_counter()
    root = job / "static_sfm_probe_stride1"
    original = best_model(root / source / "sparse")
    destination = root / f"{source}_graph_perturb_seed{seed}"
    destination.mkdir(exist_ok=True)
    database = destination / "colmap.db"
    report_path = destination / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print(json.dumps(report), flush=True)
        return report
    if database.exists():
        raise ValueError("incomplete_perturbation_database_exists")
    shutil.copy2(root / source / "colmap.db", database)
    with sqlite3.connect(database) as connection:
        pair_ids = [row[0] for row in connection.execute(
            "SELECT pair_id FROM two_view_geometries WHERE rows > 0 ORDER BY pair_id")]
        if len(pair_ids) < 100:
            raise ValueError("too_few_verified_static_pairs")
        chosen = random.Random(seed).sample(pair_ids, round(len(pair_ids) * removed_fraction))
        connection.executemany("DELETE FROM two_view_geometries WHERE pair_id = ?",
                               [(value,) for value in chosen])
        connection.commit()
    models = pycolmap.global_mapping(database, job / "frames", destination / "sparse")
    if not models:
        raise ValueError("perturbed_global_mapping_failed")
    perturbed = max(models.values(), key=lambda value: (value.num_reg_images(), value.num_points3D()))
    transform = pycolmap.align_reconstructions_via_proj_centers(perturbed, original, .05)
    if transform is None:
        raise ValueError("perturbed_camera_alignment_failed")
    rotation = np.asarray(transform.rotation.matrix())
    translation = np.asarray(transform.translation)
    original_by_name = {image.name: image for image in original.images.values() if image.has_pose}
    perturbed_by_name = {image.name: image for image in perturbed.images.values() if image.has_pose}
    sections = []
    for lower in range(1, 161, 20):
        centers, directions = [], []
        for number in range(lower, lower + 20):
            name = f"frame_{number:04d}.png"
            if name not in original_by_name or name not in perturbed_by_name:
                continue
            old_image, new_image = original_by_name[name], perturbed_by_name[name]
            center = transform.scale * rotation @ np.asarray(new_image.projection_center()) + translation
            centers.append(float(np.linalg.norm(center - np.asarray(old_image.projection_center()))))
            old_c2w = np.asarray(old_image.cam_from_world().matrix())[:3, :3].T
            new_c2w = np.asarray(new_image.cam_from_world().matrix())[:3, :3].T
            directions.append(math.degrees(Rotation.from_matrix(
                old_c2w.T @ rotation @ new_c2w).magnitude()))
        sections.append({"range": [lower, lower + 19], "common": len(centers),
                         "centerP50SceneUnits": round(float(np.median(centers)), 4) if centers else None,
                         "centerP90SceneUnits": round(float(np.quantile(centers, .9)), 4) if centers else None,
                         "directionP50Degrees": round(float(np.median(directions)), 3) if directions else None,
                         "directionP90Degrees": round(float(np.quantile(directions, .9)), 3) if directions else None})
    report = {"source": source + "_graph_copy", "calibration": "estimated_from_same_video_graph",
              "removedVerifiedPairs": len(chosen), "originalVerifiedPairs": len(pair_ids),
              "perturbedRegistered": perturbed.num_reg_images(), "commonRegistered": len(perturbed_by_name.keys() & original_by_name.keys()),
              "sections": sections, "elapsedSeconds": round(time.perf_counter() - start, 2),
              "note": "one fixed graph perturbation measures sensitivity only; it is not independent truth"}
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) not in (2, 3):
        raise SystemExit("probe_static_stability.py JOB_DIR [calibrated_global|targeted_global]")
    run(Path(sys.argv[1]), source=sys.argv[2] if len(sys.argv) == 3 else "calibrated_global")
