"""Compare actual PlayCanvas canvas pixels with gsplat at captured cameras.

Both read the same synthetic PLY. Color differences are reported, not hidden
behind the prior parse/roundtrip result. This probe never reads a portrait.
"""

from __future__ import annotations

import json
import math
from pathlib import Path, PureWindowsPath

import numpy as np
import torch
from PIL import Image
from scipy.spatial.transform import Rotation
from gsplat.rendering import rasterization

from probe_gs_contract import read_float_ply


def run() -> dict:
    root = Path(__file__).resolve().parent / ".sources" / "gs-contract-probe"
    pc_root = root / "playcanvas"
    observed = json.loads((pc_root / "report.json").read_text(encoding="utf-8"))
    ply = read_float_ply(root / "anisotropic-occlusion.ply")
    device = "cuda"
    means = torch.from_numpy(np.stack([ply[key] for key in ("x", "y", "z")], axis=1)).to(device)
    quats = torch.from_numpy(np.stack([ply[f"rot_{i}"] for i in range(4)], axis=1)).to(device)
    scales = torch.from_numpy(np.exp(np.stack([ply[f"scale_{i}"] for i in range(3)], axis=1))).to(device)
    opacities = torch.from_numpy(1 / (1 + np.exp(-ply["opacity"]))).to(device)
    dc = np.stack([ply[f"f_dc_{i}"] for i in range(3)], axis=1)[:, None, :]
    higher = np.stack([ply[f"f_rest_{i}"] for i in range(45)], axis=1).reshape(4, 3, 15).transpose(0, 2, 1)
    sh = torch.from_numpy(np.concatenate((dc, higher), axis=1).copy()).to(device)
    checks = []
    for sample in observed["samples"]:
        view = sample["snapshot"]
        width = int(view["viewportWidth"])
        height = int(view["viewportHeight"])
        camera_world = Rotation.from_quat(view["rotation"]).as_matrix()
        # PlayCanvas local camera is right/up/back; OpenCV is right/down/forward.
        cv_camera_world = camera_world @ np.diag([1., -1., -1.])
        w2c = np.eye(4, dtype=np.float32)
        w2c[:3, :3] = cv_camera_world.T
        w2c[:3, 3] = -cv_camera_world.T @ np.asarray(view["position"])
        fy = height / (2 * math.tan(math.radians(view["fovDegrees"]) / 2))
        K = np.asarray([[fy, 0, width / 2], [0, fy, height / 2], [0, 0, 1]], dtype=np.float32)
        rgb, alpha, _ = rasterization(
            means, quats, scales, opacities, sh,
            torch.from_numpy(w2c).to(device)[None], torch.from_numpy(K).to(device)[None],
            width, height, sh_degree=3, packed=True)
        expected_rgb = rgb[0].detach().cpu().numpy()
        expected_alpha = alpha[0, :, :, 0].detach().cpu().numpy()
        source = np.asarray(Image.open(pc_root / PureWindowsPath(sample["rawImage"]).name).convert("RGBA"), dtype=np.float32) / 255
        actual_rgb, actual_alpha = source[..., :3], source[..., 3]
        foreground = (actual_alpha > .1) | (expected_alpha > .1)
        # Browser PNG stores straight alpha; gsplat RGB is premultiplied.
        color_difference = np.abs(actual_rgb * actual_alpha[..., None] - expected_rgb)
        alpha_difference = np.abs(actual_alpha - expected_alpha)
        image = np.clip(expected_rgb / np.maximum(expected_alpha[..., None], .001), 0, 1)
        rgba = np.dstack((image, expected_alpha))
        ref_path = pc_root / (sample["label"] + "-gsplat.png")
        Image.fromarray(np.uint8(np.clip(rgba * 255, 0, 255)), "RGBA").save(ref_path)
        checks.append({"label": sample["label"], "referenceImage": str(ref_path),
                       "foregroundPixels": int(foreground.sum()),
                       "alphaMaeForeground": round(float(alpha_difference[foreground].mean()), 4),
                       "alphaP90Foreground": round(float(np.quantile(alpha_difference[foreground], .9)), 4),
                       "premultipliedRgbMaeForeground": round(float(color_difference[foreground].mean()), 4)})
    report = {"asset": str(root / "anisotropic-occlusion.ply"), "checks": checks,
              "note": "same PLY and captured camera; rasterizers have different compositing/color paths, so numbers are diagnostic rather than a production tolerance"}
    (pc_root / "cross_renderer.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    run()
