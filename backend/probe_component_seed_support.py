"""Audit source-triangulated local component seeds on held views.

Held pixels never create geometry or color. This only checks whether seeds
inferred from training-view pairs project onto the expected visible part.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from probe_flame_hair_hull import local_observations, pixels
from probe_flame_open_fit import HELD, SOURCE_SHA256, filename


def run(job: Path, component: str = "hair") -> dict:
    if component not in ("hair", "eyewear"):
        raise ValueError("unsupported_component")
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    root = job / "flame_open_e2_20260927"
    source = root / "private-component-tracks" / f"private-{component}-seeds.npz"
    with np.load(source) as item:
        points = item["local_points"]
        lineage = item["source_pair"]
    if len(points) < 1 or len(points) != len(lineage):
        raise ValueError("component_seeds_missing_or_mismatched")
    transforms = local_observations(root)
    out = root / "private-component-tracks" / f"private-{component}-held-audit"
    out.mkdir(exist_ok=True)
    rows = []
    for frame in HELD:
        name = filename(frame)
        raw = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
        hair = cv2.imread(str(job / "portrait_components_20260927" / f"hair-{name}"),
                          cv2.IMREAD_GRAYSCALE)
        parts = cv2.imread(str(job / "portrait_components_20260927" / f"parts-{name}"),
                           cv2.IMREAD_GRAYSCALE)
        if any(v is None for v in (raw, hair, parts)):
            raise ValueError(f"component_held_source_missing:{frame}")
        x, y, depth = pixels(points, transforms[frame])
        h, w = hair.shape
        inside = (depth > .03) & (x >= 0) & (x < w) & (y >= 0) & (y < h)
        xi, yi = x.clip(0, w-1), y.clip(0, h-1)
        # This is a 2D visibility proxy; a mask hit alone is not a valid 3D depth.
        if component == "hair":
            target = hair > 127
        else:
            gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)
            edge = cv2.dilate(cv2.Canny(gray, 55, 125), np.ones((3, 3), np.uint8)) > 0
            target = (parts == 5) & edge
        hit = inside & target[yi, xi]
        near = inside & (cv2.dilate(target.astype(np.uint8),
                                    np.ones((11, 11), np.uint8))[yi, xi] > 0)
        row = {"frame": frame, "seedCount": len(points), "inImage": int(inside.sum()),
               "directMaskHits": int(hit.sum()), "nearMaskHits": int(near.sum()),
               "directHitFractionOfInImage": float(hit.sum()/max(int(inside.sum()), 1)),
               "nearHitFractionOfInImage": float(near.sum()/max(int(inside.sum()), 1))}
        rows.append(row)
        if frame in (35, 75, 145):
            draw = raw.copy()
            for index in np.flatnonzero(inside):
                color = (40, 220, 80) if hit[index] else ((0, 170, 255) if near[index]
                                                         else (80, 40, 255))
                cv2.circle(draw, (int(x[index]), int(y[index])), 5, color, 2, cv2.LINE_AA)
            scale = .5
            cv2.imwrite(str(out / f"private-{component}-held-{frame:04d}.jpg"),
                        cv2.resize(draw, None, fx=scale, fy=scale,
                                   interpolation=cv2.INTER_AREA),
                        [cv2.IMWRITE_JPEG_QUALITY, 94])
    report = {"status": "development_held_projection_audit_not_geometry_acceptance",
              "component": component, "sourceSha256": SOURCE_SHA256,
              "seedCount": int(len(points)), "sourceTrainingPairs":
              sorted(set(tuple(int(v) for v in row) for row in lineage)),
              "heldViews": rows,
              "limits": ["Only 2D projection-mask agreement, not depth or visibility truth",
                         "Held pixels used only for audit; no seed creation or training"]}
    (out / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"component": component, "seedCount": len(points),
                      "heldViews": rows}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--component", choices=("hair", "eyewear"), default="hair")
    args = parser.parse_args()
    run(args.job, args.component)
