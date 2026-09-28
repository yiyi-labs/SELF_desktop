"""Same-Ply, same-camera gsplat/PlayCanvas image check for one private run."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath

import numpy as np
import torch
from PIL import Image
from scipy.spatial.transform import Rotation
from gsplat.rendering import rasterization

from probe_gs_contract import read_float_ply


def run(export_dir: Path) -> dict:
    ply_path = export_dir / "research-head-only.gaussian.ply"
    orbit_dir = export_dir / "continuous-orbit"
    orbit = json.loads((orbit_dir / "audit.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(ply_path.read_bytes()).hexdigest()
    if orbit["plySha256"] != digest:
        raise ValueError("fixed_orbit_asset_hash_changed")
    data = read_float_ply(ply_path)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    means = torch.from_numpy(np.stack([data[k] for k in ("x","y","z")], 1)).to(device)
    quats = torch.from_numpy(np.stack([data[f"rot_{i}"] for i in range(4)], 1)).to(device)
    scales = torch.from_numpy(np.exp(np.stack([data[f"scale_{i}"] for i in range(3)], 1))).to(device)
    alpha = torch.from_numpy(1/(1+np.exp(-data["opacity"]))).to(device)
    dc = np.stack([data[f"f_dc_{i}"] for i in range(3)], 1)[:, None]
    rest = np.stack([data[f"f_rest_{i}"] for i in range(45)], 1).reshape(len(means),3,15).transpose(0,2,1)
    sh = torch.from_numpy(np.concatenate((dc,rest), 1).copy()).to(device)
    checks = []
    for sample in orbit["samples"]:
        if sample["label"] not in ("front-start", "yaw-positive-about-60", "yaw-negative-about-60"):
            continue
        v = sample["gsView"]
        width, height = int(v["viewportWidth"]), int(v["viewportHeight"])
        camera_world = Rotation.from_quat(v["rotation"]).as_matrix() @ np.diag([1.,-1.,-1.])
        w2c = np.eye(4, dtype=np.float32)
        w2c[:3,:3] = camera_world.T
        w2c[:3,3] = -camera_world.T @ np.asarray(v["position"])
        fy = height/(2*math.tan(math.radians(v["fovDegrees"])/2))
        K = np.asarray([[fy,0,width/2],[0,fy,height/2],[0,0,1]], np.float32)
        rgb, opaque, _ = rasterization(means, quats, scales, alpha, sh,
            torch.from_numpy(w2c).to(device)[None], torch.from_numpy(K).to(device)[None],
            width, height, sh_degree=3, packed=True)
        expected = rgb[0].detach().cpu().numpy()
        expected_alpha = opaque[0,:,:,0].detach().cpu().numpy()
        observed = np.asarray(Image.open(orbit_dir / PureWindowsPath(sample["rawImage"]).name).convert("RGBA"),np.float32)/255
        observed_premul = observed[:,:,:3]*observed[:,:,3:4]
        mask = (expected_alpha>.1)|(observed[:,:,3]>.1)
        error = np.abs(observed_premul-expected)
        alpha_error = np.abs(observed[:,:,3]-expected_alpha)
        compare = np.concatenate((np.uint8(np.clip(observed[:,:,:3]*255,0,255)),
                                  np.uint8(np.clip(expected/np.maximum(expected_alpha[:,:,None],.001)*255,0,255))), 1)
        image_path = orbit_dir / f"private-{sample['label']}-playcanvas-vs-gsplat.png"
        Image.fromarray(compare,"RGB").save(image_path)
        checks.append({"label":sample["label"],"yawRadians":v["yaw"],
                       "foregroundPixels":int(mask.sum()),
                       "premultipliedRgbMaeForeground":float(error[mask].mean()),
                       "alphaMaeForeground":float(alpha_error[mask].mean()),
                       "comparison":str(image_path)})
    report = {"status":"research_same_ply_same_camera_cross_renderer",
              "plySha256":digest,"renderer":"gsplat 1.5.3 vs PlayCanvas 2.22.4 SwiftShader",
              "checks":checks,"limits":"Different rasterizers/color pipelines; diagnostic, not a final visual gate"}
    (orbit_dir/"cross-renderer.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("export_dir",type=Path)
    args = parser.parse_args()
    run(args.export_dir)
