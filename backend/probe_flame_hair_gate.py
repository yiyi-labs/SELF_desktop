"""Audit real hair coverage separately from the FLAME skin appearance sample.

The FLAME surface is not a hair model. A covered pixel can still be a bald
scalp or a skin-colored splat; coverage is only an upper bound on hair recall.
All input and output images remain in the ignored private research directory.
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

from flame_open_model import FlameOpen, MODEL, STANDARD_MODEL
from probe_flame_open_fit import HELD, SOURCE_SHA256, TRAIN, filename
from probe_flame_real_appearance import bound_points, frame_mesh, render


AUDIT_FRAMES = (25, 80, 136, 35, 75, 145)
WIDTH, HEIGHT = 540, 960


def coverage_metrics(hair: np.ndarray, portrait: np.ndarray,
                     alpha: np.ndarray, threshold: float = .2) -> dict:
    if hair.shape != portrait.shape or alpha.shape != portrait.shape:
        raise ValueError("hair_gate_dimension_mismatch")
    if hair.dtype != np.bool_ or portrait.dtype != np.bool_:
        raise ValueError("hair_gate_masks_must_be_boolean")
    observed = hair & portrait
    count = int(observed.sum())
    if count < 100:
        raise ValueError("hair_gate_no_observed_hair")
    covered = alpha >= threshold
    # This is an optimistic silhouette score, not reconstructed hair. FLAME
    # has no hair geometry and can cover true hair with wrongly colored scalp.
    return {
        "observedHairPixels": count,
        "outsideHeadAppearancePixels": int((observed & ~covered).sum()),
        "outsideHeadAppearanceFraction": round(float((observed & ~covered).sum() / count), 4),
        "alphaCoverageUpperBoundFraction": round(float((observed & covered).sum() / count), 4),
        "isActualHairGeometryPresent": False,
    }


def run(job: Path, variant: str = "open", count: int = 20000) -> dict:
    start = time.perf_counter()
    if variant not in ("open", "standard"):
        raise ValueError("unsupported_variant")
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    root = job / ("flame_open_e2_20260927" if variant == "open"
                  else "flame_standard_e2_20260927")
    sample = root / f"private-real-appearance-semantic_skin-{count}"
    with np.load(sample / "private-bound-splats.npz") as splats:
        face_ids = splats["face_ids"]
        barycentric = splats["barycentric"]
        colors = splats["rgb_from_source"]
        opacity = splats["opacity"]
        scale = splats["scale"]
    train = dict(np.load(root / "private-fit-parameters.npz"))
    held = dict(np.load(root / "private-held-local-parameters.npz"))
    if tuple(train["train_frame_indices"]) != TRAIN or tuple(held["held_frame_indices"]) != HELD:
        raise ValueError("hair_gate_split_changed")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = FlameOpen(24, 12, model_path=MODEL if variant == "open" else STANDARD_MODEL).to(device)
    faces = model.faces.cpu().numpy()
    out = root / f"private-hair-gate-{count}"
    out.mkdir(exist_ok=True)
    rows = []
    for frame in AUDIT_FRAMES:
        role = "training" if frame in TRAIN else "color_held_out"
        name = filename(frame)
        parameters = train if role == "training" else held
        mesh = frame_mesh(model, parameters, frame, device, held=role == "color_held_out")
        points, _ = bound_points(mesh, faces, face_ids, barycentric)
        _, alpha = render(points, colors, opacity, scale, device)
        source = cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR)
        hair_mask = cv2.imread(str(job / "portrait_components_20260927" / f"hair-{name}"),
                               cv2.IMREAD_GRAYSCALE)
        portrait_mask = cv2.imread(str(job / "face_masks" / (name + ".png")),
                                   cv2.IMREAD_GRAYSCALE)
        if source is None or hair_mask is None or portrait_mask is None:
            raise ValueError(f"hair_gate_missing_input:{name}")
        hair = cv2.resize(hair_mask, (WIDTH, HEIGHT), interpolation=cv2.INTER_NEAREST) >= 127
        portrait = cv2.resize(portrait_mask, (WIDTH, HEIGHT),
                              interpolation=cv2.INTER_NEAREST) >= 127
        metrics = coverage_metrics(hair, portrait, alpha)
        # One private diagnostic: orange = observed hair without current GS
        # coverage. Blue = observed hair projected onto non-hair head surface.
        photo = cv2.resize(source, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA)
        marked = photo.copy()
        missing = hair & portrait & (alpha < .2)
        falsely_claimed = hair & portrait & (alpha >= .2)
        marked[missing] = (marked[missing] * .45 + np.array([0, 125, 255]) * .55).astype(np.uint8)
        marked[falsely_claimed] = (marked[falsely_claimed] * .62 +
                                   np.array([255, 85, 0]) * .38).astype(np.uint8)
        image_name = f"private-hair-{frame:04d}.jpg"
        cv2.imwrite(str(out / image_name), np.concatenate((photo, marked), axis=1),
                    [cv2.IMWRITE_JPEG_QUALITY, 93])
        rows.append({"frame": frame, "role": role, "diagnostic": image_name, **metrics})
    report = {
        "status": "hair_missing_from_current_3d_sample_release_gate_failed",
        "variant": variant, "sourceSha256": SOURCE_SHA256,
        "modelSha256": model.model_sha256,
        "sampleSplats": int(count), "frames": rows,
        "elapsedSeconds": round(time.perf_counter() - start, 2),
        "interpretation": [
            "The FLAME mesh has no source-specific hair, glasses or clothing geometry.",
            "Source-video 2D hair labels show what must be reconstructed; they do not provide depth.",
            "Alpha coverage is an optimistic silhouette upper bound, not evidence of realistic hair.",
            "A separate locally head-bound 3D hair/eyewear component needs cross-view geometry, source colors and held-view checks before full-scene release.",
        ],
    }
    (out / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "variant": variant,
                      "elapsedSeconds": report["elapsedSeconds"], "frames": rows}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    parser.add_argument("--count", type=int, default=20000)
    args = parser.parse_args()
    run(args.job, args.variant, args.count)
