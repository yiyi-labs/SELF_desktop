"""Derive a face-centred opening camera from registered source views.

The Gaussian PLY is kept in COLMAP world coordinates.  The viewer receives
an explicit source camera so it never guesses from background-heavy bounds.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def derive(path: Path) -> dict:
    import numpy as np
    import pycolmap

    model = pycolmap.Reconstruction(path / "sparse" / "0")
    faces = json.loads((path / "face_regions.json").read_text(encoding="utf-8"))
    candidates = []
    for image in model.images.values():
        if not image.has_pose or image.name not in faces:
            continue
        x, y, w, h = faces[image.name]
        camera = model.cameras[image.camera_id]
        visible = []
        for point in image.points2D:
            if point.has_point3D() and x <= point.xy[0] <= x + w and y <= point.xy[1] <= y + h:
                visible.append(model.points3D[point.point3D_id].xyz)
        if len(visible) < 30:
            continue
        points = np.asarray(visible, dtype=np.float64)
        center = np.median(points, axis=0)
        distances = np.linalg.norm(points - center, axis=1)
        spread = np.median(distances)
        retained = points[distances < max(spread * 3.5, 1e-5)]
        if len(retained) >= 30:
            center = np.median(retained, axis=0)
        world_from_camera = np.linalg.inv(np.asarray(image.cam_from_world().matrix(), dtype=np.float64)[:3, :3])
        camera_center = -world_from_camera @ np.asarray(image.cam_from_world().matrix(), dtype=np.float64)[:3, 3]
        forward = world_from_camera[:, 2]
        depth = float(np.dot(center - camera_center, forward))
        if depth <= .01 or not np.isfinite(center).all():
            continue
        intrinsic = np.asarray(camera.calibration_matrix(), dtype=np.float64)
        source_fov = 2 * math.atan(camera.height / (2 * intrinsic[1, 1]))
        face_fraction = h / camera.height
        target_fraction = .5
        fov = 2 * math.atan(math.tan(source_fov / 2) * min(1.0, face_fraction / target_fraction))
        fov_degrees = min(70.0, max(12.0, math.degrees(fov)))
        # Prefer a substantial frontal face with enough triangulated observations.
        centrality = abs((x + w / 2) / camera.width - .5) + abs((y + h / 2) / camera.height - .5)
        score = min(len(visible), 500) / 1500 + min(face_fraction, .5) - centrality
        candidates.append((image.name, score, {
            "schemaVersion": 1,
            "sourceFrame": image.name,
            "target": [float(v) for v in center],
            "camera": [float(v) for v in camera_center],
            "up": [float(v) for v in -world_from_camera[:, 1]],
            "fovDegrees": round(fov_degrees, 3),
            "faceTrackCount": len(visible),
            "sourceFaceFraction": round(face_fraction, 4),
            "targetFaceFraction": target_fraction,
        }))
    if not candidates:
        raise RuntimeError("No registered frontal face camera can frame the Gaussian asset")
    # Capture guidance starts from a frontal view, then moves around the face.
    # Keep the opening camera within the first fifth of confirmed frames;
    # later views can have more tracks yet start at an unflattering side angle.
    early = sorted(candidates, key=lambda item: item[0])[:max(3, len(candidates) // 5)]
    return max(early, key=lambda item: item[1])[2]


def coverage(path: Path, view: dict) -> dict:
    """Use recovered *camera* positions, not estimated head yaw, as coverage proof."""
    import numpy as np
    import pycolmap

    model = pycolmap.Reconstruction(path / "sparse" / "0")
    target = np.asarray(view["target"], dtype=np.float64)
    front = np.asarray(view["camera"], dtype=np.float64) - target
    front /= np.linalg.norm(front)
    up = np.asarray(view["up"], dtype=np.float64)
    right = np.cross(up, front)
    right /= np.linalg.norm(right)
    angles = []
    for image in model.images.values():
        if not image.has_pose:
            continue
        transform = np.asarray(image.cam_from_world().matrix(), dtype=np.float64)
        camera = -transform[:3, :3].T @ transform[:3, 3]
        direction = camera - target
        distance = np.linalg.norm(direction)
        if distance < 1e-5 or not math.isfinite(distance):
            continue
        direction /= distance
        yaw = math.degrees(math.atan2(float(direction @ right), float(direction @ front)))
        if math.isfinite(yaw):
            angles.append(yaw)
    if not angles:
        raise RuntimeError("No usable registered camera poses")
    bins = {round(angle / 10) for angle in angles if abs(angle) <= 55}
    left = sum(angle <= -35 for angle in angles)
    right_count = sum(angle >= 35 for angle in angles)
    return {"registeredViews": len(angles), "minYawDegrees": round(min(angles), 1),
            "maxYawDegrees": round(max(angles), 1), "tenDegreeBins": len(bins),
            "leftViews": left, "rightViews": right_count,
            "broadSideCoverage": left >= 2 and right_count >= 2 and len(bins) >= 7}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: reconstruction_view.py JOB_DIR")
    path = Path(sys.argv[1])
    view = derive(path)
    (path / "portrait.view.json").write_text(json.dumps(view, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(view, separators=(",", ":")))
