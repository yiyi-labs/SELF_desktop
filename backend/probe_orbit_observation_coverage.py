"""Relate a fixed PLY orbit to actual fitted head-local source observations.

This audit deliberately separates 14 color-training views from eight pose-only
development views. A semantic mask hit plus splat depth is only a visibility
proxy, especially for the known-wrong hair hull.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
import cv2
from scipy.spatial.transform import Rotation

from export_flame_appearance_research import means_for_view
from flame_open_model import FlameOpen, MODEL
from probe_flame_hair_hull import local_observations
from probe_flame_open_fit import HELD, SOURCE_SHA256, TRAIN, filename
from train_flame_local_appearance import build_candidates, make_view


def normalize(value: np.ndarray) -> np.ndarray:
    return value/np.maximum(np.linalg.norm(value,axis=-1,keepdims=True),1e-9)


def projection_support(view, roles: np.ndarray, offsets: np.ndarray) -> np.ndarray:
    xyz=means_for_view(view,roles,offsets)
    K=view.K.cpu().numpy()
    z=xyz[:,2]
    x=np.rint(xyz[:,0]*K[0,0]/np.maximum(z,1e-8)+K[0,2]).astype(np.int32)
    y=np.rint(xyz[:,1]*K[1,1]/np.maximum(z,1e-8)+K[1,2]).astype(np.int32)
    h,w=view.rgb.shape[:2]
    valid=(z>.04)&(x>=0)&(x<w)&(y>=0)&(y<h)
    xi,yi=x.clip(0,w-1),y.clip(0,h-1)
    # Shared person visibility proxy; excluded color-held pixels never enter a
    # fit or candidate update. This cannot validate unknown hair back volume.
    depth=np.full(((h+1)//2,(w+1)//2),np.inf,np.float32)
    np.minimum.at(depth,(yi[valid]//2,xi[valid]//2),z[valid])
    front=z<=depth[yi//2,xi//2]+.005
    face=view.face_region.cpu().numpy()
    hair=view.hair.cpu().numpy()
    semantic=np.where(roles==2,hair[yi,xi],face[yi,xi])
    return valid&front&semantic


def run(job: Path, parameters: Path, export_dir: Path, run_id: str) -> dict:
    if hashlib.sha256((job/"capture.mp4").read_bytes()).hexdigest()!=SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    orbit=json.loads((export_dir/"continuous-orbit/audit.json").read_text(encoding="utf-8"))
    if orbit["plySha256"]!=hashlib.sha256((export_dir/"research-head-only.gaussian.ply").read_bytes()).hexdigest():
        raise ValueError("orbit_asset_changed")
    root=job/"flame_open_e2_20260927"
    out=root/f"private-orbit-observation-{run_id}"
    if out.exists():
        raise FileExistsError(out)
    out.mkdir()
    with np.load(parameters) as data:
        params={key:data[key] for key in data.files}
    device=torch.device("cpu")
    geometry=FlameOpen(24,12,model_path=MODEL)
    candidate=build_candidates(job,geometry,device)
    roles=params["role"]
    if not np.array_equal(roles,candidate["roles"]):
        raise ValueError("asset_binding_mismatch")
    fit=dict(np.load(root/"private-fit-parameters.npz"))
    held=dict(np.load(root/"private-held-local-parameters.npz"))
    Fs=local_observations(root)
    ref=make_view(job,geometry,fit,held,candidate,35,Fs[35],device)
    p_ref=means_for_view(ref,roles,params["local_offsets"])
    F_ref=Fs[35]
    local=(p_ref-F_ref[:3,3])@F_ref[:3,:3]
    face_center=np.median(local[roles==0],axis=0)
    ref_cam=-F_ref[:3,:3].T@F_ref[:3,3]
    ref_ray=normalize(ref_cam-face_center)
    with np.load(job/"face_landmarks.npz") as data:
        marks=data[filename(35)]
    proj=p_ref[:,:2]/np.maximum(p_ref[:,2:3],1e-8)*1181.055+np.array([540.,960.])
    nose_xy=marks[[1,2,4,5,98,327]].mean(axis=0)
    lips_xy=marks[[61,291,13,14,0,17]].mean(axis=0)
    group={
        "nose":(roles==0)&(np.linalg.norm(proj-nose_xy,axis=1)<38),
        "lips":(roles==0)&(np.linalg.norm(proj-lips_xy,axis=1)<32),
        "cheek_skin":(roles==0)&(np.abs(proj[:,0]-540)>45)&(np.abs(proj[:,0]-540)<145)&
            (proj[:,1]>nose_xy[1]-20)&(proj[:,1]<lips_xy[1]+30),
        "hair":roles==2,
        "detail_eyewear_proxy":roles==1,
    }
    directions=[]
    support=[]
    source_records=[]
    for frame in TRAIN+HELD:
        view=make_view(job,geometry,fit,held,candidate,frame,Fs[frame],device)
        camera=-Fs[frame][:3,:3].T@Fs[frame][:3,3]
        directions.append(normalize(camera-local))
        hit=projection_support(view,roles,params["local_offsets"])
        support.append(hit)
        gray=cv2.cvtColor(np.uint8(np.clip(view.rgb.cpu().numpy()*255,0,255)),cv2.COLOR_RGB2GRAY)
        lap=np.abs(cv2.Laplacian(gray,cv2.CV_32F))
        hairmask=view.hair.cpu().numpy()
        face=view.face_region.cpu().numpy()
        source_records.append({"frame":frame,"role":"train" if frame in TRAIN else "development_pose_only",
            "localCameraRayAngleFromReferenceDeg":float(np.degrees(np.arccos(np.clip(
                normalize(camera-face_center)@ref_ray,-1,1)))),
            "faceWidthPx":view.face_width_px,
            "faceMedianAbsoluteLaplacian":float(np.median(lap[face])) if face.any() else None,
            "hairMedianAbsoluteLaplacian":float(np.median(lap[hairmask])) if hairmask.any() else None,
            "regionProxySupportedPointFraction":{label:float(hit[mask].mean()) if mask.any() else None
                                                  for label,mask in group.items()}})
    directions=np.stack(directions)
    support=np.stack(support)
    samples=[]
    for sample in orbit["samples"]:
        v=sample["gsView"]
        camera_ref=np.asarray(v["position"],np.float64)
        camera_local=(camera_ref-F_ref[:3,3])@F_ref[:3,:3]
        ray=normalize(camera_local-face_center)
        target=normalize(camera_local-local)
        rotation=Rotation.from_quat(v["rotation"]).as_matrix()@np.diag([1.,-1.,-1.])
        target_camera=(p_ref-camera_ref)@rotation
        focal=v["viewportHeight"]/(2*np.tan(np.deg2rad(v["fovDegrees"])/2))
        skin_z=target_camera[roles==0,2]
        skin_x=target_camera[roles==0,0]/np.maximum(skin_z,1e-8)*focal+v["viewportWidth"]/2
        skin_projected_width=float(np.quantile(skin_x[skin_z>.04],.95)-
                                   np.quantile(skin_x[skin_z>.04],.05)) if (skin_z>.04).any() else None
        dots=np.einsum("vni,ni->vn",directions,target).clip(-1,1)
        angles=np.degrees(np.arccos(dots))
        region={}
        for label,mask in group.items():
            if not mask.any():
                region[label]={"points":0};continue
            entry={"points":int(mask.sum())}
            for role_name,sl in (("training",slice(0,len(TRAIN))),
                                 ("trainingAndDevelopment",slice(None))):
                usable=np.where(support[sl],angles[sl],np.inf)
                closest=np.min(usable[:,mask],axis=0)
                finite=np.isfinite(closest)
                entry[role_name]={"maskAndDepthProxyObservedFraction":float(finite.mean()),
                    "nearestAngleDegP50":float(np.median(closest[finite])) if finite.any() else None,
                    "within10DegFraction":float((closest<=10).mean()),
                    "within20DegFraction":float((closest<=20).mean())}
                medians=[]
                for frame_slot in range(*sl.indices(len(TRAIN+HELD))):
                    visible=support[frame_slot,mask]
                    medians.append(float(np.median(angles[frame_slot,mask][visible])) if visible.any() else np.inf)
                if medians and np.isfinite(medians).any():
                    local_slot=int(np.argmin(medians))
                    entry[role_name]["nearestMedianSourceFrame"]=(TRAIN+HELD)[
                        list(range(*sl.indices(len(TRAIN+HELD))))[local_slot]]
            region[label]=entry
        samples.append({"label":sample["label"],"viewerYawRadians":v["yaw"],
                        "headLocalRayAngleFromReferenceDeg":float(np.degrees(np.arccos(np.clip(ray@ref_ray,-1,1)))),
                        "headLocalCameraDistanceFromFaceCenter":float(np.linalg.norm(camera_local-face_center)),
                        "projectedSkinWidthPxP95MinusP5":skin_projected_width,
                        "viewerFovDegrees":v["fovDegrees"],"viewport":[v["viewportWidth"],v["viewportHeight"]],
                        "region":region})
    report={"status":"fixed_asset_orbit_vs_fitted_local_source_observation",
            "sourceSha256":SOURCE_SHA256,"assetSha256":orbit["plySha256"],
            "parameterSha256":hashlib.sha256(parameters.read_bytes()).hexdigest(),
            "referenceFrame":35,"trainingFrames":list(TRAIN),"developmentPoseOnlyFrames":list(HELD),
            "sourceViews":source_records,"samples":samples,"limits":["A projected semantic mask plus approximate splat depth is a visibility proxy, not measured surface truth",
                "Hair/eyewear geometry is presently wrong, so their support is an upper-bound proxy",
                "No source pixels from development views change the asset or select a candidate",
                "Viewer yaw is not the measured person-relative viewing angle"]}
    (out/"audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"status":report["status"],"assetSha256":report["assetSha256"],
        "samples":[{"label":row["label"],"viewerYawRadians":row["viewerYawRadians"],
                    "headLocalRayAngleFromReferenceDeg":row["headLocalRayAngleFromReferenceDeg"],
                    "regions":{name:data["training"] for name,data in row["region"].items() if "training" in data}}
                   for row in samples]},indent=2))
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("job",type=Path)
    parser.add_argument("parameters",type=Path)
    parser.add_argument("export_dir",type=Path)
    parser.add_argument("--run-id",required=True)
    a=parser.parse_args()
    run(a.job,a.parameters,a.export_dir,a.run_id)
