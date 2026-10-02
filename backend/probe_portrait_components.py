"""Private 2D source-video part labels, never a publishable 3D avatar."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from probe_flame_open_fit import HELD, SOURCE_SHA256, TRAIN, filename


MODEL_DIR = Path(__file__).resolve().parent / ".sources/third_party/mediapipe"
HAIR_MODEL = MODEL_DIR / "hair_segmenter.tflite"
PART_MODEL = MODEL_DIR / "selfie_multiclass_256x256.tflite"
HAIR_SHA256 = "2628cf3ce5f695f604cbea2841e00befcaa3624bf80caf3664bef2656d59bf84"
PART_SHA256 = "c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0"
PALETTE = np.asarray([[0, 0, 0], [230, 120, 30], [20, 200, 30],
                      [100, 80, 230], [200, 190, 20], [200, 30, 200]], np.float32)


def segmenter(path: Path) -> mp.tasks.vision.ImageSegmenter:
    return mp.tasks.vision.ImageSegmenter.create_from_options(
        mp.tasks.vision.ImageSegmenterOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
            output_category_mask=True, output_confidence_masks=True))


def run(job: Path) -> dict:
    start = time.perf_counter()
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    for path, expected in ((HAIR_MODEL, HAIR_SHA256), (PART_MODEL, PART_SHA256)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"model_hash_mismatch:{path.name}")
    out = job / "portrait_components_20260927"
    out.mkdir(exist_ok=True)
    rows = []
    with segmenter(HAIR_MODEL) as hair_segmenter, segmenter(PART_MODEL) as part_segmenter:
        if (hair_segmenter.labels != ["background", "hair"] or
                part_segmenter.labels != ["background", "hair", "body-skin",
                                          "face-skin", "clothes", "others"]):
            raise ValueError("unexpected_segmenter_labels")
        for frame in TRAIN + HELD:
            name = filename(frame)
            bgr = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
            head = cv2.imread(str(job / "face_masks" / (name + ".png")),
                              cv2.IMREAD_GRAYSCALE)
            if bgr is None or head is None or bgr.shape[:2] != (1920, 1080):
                raise ValueError(f"missing_component_frame:{name}")
            image = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            hair_result = hair_segmenter.segment(image)
            part_result = part_segmenter.segment(image)
            parts = np.asarray(part_result.category_mask.numpy_view()).squeeze().copy()
            hair_confidence = np.asarray(hair_result.confidence_masks[1].numpy_view()).squeeze()
            high_res_hair = ((hair_confidence >= .6) & (head > 0)).astype(np.uint8)
            # Keep both masks and measure disagreement; do not relabel pixels
            # silently or paint high-res hair onto the FLAME skin surface.
            cv2.imwrite(str(out / f"parts-{name}"), parts)
            cv2.imwrite(str(out / f"hair-{name}"), high_res_hair * 255)
            row = {"frame": frame, "role": "color_training" if frame in TRAIN else "audit_only",
                   "sourceImageSha256": hashlib.sha256((job / "frames" / name).read_bytes()).hexdigest(),
                   "classPixelCounts": np.bincount(parts.ravel(), minlength=6).tolist(),
                   "highResHairPixels": int(high_res_hair.sum()),
                   "hairAgainstFaceSkinConflictPixels": int(((parts == 3) & (high_res_hair > 0)).sum()),
                   "partsMaskSha256": hashlib.sha256((out / f"parts-{name}").read_bytes()).hexdigest(),
                   "hairMaskSha256": hashlib.sha256((out / f"hair-{name}").read_bytes()).hexdigest()}
            rows.append(row)
            if frame in (25, 80, 136):
                overlay = bgr.astype(np.float32) * .65 + PALETTE[parts] * .35
                cv2.imwrite(str(out / f"private-components-{frame:04d}.jpg"),
                            cv2.resize(overlay.astype(np.uint8), (540, 960)),
                            [cv2.IMWRITE_JPEG_QUALITY, 93])
    report = {"status": "2d_component_observations_only_not_3d_geometry",
              "sourceSha256": SOURCE_SHA256,
              "models": {"hair": {"sha256": HAIR_SHA256, "license": "Apache-2.0"},
                         "parts": {"sha256": PART_SHA256, "license": "Apache-2.0"}},
              "labels": ["background", "hair", "body-skin", "face-skin", "clothes", "others"],
              "frames": rows, "elapsedSeconds": round(time.perf_counter() - start, 2),
              "limits": ["2D labels cannot establish hair thickness or 3D depth",
                         "256-pixel part boundary is approximate",
                         "glasses/ears/collar require separate multi-view validation"]}
    (out / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "frames": len(rows),
                      "elapsedSeconds": report["elapsedSeconds"],
                      "examples": [row for row in rows if row["frame"] in (25, 80, 136)]},
                     indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    args = parser.parse_args()
    run(args.job)
