"""Extract a bounded source-frame bridge without touching the 160-frame base.

Output is private and ignored. Names here are *source indices*, never COLMAP
IMAGE_IDs or original selected-frame ordinals.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

from probe_source_frame_coverage import frame_timestamps
from probe_static_camera import person_mask
from reconstruction_face import SEGMENTER, check_models


SOURCE_INDICES = (734, 743, 750, 756, 762, 770, 774, 785, 786, 792,
                  809, 816, 829, 842, 850)
SOURCE_SHA256 = "7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf"


def run(job: Path) -> dict:
    check_models()
    video = job / "capture.mp4"
    if hashlib.sha256(video.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("source_video_hash_changed")
    original = json.loads((job / "frame_manifest.audit.json").read_text(encoding="utf-8"))
    selected = {row["sourceIndexZeroBased"]: row["name"] for row in original["frames"]}
    timestamps = frame_timestamps(video)
    root = job / "source_bridge_job_20260927"
    images = root / "frames"
    masks = root / "static_sfm_probe_stride1/masks"
    images.mkdir(parents=True, exist_ok=True)
    masks.mkdir(parents=True, exist_ok=True)
    options = mp.tasks.vision.ImageSegmenterOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(SEGMENTER)),
        output_confidence_masks=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError("video_decode_failed")
    records = []
    index = -1
    try:
        with mp.tasks.vision.ImageSegmenter.create_from_options(options) as segmenter:
            while index < SOURCE_INDICES[-1]:
                ok, frame = capture.read()
                if not ok:
                    raise ValueError(f"source_frame_missing_after:{index}")
                index += 1
                if index not in SOURCE_INDICES:
                    continue
                if frame.shape[:2] != (1920, 1080):
                    raise ValueError(f"source_orientation_changed:{index}")
                name = f"frame_{index:04d}.png"
                target = images / name
                cv2.imwrite(str(target), frame)
                if index in selected:
                    baseline = cv2.imread(str(job / "frames" / selected[index]),
                                          cv2.IMREAD_COLOR)
                    if baseline is None or not np.array_equal(frame, baseline):
                        raise ValueError(f"selected_source_pixel_mismatch:{index}")
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                task_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                                      data=np.ascontiguousarray(rgb))
                result = segmenter.segment(task_image)
                confidence = [layer.numpy_view().squeeze().copy()
                              for layer in result.confidence_masks]
                mask, excluded_fraction = person_mask(confidence, 1080, 1920)
                mask_target = masks / (name + ".png")
                cv2.imwrite(str(mask_target), mask)
                records.append({"sourceIndexZeroBased": index,
                                "timestampSeconds": timestamps[index],
                                "originalSelectedName": selected.get(index),
                                "imageSha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                                "staticMaskSha256": hashlib.sha256(mask_target.read_bytes()).hexdigest(),
                                "excludedFraction": round(excluded_fraction, 4)})
    finally:
        capture.release()
    if len(records) != len(SOURCE_INDICES):
        raise ValueError("bounded_bridge_extraction_incomplete")
    report = {"sourceSha256": SOURCE_SHA256,
              "baselineFramesUntouched": True,
              "imageIdIsNotSourceIndex": True,
              "requestedSourceIndices": list(SOURCE_INDICES),
              "records": records}
    (root / "bridge.manifest.json").write_text(json.dumps(report, indent=2),
                                                encoding="utf-8")
    print(json.dumps({"sourceSha256": SOURCE_SHA256,
                      "sourceFrames": len(records),
                      "newUnselected": sum(row["originalSelectedName"] is None
                                           for row in records)}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    run(parser.parse_args().job)
