"""Private E2 appearance sample: triangle-bound GS colored from the source video.

This is deliberately a head-only research sample, never a publishable portrait.
Held video frames contribute pose landmarks only; their pixels cannot color GS.
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
from gsplat.rendering import rasterization

from flame_open_model import FlameOpen, MODEL, STANDARD_MODEL
from probe_flame_open_fit import HELD, INTRINSIC, SOURCE_SHA256, TRAIN, filename


WIDTH, HEIGHT = 540, 960
FACE_OVAL = (10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361,
             288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149,
             150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103,
             67, 109)


def barycentric_samples(vertices: np.ndarray, faces: np.ndarray,
                        count: int, seed: int = 260927) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Area-weighted permanent face IDs and barycentric binding."""
    triangles = vertices[faces]
    areas = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                    triangles[:, 2] - triangles[:, 0]), axis=1) * .5
    if not np.isfinite(areas).all() or areas.sum() <= 0:
        raise ValueError("invalid_flame_surface")
    rng = np.random.default_rng(seed)
    face_ids = rng.choice(len(faces), size=count, p=areas / areas.sum()).astype(np.int32)
    u, v = rng.random(count), rng.random(count)
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    bary = np.stack((1 - u - v, u, v), axis=1).astype(np.float32)
    # A bounded screen-space splat footprint at the reference depth. No giant
    # ellipsoids to cover unseen surfaces; density is measured in the audit.
    spacing = np.float32(np.sqrt(areas.sum() / count) * .88)
    return face_ids, bary, np.full(count, spacing, np.float32)


def bound_points(vertices: np.ndarray, faces: np.ndarray,
                 face_ids: np.ndarray, bary: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    triangles = vertices[faces[face_ids]]
    points = (triangles * bary[..., None]).sum(axis=1)
    normal = np.cross(triangles[:, 1] - triangles[:, 0],
                      triangles[:, 2] - triangles[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-9)
    return points, normal


def project(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    depth = points[:, 2]
    xy = (points[:, :2] / np.maximum(depth[:, None], 1e-6)) * 1181.055
    xy += np.asarray([540., 960.])
    return xy, depth


def visible_source_colors(points: np.ndarray, normal: np.ndarray,
                          rgb: np.ndarray, mask: np.ndarray
                          ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xy, depth = project(points)
    x, y = np.rint(xy[:, 0]).astype(np.int32), np.rint(xy[:, 1]).astype(np.int32)
    inside = ((depth > .04) & (x >= 8) & (x < rgb.shape[1] - 8)
              & (y >= 8) & (y < rgb.shape[0] - 8))
    sx, sy = np.clip(x, 0, rgb.shape[1] - 1), np.clip(y, 0, rgb.shape[0] - 1)
    # Conservative point-depth visibility at half size. This does not assert
    # that eyeglasses, hair or facial microgeometry have been reconstructed.
    hx, hy = sx // 2, sy // 2
    depth_image = np.full((HEIGHT, WIDTH), np.inf, np.float32)
    np.minimum.at(depth_image, (hy[inside], hx[inside]), depth[inside])
    visible = inside & (depth <= depth_image[hy, hx] + .0035)
    clean_mask = cv2.erode(mask, np.ones((9, 9), np.uint8))
    visible &= clean_mask[sy, sx] > 127
    camera_direction = -points / np.maximum(np.linalg.norm(points, axis=1, keepdims=True), 1e-8)
    # FLAME faces have outward winding. Back-facing triangles must never take
    # a photo sample merely because their projection lands inside a 2D mask.
    alignment = (normal * camera_direction).sum(axis=1)
    visible &= alignment > .22
    return rgb[sy, sx].astype(np.float32) / 255, visible, alignment


def observed_face_interior(mask: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
    """Exclude hair/scalp and collar from skin-surface color supervision.

    The polygon is a conservative 2D label, not a 3D hair or glasses model.
    """
    if landmarks.shape != (468, 2):
        raise ValueError("unexpected_landmark_count")
    oval = np.zeros(mask.shape, np.uint8)
    cv2.fillPoly(oval, [np.rint(landmarks[list(FACE_OVAL)]).astype(np.int32)], 255)
    oval = cv2.erode(oval, np.ones((13, 13), np.uint8))
    return cv2.bitwise_and(mask, oval)


def frame_mesh(model: FlameOpen, parameters: dict, frame: int,
               device: torch.device, held: bool = False) -> np.ndarray:
    indices = HELD if held else TRAIN
    entry = indices.index(frame)
    shape = torch.from_numpy(parameters["shared_shape"]).to(device)
    expression = torch.from_numpy(parameters["expressions"][entry:entry + 1]).to(device)
    pose = torch.from_numpy(parameters["joint_axis_angles"][entry:entry + 1]).to(device)
    with torch.no_grad():
        vertices, _ = model(shape, expression, pose)
    return (vertices[0].cpu().numpy() + parameters["camera_translations"][entry]).astype(np.float32)


def render(points: np.ndarray, colors: np.ndarray, opacity: np.ndarray,
           scale: np.ndarray, device: torch.device) -> tuple[np.ndarray, np.ndarray]:
    count = len(points)
    K = INTRINSIC.copy().astype(np.float32)
    K[:2] *= .5
    K[2, 2] = 1
    with torch.no_grad():
        image, alpha, _ = rasterization(
            torch.from_numpy(points).to(device),
            torch.tensor([[1., 0., 0., 0.]], device=device).repeat(count, 1),
            torch.from_numpy(np.repeat(scale[:, None], 3, axis=1)).to(device),
            torch.from_numpy(opacity).to(device),
            torch.from_numpy(colors).to(device),
            torch.eye(4, device=device)[None], torch.from_numpy(K).to(device)[None],
            WIDTH, HEIGHT, packed=True, sh_degree=None, near_plane=.01)
    return image[0].cpu().numpy(), alpha[0, :, :, 0].cpu().numpy()


def run(job: Path, variant: str = "open", count: int = 40000,
        color_region: str = "face_interior") -> dict:
    start = time.perf_counter()
    if (variant not in ("open", "standard") or count < 5000 or count > 100000
            or color_region not in ("face_interior", "full_head", "semantic_skin")):
        raise ValueError("unsupported_variant_or_sample_count")
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    root = job / ("flame_open_e2_20260927" if variant == "open"
                  else "flame_standard_e2_20260927")
    out = root / f"private-real-appearance-{color_region}-{count}"
    out.mkdir(exist_ok=True)
    fit = dict(np.load(root / "private-fit-parameters.npz"))
    held = dict(np.load(root / "private-held-local-parameters.npz"))
    if tuple(fit["train_frame_indices"]) != TRAIN or tuple(held["held_frame_indices"]) != HELD:
        raise ValueError("training_holdout_split_changed")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        free_start, total_vram = torch.cuda.mem_get_info()
    model = FlameOpen(24, 12, model_path=MODEL if variant == "open" else STANDARD_MODEL).to(device)
    with torch.no_grad():
        shape = torch.from_numpy(fit["shared_shape"]).to(device)
        neutral, _ = model(shape, torch.zeros((1, 12), device=device),
                           torch.zeros((1, 5, 3), device=device))
    faces = model.faces.cpu().numpy()
    face_ids, bary, scale = barycentric_samples(neutral[0].cpu().numpy(), faces, count)
    observations = np.zeros((len(TRAIN), count, 3), np.float32)
    valid = np.zeros((len(TRAIN), count), bool)
    weights = np.zeros((len(TRAIN), count), np.float32)
    frame_use = []
    with np.load(job / "face_landmarks.npz") as landmark_file:
        for row, frame in enumerate(TRAIN):
            name = filename(frame)
            rgb_bgr = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
            mask = cv2.imread(str(job / "face_masks" / (name + ".png")), cv2.IMREAD_GRAYSCALE)
            if rgb_bgr is None or mask is None or rgb_bgr.shape[:2] != (1920, 1080):
                raise ValueError(f"missing_or_wrong_size_training_frame:{name}")
            mesh = frame_mesh(model, fit, frame, device)
            points, normal = bound_points(mesh, faces, face_ids, bary)
            rgb = cv2.cvtColor(rgb_bgr, cv2.COLOR_BGR2RGB)
            if color_region == "face_interior":
                skin = observed_face_interior(mask, landmark_file[name])
            elif color_region == "semantic_skin":
                component_root = job / "portrait_components_20260927"
                parts = cv2.imread(str(component_root / f"parts-{name}"), cv2.IMREAD_GRAYSCALE)
                hair = cv2.imread(str(component_root / f"hair-{name}"), cv2.IMREAD_GRAYSCALE)
                if parts is None or hair is None or parts.shape != mask.shape:
                    raise ValueError(f"missing_semantic_parts:{name}")
                skin = ((np.isin(parts, (2, 3)) & (hair < 127) & (mask > 127))
                        .astype(np.uint8) * 255)
            else:
                skin = mask
            observations[row], valid[row], weights[row] = visible_source_colors(points, normal, rgb, skin)
            frame_use.append({"frame": frame, "role": f"{color_region}_color_training_and_pose_fit",
                              "usableSamples": int(valid[row].sum())})
    support = valid.sum(axis=0)
    if int((support > 0).sum()) < count // 5:
        raise ValueError("real_color_support_insufficient")
    # Weighted best-observed color retains original detail without inventing
    # pigmentation. Unsupported geometry stays transparent, not generic skin.
    weights *= valid
    best = weights.argmax(axis=0)
    colors = observations[best, np.arange(count)]
    opacities = np.where(support > 0, .84, 0.).astype(np.float32)
    report_views = []
    for frame, role in ((25, "training"), (80, "training"), (136, "training"),
                        (35, "color_held_out"), (75, "color_held_out"),
                        (145, "color_held_out")):
        parameters = held if role == "color_held_out" else fit
        mesh = frame_mesh(model, parameters, frame, device, held=role == "color_held_out")
        points, _ = bound_points(mesh, faces, face_ids, bary)
        image, alpha = render(points, colors, opacities, scale, device)
        source = cv2.cvtColor(cv2.imread(str(job / "frames" / filename(frame))),
                              cv2.COLOR_BGR2RGB)
        source = cv2.resize(source, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA) / 255
        mask = cv2.imread(str(job / "face_masks" / (filename(frame) + ".png")),
                          cv2.IMREAD_GRAYSCALE)
        mask = cv2.resize(mask, (WIDTH, HEIGHT), interpolation=cv2.INTER_NEAREST) > 127
        scored = mask & (alpha > .2)
        rgb_l1 = float(np.abs(image[scored] / np.maximum(alpha[scored, None], .1)
                               - source[scored]).mean()) if scored.any() else None
        # Original image, shape-only surface coverage and actual source-color GS.
        gray = np.repeat(alpha[..., None], 3, axis=2) * .72
        display = np.concatenate((source, gray, np.clip(image + (1 - alpha[..., None]) * .08, 0, 1)), axis=1)
        output = out / f"private-{role}-{frame:04d}.jpg"
        cv2.imwrite(str(output), cv2.cvtColor(np.uint8(np.clip(display * 255, 0, 255)),
                                               cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 94])
        report_views.append({"frame": frame, "role": role, "comparison": output.name,
                             "faceMaskCoveredFraction": round(float((mask & (alpha > .2)).sum()
                                                                      / max(mask.sum(), 1)), 4),
                             "visiblePixelRgbL1": round(rgb_l1, 4) if rgb_l1 is not None else None})
    if device.type == "cuda":
        torch.cuda.synchronize()
        free_end, _ = torch.cuda.mem_get_info()
    np.savez_compressed(out / "private-bound-splats.npz", face_ids=face_ids, barycentric=bary,
                        rgb_from_source=colors, source_support_count=support,
                        opacity=opacities, scale=scale, model_sha256=np.asarray(model.model_sha256),
                        source_sha256=np.asarray(SOURCE_SHA256), train_frames=np.asarray(TRAIN))
    report = {"status": "isolated_head_appearance_sample_not_complete_scene",
              "variant": variant, "colorRegion": color_region,
              "sourceSha256": SOURCE_SHA256,
              "modelSha256": model.model_sha256, "splats": count,
              "boundTriangleCount": int(len(np.unique(face_ids))),
              "colorSupportedFraction": round(float((support > 0).mean()), 4),
              "trainFrames": frame_use,
              "heldFrames": [{"frame": frame, "role": "landmarks_for_local_pose_only;pixels_excluded_from_color"}
                             for frame in HELD],
              "views": report_views,
              "limits": [f"color supervision region: {color_region}; unsupported surface is transparent",
                         "FLAME surface excludes actual hair, glasses and clothing geometry",
                         "point-depth visibility is approximate; no attachment model",
                         "RGB L1 evaluates only covered pixels, not overall portrait quality"],
              "elapsedSeconds": round(time.perf_counter() - start, 2),
              "torchPeakReservedMiB": (round(torch.cuda.max_memory_reserved() / 1024 ** 2, 1)
                                       if device.type == "cuda" else None),
              "deviceTotalMiB": (round(total_vram / 1024 ** 2, 1) if device.type == "cuda" else None),
              "deviceFreeStartMiB": (round(free_start / 1024 ** 2, 1) if device.type == "cuda" else None),
              "deviceFreeEndMiB": (round(free_end / 1024 ** 2, 1) if device.type == "cuda" else None)}
    (out / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    parser.add_argument("--samples", type=int, default=40000)
    parser.add_argument("--color-region", choices=("face_interior", "full_head", "semantic_skin"),
                        default="face_interior")
    args = parser.parse_args()
    run(args.job, args.variant, args.samples, args.color_region)
