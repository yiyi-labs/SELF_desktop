"""Audit dynamic-mask boundary support without changing SfM observations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import cv2
import numpy as np

from probe_static_alignment import best_model


def run(job: Path) -> dict:
    root = job / "static_sfm_probe_stride1"
    model = best_model(root / "calibrated_global" / "sparse")
    by_name = {image.name: image for image in model.images.values() if image.has_pose}
    sections = {start: {"keypoints": 0, "keypointsWithin10Px": 0,
                        "triangulated": 0, "triangulatedWithin10Px": 0,
                        "triangulatedWithin20Px": 0}
                for start in range(1, 161, 20)}
    per_frame = {}
    with sqlite3.connect(root / "colmap.db") as connection:
        rows = connection.execute(
            "SELECT images.name,keypoints.rows,keypoints.cols,keypoints.data "
            "FROM images JOIN keypoints USING(image_id)").fetchall()
    for name, count, cols, blob in rows:
        points = np.frombuffer(blob, dtype="<f4").reshape(count, cols)
        if count == 0:
            raise ValueError(f"no_static_keypoints:{name}")
        mask = cv2.imread(str(root / "masks" / (name + ".png")), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise ValueError(f"mask_missing:{name}")
        distance = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
        u = np.clip(points[:, 0].astype(np.int32), 0, mask.shape[1] - 1)
        v = np.clip(points[:, 1].astype(np.int32), 0, mask.shape[0] - 1)
        margin = distance[v, u]
        if (margin <= 0).any():
            raise ValueError(f"static_keypoint_center_in_person:{name}")
        image = by_name.get(name)
        used = np.asarray([feature.has_point3D() for feature in image.points2D], dtype=bool) \
            if image is not None else np.zeros(count, dtype=bool)
        if len(used) != count:
            raise ValueError(f"colmap_feature_order_mismatch:{name}")
        frame = {"keypoints": count, "triangulated": int(used.sum()),
                 "keypointsWithin10Px": int((margin <= 10).sum()),
                 "triangulatedWithin10Px": int((used & (margin <= 10)).sum()),
                 "triangulatedWithin20Px": int((used & (margin <= 20)).sum())}
        per_frame[name] = frame
        section = sections[1 + 20 * ((int(name[6:10]) - 1) // 20)]
        for key in section:
            section[key] += frame[key]
    report = {"sectionTotals": [{"range": [start, start + 19], **values}
                                for start, values in sections.items()],
              "perFrame": per_frame,
              "interpretation": "center-distance only; descriptor support may cross the boundary, so this cannot prove zero dynamic texture"}
    output = root / "mask_edges.audit.json"
    output.write_text(json.dumps(report, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"sectionTotals": report["sectionTotals"]}), flush=True)
    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_static_mask_edges.py JOB_DIR")
    run(Path(sys.argv[1]))
