"""Bounded local scale-only ablation, without changing the model or source.

Tests whether excess nose/lip projected footprint contributes to detail loss.
Every full-head forward keeps hair, eyewear and the rest of the face present.
No global scale reduction or candidate export occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from flame_open_model import FlameOpen, MODEL
from probe_flame_hair_hull import local_observations
from probe_flame_open_fit import HELD, TRAIN
from research_face_surface_refinement import (load_params,region_indices,roi_metrics)
from train_flame_local_appearance import TrainablePortrait,build_candidates,make_view


def run(job:Path,parameters:Path,run_id:str)->dict:
    with np.load(parameters) as p:
        data={k:p[k] for k in p.files}
    source=hashlib.sha256((job/"capture.mp4").read_bytes()).hexdigest()
    if str(data["source_sha256"])!=source or str(data["color_mode"])!="head-local-sh1":
        raise ValueError("frozen_source_or_color_mismatch")
    root=job/"flame_open_e2_20260927"
    out=root/f"private-local-footprint-{run_id}"
    if out.exists():raise FileExistsError(out)
    out.mkdir()
    device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
    geometry=FlameOpen(24,12,model_path=MODEL).to(device)
    candidate=build_candidates(job,geometry,device)
    fit=dict(np.load(root/"private-fit-parameters.npz"))
    held=dict(np.load(root/"private-held-local-parameters.npz"))
    Fs=local_observations(root)
    views={i:make_view(job,geometry,fit,held,candidate,i,Fs[i],device) for i in TRAIN+HELD}
    votes=np.zeros(len(candidate["roles"]),np.uint16)
    for i in TRAIN:
        ids,_=region_indices(candidate,views[i])
        votes[ids]+=1
    selected=(votes>=2)&(candidate["roles"]==0)
    model=TrainablePortrait(candidate,device,"head-local-sh1").to(device)
    load_params(model,data)
    original=model.log_scales.detach().clone()
    audit=[]
    for factor in (1.,.85,.7,.55,.4):
        with torch.no_grad():
            model.log_scales.copy_(original)
            model.log_scales[selected]+=np.log(factor)
        rows={str(i):roi_metrics(model,views[i]) for i in HELD}
        audit.append({"selectedScaleFactor":factor,"development":rows,
            "meanLocalRgbL1":float(np.mean([r["noseLipFixedSkinRgbL1"] for r in rows.values()])),
            "meanLocalEdgeL1":float(np.mean([r["noseLipNativeEdgeL1"] for r in rows.values()])),
            "meanLocalAlphaCoverage":float(np.mean([r["noseLipAlphaCoverageAbove02"] for r in rows.values()])),
            "meanFullRoiRgbL1":float(np.mean([r["full"]["fixedRoiRgbL1IncludingMissing"] for r in rows.values()])),
            "meanFullRoiAlphaCoverage":float(np.mean([r["full"]["fixedRoiAlphaCoverage"] for r in rows.values()]))})
    report={"status":"local_surface_footprint_capacity_diagnostic_only",
        "sourceSha256":source,"parameterSha256":hashlib.sha256(parameters.read_bytes()).hexdigest(),
        "selectedSourceSupportedSkinPoints":int(selected.sum()),
        "selection":"face-skin nose/lips feature boxes in >=2 true training views",
        "options":audit,"limits":["No retraining, no fake sharpening, no global shrink",
            "A scale-only sweep may lose opacity coverage and does not prove 3D geometry correctness",
            "Development views are not independent final audit"]}
    (out/"audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"selectedPoints":int(selected.sum()),"options":[{k:v for k,v in x.items()
        if k!="development"} for x in audit]},indent=2))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("job",type=Path)
    p.add_argument("parameters",type=Path)
    p.add_argument("--run-id",required=True)
    a=p.parse_args()
    run(a.job,a.parameters,a.run_id)
