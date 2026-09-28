"""Reconstruct an exact frame/name/PTS/pose manifest for an existing job.

The capture is decoded once to replay the *current* frame selector. Every
replayed selected pixel buffer is compared with its stored PNG before a
timestamp is assigned. COLMAP image IDs are joined only by image name.
No image content is written to the report.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import pycolmap

from probe_static_alignment import best_model


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_pts(capture: Path) -> list[float]:
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "frame=best_effort_timestamp_time",
                             "-of", "csv=p=0", str(capture)], capture_output=True,
                            text=True, timeout=90, check=True)
    values = [float(line.split(",", 1)[0]) for line in result.stdout.splitlines()
              if line.strip()]
    if len(values) < 18 or not np.isfinite(values).all() or any(
            later <= earlier for earlier, later in zip(values, values[1:])):
        raise ValueError("source_timestamp_invalid")
    return values


def score_frame(frame: np.ndarray, second: float, interval: float) -> float:
    """Replay the old production scorer exactly; do not silently resample."""
    small = cv2.resize(frame, (480, 270), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    central = gray[round(gray.shape[0] * .16):round(gray.shape[0] * .88),
                   round(gray.shape[1] * .20):round(gray.shape[1] * .80)]
    sharpness = (.8 * float(cv2.Laplacian(central, cv2.CV_32F).var()) +
                 .2 * float(cv2.Laplacian(gray, cv2.CV_32F).var()))
    center_bonus = 1.0 - .04 * abs((second / interval) % 1 - .5)
    return sharpness * center_bonus


def replay_selected(job: Path, pts: list[float]) -> list[dict]:
    quality = json.loads((job / "capture_quality.json").read_text(encoding="utf-8"))
    max_frames = int(quality["sampledFrames"])
    interval = float(quality["durationSeconds"]) / max_frames
    capture = cv2.VideoCapture(str(job / "capture.mp4"))
    if not capture.isOpened():
        raise ValueError("capture_decode_failed")
    fps = capture.get(cv2.CAP_PROP_FPS)
    if not math.isfinite(fps) or fps < 8:
        raise ValueError("capture_frame_rate_unreliable")
    records: list[dict] = []
    bucket = -1
    best = None
    decoded = 0

    def append(candidate) -> None:
        if candidate is None:
            return
        name = f"frame_{len(records) + 1:04d}.png"
        stored = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
        if stored is None or stored.shape != candidate[1].shape or not np.array_equal(
                stored, candidate[1]):
            raise ValueError(f"stored_frame_not_exact_replay:{name}")
        index = candidate[2]
        records.append({"name": name, "sourceIndexZeroBased": index,
                        "timestampSeconds": pts[index], "decodedWidth": stored.shape[1],
                        "decodedHeight": stored.shape[0],
                        "pngSha256": sha_file(job / "frames" / name)})

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if decoded >= len(pts):
                raise ValueError("more_decoded_frames_than_pts")
            second = decoded / fps
            next_bucket = min(max_frames - 1, int(second / interval))
            if next_bucket != bucket:
                append(best)
                best = None
                bucket = next_bucket
            score = score_frame(frame, second, interval)
            if best is None or score > best[0]:
                best = (score, frame.copy(), decoded)
            decoded += 1
        append(best)
    finally:
        capture.release()
    if decoded != len(pts) or len(records) != max_frames:
        raise ValueError(f"frame_pts_or_selection_count_mismatch:{decoded}:{len(pts)}:{len(records)}")
    return records


def camera_links(model: pycolmap.Reconstruction, database: Path,
                 records: list[dict]) -> dict[str, dict]:
    with sqlite3.connect(database) as conn:
        database_ids = {name: (int(image_id), int(camera_id))
                        for image_id, name, camera_id in conn.execute(
                            "SELECT image_id,name,camera_id FROM images")}
    if set(database_ids) != {record["name"] for record in records}:
        raise ValueError("database_image_names_not_exact_manifest")
    model_by_name = {image.name: image for image in model.images.values() if image.has_pose}
    if len(model_by_name) != model.num_reg_images():
        raise ValueError("duplicate_model_image_name")
    links = {}
    for record in records:
        name = record["name"]
        db_image_id, db_camera_id = database_ids[name]
        image = model_by_name.get(name)
        if image is None:
            links[name] = {"registered": False, "databaseImageId": db_image_id,
                           "databaseCameraId": db_camera_id, "reason": "not_registered"}
            continue
        if image.image_id != db_image_id or image.camera_id != db_camera_id:
            raise ValueError(f"colmap_id_mismatch:{name}")
        camera = model.cameras[image.camera_id]
        if (camera.width, camera.height) != (record["decodedWidth"], record["decodedHeight"]):
            raise ValueError(f"camera_decoded_size_mismatch:{name}")
        world_to_camera = np.eye(4, dtype=np.float64)
        world_to_camera[:3, :] = np.asarray(image.cam_from_world().matrix())
        K = np.asarray(camera.calibration_matrix())
        if not np.isfinite(world_to_camera).all() or not np.isfinite(K).all() or np.linalg.det(
                world_to_camera[:3, :3]) < .99:
            raise ValueError(f"camera_matrix_invalid:{name}")
        links[name] = {"registered": True, "imageId": int(image.image_id),
                       "cameraId": int(image.camera_id), "cameraModel": str(camera.model.name),
                       "cameraParams": [float(v) for v in camera.params],
                       "K": K.tolist(), "worldToCamera": world_to_camera.tolist()}
    return links


def run(job: Path) -> dict:
    start = time.perf_counter()
    pts = source_pts(job / "capture.mp4")
    records = replay_selected(job, pts)
    root = job / "static_sfm_probe_stride1"
    candidates = {
        "mixed_current": (pycolmap.Reconstruction(job / "sparse" / "0"), job / "colmap.db"),
        "static_incremental": (best_model(root / "sparse"), root / "colmap.db"),
        "static_global_estimated_focal": (
            best_model(root / "calibrated_global" / "sparse"),
            root / "calibrated_global" / "colmap.db"),
    }
    links = {name: camera_links(model, database, records)
             for name, (model, database) in candidates.items()}
    with np.load(job / "face_landmarks.npz") as source:
        landmark_names = set(source.files)
    with np.load(job / "face_camera_poses.npz") as source:
        pose_names = [str(value) for value in source["names"]]
        pose_values = source["w2c"]
    if len(set(pose_names)) != len(pose_names) or len(pose_names) != len(pose_values):
        raise ValueError("face_view_names_not_unique")
    pose_by_name = dict(zip(pose_names, pose_values))
    frame_names = {record["name"] for record in records}
    if landmark_names != frame_names or set(pose_by_name) != frame_names:
        raise ValueError("person_observation_names_not_exact_frames")
    face_regions = json.loads((job / "face_regions.json").read_text(encoding="utf-8"))
    if set(face_regions) != frame_names:
        raise ValueError("face_region_names_not_exact_frames")
    for record in records:
        name = record["name"]
        for folder, label in (("face_masks", "faceMask"),
                              ("scene_exclusions", "sceneExclusion"),
                              ("static_sfm_probe_stride1/masks", "wholePersonSfmMask")):
            mask_path = job / folder / (name + ".png")
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if mask is None or mask.shape != (record["decodedHeight"], record["decodedWidth"]):
                raise ValueError(f"mask_missing_or_wrong_size:{label}:{name}")
            record[label + "Sha256"] = sha_file(mask_path)
        record["faceRegion"] = face_regions[name]
        # This is a pose-corrected *training camera*, not H_t or B_t.
        record["faceViewCorrectionWorldToCamera"] = np.asarray(
            pose_by_name[name], dtype=np.float64).tolist()
        record["personMotionFit"] = None
        record["candidates"] = {key: value[name] for key, value in links.items()}
    manifest = {"schemaVersion": 1, "captureSha256": sha_file(job / "capture.mp4"),
                "sourceFrameCount": len(pts), "selectedFrameCount": len(records),
                "selectionMethod": "exact_replay_of_current_time_bucket_scoring",
                "timestampSource": "ffprobe_best_effort_timestamp_time",
                "imageJoinKey": "relative_image_name_not_COLMAP_ID",
                "coordinateContract": "COLMAP right/down/front; worldToCamera; camera center=-R.T@t; K in decoded upright pixels",
                "intrinsicsStatus": "estimated_from_video_not_independent_calibration",
                "elapsedSeconds": round(time.perf_counter() - start, 2),
                "frames": records}
    output = job / "frame_manifest.audit.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
                      encoding="utf-8")
    summary = {"manifest": str(output), "frames": len(records),
               "timestampFirst": records[0]["timestampSeconds"],
               "timestampLast": records[-1]["timestampSeconds"],
               "candidateRegistered": {key: sum(value[name]["registered"] for name in frame_names)
                                       for key, value in links.items()},
               "elapsedSeconds": manifest["elapsedSeconds"]}
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("probe_frame_manifest.py JOB_DIR")
    run(Path(sys.argv[1]))
