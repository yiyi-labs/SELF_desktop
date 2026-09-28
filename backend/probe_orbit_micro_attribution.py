"""Small, frozen-asset orbit check for SH, edge light and sort approximations.

Uses one existing PLY and the existing PlayCanvas orbit camera contract.  This
is an offline diagnostic; it neither changes the viewer nor edits the asset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from scipy.spatial.transform import Rotation
from gsplat.rendering import rasterization

from probe_gs_contract import read_float_ply


def render(means, quats, scales, opacity, colors, w2c, K, width, height, degree):
    image, alpha, info = rasterization(
        means, quats, scales, opacity, colors, w2c[None], K[None],
        width, height, sh_degree=degree, packed=True, near_plane=.01)
    return image[0].detach().cpu().numpy(), alpha[0, :, :, 0].detach().cpu().numpy(), info


def run(export_dir: Path, parameters: Path, run_id: str) -> dict:
    ply = export_dir / "research-head-only.gaussian.ply"
    orbit = json.loads((export_dir / "continuous-orbit/audit.json").read_text())
    digest = hashlib.sha256(ply.read_bytes()).hexdigest()
    if digest != orbit["plySha256"]:
        raise ValueError("asset_hash_changed")
    data = read_float_ply(ply)
    with np.load(parameters) as p:
        role = p["role"].copy()
    if len(role) != len(data["x"]):
        raise ValueError("role_index_contract_failed")
    out = parameters.parent / f"private-orbit-micro-{run_id}"
    if out.exists():
        raise FileExistsError(out)
    out.mkdir()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    points = np.stack([data[k] for k in ("x", "y", "z")], axis=1)
    means = torch.from_numpy(points).to(device)
    quats = torch.from_numpy(np.stack([data[f"rot_{i}"] for i in range(4)], axis=1)).to(device)
    scales = torch.from_numpy(np.exp(np.stack([data[f"scale_{i}"] for i in range(3)], axis=1))).to(device)
    opacity = torch.from_numpy(1 / (1 + np.exp(-data["opacity"]))).to(device)
    dc = np.stack([data[f"f_dc_{i}"] for i in range(3)], axis=1)[:, None]
    rest = np.stack([data[f"f_rest_{i}"] for i in range(45)], axis=1).reshape(len(points), 3, 15).transpose(0, 2, 1)
    sh = torch.from_numpy(np.concatenate((dc, rest), axis=1).copy()).to(device)
    one_hot = torch.nn.functional.one_hot(torch.from_numpy(role.astype(np.int64)).to(device), 3).float()
    front = orbit["samples"][0]["gsView"]
    width, height = int(front["viewportWidth"]), int(front["viewportHeight"])
    focal = height / (2 * math.tan(math.radians(front["fovDegrees"]) / 2))
    K = torch.tensor([[focal, 0, width/2], [0, focal, height/2], [0, 0, 1]], device=device, dtype=torch.float32)
    target = np.asarray(front["target"], np.float32)
    distance = float(front["distance"])
    # The bad angle is observed around +60 viewer degrees.  Two-degree steps
    # are small enough to reveal abrupt sorting changes without retraining.
    frames = []
    for angle in (54, 56, 58, 60, 62, 64, 66):
        radians = math.radians(angle)
        position = target + np.asarray([distance*math.sin(radians), 0,
                                         -distance*math.cos(radians)], np.float32)
        # PlayCanvas snapshot stores [x,y,z,w], and the viewer front is the
        # 180-degree X quaternion [1,0,0,0], not an identity quaternion.
        # Reproduce its own orbit exactly before the renderer-axis conversion.
        rotation = Rotation.from_quat([math.cos(radians/2), 0,
                                       math.sin(radians/2), 0]).as_matrix() @ np.diag([1., -1., -1.])
        w2c_np = np.eye(4, dtype=np.float32)
        w2c_np[:3, :3] = rotation.T
        w2c_np[:3, 3] = -rotation.T @ position
        w2c = torch.from_numpy(w2c_np).to(device)
        full, alpha, info = render(means, quats, scales, opacity, sh,
                                   w2c, K, width, height, 3)
        dc_only, _, _ = render(means, quats, scales, opacity, sh[:, :1],
                                w2c, K, width, height, 0)
        semantic, _, _ = render(means, quats, scales, opacity, one_hot,
                                w2c, K, width, height, None)
        # Original failure is on screen-right upper hair.  The region is
        # fixed across all views, so differences cannot be chosen post hoc.
        region = np.s_[280:740, 470:720]
        frgb = full[region]
        drgb = dc_only[region]
        a = alpha[region]
        contributions = semantic[region].sum(axis=(0, 1))
        pix = a > .2
        clipped_full = np.clip(frgb/np.maximum(a[..., None], .005), 0, 1)
        clipped_dc = np.clip(drgb/np.maximum(a[..., None], .005), 0, 1)
        bright = (clipped_full.max(axis=2) > .9) & pix
        bright_dc = (clipped_dc.max(axis=2) > .9) & pix
        screen = np.uint8(np.clip(full/np.maximum(alpha[..., None], .005), 0, 1)*255)
        Image.fromarray(screen).save(out/f"private-yaw-{angle:02d}-full.png")
        dscreen = np.uint8(np.clip(dc_only/np.maximum(alpha[..., None], .005), 0, 1)*255)
        Image.fromarray(dscreen).save(out/f"private-yaw-{angle:02d}-dc.png")
        # Reuse gsplat's actual projection intermediates, including packed
        # splat IDs.  Footprints/depth ranges diagnose possible sort stress;
        # they do not prove the true per-pixel intersection order.
        ids = info.get("gaussian_ids")
        radii = info.get("radii")
        depths = info.get("depths")
        means2d = info.get("means2d")
        projection = {}
        if all(isinstance(x, torch.Tensor) for x in (ids, radii, depths, means2d)):
            ids_np = ids.detach().cpu().numpy().astype(np.int64).reshape(-1)
            # gsplat 1.5.3 returns projected ellipse radii [N,2] here.
            rr = radii.detach().cpu().numpy().reshape(-1, 2).max(axis=1)
            zz = depths.detach().cpu().numpy().reshape(-1)
            xy = means2d.detach().cpu().numpy().reshape(-1, 2)
            if len(ids_np) == len(rr):
                roi_hit = ((xy[:, 0]+rr >= 470) & (xy[:, 0]-rr < 720) &
                           (xy[:, 1]+rr >= 280) & (xy[:, 1]-rr < 740))
                sel = np.where(roi_hit & (rr > 0))[0]
                projection = {"count": int(len(sel)),
                    "radiusP50P90P99": np.quantile(rr[sel], [.5, .9, .99]).tolist() if len(sel) else [],
                    "depthP10P50P90": np.quantile(zz[sel], [.1, .5, .9]).tolist() if len(sel) else [],
                    "wideFootprintOver25Px": int((rr[sel] > 25).sum()),
                    "wideFootprintOver50Px": int((rr[sel] > 50).sum()),
                    "hairFractionOfWideOver25Px": float((role[ids_np[sel][rr[sel] > 25]] == 2).mean())
                    if (rr[sel] > 25).any() else None}
        frames.append({"viewerYawDeg": angle,
            "fixedRoiBrightPixelCountFullSh": int(bright.sum()),
            "fixedRoiBrightPixelCountDcOnly": int(bright_dc.sum()),
            "fixedRoiFullVsDcPremultipliedMae": float(np.abs(frgb-drgb).mean()),
            "fixedRoiAlphaMean": float(a.mean()),
            "fixedRoiRoleContributions": contributions.tolist(),
            "projection": projection})
    report = {"status": "frozen_same_ply_micro_orbit_attribution",
        "plySha256": digest,
        "parameterSha256": hashlib.sha256(parameters.read_bytes()).hexdigest(),
        "gsplatVersion": "1.5.3", "width": width, "height": height,
        "roiXYXY": [470, 280, 720, 740], "frames": frames,
        "limits": ["No renderer replacement; center-depth sorting may still explain discontinuity",
                   "DC-only changes color, not geometry or sorting",
                   "Brightness uses unpremultiplied pixels with alpha > 0.2; both full and DC use identical alpha",
                   "Projection radii are conservative support estimates, not an exact per-pixel sorted reference"]}
    (out/"audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("export_dir", type=Path)
    p.add_argument("parameters", type=Path)
    p.add_argument("--run-id", required=True)
    a = p.parse_args()
    run(a.export_dir, a.parameters, a.run_id)
