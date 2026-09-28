"""Correct only inconsistent hair color using original, visible training pixels.

No color is generated or borrowed from skin/background. Geometry, alpha,
scale, and all non-hair points remain byte-equivalent in the parameter set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from appearance_direction_contract import C0, camera_to_point_in_head, sh1_basis, sh1_rgb
from probe_flame_hair_hull import local_observations, pixels
from probe_flame_open_fit import SOURCE_SHA256, TRAIN, filename
from train_flame_local_appearance import build_candidates
from flame_open_model import FlameOpen, MODEL


def run(job: Path, parameters: Path, run_id: str) -> dict:
    if not run_id.replace("-", "").isalnum():
        raise ValueError("invalid_isolated_run")
    if hashlib.sha256((job/"capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    root = job/"flame_open_e2_20260927"
    out = root/f"private-observed-hair-color-{run_id}"
    if out.exists():
        raise FileExistsError(out)
    out.mkdir()
    with np.load(parameters) as data:
        params = {key:data[key].copy() for key in data.files}
    if str(params["color_mode"]) != "head-local-sh1":
        raise ValueError("expected_head_local_sh1")
    model = FlameOpen(24,12,model_path=MODEL)
    candidate = build_candidates(job,model,__import__("torch").device("cpu"))
    points = candidate["hair_points"]
    start = candidate["surface_count"]
    if not np.array_equal(points,params["hair_local_points"]):
        raise ValueError("hair_binding_mismatch")
    Fs = local_observations(root)
    observations: list[list[tuple[np.ndarray,np.ndarray]]] = [[] for _ in points]
    for frame in TRAIN:
        img = cv2.imread(str(job/"frames"/filename(frame)),cv2.IMREAD_COLOR)
        mask = cv2.imread(str(job/"portrait_components_20260927"/
                             f"hair-{filename(frame)}"),cv2.IMREAD_GRAYSCALE)
        if img is None or mask is None:
            raise FileNotFoundError(frame)
        x,y,z = pixels(points,Fs[frame])
        inside = (z>.03)&(x>=0)&(x<img.shape[1])&(y>=0)&(y<img.shape[0])
        xi,yi = x.clip(0,img.shape[1]-1),y.clip(0,img.shape[0]-1)
        half_depth = np.full((img.shape[0]//2,img.shape[1]//2),np.inf,np.float32)
        np.minimum.at(half_depth,(yi[inside]//2,xi[inside]//2),z[inside])
        visible = z <= half_depth[yi//2,xi//2]+.0035
        good = inside&visible&(mask[yi,xi]>127)
        cam = points@Fs[frame][:3,:3].T+Fs[frame][:3,3]
        local_ray = camera_to_point_in_head(cam,Fs[frame][:3,:3])
        rgb = cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
        for index in np.flatnonzero(good):
            observations[index].append((local_ray[index],rgb[yi[index],xi[index]]/255.))
    coeff = params["sh_coeff"].copy()
    original = coeff.copy()
    evaluated = 0
    changed = []
    before_error,after_error = [],[]
    for index,items in enumerate(observations):
        if len(items)<3:
            continue
        directions=np.stack([v[0] for v in items]).astype(np.float32)
        colors=np.stack([v[1] for v in items]).astype(np.float32)
        median=np.median(colors,axis=0)
        color_mad=np.median(np.abs(colors-median),axis=0).mean()
        # Only repair a demonstrable first-source disagreement; all values
        # below are measured from source hair pixels in distinct TRAIN views.
        if color_mad>.10 or np.abs(candidate["initial_rgb"][start+index]-median).mean()<.16:
            continue
        evaluated+=1
        B=sh1_basis(directions)
        ridge=np.diag([.0005,.08,.08,.08]).astype(np.float32)
        fitted=np.linalg.solve(B.T@B+ridge,B.T@(colors-.5)).astype(np.float32)
        old=sh1_rgb(directions,coeff[start+index])
        new=sh1_rgb(directions,fitted)
        old_error=float(np.abs(old-colors).mean())
        new_error=float(np.abs(new-colors).mean())
        if new_error>=old_error-.006:
            continue
        # The fitted result must itself remain within the observed color
        # envelope on training rays; unobserved directions remain unaudited.
        if np.max(new) > np.max(colors)+.12:
            continue
        coeff[start+index]=fitted
        changed.append(index)
        before_error.append(old_error)
        after_error.append(new_error)
    params["sh_coeff"]=coeff
    params["research_color_source"]=np.asarray("visible_training_hair_pixels_only")
    param_path=out/"private-observed-hair-color-parameters.npz"
    np.savez_compressed(param_path,**params)
    report={"status":"isolated_observed_hair_color_correction_not_geometry",
            "sourceSha256":SOURCE_SHA256,
            "baselineParameterSha256":hashlib.sha256(parameters.read_bytes()).hexdigest(),
            "parameterSha256":hashlib.sha256(param_path.read_bytes()).hexdigest(),
            "hairPoints":len(points),"visibleTrainingDisagreementCandidates":evaluated,
            "changedHairPoints":len(changed),"changedHairPointIndices":changed,
            "observedTrainingRgbL1BeforeAfter": [float(np.mean(before_error)),float(np.mean(after_error))] if changed else [],
            "geometryAlphaAndScaleUnchanged":True,
            "heldColorExcluded":True,
            "limits":["This only corrects source-inconsistent colors, not a false hair hull",
                      "The same frozen PLY must be orbited and checked before acceptance",
                      "No tablet transfer or publication"]}
    (out/"audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("status","visibleTrainingDisagreementCandidates",
                        "changedHairPoints","observedTrainingRgbL1BeforeAfter",
                        "parameterSha256")},indent=2))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("job",type=Path)
    parser.add_argument("parameters",type=Path)
    parser.add_argument("--run-id",required=True)
    args=parser.parse_args()
    run(args.job,args.parameters,args.run_id)
