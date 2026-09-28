"""Read-only partwise audit of the private, unreleased FLAME/GS optimizer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from flame_open_model import FlameOpen, MODEL, STANDARD_MODEL
from train_flame_local_appearance import build_candidates


def logistic(x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


def run(job: Path, optimized: Path, variant: str) -> dict:
    model = FlameOpen(24, 12, model_path=MODEL if variant == "open" else STANDARD_MODEL)
    candidate = build_candidates(job, model, torch.device("cpu"), 1., variant)
    with np.load(optimized / "private-optimized-parameters.npz") as saved:
        params = {key: saved[key] for key in saved.files}
    if (not np.array_equal(params["role"], candidate["roles"]) or
            not np.array_equal(params["source_index"], candidate["source_index"])):
        raise ValueError("partwise_audit_candidate_changed")
    output = {}
    for role_id, label in enumerate(("skin", "detail_near_flame", "hair_local_hull")):
        mask = params["role"] == role_id
        bound = (.006, .012, .018)[role_id]
        offset = np.tanh(params["local_offsets"][mask]) * bound
        displacement = np.linalg.norm(offset, axis=1) if role_id == 2 else np.abs(offset[:, 0])
        scale = np.exp(params["log_scales"][mask]).clip(.00045, .018)
        old_scale = candidate["initial_scale"][mask]
        opacity = logistic(params["opacity_logits"][mask])
        old_opacity = (.76, .67, .55)[role_id]
        old_rgb = candidate["initial_rgb"][mask]
        new_rgb = logistic(params["base_rgb_logits"][mask])
        output[label] = {
            "count": int(mask.sum()),
            "sourceColorSupportMedian": float(np.median(candidate["confidence"][mask])),
            "physicalOffsetMmMean": float(displacement.mean()*1000),
            "physicalOffsetMmP90": float(np.quantile(displacement, .9)*1000),
            "configuredPerAxisOffsetBoundMm": bound*1000,
            "scaleMeanOverInitial": float((scale/old_scale).mean()),
            "scaleMedianMeters": float(np.median(scale)),
            "opacityMeanInitial": old_opacity,
            "opacityMeanAfter": float(opacity.mean()),
            "baseColorAbsoluteMeanChange": float(np.abs(new_rgb-old_rgb).mean()),
            "directionTermAbsMean": float(np.abs(params["sh1"][mask]).mean())
        }
    report = {"status": "isolated_trained_part_parameters_not_publishable",
              "optimized": str(optimized), "modelVariant": variant, "parts": output}
    (optimized / "part-parameters.audit.json").write_text(json.dumps(report, indent=2),
                                                             encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("optimized", type=Path)
    parser.add_argument("--variant", choices=("open", "standard"), default="open")
    args = parser.parse_args()
    run(args.job, args.optimized, args.variant)
