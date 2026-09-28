"""Disaggregate correlated MediaPipe landmark residuals by part and view.

These are *not* independent image/3D validation. The 105-point embedding has
no facial-oval points, so silhouette quality must be inspected separately.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch

from flame_open_model import FlameOpen, MODEL, STANDARD_MODEL
from probe_flame_open_fit import HELD, TRAIN, filename


PARTS = {
    "lips": {0, 17, 37, 39, 40, 61, 84, 91, 146, 181, 185, 267,
             269, 270, 291, 314, 321, 375, 405, 409},
    "left_eye": {7, 33, 133, 144, 145, 153, 154, 155, 157, 158, 159, 160,
                 161, 163, 173, 246},
    "right_eye": {249, 263, 362, 373, 374, 380, 381, 382, 384, 385, 386,
                  387, 388, 390, 398, 466},
    "nose": {2, 4, 5, 6, 168, 195, 197},
}


def run(job: Path, variant: str = "open") -> dict:
    root = job / ("flame_open_e2_20260927" if variant == "open"
                  else "flame_standard_e2_20260927")
    model = FlameOpen(24, 12, model_path=MODEL if variant == "open" else STANDARD_MODEL)
    indices = model.landmark_indices.numpy()
    groups = {name: np.isin(indices, list(members)) for name, members in PARTS.items()}
    groups["other_embedded_points"] = ~np.logical_or.reduce(list(groups.values()))
    train = dict(np.load(root / "private-fit-parameters.npz"))
    held = dict(np.load(root / "private-held-local-parameters.npz"))
    reference_rotation = cv2.Rodrigues(train["joint_axis_angles"][TRAIN.index(12), 0]
                                       .astype(np.float64))[0]
    reference_forward = reference_rotation[:, 2]
    reference_yaw = float(np.degrees(np.arctan2(reference_forward[0],
                                               reference_forward[2])))
    manifest = json.loads((job / "frame_manifest.audit.json").read_text(encoding="utf-8"))
    regions = {row["name"]: row["faceRegion"] for row in manifest["frames"]}
    all_rows = []
    with np.load(job / "face_landmarks.npz") as source:
        for frames, params, role in ((TRAIN, train, "fit"), (HELD, held, "local_pose_held")):
            for i, frame in enumerate(frames):
                shape = torch.from_numpy(params["shared_shape"])
                expression = torch.from_numpy(params["expressions"][i:i + 1])
                pose = torch.from_numpy(params["joint_axis_angles"][i:i + 1])
                with torch.no_grad():
                    _, points = model(shape, expression, pose)
                xyz = points[0].numpy() + params["camera_translations"][i]
                uv = xyz[:, :2] / xyz[:, 2, None] * 1181.055 + [540., 960.]
                observed = source[filename(frame)][indices]
                residual = np.linalg.norm(uv - observed, axis=1)
                rotation = cv2.Rodrigues(pose[0, 0].numpy().astype(np.float64))[0]
                forward = rotation[:, 2]
                yaw = float(np.degrees(np.arctan2(forward[0], forward[2])))
                relative_yaw = (yaw - reference_yaw + 180) % 360 - 180
                part = {}
                for name, selection in groups.items():
                    errors = residual[selection]
                    part[name] = {"points": int(len(errors)),
                                  "medianPx": round(float(np.median(errors)), 3) if len(errors) else None,
                                  "p90Px": round(float(np.percentile(errors, 90)), 3) if len(errors) else None}
                all_rows.append({"frame": frame, "role": role,
                                 "yawDiagnosticDegrees": round(yaw, 2),
                                 "yawRelativeToFrame12Degrees": round(relative_yaw, 2),
                                 "visiblePointCount": int(len(residual)),
                                 "faceRegionWidthPx": int(regions[filename(frame)][2]),
                                 "parts": part})
    report = {"modelSha256": model.model_sha256,
              "note": "All residuals are correlated MediaPipe labels; held pose uses 84 of 105 labels. No oval landmarks exist in the supplied embedding. Yaw is a pose diagnostic, not independent truth.",
              "counts": {name: int(selection.sum()) for name, selection in groups.items()},
              "frames": all_rows}
    (root / "private-region-errors.audit.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"variant": variant, "counts": report["counts"],
                      "held": [row for row in all_rows if row["role"] == "local_pose_held"]},
                     indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    args = parser.parse_args()
    run(args.job, args.variant)
