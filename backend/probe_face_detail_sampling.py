"""Frozen model footprint versus real source detail at native pixel scale."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from flame_open_model import FlameOpen, MODEL
from probe_flame_hair_hull import local_observations
from probe_flame_open_fit import HELD, SOURCE_SHA256
from research_face_surface_refinement import (PARAMETERS, feature_mask, load_params,
                                              source_edge_l1)
from train_flame_local_appearance import TrainablePortrait, build_candidates, make_view


def run(job:Path,parameters:Path,frames:tuple[int,...],run_id:str)->dict:
    if hashlib.sha256((job/"capture.mp4").read_bytes()).hexdigest()!=SOURCE_SHA256:
        raise ValueError("source_changed")
    with np.load(parameters) as p:
        params={k:p[k] for k in p.files}
    if str(params["color_mode"])!="head-local-sh1":
        raise ValueError("corrected_baseline_required")
    root=job/"flame_open_e2_20260927"
    out=root/f"private-detail-sampling-{run_id}"
    if out.exists():
        raise FileExistsError(out)
    out.mkdir()
    device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
    geometry=FlameOpen(24,12,model_path=MODEL).to(device)
    candidate=build_candidates(job,geometry,device)
    model=TrainablePortrait(candidate,device,"head-local-sh1").to(device)
    load_params(model,params)
    fit=dict(np.load(root/"private-fit-parameters.npz"))
    held=dict(np.load(root/"private-held-local-parameters.npz"))
    Fs=local_observations(root)
    entries=[]
    with torch.no_grad():
        for frame in frames:
            view=make_view(job,geometry,fit,held,candidate,frame,Fs[frame],device)
            image,alpha,info=model.raster(view)
            idx=info["gaussian_ids"].cpu().numpy().astype(np.int64)
            radii=info["radii"].cpu().numpy().reshape(-1,2).max(axis=1)
            xy=info["means2d"].cpu().numpy().reshape(-1,2)
            regions={}
            for label in ("nose","lips"):
                x0,y0,x1,y1=view.feature_boxes[label]
                valid=(candidate["roles"][idx]==0)&(candidate["confidence"][idx]>=2)&(
                    xy[:,0]>=x0)&(xy[:,0]<x1)&(xy[:,1]>=y0)&(xy[:,1]<y1)&(radii>0)
                crop=view.rgb[y0:y1,x0:x1]
                rendered=image[y0:y1,x0:x1,:3]
                mask=feature_mask(view)[y0:y1,x0:x1]
                source_dx=(crop[:,1:]-crop[:,:-1]).abs().mean(2)
                render_dx=(rendered[:,1:]-rendered[:,:-1]).abs().mean(2)
                mx=mask[:,1:]&mask[:,:-1]
                source_edge=float((source_dx*mx).sum()/mx.sum().clamp_min(1))
                render_edge=float((render_dx*mx).sum()/mx.sum().clamp_min(1))
                regions[label]={"sourceSupportedProjectedSkinCount":int(valid.sum()),
                    "projectedRadiusPxP10P50P90":np.quantile(radii[valid],[.1,.5,.9]).tolist() if valid.any() else [],
                    "sourceHorizontalEdgeMean":source_edge,
                    "renderHorizontalEdgeMean":render_edge,
                    "renderToSourceEdgeRatio":render_edge/max(source_edge,1e-8),
                    "nativeSourceEdgeL1":float(source_edge_l1(rendered,crop,mask)),
                    "skinMaskPixels":int(mask.sum())}
            entries.append({"frame":frame,"role":"development" if frame in HELD else "train",
                "faceWidthPx":view.face_width_px,"cropXYXY":view.crop,"regions":regions})
    report={"status":"frozen_native_pixel_face_detail_sampling",
        "sourceSha256":SOURCE_SHA256,"parameterSha256":hashlib.sha256(parameters.read_bytes()).hexdigest(),
        "entries":entries,"limits":["Projected Gaussian radius is a raster footprint, not a measured skin feature size",
            "Source gradients include camera optics and compression; no invented fine texture",
            "Development images only evaluated, not used for this candidate training"]}
    (out/"audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("job",type=Path)
    p.add_argument("parameters",type=Path)
    p.add_argument("--frames",type=int,nargs="+",default=(35,75,145))
    p.add_argument("--run-id",required=True)
    a=p.parse_args()
    run(a.job,a.parameters,tuple(a.frames),a.run_id)
