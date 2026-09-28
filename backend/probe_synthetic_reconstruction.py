"""Exercise the full trainer with a tiny, entirely synthetic head-like scene.

This verifies code paths and GPU memory, never portrait fidelity. Artifacts
go to backend/.sources (ignored), and no user capture is read.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch
from PIL import Image
from gsplat.rendering import rasterization

import reconstruction_train


def main() -> None:
    root = Path(__file__).resolve().parent / ".sources" / "synthetic-train-probe"
    frames = root / "frames"
    masks = root / "face_masks"
    frames.mkdir(parents=True, exist_ok=True)
    masks.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(11)
    # Dense pseudo-surface has source colors and camera-parallax, but is not a
    # human face; it only checks training and PLY export compatibility.
    theta = rng.uniform(0, 2 * np.pi, 1600)
    phi = rng.uniform(0, np.pi, 1600)
    points = np.column_stack((.46 * np.sin(phi) * np.cos(theta),
                              .61 * np.cos(phi),
                              2 + .34 * np.sin(phi) * np.sin(theta))).astype(np.float32)
    rgbs = np.column_stack((.55 + .17 * np.cos(theta),
                             .40 + .16 * np.sin(theta),
                             np.full(1600, .36))).clip(0, 1).astype(np.float32)
    device = "cuda"
    means = torch.from_numpy(points).to(device)
    quats = torch.tensor([[1., 0., 0., 0.]], device=device).repeat(len(points), 1)
    scales = torch.full((len(points), 3), .025, device=device)
    opacities = torch.full((len(points),), .8, device=device)
    colors = torch.from_numpy(rgbs).to(device)
    intrinsic = np.asarray([[70, 0, 32], [0, 70, 32], [0, 0, 1]], dtype=np.float32)
    cameras = []
    regions = {}
    with torch.no_grad():
        for index in range(20):
            name = f"frame_{index:04d}.png"
            pose = np.eye(4, dtype=np.float32)
            pose[0, 3] = .14 * np.sin(index * 2 * np.pi / 20)
            pose[1, 3] = .06 * np.cos(index * 2 * np.pi / 20)
            output, _, _ = rasterization(
                means, quats, scales, opacities, colors,
                torch.from_numpy(pose).to(device)[None],
                torch.from_numpy(intrinsic).to(device)[None],
                64, 64, packed=True)
            Image.fromarray((output[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)).save(frames / name)
            Image.fromarray(np.full((64, 64), 255, dtype=np.uint8)).save(masks / (name + ".png"))
            cameras.append((frames / name, pose, intrinsic, 64, 64))
            regions[name] = [0, 0, 64, 64]
    (root / "face_regions.json").write_text(json.dumps(regions), encoding="utf-8")
    (root / "job.json").write_text('{"state":"running","progress":62}', encoding="utf-8")
    with patch.object(reconstruction_train, "load_scene", return_value=(cameras, points, rgbs)):
        reconstruction_train.train(root, steps=3000)
    metric = json.loads((root / "training_metrics.json").read_text(encoding="utf-8"))
    print(json.dumps({key: metric[key] for key in
                      ("headPsnrDb", "worstHeadPsnrDb", "outsideHeadAlpha",
                       "gaussians", "exportSplats", "peakCudaMemoryMiB")}, separators=(",", ":")))


if __name__ == "__main__":
    main()
