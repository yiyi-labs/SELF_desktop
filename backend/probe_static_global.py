"""Alternative *isolated* global SfM on the identical masked feature graph."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pycolmap


def main(root: Path) -> None:
    start = time.perf_counter()
    output = root / "global_sparse"
    output.mkdir(exist_ok=True)
    models = pycolmap.global_mapping(root / "colmap.db", root.parent / "frames", output)
    if not models:
        raise ValueError("global_static_mapping_failed")
    model = max(models.values(), key=lambda item: (item.num_reg_images(), item.num_points3D()))
    report = {"registeredFrames": model.num_reg_images(), "staticPoints": model.num_points3D(),
              "medianReprojectionPx": float(np.median([point.error for point in model.points3D.values()])),
              "seconds": round(time.perf_counter() - start, 2),
              "method": "GLOMAP on same whole-person-masked SIFT graph"}
    (root / "global_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_static_global.py STATIC_PROBE_DIR")
    main(Path(sys.argv[1]))
