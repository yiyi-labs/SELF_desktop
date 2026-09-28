"""Bounded source-frame audit for one existing private capture.

The 160-frame baseline is untouched. Extra frames are indexed only to decide
whether a few source observations merit isolated matching/localization.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageDraw

from reconstruction_face import LANDMARKER, SEGMENTER, check_models, head_box
from reconstruction_pose import canonical_vertices, pose_from_landmarks


def frame_timestamps(video: Path) -> list[float]:
    completed = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(video),
    ], check=True, capture_output=True, text=True)
    return [float(line.strip()) for line in completed.stdout.splitlines() if line.strip()]


def run(job: Path) -> dict:
    check_models()
    video = job / "capture.mp4"
    manifest = json.loads((job / "frame_manifest.audit.json").read_text(encoding="utf-8"))
    if hashlib.sha256(video.read_bytes()).hexdigest() != manifest["captureSha256"]:
        raise ValueError("source_capture_hash_changed")
    selected = {int(row["sourceIndexZeroBased"]) for row in manifest["frames"]}
    pts = frame_timestamps(video)
    if len(pts) != manifest["sourceFrameCount"]:
        raise ValueError(f"source_pts_count_mismatch:{len(pts)}")
    # About 180 low-cost samples, concentrated at the known 61--100 gap.
    targets = {i for i in range(len(pts)) if i % 30 == 0 or
               (650 <= i <= 1300 and i % 6 == 0)}
    targets.update(row["sourceIndexZeroBased"] for row in manifest["frames"]
                   if int(row["name"][6:10]) in (40, 50, 60, 61, 70, 80, 90, 100, 110, 120, 130, 140, 150))
    face_options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(LANDMARKER)),
        num_faces=1, min_face_detection_confidence=.30,
        min_face_presence_confidence=.35)
    segment_options = mp.tasks.vision.ImageSegmenterOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(SEGMENTER)),
        output_confidence_masks=True)
    canonical = canonical_vertices()
    out = job / "source_coverage_20260927"
    out.mkdir(exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError("capture_decode_failed")
    records = []
    thumbnails = []
    started = time.perf_counter()
    try:
        with mp.tasks.vision.FaceLandmarker.create_from_options(face_options) as landmarker, \
             mp.tasks.vision.ImageSegmenter.create_from_options(segment_options) as segmenter:
            index = -1
            while True:
                ok, image = cap.read()
                if not ok:
                    break
                index += 1
                if index not in targets:
                    continue
                if image.shape[:2] != (1920, 1080):
                    raise ValueError(f"decoded_orientation_changed:{index}:{image.shape}")
                small = cv2.resize(image, (540, 960), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                task_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                                      data=np.ascontiguousarray(rgb))
                face = landmarker.detect(task_image)
                segment = segmenter.segment(task_image)
                layers = [layer.numpy_view().squeeze().copy() for layer in segment.confidence_masks]
                if len(layers) != 6:
                    raise ValueError("segmenter_labels_changed")
                foreground = np.maximum.reduce(layers[1:])
                foreground = cv2.resize(foreground, (540, 960))
                person = cv2.dilate((foreground >= .28).astype(np.uint8),
                                    cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                # Static corners are only a screening signal, not 2D--3D proof.
                corners = cv2.goodFeaturesToTrack(gray, 450, .012, 10,
                                                  mask=((1 - person) * 255).astype(np.uint8))
                cells = set()
                if corners is not None:
                    for u, v in corners.reshape(-1, 2):
                        cells.add((min(3, int(u * 4 / 540)), min(3, int(v * 4 / 960))))
                result = {"sourceIndexZeroBased": index, "timestampSeconds": pts[index],
                          "originallySelected": index in selected,
                          "staticCornerCountLowRes": 0 if corners is None else len(corners),
                          "staticGridCells4x4": len(cells),
                          "wholePersonFractionLowRes": round(float(person.mean()), 4),
                          "faceDetected": len(face.face_landmarks) == 1,
                          "facePoseRawYawDegrees": None,
                          "facePoseRelativeYawDegrees": None,
                          "facePoseRmseLowResPx": None,
                          "faceSharpnessLowRes": None}
                if len(face.face_landmarks) == 1:
                    marks = face.face_landmarks[0]
                    x, y, w, h = head_box(marks, 540, 960)
                    crop = gray[y:y+h, x:x+w]
                    if crop.size:
                        result["faceSharpnessLowRes"] = round(float(
                            cv2.Laplacian(crop, cv2.CV_32F).var()), 2)
                    points = np.asarray([[mark.x * 540, mark.y * 960]
                                         for mark in marks[:468]], dtype=np.float64)
                    K = np.asarray([[1181.055 / 2, 0, 270], [0, 1181.055 / 2, 480],
                                    [0, 0, 1]], dtype=np.float64)
                    try:
                        rotation, _, rmse, _ = pose_from_landmarks(canonical, points, K)
                        raw_yaw = math.degrees(math.atan2(rotation[0, 2], rotation[2, 2]))
                        # This canonical mesh faces toward -Z.  Its frontal
                        # PnP solution sits around +/-180, not zero.
                        result["facePoseRawYawDegrees"] = round(float(raw_yaw), 2)
                        result["facePoseRelativeYawDegrees"] = round(float(
                            (raw_yaw % 360) - 180), 2)
                        result["facePoseRmseLowResPx"] = round(rmse, 2)
                    except RuntimeError:
                        pass
                records.append(result)
                # Private visual review at a fixed, small budget.
                if index % 60 == 0 or index in selected and 650 <= index <= 1300:
                    tile = Image.fromarray(rgb).resize((135, 240), Image.Resampling.LANCZOS)
                    thumbnails.append((index, tile))
    finally:
        cap.release()
    if index + 1 != len(pts):
        raise ValueError(f"decoded_frame_count_mismatch:{index + 1}:{len(pts)}")
    rows = 1 + (len(thumbnails) - 1) // 8
    sheet = Image.new("RGB", (8 * 151, rows * 265), "#111820")
    draw = ImageDraw.Draw(sheet)
    for order, (source_index, tile) in enumerate(thumbnails):
        x, y = (order % 8) * 151, (order // 8) * 265
        sheet.paste(tile, (x, y))
        draw.text((x + 3, y + 242), f"{source_index}  {pts[source_index]:.1f}s", fill="#ffffff")
    sheet.save(out / "private-contact-sheet.jpg", quality=85)
    result = {"sourceSha256": manifest["captureSha256"], "sourceFrames": len(pts),
              "baselineSelected": len(selected), "sampledForIndex": len(records),
              "sampledUnselected": sum(not row["originallySelected"] for row in records),
              "samplingRule": "every 30th source frame, every 6th in 650--1300, plus 13 anchors",
              "facePoseIsDiagnosticNotGroundTruth": True,
              "elapsedSeconds": round(time.perf_counter() - started, 2),
              "frames": records}
    (out / "index.json").write_text(json.dumps(result, ensure_ascii=False,
                                               separators=(",", ":")), encoding="utf-8")
    print(json.dumps({key: val for key, val in result.items() if key != "frames"}), flush=True)
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_source_frame_coverage.py JOB_DIR")
    run(Path(sys.argv[1]))
