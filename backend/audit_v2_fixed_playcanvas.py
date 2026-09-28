"""Actual PlayCanvas canvas vs gsplat, exact frozen PLY and browser camera."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from scipy.spatial.transform import Rotation

from reconstruction_joint_visibility import load_recorded_ply,render_components,sha256_file
from reconstruction_components_v2 import write_json


def run(root):
    orbit=root/"continuous-orbit-small";report=json.loads((orbit/"audit.json").read_text())
    digest=sha256_file(root/"portrait.gaussian.ply")
    if digest!=report["plySha256"]:raise ValueError("fixed_orbit_asset_hash_changed")
    sidecar=dict(np.load(root/"portrait.components.npz"))
    if str(sidecar["asset_sha256"])!=digest:raise ValueError("fixed_component_asset_hash_changed")
    view=json.loads((root/"portrait.view.json").read_text())
    asset=load_recorded_ply(root/"portrait.gaussian.ply",view["editableSplats"])
    parts=torch.as_tensor(sidecar["component"],device="cuda")
    results=[]
    with torch.no_grad():
        for row in report["samples"]:
            png=orbit/("private-"+row["label"]+"-canvas.png")
            raw=cv2.imread(str(png),cv2.IMREAD_UNCHANGED)
            if raw is None or raw.shape[2]!=4:raise ValueError("browser_canvas_rgba_missing")
            h,w=raw.shape[:2];gs=row["gsView"]
            R=Rotation.from_quat(gs["rotation"]).as_matrix();C=np.eye(4)
            C[:3,:3]=np.diag([1.,-1.,-1.])@R.T;C[:3,3]=-C[:3,:3]@np.asarray(gs["position"])
            focal=h/(2*np.tan(np.deg2rad(gs["fovDegrees"])/2))
            K=np.array([[focal,0,w/2],[0,focal,h/2],[0,0,1]],np.float32)
            actual=cv2.cvtColor(raw[:,:,:3],cv2.COLOR_BGR2RGB).astype(np.float32)/255*(raw[:,:,3:]/255.)
            frame=render_components(asset["means"],asset["quats"],asset["scales"],asset["opacity"],asset["sh"],parts,
                torch.as_tensor(C,dtype=torch.float32,device="cuda"),torch.as_tensor(K,device="cuda"),w,h,degree=1)
            expected=frame["rgb"].cpu().numpy();q=frame["q"].cpu().numpy()
            difference=np.abs(actual-expected).mean(-1);face=q[:,:,1]>.5;room=q[:,:,0]>.5
            result={"label":row["label"],"camera":gs,"C":C.tolist(),"K":K.tolist(),
                "sourceFrame":view["sourceFrame"],"assetHash":digest,"canvasSha256":sha256_file(png),
                "wholeImageL1":float(difference.mean()),"visibleSkinL1":float(difference[face].mean()) if face.any() else None,
                "visibleRoomL1":float(difference[room].mean()) if room.any() else None}
            results.append(result)
            montage=np.concatenate((actual,expected,np.abs(actual-expected).clip(0,1)*3),axis=1)
            cv2.imwrite(str(orbit/("private-"+row["label"]+"-playcanvas-gsplat-difference.jpg")),
                cv2.cvtColor((montage*255).round().clip(0,255).astype(np.uint8),cv2.COLOR_RGB2BGR))
    write_json(orbit/"cross-renderer-audit.json",{"assetHash":digest,"browser":"Chrome SwiftShader PlayCanvas2.22.4",
        "samples":results,"limits":["Shared center-depth sorting approximation is not ruled out",
        "This is desktop graphics evidence, not Harmony quality/performance"]})
    print(json.dumps({"assetHash":digest,"samples":[{k:r[k] for k in ("label","wholeImageL1","visibleSkinL1")} for r in results]}),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("root",type=Path);run(parser.parse_args().root)
