"""Bounded, private multi-view hair visual-hull experiment in local head space.

This is a geometric support probe, not a trained hairstyle or release asset.
Only training frames constrain occupancy and color; held frames audit the
projection. Ambiguous face/eyewear occlusion cannot carve a voxel. The masks
and fitted local poses are approximate, so failure is expected to be explicit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from scipy import ndimage

from flame_open_model import FlameOpen, MODEL, STANDARD_MODEL
from probe_flame_open_fit import HELD, INTRINSIC, SOURCE_SHA256, TRAIN, filename
from probe_flame_real_appearance import bound_points, frame_mesh, render


SAMPLE_FRAMES = (25, 80, 136, 35, 75, 145)
GRID_STEP = .006
WIDTH, HEIGHT = 540, 960


def to_camera(points: np.ndarray, local_to_camera: np.ndarray) -> np.ndarray:
    return points @ local_to_camera[:3, :3].T + local_to_camera[:3, 3]


def pixels(points: np.ndarray, local_to_camera: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    camera = to_camera(points, local_to_camera)
    depth = camera[:, 2]
    xy = camera[:, :2] / np.maximum(depth[:, None], 1e-8)
    xy[:, 0] = xy[:, 0] * INTRINSIC[0, 0] + INTRINSIC[0, 2]
    xy[:, 1] = xy[:, 1] * INTRINSIC[1, 1] + INTRINSIC[1, 2]
    return xy[:, 0].round().astype(np.int32), xy[:, 1].round().astype(np.int32), depth


def head_grid() -> tuple[np.ndarray, tuple[int, int, int]]:
    # This search box encloses the actual fitted FLAME skull plus observed
    # 2D hairstyle extent, without asserting that every voxel is real hair.
    x = np.arange(-.15, .151, GRID_STEP, dtype=np.float32)
    y = np.arange(-.015, .201, GRID_STEP, dtype=np.float32)
    z = np.arange(-.181, .121, GRID_STEP, dtype=np.float32)
    mesh = np.stack(np.meshgrid(x, y, z, indexing="ij"), axis=-1)
    return mesh.reshape(-1, 3), mesh.shape[:3]


def local_observations(root: Path) -> dict[int, np.ndarray]:
    data = json.loads((root / "private-observations.audit.json").read_text(encoding="utf-8"))
    if data["sourceSha256"] != SOURCE_SHA256 or data["headInWorldCount"] != 0:
        raise ValueError("unexpected_observation_contract")
    transforms = {}
    for row in data["records"]:
        if row["faceObservation"] is not None:
            transforms[int(Path(row["name"]).stem.rsplit("_", 1)[-1])] = np.asarray(
                row["faceObservation"]["localHeadToCameraF"], np.float32)
    if not set(TRAIN + HELD).issubset(transforms):
        raise ValueError("missing_local_hair_poses")
    return transforms


def classify_projection(points: np.ndarray, F: np.ndarray, hair: np.ndarray,
                        parts: np.ndarray, skin_depth: np.ndarray,
                        visible_positive_only: bool = False
                        ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x, y, depth = pixels(points, F)
    h, w = hair.shape
    inside = ((depth > .03) & (x >= 0) & (x < w) & (y >= 0) & (y < h))
    ix, iy = x.clip(0, w - 1), y.clip(0, h - 1)
    hair_support = cv2.dilate(hair, np.ones((9, 9), np.uint8)) > 127
    # A hair label is evidence of a *visible* front surface, not arbitrary
    # occupied volume behind the fitted face. Keep uncertain depth unknown.
    occluded_by_skin = depth > skin_depth[(iy // 2).clip(0, skin_depth.shape[0] - 1),
                                          (ix // 2).clip(0, skin_depth.shape[1] - 1)] + .005
    positive = inside & hair_support[iy, ix] & (
        ~occluded_by_skin if visible_positive_only else True)
    # Projecting onto face, glasses/others, clothing or a frame edge is not
    # evidence that a hair voxel behind that surface does not exist.
    hx, hy = (ix // 2).clip(0, skin_depth.shape[1] - 1), (iy // 2).clip(0, skin_depth.shape[0] - 1)
    in_front_of_skin = depth < skin_depth[hy, hx] - .005
    contradicted = inside & ~hair_support[iy, ix] & (
        (parts[iy, ix] == 0) |
        ((parts[iy, ix] == 3) & in_front_of_skin))
    unknown = inside & ~positive & ~contradicted
    return positive, contradicted, unknown


def skin_depth_map(mesh: np.ndarray, faces: np.ndarray, face_ids: np.ndarray,
                   barycentric: np.ndarray) -> np.ndarray:
    skin, _ = bound_points(mesh, faces, face_ids, barycentric)
    depth = skin[:, 2]
    x = np.rint((skin[:, 0] / np.maximum(depth, 1e-8) * INTRINSIC[0, 0] +
                 INTRINSIC[0, 2]) * .5).astype(np.int32)
    y = np.rint((skin[:, 1] / np.maximum(depth, 1e-8) * INTRINSIC[1, 1] +
                 INTRINSIC[1, 2]) * .5).astype(np.int32)
    valid = (depth > .03) & (x >= 0) & (x < WIDTH) & (y >= 0) & (y < HEIGHT)
    result = np.full((HEIGHT, WIDTH), np.inf, np.float32)
    np.minimum.at(result, (y[valid], x[valid]), depth[valid])
    return ndimage.minimum_filter(result, size=9)


def held_silhouette_metrics(projected: np.ndarray, observed: np.ndarray,
                            face: np.ndarray) -> dict:
    if projected.shape != observed.shape or observed.shape != face.shape:
        raise ValueError("hair_hull_mask_shape_mismatch")
    truth = observed & face
    guess = projected & face
    overlap = int((truth & guess).sum())
    return {
        "observedHairPixels": int(truth.sum()),
        "projectedHairPixels": int(guess.sum()),
        "hairRecall": round(overlap / max(int(truth.sum()), 1), 4),
        "hairPrecisionProxy": round(overlap / max(int(guess.sum()), 1), 4),
        "hairIoU": round(overlap / max(int((truth | guess).sum()), 1), 4),
    }


def run(job: Path, variant: str = "open", render_comparisons: bool = True,
        min_support: int = 3, max_contradictions: int = 1,
        fill_holes: bool = True, visible_positive_only: bool = False) -> dict:
    started = time.perf_counter()
    if variant not in ("open", "standard"):
        raise ValueError("unsupported_flame_variant")
    if not (2 <= min_support <= 10 and 0 <= max_contradictions <= 3):
        raise ValueError("unsupported_hair_occupancy_gate")
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    root = job / ("flame_open_e2_20260927" if variant == "open"
                  else "flame_standard_e2_20260927")
    suffix = ("" if (min_support, max_contradictions, fill_holes,
                      visible_positive_only) == (3, 1, True, False)
              else f"-s{min_support}-c{max_contradictions}-"
                   f"{'fill' if fill_holes else 'open'}"
                   f"{'-visible' if visible_positive_only else ''}")
    out = root / f"private-hair-hull-20260927{suffix}"
    out.mkdir(exist_ok=True)
    transforms = local_observations(root)
    points, shape = head_grid()
    with np.load(root / "private-real-appearance-semantic_skin-20000" /
                 "private-bound-splats.npz") as skin:
        skin_ids = skin["face_ids"]
        skin_bary = skin["barycentric"]
        skin_color = skin["rgb_from_source"]
        skin_opacity = skin["opacity"]
        skin_scale = skin["scale"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = FlameOpen(24, 12, model_path=MODEL if variant == "open"
                       else STANDARD_MODEL).to(device)
    faces = model.faces.cpu().numpy()
    train = dict(np.load(root / "private-fit-parameters.npz"))
    held = dict(np.load(root / "private-held-local-parameters.npz"))
    positive = np.zeros(len(points), np.uint8)
    contradicted = np.zeros(len(points), np.uint8)
    unknown_observations = 0
    for frame in TRAIN:
        name = filename(frame)
        hair = cv2.imread(str(job / "portrait_components_20260927" / f"hair-{name}"),
                          cv2.IMREAD_GRAYSCALE)
        parts = cv2.imread(str(job / "portrait_components_20260927" / f"parts-{name}"),
                           cv2.IMREAD_GRAYSCALE)
        if hair is None or parts is None:
            raise ValueError(f"missing_hair_observation:{name}")
        mesh = frame_mesh(model, train, frame, device)
        depth_map = skin_depth_map(mesh, faces, skin_ids, skin_bary)
        match, contradiction, unknown = classify_projection(
            points, transforms[frame], hair, parts, depth_map,
            visible_positive_only)
        positive += match.astype(np.uint8)
        contradicted += contradiction.astype(np.uint8)
        unknown_observations += int(unknown.sum())
    # Each retained cell has support in at least three distinct training
    # views and no more than one background contradiction. This is deliberately
    # conservative; the shell must still pass genuinely held projections.
    occupied = ((positive >= min_support) &
                (contradicted <= max_contradictions)).reshape(shape)
    occupied = ndimage.binary_opening(occupied, iterations=1)
    if fill_holes:
        occupied = ndimage.binary_fill_holes(occupied)
    shell = occupied & ~ndimage.binary_erosion(occupied, iterations=1)
    shell_points = points[shell.ravel()]
    if len(shell_points) < 100 or len(shell_points) > 60000:
        raise ValueError(f"unsupported_hair_hull_size:{len(shell_points)}")
    metrics = []
    for frame in SAMPLE_FRAMES:
        name = filename(frame)
        hair = cv2.imread(str(job / "portrait_components_20260927" / f"hair-{name}"),
                          cv2.IMREAD_GRAYSCALE)
        face = cv2.imread(str(job / "face_masks" / (name + ".png")),
                          cv2.IMREAD_GRAYSCALE)
        photo = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
        if hair is None or face is None or photo is None:
            raise ValueError(f"missing_hair_hull_audit:{name}")
        x, y, depth = pixels(shell_points, transforms[frame])
        projected = np.zeros(hair.shape, np.uint8)
        good = ((depth > .03) & (x >= 0) & (x < hair.shape[1]) &
                (y >= 0) & (y < hair.shape[0]))
        projected[y[good], x[good]] = 255
        projected = cv2.dilate(projected, np.ones((11, 11), np.uint8))
        observed = hair > 127
        face_mask = face > 127
        row = held_silhouette_metrics(projected > 127, observed, face_mask)
        row.update({"frame": frame, "role": "training" if frame in TRAIN else "held_out"})
        metrics.append(row)
        original = cv2.resize(photo, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
        indicator = original.copy()
        project_small = cv2.resize(projected, (WIDTH, HEIGHT), interpolation=cv2.INTER_NEAREST) > 0
        observed_small = cv2.resize(hair, (WIDTH, HEIGHT), interpolation=cv2.INTER_NEAREST) > 0
        missing = observed_small & ~project_small
        extra = project_small & ~observed_small
        indicator[missing] = (indicator[missing] * .45 +
                              np.array([0, 120, 250]) * .55).astype(np.uint8)
        indicator[extra] = (indicator[extra] * .45 +
                            np.array([250, 80, 30]) * .55).astype(np.uint8)
        cv2.imwrite(str(out / f"private-hull-audit-{frame:04d}.jpg"),
                    np.concatenate((original, indicator), axis=1),
                    [cv2.IMWRITE_JPEG_QUALITY, 93])

    # Multi-view dark hair color is sampled only from actual training pixels,
    # never from held images. It is intentionally not exported to the app.
    colors = np.zeros((len(shell_points), 3), np.float32)
    color_support = np.zeros(len(shell_points), np.uint8)
    for frame in TRAIN:
        name = filename(frame)
        photo = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
        hair = cv2.imread(str(job / "portrait_components_20260927" / f"hair-{name}"),
                          cv2.IMREAD_GRAYSCALE)
        x, y, depth = pixels(shell_points, transforms[frame])
        good = ((depth > .03) & (x >= 0) & (x < photo.shape[1]) &
                (y >= 0) & (y < photo.shape[0]))
        xi, yi = x.clip(0, photo.shape[1] - 1), y.clip(0, photo.shape[0] - 1)
        good &= hair[yi, xi] > 127
        first = good & (color_support == 0)
        colors[first] = cv2.cvtColor(photo, cv2.COLOR_BGR2RGB)[yi[first], xi[first]] / 255
        color_support[good] += 1
    if (color_support > 0).sum() < len(shell_points) // 2:
        raise ValueError("hair_shell_color_support_insufficient")
    colors[color_support == 0] = np.median(colors[color_support > 0], axis=0)
    if render_comparisons:
        for frame in SAMPLE_FRAMES:
            parameters = train if frame in TRAIN else held
            mesh = frame_mesh(model, parameters, frame, device, held=frame in HELD)
            head_points, _ = bound_points(mesh, faces, skin_ids, skin_bary)
            hair_points = to_camera(shell_points, transforms[frame])
            all_points = np.concatenate((head_points, hair_points.astype(np.float32)), axis=0)
            all_colors = np.concatenate((skin_color, colors), axis=0)
            all_opacity = np.concatenate((skin_opacity, np.full(len(shell_points), .78, np.float32)))
            all_scales = np.concatenate((skin_scale, np.full(len(shell_points), GRID_STEP * .8, np.float32)))
            image, alpha = render(all_points, all_colors, all_opacity, all_scales, device)
            source = cv2.resize(cv2.imread(str(job / "frames" / filename(frame))),
                                (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
            final = (np.clip(image + (1 - alpha[..., None]) * .08, 0, 1) * 255).astype(np.uint8)
            final = cv2.cvtColor(final, cv2.COLOR_RGB2BGR)
            cv2.imwrite(str(out / f"private-hull-render-{frame:04d}.jpg"),
                        np.concatenate((source, final), axis=1),
                        [cv2.IMWRITE_JPEG_QUALITY, 93])
    np.savez_compressed(out / "private-hair-shell.npz", local_points=shell_points,
                        observed_rgb=colors, source_support_count=color_support,
                        source_sha256=np.asarray(SOURCE_SHA256))
    held_iou = [row["hairIoU"] for row in metrics if row["role"] == "held_out"]
    held_precision = [row["hairPrecisionProxy"] for row in metrics
                      if row["role"] == "held_out"]
    # This experiment must be explicitly rejected when it grows into the
    # forehead or loses held-view silhouette agreement. A valid 3D file alone
    # is not a useful avatar and is never eligible for app transfer.
    acceptable = min(held_iou) >= .7 and min(held_precision) >= .8
    report = {
        "status": ("isolated_hair_geometry_research_only" if acceptable else
                   "hair_geometry_failed_held_view_gate_not_for_transfer"),
        "eligibleForAppTransfer": False,
        "sourceSha256": SOURCE_SHA256, "modelVariant": variant,
        "modelSha256": model.model_sha256,
        "renderComparisons": render_comparisons,
        "minPositiveTrainingViews": min_support,
        "maxContradictoryTrainingViews": max_contradictions,
        "fillHolesBeforeShell": fill_holes,
        "visiblePositiveOnly": visible_positive_only,
        "unknownProjectionObservations": unknown_observations,
        "gridStepMetersUnderUncalibratedLocalScale": GRID_STEP,
        "occupiedCells": int(occupied.sum()), "shellPoints": int(len(shell_points)),
        "heldHairIoUMean": round(float(np.mean(held_iou)), 4),
        "heldHairPrecisionProxyMean": round(float(np.mean(held_precision)), 4),
        "heldViewSilhouetteGatePassed": acceptable,
        "views": metrics,
        "elapsedSeconds": round(time.perf_counter() - started, 2),
        "limits": [
            "Local FLAME scale and camera poses are estimated, not independently calibrated.",
            "Visual hull from 2D masks cannot recover individual strands or hidden back hair.",
            "Held silhouettes audit geometry only; no held colors were sampled.",
            "Hair, skin, glasses, shoulders and room have not passed joint training or full-scene occlusion.",
        ],
    }
    (out / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    parser.add_argument("--skip-render-comparisons", action="store_true")
    parser.add_argument("--min-support", type=int, default=3)
    parser.add_argument("--max-contradictions", type=int, default=1)
    parser.add_argument("--no-fill-holes", action="store_true")
    parser.add_argument("--visible-positive-only", action="store_true")
    args = parser.parse_args()
    run(args.job, args.variant, not args.skip_render_comparisons,
        args.min_support, args.max_contradictions, not args.no_fill_holes,
        args.visible_positive_only)
