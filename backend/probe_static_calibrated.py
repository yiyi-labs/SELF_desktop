"""Isolated focal-calibration + global SfM comparison on the same masks."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import numpy as np
import pycolmap


def main(root: Path) -> None:
    target = root / "calibrated_global"
    target.mkdir(exist_ok=True)
    database = target / "colmap.db"
    shutil.copy2(root / "colmap.db", database)
    start = time.perf_counter()
    calibrated = bool(pycolmap.calibrate_view_graph(database))
    calibration_seconds = time.perf_counter() - start
    if not calibrated:
        raise ValueError("view_graph_calibration_failed")
    models = pycolmap.global_mapping(database, root.parent / "frames", target / "sparse")
    if not models:
        raise ValueError("calibrated_global_mapping_failed")
    model = max(models.values(), key=lambda item: (item.num_reg_images(), item.num_points3D()))
    report = {"registeredFrames": model.num_reg_images(), "staticPoints": model.num_points3D(),
              "medianReprojectionPx": round(float(np.median(
                  [point.error for point in model.points3D.values()])), 3),
              "focalPixels": sorted({round(float(camera.calibration_matrix()[0, 0]), 3)
                                     for camera in model.cameras.values()}),
              "calibrationSeconds": round(calibration_seconds, 2),
              "totalSeconds": round(time.perf_counter() - start, 2)}
    (target / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_static_calibrated.py STATIC_PROBE_DIR")
    main(Path(sys.argv[1]))
