"""Isolated static-room SfM probe for an existing reconstruction job.

This does not change the production worker or any published asset.  It uses
the same decoded frames and creates whole-person COLMAP masks *before*
feature extraction.  The report contains only numerical diagnostics.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import pycolmap

from reconstruction_face import SEGMENTER, check_models


def person_mask(confidence: list[np.ndarray], width: int, height: int,
                threshold: float = .28) -> tuple[np.ndarray, float]:
    """Black excludes hair, skin, clothes and accessories from static SfM."""
    if len(confidence) != 6:
        raise ValueError("segmenter_labels_changed")
    # The published six classes are background, hair, body skin, face skin,
    # clothing and accessory. Include weak edges rather than leaking a moving
    # sleeve into the room camera. This mask is *only* for feature extraction.
    foreground = np.maximum.reduce(confidence[1:])
    foreground = cv2.resize(foreground, (width, height), interpolation=cv2.INTER_LINEAR)
    excluded = (foreground >= threshold).astype(np.uint8)
    radius = max(4, min(12, round(min(width, height) * .006)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1,) * 2)
    excluded = cv2.dilate(excluded, kernel)
    fraction = float(np.count_nonzero(excluded)) / excluded.size
    if not .03 <= fraction <= .8:
        raise ValueError("person_mask_area_unreliable")
    return 255 * (1 - excluded), fraction


def run(job: Path, stride: int, threshold: float = .28) -> dict:
    check_models()
    frames_dir = job / "frames"
    names = [item.name for item in sorted(frames_dir.glob("frame_*.png"))][::stride]
    if len(names) < 24:
        raise ValueError("too_few_probe_frames")
    root = job / f"static_sfm_probe_stride{stride}_threshold{round(threshold * 100)}" if threshold != .28 \
        else job / f"static_sfm_probe_stride{stride}"
    root.mkdir(exist_ok=True)
    masks = root / "masks"
    masks.mkdir(exist_ok=True)
    strict_masks = root / "strict_masks"
    if threshold > .28:
        strict_masks.mkdir(exist_ok=True)
    started = time.perf_counter()
    segment_options = mp.tasks.vision.ImageSegmenterOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(SEGMENTER)),
        output_confidence_masks=True)
    fractions = []
    with mp.tasks.vision.ImageSegmenter.create_from_options(segment_options) as segmenter:
        for name in names:
            bgr = cv2.imread(str(frames_dir / name), cv2.IMREAD_COLOR)
            if bgr is None:
                raise ValueError("frame_decode_failed")
            height, width = bgr.shape[:2]
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            result = segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB,
                                                data=np.ascontiguousarray(rgb)))
            layers = [layer.numpy_view().squeeze().copy() for layer in result.confidence_masks]
            mask, fraction = person_mask(layers, width, height, threshold)
            if not cv2.imwrite(str(masks / (name + ".png")), mask):
                raise OSError("mask_write_failed")
            if threshold > .28:
                strict, _ = person_mask(layers, width, height)
                if not cv2.imwrite(str(strict_masks / (name + ".png")), strict):
                    raise OSError("strict_mask_write_failed")
            fractions.append(fraction)
    masks_seconds = time.perf_counter() - started
    database = root / "colmap.db"
    database.unlink(missing_ok=True)
    extraction = pycolmap.FeatureExtractionOptions(num_threads=8, max_image_size=-1)
    pycolmap.extract_features(database, frames_dir, image_names=names,
                             camera_mode=pycolmap.CameraMode.SINGLE,
                             reader_options=pycolmap.ImageReaderOptions(mask_path=masks),
                             extraction_options=extraction, device=pycolmap.Device.cpu)
    extraction_seconds = time.perf_counter() - started - masks_seconds
    # Verify the exact installed PyCOLMAP call read masks, not just that mask
    # files exist. All extracted keypoints must land on allowed pixels.
    outside = possible_person_leak = total = 0
    with sqlite3.connect(database) as db:
        for name, rows, cols, blob in db.execute(
            "SELECT images.name, keypoints.rows, keypoints.cols, keypoints.data "
            "FROM images JOIN keypoints USING(image_id)"
        ):
            points = np.frombuffer(blob, dtype="<f4").reshape(rows, cols)
            mask = cv2.imread(str(masks / (name + ".png")), cv2.IMREAD_GRAYSCALE)
            u = np.clip(points[:, 0].astype(np.int32), 0, mask.shape[1] - 1)
            v = np.clip(points[:, 1].astype(np.int32), 0, mask.shape[0] - 1)
            outside += int(np.count_nonzero(mask[v, u] == 0))
            if threshold > .28:
                strict = cv2.imread(str(strict_masks / (name + ".png")), cv2.IMREAD_GRAYSCALE)
                possible_person_leak += int(np.count_nonzero(strict[v, u] == 0))
            total += rows
    if outside:
        raise AssertionError(f"COLMAP keypoints leaked into person mask: {outside}/{total}")
    matched = time.perf_counter()
    pycolmap.match_sequential(database, pairing_options=pycolmap.SequentialPairingOptions(
        overlap=18, quadratic_overlap=True, num_threads=8), device=pycolmap.Device.cpu)
    matching_seconds = time.perf_counter() - matched
    mapped = time.perf_counter()
    sparse = root / "sparse"
    sparse.mkdir(exist_ok=True)
    models = pycolmap.incremental_mapping(database, frames_dir, sparse)
    mapping_seconds = time.perf_counter() - mapped
    if not models:
        raise ValueError("static_camera_mapping_failed")
    model = max(models.values(), key=lambda item: (item.num_reg_images(), item.num_points3D()))
    errors = np.asarray([point.error for point in model.points3D.values()])
    report = {
        "inputFrames": len(names), "registeredFrames": model.num_reg_images(),
        "staticPoints": model.num_points3D(), "excludedAreaMedian": round(float(np.median(fractions)), 4),
        "excludedAreaMin": round(float(min(fractions)), 4),
        "extractedKeypoints": total, "keypointsInsidePersonMask": outside,
        "keypointsInConservativePersonBand": possible_person_leak,
        "personThreshold": threshold,
        "staticPointReprojectionMedianPx": round(float(np.median(errors)), 3),
        "timingSeconds": {"masks": round(masks_seconds, 2),
                          "extract": round(extraction_seconds, 2),
                          "match": round(matching_seconds, 2),
                          "map": round(mapping_seconds, 2)},
        "note": "Background-only camera probe; no portrait model is produced",
    }
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--stride", type=int, default=2)
    parser.add_argument("--threshold", type=float, default=.28)
    args = parser.parse_args()
    if args.stride < 1 or args.stride > 4:
        parser.error("stride must be between 1 and 4")
    if not .28 <= args.threshold <= .5:
        parser.error("threshold must be between .28 and .5")
    run(args.job, args.stride, args.threshold)
