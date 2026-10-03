"""Per-job frame, face and world evidence without invented camera poses.

This is metadata for reconstruction experiments and audit.  A registered
COLMAP pose from the current mixed-feature mapper is recorded as an estimate,
not promoted to a trusted static-world observation by its frame count alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pycolmap
from PIL import Image

from joint_visibility import sha256_file


def _poses(path: Path, field: str) -> dict[str, np.ndarray]:
    if not path.is_file():
        return {}
    with np.load(path) as source:
        names = [str(name) for name in source["names"]]
        matrices = source[field]
    if len(names) != len(set(names)) or len(names) != len(matrices):
        raise ValueError(f"duplicate_or_unpaired_pose_name:{path.name}")
    return dict(zip(names, matrices))


def component_observation_record(job, name, directory, camera, local_pose,
                                 role, world_status):
    """Join component evidence by exact image name, never positional zip."""
    from face import COMPONENT_MASK_NAMES
    frame = job/"frames"/name
    masks = {}
    with Image.open(frame) as source:
        size = source.size
    for label in COMPONENT_MASK_NAMES:
        item = directory/label/(name+".png")
        with Image.open(item) as source:
            if source.size != size:
                raise ValueError(f"component_mask_size_mismatch:{name}:{label}")
        masks[label] = {"path":str(item),"sha256":sha256_file(item)}
    return {"name":name,"imageSha256":sha256_file(frame),"pixelSize":size,
            "masks":masks,"semanticConfidencePath":str(directory/"confidence"/(name+".npz")),
            "faceObservation":local_pose,"worldObservation":camera,
            "worldEvidenceStatus":world_status,"role":role,
            "finalAudit":False,"glassesMaskMeaning":"accessory_edge_candidates_not_eyewear_truth",
            "unknownMeaning":"2D_unassigned_or_boundary_not_empty_3D_volume"}


def build_observation_bundle(job: Path, selection: Path | None = None) -> dict:
    selection = selection or job / "frame_selection.json"
    manifest = json.loads(selection.read_text(encoding="utf-8"))
    frames = manifest.get("selectedFrames", manifest.get("frames"))
    if not isinstance(frames, list) or len(frames) < 18:
        raise ValueError("frame_selection_missing")
    names = [row["name"] for row in frames]
    if len(names) != len(set(names)):
        raise ValueError("duplicate_frame_name")
    indices = [row.get("sourceIndexZeroBased") for row in frames]
    if all(index is not None for index in indices) and any(
            right <= left for left, right in zip(indices, indices[1:])):
        raise ValueError("selected_source_indices_not_strictly_increasing")
    timestamps = [row.get("timestampSeconds") for row in frames]
    if all(value is not None for value in timestamps) and any(
            right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("selected_source_timestamps_not_strictly_increasing")
    capture_hash = sha256_file(job / "capture.mp4")
    if capture_hash != manifest["captureSha256"]:
        raise ValueError("source_capture_hash_changed")
    model = pycolmap.Reconstruction(job / "sparse" / "0")
    worlds = {image.name: image for image in model.images.values() if image.has_pose}
    if not set(worlds).issubset(names):
        raise ValueError("registered_image_outside_selected_frames")
    corrected = _poses(job / "face_camera_poses.npz", "w2c")
    local = _poses(job / "face_head_to_camera.npz", "head_to_camera")
    if not set(corrected).issubset(names) or not set(local).issubset(names):
        raise ValueError("face_pose_name_not_in_selection")
    with np.load(job / "face_landmarks.npz") as source:
        landmark_names = set(source.files)
    if not landmark_names.issubset(names):
        raise ValueError("landmark_name_not_in_selection")
    registered_names = sorted(worlds)
    held_stride = max(5, len(registered_names) // 10)
    development = set(registered_names[::held_stride])
    output = []
    for row in frames:
        name = row["name"]
        image_path = job / "frames" / name
        if not image_path.is_file() or sha256_file(image_path) != row["pngSha256"]:
            raise ValueError(f"selected_frame_hash_changed:{name}")
        with Image.open(image_path) as source_image:
            image_size = source_image.size
        image = worlds.get(name)
        world = None
        intrinsics = None
        if image is not None:
            camera = model.cameras[image.camera_id]
            if image_size != (camera.width, camera.height):
                raise ValueError(f"registered_camera_frame_size_mismatch:{name}")
            matrix = np.eye(4, dtype=np.float64)
            matrix[:3, :] = np.asarray(image.cam_from_world().matrix())
            K = np.asarray(camera.calibration_matrix())
            if not np.isfinite(matrix).all() or not np.isfinite(K).all():
                raise ValueError(f"registered_camera_nonfinite:{name}")
            intrinsics = {"K": K.tolist(), "cameraModel": str(camera.model.name),
                          "cameraParams": [float(value) for value in camera.params],
                          "status": "COLMAP_estimated_not_independently_calibrated"}
            world = {"worldToCamera": matrix.tolist(),
                     "colmapImageId": int(image.image_id),
                     "colmapCameraId": int(image.camera_id),
                     "status": "registered_mixed_person_room_features_not_static_verified",
                     "trustedForFinalJointTraining": False}
        masks = {}
        for label, directory in (("head", "face_masks"),
                                 ("sceneExclusion", "scene_exclusions"),
                                 ("visibleEnvironment", "environment_masks"),
                                 ("personComponents", "person_components"),
                                 ("staticFeatureCandidate", "static_feature_masks")):
            file = job / directory / (name + ".png")
            if file.is_file():
                with Image.open(file) as mask_image:
                    if mask_image.size != image_size:
                        raise ValueError(f"mask_frame_size_mismatch:{label}:{name}")
                masks[label] = {"relativePath": f"{directory}/{name}.png",
                                "sha256": sha256_file(file)}
            else:
                masks[label] = None
        for label, matrix in (("head", local.get(name)),
                              ("corrected", corrected.get(name))):
            if matrix is not None and (matrix.shape != (4, 4) or
                                       not np.isfinite(matrix).all() or
                                       not .99 <= np.linalg.det(matrix[:3, :3]) <= 1.01):
                raise ValueError(f"invalid_face_pose:{label}:{name}")
        output.append({"name": name,
                       "sourceIndexZeroBased": row.get("sourceIndexZeroBased"),
                       "timestampSeconds": row.get("timestampSeconds"),
                       "imageSha256": row["pngSha256"],
                       "decodedPixelSize": list(image_size),
                       "imageTransform": {"pixels": "decoded_upright_as_saved",
                                          "mirror": "not_independently_verified",
                                          "crop": None, "resize": None},
                       "intrinsics": intrinsics,
                       "faceObservation": {
                           "headToCamera": local[name].tolist() if name in local else None,
                           "poseMethod": "canonical_mediapipe_pnp_with_estimated_colmap_scale"
                           if name in local else "not_saved_in_historical_run",
                           "poseCompensatedWorldToCamera":
                           corrected[name].tolist() if name in corrected else None,
                           "landmarksAvailable": name in landmark_names,
                           "headMask": masks["head"],
                           "personComponents": masks["personComponents"],
                           "visibility": "observed_2d_head_mask_not_3d_occlusion_truth"},
                       "worldObservation": world,
                       "masks": masks,
                       "staticFeatureMaskStatus": "shadow_candidate_not_used_by_production_mapper",
                       "roles": {"productionFit": name in worlds and name not in development,
                                 "development": name in development,
                                 "finalAudit": False}})
    bundle = {"schemaVersion": 1, "sourceSha256": capture_hash,
              "selectionMethod": manifest.get("selectionMethod", manifest.get("sampling")),
              "timestampStatus": manifest.get("timestampStatus", manifest.get("timestampSource")),
              "joinKey": "relative_image_name_not_colmap_id",
              "worldEvidenceStatus": "mixed_feature_registration_requires_static_audit",
              "registeredWorldEstimateCount": len(worlds),
              "trustedStaticWorldCount": 0,
              "localHeadPoseCount": len(local), "poseCompensatedViewCount": len(corrected),
              "developmentCount": len(development), "frames": output}
    (job / "observation_bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return bundle


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--selection", type=Path)
    args = parser.parse_args()
    result = build_observation_bundle(args.job, args.selection)
    print(json.dumps({key: result[key] for key in
                      ("sourceSha256", "registeredWorldEstimateCount",
                       "trustedStaticWorldCount", "localHeadPoseCount",
                       "poseCompensatedViewCount", "developmentCount")}))
