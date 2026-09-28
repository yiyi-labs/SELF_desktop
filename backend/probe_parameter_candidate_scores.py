"""Compare frozen research parameters on the same development-held images."""

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
from train_flame_local_appearance import (TrainablePortrait, build_candidates,
                                          make_view, save_comparison, score)


def run(job: Path, baseline: Path, proposal: Path, out: Path) -> dict:
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    if hashlib.sha256((job/"capture.mp4").read_bytes()).hexdigest()!=SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    root=job/"flame_open_e2_20260927"
    device=torch.device("cuda")
    geometry=FlameOpen(24,12,model_path=MODEL).to(device)
    candidate=build_candidates(job,geometry,device)
    fit=dict(np.load(root/"private-fit-parameters.npz"))
    held=dict(np.load(root/"private-held-local-parameters.npz"))
    F=local_observations(root)
    views={i:make_view(job,geometry,fit,held,candidate,i,F[i],device) for i in HELD}
    models=[]
    for path in (baseline,proposal):
        with np.load(path) as data:
            params={key:data[key] for key in data.files}
        if not np.array_equal(params["hair_local_points"],candidate["hair_points"]):
            raise ValueError("candidate_binding_changed")
        model=TrainablePortrait(candidate,device,str(params["color_mode"])).to(device)
        with torch.no_grad():
            for name,p in model.named_parameters():
                p.copy_(torch.from_numpy(params[name]).to(device))
        models.append(model)
    baseline_images={}
    with torch.no_grad():
        for i in HELD:
            image,_,_=models[0].raster(views[i])
            baseline_images[i]=(image[:,:,:3].cpu().numpy()*255).round().clip(0,255).astype(np.uint8)
    save_comparison(out,"final",models[1],[views[i] for i in (35,75,145)],baseline_images)
    measured={name:{str(i):score(model,views[i]) for i in HELD}
              for name,model in zip(("baseline","proposal"),models)}
    report={"status":"same_geometry_held_image_candidate_comparison",
            "baselineParameterSha256":hashlib.sha256(baseline.read_bytes()).hexdigest(),
            "proposalParameterSha256":hashlib.sha256(proposal.read_bytes()).hexdigest(),
            "heldColorExcludedFromCandidateConstruction":True,
            "metrics":measured}
    (out/"audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    for key in ("fixedRoiRgbL1IncludingMissing","fixedHairRgbL1IncludingMissing",
                "hairMaskRecall","hairMaskPrecisionProxy"):
        print(key,*(round(np.mean([measured[version][str(i)][key] for i in HELD]),6)
                    for version in ("baseline","proposal")))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("job",type=Path)
    parser.add_argument("baseline",type=Path)
    parser.add_argument("proposal",type=Path)
    parser.add_argument("out",type=Path)
    args=parser.parse_args()
    run(args.job,args.baseline,args.proposal,args.out)
