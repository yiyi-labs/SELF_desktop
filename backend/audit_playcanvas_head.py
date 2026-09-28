"""Compare a private local-head gsplat render with the actual SELF PlayCanvas draw.

This is a same-asset/reference-camera graphics gate, not release approval.
The archived optimization montage is native-pixel source/init/final and the
browser canvas is captured at 1080x1920 with the same fixed K and pose.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def run(job: Path, optimized: Path, reference: int = 35) -> dict:
    training = json.loads((optimized / "audit.json").read_text(encoding="utf-8"))
    export = optimized / f"private-reference-{reference:04d}-ply-contract"
    browser = json.loads((export / "playcanvas" / "audit.json").read_text(encoding="utf-8"))
    if (browser["plySha256"] != json.loads((export / "audit.json").read_text(
            encoding="utf-8"))["plySha256"] or browser["referenceFrame"] != reference):
        raise ValueError("playcanvas_asset_or_camera_mismatch")
    crop = training["nativePixelViews"][str(reference)]["cropXYXY"]
    x0, y0, x1, y1 = crop
    width, height = x1-x0, y1-y0
    montage = cv2.imread(str(optimized / f"private-final-held-{reference:04d}.jpg"),
                         cv2.IMREAD_COLOR)
    raw = cv2.imread(str(export / "playcanvas" /
                         f"private-reference-{reference:04d}-canvas.png"),
                     cv2.IMREAD_UNCHANGED)
    if (montage is None or raw is None or montage.shape[:2] != (height, width*3)
            or raw.shape[:2] != (1920, 1080)
            or raw.shape[2] != 4):
        raise ValueError("non_native_comparison_images")
    expected = montage[:, width*2:]
    browser_bgra = raw[y0:y1, x0:x1]
    alpha = browser_bgra[:, :, 3].astype(np.float32) / 255
    actual = browser_bgra[:, :, :3].astype(np.float32) * alpha[..., None]
    source = montage[:, :width]
    hair = cv2.imread(str(job / "portrait_components_20260927" /
                           f"hair-frame_{reference:04d}.png"), cv2.IMREAD_GRAYSCALE)
    head = cv2.imread(str(job / "face_masks" /
                           f"frame_{reference:04d}.png.png"), cv2.IMREAD_GRAYSCALE)
    if hair is None or head is None:
        raise ValueError("source_region_missing")
    fg = (hair[y0:y1, x0:x1] > 127) | (head[y0:y1, x0:x1] > 127)
    err = np.abs(actual - expected.astype(np.float32)).mean(axis=2) / 255
    source_err = np.abs(actual - source.astype(np.float32)).mean(axis=2) / 255
    safe_empty = cv2.dilate(fg.astype(np.uint8), np.ones((17, 17), np.uint8)) == 0
    unexpected = safe_empty & (alpha > .2) & (actual.max(axis=2) > 210)
    report = {"referenceFrame": reference, "cropXYXY": crop,
              "playcanvasToGsplatFixedRoiL1": float(err[fg].mean()),
              "playcanvasToSourceFixedRoiL1": float(source_err[fg].mean()),
              "playcanvasToGsplatFullCropL1": float(err.mean()),
              "browserUnexpectedBrightOutsideForegroundPixels": int(unexpected.sum()),
              "browserMeanAlphaOnFixedForeground": float(alpha[fg].mean()),
              "sourceAssetSha256": browser["plySha256"],
              "status": "research_graphics_gate_measurement_not_release"}
    diff = np.clip(np.abs(actual-expected.astype(np.float32))*2.5, 0, 255).astype(np.uint8)
    row = np.concatenate((expected, actual.round().clip(0, 255).astype(np.uint8), diff), axis=1)
    cv2.imwrite(str(export / "playcanvas" / f"private-native-comparison-{reference:04d}.jpg"),
                row, [cv2.IMWRITE_JPEG_QUALITY, 95])
    (export / "playcanvas" / "comparison.audit.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("optimized", type=Path)
    parser.add_argument("--reference", type=int, default=35)
    args = parser.parse_args()
    run(args.job, args.optimized, args.reference)
