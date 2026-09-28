"""Same input pixels, complete scenes; parametric views != fixed PLY orbit."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import pycolmap
import torch

from reconstruction_components_v2 import load_prepared,camera_matrix,write_json
from reconstruction_joint_visibility import load_recorded_ply,render_shared,sha256_file
from reconstruction_shared_v2 import make_frame,draw,average,boxes,mesh_depth


def run(candidate,assets,parametric_baselines=()):
    data=load_prepared(candidate)
    data["reference"]=json.loads((candidate/"portrait.view.json").read_text())["sourceFrame"]
    faces=data["geometry"].faces.numpy()
    names=list(dict.fromkeys([data["reference"]]+data["development"]))
    data["depths"]={name:mesh_depth((data["local"][name]["mesh"],faces),data["local"][name]["F"],
        data["K"],data["rgb"][name].shape[1],data["rgb"][name].shape[0])*data["scale"] for name in names}
    params=torch.nn.ParameterDict({key:torch.nn.Parameter(torch.from_numpy(value).cuda()) for key,value in np.load(candidate/"trained_parameters.npz").items()})
    source=Path(data["source"]);old_model=pycolmap.Reconstruction(source/"sparse/0")
    old_worlds={im.name:camera_matrix(im) for im in old_model.images.values() if im.has_pose}
    with np.load(source/"face_camera_poses.npz") as old:
        old_faces={str(name):old["w2c"][i] for i,name in enumerate(old["names"])}
    groups={}
    for label,path in assets:
        view=json.loads((path.parent/"portrait.view.json").read_text())
        groups[label]=load_recorded_ply(path,view["editableSplats"])
    other_parameters={}
    for label,root in parametric_baselines:
        if sha256_file(root/"preparation.json")!=sha256_file(candidate/"preparation.json"):
            raise ValueError("parametric_baseline_observations_differ")
        other_parameters[label]=torch.nn.ParameterDict({key:torch.nn.Parameter(torch.from_numpy(value).cuda())
            for key,value in np.load(root/"trained_parameters.npz").items()})
    new_view=json.loads((candidate/"portrait.view.json").read_text())
    new_asset=load_recorded_ply(candidate/"portrait.gaussian.ply",new_view["editableSplats"])
    report={"sourceHash":data["sourceHash"],"candidateHash":sha256_file(candidate/"portrait.gaussian.ply"),
        "assets":{label:asset["ply_sha256"] for label,asset in groups.items()},"views":{},
        "parametricBaselines":{label:sha256_file(root/"portrait.gaussian.ply") for label,root in parametric_baselines},
        "comparisonMeaning":"whole-pipeline comparison in identical rectified source pixels; world gauges/pose methods differ",
        "roles":"all development/repeated scheme selection, not independent final audit",
        "fixedAssetMeaning":"one reference PLY audited separately, not replaced for source views"}
    out=candidate/"source-comparison";out.mkdir(exist_ok=True)
    with torch.no_grad():
        for name in names:
            boxes_here=boxes(data,name);all_results={}
            for feature,box in boxes_here.items():
                if box is None:continue
                frame=make_frame(data,name,box=box);h,w=frame["rgb"].shape[:2]
                truth=frame["rgb"].cpu().numpy();photos=[truth];results={}
                mask=frame["masks"]["face_core"]|frame["masks"]["face_boundary"]
                for label,asset in groups.items():
                    # Same rectification K/crop for all images. The stored
                    # estimate cameras are explicit, not invented alignment.
                    old=render_shared(asset,old_worlds[name],old_faces[name],
                        frame["K"].cpu().numpy(),w,h,antialiased=True)
                    rgb=old["rgb"].cpu().numpy();photos.append(rgb)
                    results[label]=metrics(rgb,truth,mask.cpu().numpy())
                for label,other in other_parameters.items():
                    rgb=draw(other,data,name,frame,True)["rgb"].cpu().numpy();photos.append(rgb)
                    results[label]=metrics(rgb,truth,mask.cpu().numpy())
                new=draw(params,data,name,frame,True);rgb=new["rgb"].cpu().numpy();photos.append(rgb)
                results["V2"]=metrics(rgb,truth,mask.cpu().numpy())
                montage=(np.concatenate(photos,axis=1)*255).round().clip(0,255).astype(np.uint8)
                cv2.imwrite(str(out/(name+"-"+feature+".jpg")),cv2.cvtColor(montage,cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,95])
                all_results[feature]=results
            report["views"][name]=all_results
        # Roundtrip in the exact reference camera and color convention. The
        # AA/classic difference is retained rather than hidden in a converter.
        name=data["reference"];frame=make_frame(data,name,box=boxes(data,name)["face"])
        train=draw(params,data,name,frame,True)["rgb"]
        h,w=frame["rgb"].shape[:2];C=data["worlds"][name];K=frame["K"].cpu().numpy()
        exported_aa=render_shared(new_asset,C,C,K,w,h,degree=1,antialiased=True)["rgb"]
        exported_classic=render_shared(new_asset,C,C,K,w,h,degree=1,antialiased=False)["rgb"]
        delta=(exported_aa-train).abs()
        report["referencePlyRoundtrip"]={"meanRgbL1AA":float(delta.mean()),"maxRgbAA":float(delta.max()),
            "meanRgbL1ClassicVsTraining":float((exported_classic-train).abs().mean()),
            "camera":C.tolist(),"cropK":K.tolist(),"referenceFrame":name,
            "note":"Desktop gsplat roundtrip; actual PlayCanvas/Harmony comparison is separate"}
        cv2.imwrite(str(out/"private-reference-training-ply-aa-ply-classic.jpg"),cv2.cvtColor(
            (torch.cat((train,exported_aa,exported_classic),1).cpu().numpy()*255).round().clip(0,255).astype(np.uint8),cv2.COLOR_RGB2BGR))
    write_json(out/"audit.json",report)
    print(json.dumps({"candidateHash":report["candidateHash"],"roundtrip":report["referencePlyRoundtrip"],
        "face":{name:value["face"] for name,value in report["views"].items()}}),flush=True)


def metrics(rgb,truth,mask):
    error=np.abs(rgb-truth).mean(-1)
    valid=mask if mask.any() else np.ones(error.shape,bool)
    a=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);t=cv2.cvtColor(truth,cv2.COLOR_RGB2GRAY)
    edge=np.abs(np.diff(a,axis=1)-np.diff(t,axis=1))
    interior=valid[:,:-1]&valid[:,1:]
    return {"fixedRgbL1IncludingMissing":float(error[valid].mean()),
            "edgeL1":float(edge[interior].mean()) if interior.any() else None,
            "pixelCount":int(valid.sum())}


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("candidate",type=Path)
    parser.add_argument("--asset",action="append",required=True)
    parser.add_argument("--parametric-baseline",action="append",default=[])
    args=parser.parse_args();run(args.candidate,[(s.split('=',1)[0],Path(s.split('=',1)[1])) for s in args.asset],
        [(s.split('=',1)[0],Path(s.split('=',1)[1])) for s in args.parametric_baseline])
