"""Identify which frozen reference splat group causes side-view artifacts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from scipy.spatial.transform import Rotation
from gsplat.rendering import rasterization

from probe_gs_contract import read_float_ply


def run(export_dir: Path, parameters: Path) -> dict:
    data = read_float_ply(export_dir/"research-head-only.gaussian.ply")
    with np.load(parameters) as params:
        role = params["role"].copy()
    if len(role) != len(data["x"]):
        raise ValueError("semantic_and_ply_point_count_mismatch")
    orbit_dir = export_dir/"continuous-orbit"
    orbit = json.loads((orbit_dir/"audit.json").read_text(encoding="utf-8"))
    means = torch.from_numpy(np.stack([data[k] for k in ("x","y","z")],1)).cuda()
    quats = torch.from_numpy(np.stack([data[f"rot_{i}"] for i in range(4)],1)).cuda()
    scales = torch.from_numpy(np.exp(np.stack([data[f"scale_{i}"] for i in range(3)],1))).cuda()
    opacity = torch.from_numpy(1/(1+np.exp(-data["opacity"]))).cuda()
    features = torch.nn.functional.one_hot(torch.from_numpy(role.astype(np.int64)).cuda(),3).float()
    checks=[]
    for sample in orbit["samples"]:
        if sample["label"] not in ("front-start","yaw-positive-about-60","yaw-negative-about-60"):
            continue
        v=sample["gsView"]
        width,height=int(v["viewportWidth"]),int(v["viewportHeight"])
        cam=Rotation.from_quat(v["rotation"]).as_matrix()@np.diag([1.,-1.,-1.])
        w2c=np.eye(4,dtype=np.float32);w2c[:3,:3]=cam.T;w2c[:3,3]=-cam.T@np.asarray(v["position"])
        fy=height/(2*math.tan(math.radians(v["fovDegrees"])/2))
        K=np.asarray([[fy,0,width/2],[0,fy,height/2],[0,0,1]],np.float32)
        rgb,alpha,_=rasterization(means,quats,scales,opacity,features,
            torch.from_numpy(w2c).cuda()[None],torch.from_numpy(K).cuda()[None],
            width,height,packed=True)
        q=rgb[0].detach().cpu().numpy(); a=alpha[0,:,:,0].detach().cpu().numpy()
        vis=np.uint8(np.clip(q*255,0,255))
        image=orbit_dir/f"private-{sample['label']}-semantic-rgb.png"
        Image.fromarray(vis,"RGB").save(image)
        # Screen-right upper side tear, within the actual 720x1280 canvas.
        region=np.s_[280:740,470:720]
        contributions=q[region].sum(axis=(0,1))
        checks.append({"label":sample["label"],"semanticImage":str(image),
                       "rightSideRegionContributionsSkinDetailHair":contributions.tolist(),
                       "rightSideRegionShareSkinDetailHair":(contributions/np.maximum(contributions.sum(),1e-9)).tolist(),
                       "rightSideAlphaMean":float(a[region].mean())})
    report={"status":"single_asset_side_artifact_semantic_attribution",
            "checks":checks,"limits":"Screen ROI is a diagnostic selection; visual inspection still required"}
    (orbit_dir/"semantic-contribution.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("export_dir",type=Path)
    parser.add_argument("parameters",type=Path)
    args=parser.parse_args()
    run(args.export_dir,args.parameters)
