"""Keep local face observations separate from evidence-backed world cameras.

Private audit for the current video. F_t uses FLAME local root-neutral vertices;
the fitted root rotation is removed from the mesh exactly once. A world head
matrix is never filled while metric/scene scale and K remain incompatible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch

from flame_open_model import FlameOpen, MODEL, STANDARD_MODEL
from probe_flame_open_fit import HELD, INTRINSIC, SOURCE_SHA256, TRAIN, filename
from probe_static_alignment import best_model


def root_neutral_contract(model: FlameOpen, shape: torch.Tensor,
                          expression: torch.Tensor, pose: torch.Tensor,
                          translation: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Return local mesh and F_t, checking nonzero shape/neck/jaw consistency."""
    neutral_pose = pose.clone()
    neutral_pose[:, 0] = 0
    with torch.no_grad():
        local, _ = model(shape, expression, neutral_pose)
        posed, _ = model(shape, expression, pose)
        shaped = model.template[None] + torch.einsum(
            "vci,bi->bvc", model.directions,
            torch.cat((shape, expression), dim=1))
        root_joint = torch.einsum("v,bvc->bc", model.joint_regressor[0], shaped)[0]
    rotation, _ = cv2.Rodrigues(pose[0, 0].cpu().numpy().astype(np.float64))
    center = root_joint.cpu().numpy().astype(np.float64)
    F = np.eye(4, dtype=np.float64)
    F[:3, :3] = rotation
    F[:3, 3] = np.asarray(translation, np.float64) + center - rotation @ center
    reconstructed = local[0].cpu().numpy() @ rotation.T + F[:3, 3]
    actual = posed[0].cpu().numpy() + translation
    error = float(np.linalg.norm(reconstructed - actual, axis=1).max())
    return local[0].cpu().numpy(), F, error


def run(job: Path, variant: str = "open") -> dict:
    if variant not in ("open", "standard"):
        raise ValueError("unsupported_variant")
    fit_dir = job / ("flame_open_e2_20260927" if variant == "open"
                     else "flame_standard_e2_20260927")
    model = FlameOpen(24, 12, model_path=MODEL if variant == "open" else STANDARD_MODEL)
    train = dict(np.load(fit_dir / "private-fit-parameters.npz"))
    held = dict(np.load(fit_dir / "private-held-local-parameters.npz"))
    manifest = json.loads((job / "frame_manifest.audit.json").read_text(encoding="utf-8"))
    if manifest["captureSha256"] != SOURCE_SHA256:
        raise ValueError("manifest_source_mismatch")
    by_name = {entry["name"]: entry for entry in manifest["frames"]}
    trust_root = job / "static_sfm_probe_stride1"
    trusted = {row["name"]: row for row in json.loads((trust_root / "trusted_views.audit.json")
                                               .read_text(encoding="utf-8"))["frames"]}
    world_model = best_model(trust_root / "targeted_global" / "sparse")
    world_images = {image.name: image for image in world_model.images.values() if image.has_pose}
    records = []
    largest_root_error = 0.
    for index in range(1, 161):
        name = filename(index)
        source = by_name[name]
        row = {"name": name, "sourceFrameZeroBased": source["sourceIndexZeroBased"],
               "timestampSeconds": source["timestampSeconds"],
               "imageSha256": source["pngSha256"],
               "faceObservation": None, "worldObservation": None,
               "headInWorld": None}
        if index in TRAIN or index in HELD:
            params = train if index in TRAIN else held
            local_index = (TRAIN if index in TRAIN else HELD).index(index)
            shape = torch.from_numpy(params["shared_shape"])
            expression = torch.from_numpy(params["expressions"][local_index:local_index + 1])
            pose = torch.from_numpy(params["joint_axis_angles"][local_index:local_index + 1])
            _, F, error = root_neutral_contract(model, shape, expression, pose,
                                                params["camera_translations"][local_index])
            largest_root_error = max(largest_root_error, error)
            if error > 1e-5:
                raise AssertionError(f"root_applied_twice:{index}:{error}")
            row["faceObservation"] = {
                "role": "shape_and_color_fit" if index in TRAIN else "pose_landmarks_only_color_held_out",
                "imageSize": [source["decodedWidth"], source["decodedHeight"]],
                "imageTransform": "video rotation metadata applied by decoding; frame PNG upright",
                "estimatedK": INTRINSIC.tolist(), "distortion": "ignored_in_local_fit",
                "localHeadToCameraF": F.tolist(),
                "localMeshHasRootRotation": False,
                "expression": expression[0].tolist(), "jointAxisAngles": pose[0].tolist(),
                "visibleRegion": source["faceRegion"],
                "faceMaskSha256": source["faceMaskSha256"],
                "landmarkSource": "MediaPipe 105 embedding; 84 used for held local pose",
                "rootContractMaxVertexError": error,
            }
        if trusted[name]["researchTrusted"]:
            image = world_images.get(name)
            if image is None:
                raise ValueError(f"trusted_camera_missing:{name}")
            C = np.eye(4)
            C[:3] = np.asarray(image.cam_from_world().matrix())
            camera = world_model.cameras[image.camera_id]
            row["worldObservation"] = {
                "worldToCameraC": C.tolist(), "cameraId": int(image.camera_id),
                "colmapImageId": int(image.image_id),
                "K": np.asarray(camera.calibration_matrix()).tolist(),
                "cameraModel": camera.model.name,
                "staticMap": "targeted_global/sparse; temporarily research-trusted only",
                "staticInliers": trusted[name]["globalStaticInliers"],
                "imageGridOccupancy": "see separate static-camera audit",
            }
        records.append(row)
    report = {"status": "separated_local_and_world_observations_no_synthetic_head_world_pose",
              "sourceSha256": SOURCE_SHA256, "modelSha256": model.model_sha256,
              "faceObservationCount": sum(row["faceObservation"] is not None for row in records),
              "worldObservationCount": sum(row["worldObservation"] is not None for row in records),
              "bothCount": sum(row["faceObservation"] is not None and
                               row["worldObservation"] is not None for row in records),
              "headInWorldCount": 0,
              "whyNoHeadInWorld": "local K ignores radial distortion and world scene scale is not independently calibrated; H=C^-1 F would mix coordinate/scale conventions",
              "maxRootContractVertexError": largest_root_error,
              "records": records}
    out = fit_dir / "private-observations.audit.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "faceObservationCount",
                 "worldObservationCount", "bothCount", "headInWorldCount",
                 "maxRootContractVertexError")}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    args = parser.parse_args()
    run(args.job, args.variant)
