"""Numerical diagnostics for a static-only COLMAP feature graph."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np


def run(database: Path) -> dict:
    with sqlite3.connect(database) as conn:
        names = {image_id: name for image_id, name in conn.execute("SELECT image_id, name FROM images")}
        keypoints = {int(name[6:10]): count for name, count in conn.execute(
            "SELECT images.name, keypoints.rows FROM images JOIN keypoints USING(image_id)")}
        verified = []
        for pair_id, rows in conn.execute("SELECT pair_id, rows FROM two_view_geometries WHERE rows > 0"):
            second = int(pair_id % 2147483647)
            first = int((pair_id - second) // 2147483647)
            if first not in names or second not in names:
                continue
            a, b = int(names[first][6:10]), int(names[second][6:10])
            verified.append((a, b, rows))
    sections = []
    for start in range(1, max(keypoints) + 1, 20):
        group = range(start, min(start + 20, max(keypoints) + 1))
        same = [rows for a, b, rows in verified if a in group and b in group]
        sections.append({"frames": [start, min(start + 19, max(keypoints))],
                         "medianKeypoints": int(np.median([keypoints[i] for i in group if i in keypoints])),
                         "verifiedPairsInside": len(same),
                         "medianPairInliers": int(np.median(same)) if same else 0})
    report = {"sections": sections, "verifiedPairs": len(verified),
              "nonAdjacentPairs": sum(abs(a - b) > 20 for a, b, _ in verified)}
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    run(parser.parse_args().database)
