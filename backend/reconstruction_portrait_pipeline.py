"""Portrait-first reconstruction stages within the existing E2/E3/E5 rules.

This is a callable backend engine, not a publisher. It accepts a validated
observation preparation rather than hard-coded frame numbers or a video name.
Every full-scene forward uses one gsplat 1.5.3 sort and alpha compositing pass.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as functional
from gsplat import export_splats
from gsplat.rendering import rasterization

from reconstruction_components_v2 import load_prepared, write_json
from reconstruction_portrait_model import (LocalPortraitModel, GaussianState,
    CandidateTransaction, joined_state, evaluate_sh1)
from reconstruction_shared_v2 import initialize, boxes

ENGINE_VERSION = "portrait-first-soft-surface-0.1-research"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()


def draw(state, C, K, width, height, *, unit_scale=1., antialiased=False, absgrad=False):
    center = torch.linalg.inv(C)[:3, 3]
    rgb = evaluate_sh1(state.sh, state.means-center)
    groups = functional.one_hot(state.parts.long(), 5).to(rgb.dtype)
    depth = (state.means@C[:3, :3].T+C[:3, 3])[:, 2]
    features = torch.cat((rgb, groups, groups*depth[:, None]), dim=1)
    image, alpha, info = rasterization(state.means, state.quats, state.scales, state.opacity,
        features, C[None], K[None], width, height, packed=True, sh_degree=None,
        render_mode="RGB+D", rasterize_mode="antialiased" if antialiased else "classic",
        near_plane=.01*unit_scale, far_plane=1e10*unit_scale, absgrad=absgrad)
    return {"rgb": image[0, :, :, :3], "alpha": alpha[0, :, :, 0], "q": image[0, :, :, 3:8],
            "q_depth": image[0, :, :, 8:13]/unit_scale,
            "depth": image[0, :, :, -1]/unit_scale, "info": info}


def masked_mean(value, mask):
    return (value*mask).sum()/mask.sum().clamp_min(1)


def tensor(x, device="cuda"):
    return torch.as_tensor(np.ascontiguousarray(x), device=device, dtype=torch.float32)


def make_frame(data, name, *, crop=True, half=False, device="cuda"):
    rgb = data["rgb"][name]; labels = data["labels"][name]
    K = data["K"].copy(); h, w = rgb.shape[:2]; rectangle = (0, 0, w, h)
    full_size = (w, h); full_K = K.copy()
    if crop:
        observed = labels["face_core"] | labels["face_boundary"] | labels["hair_visible"] | labels["glasses_visible"]
        y, x = np.where(observed)
        if not len(x): raise ValueError(f"missing_head_observation:{name}")
        rectangle = (max(0, int(x.min())-24), max(0, int(y.min())-24), min(w, int(x.max())+25), min(h, int(y.max())+25))
        x0, y0, x1, y1 = rectangle
        rgb = rgb[y0:y1, x0:x1]; labels = {k:v[y0:y1, x0:x1] for k,v in labels.items()}
        K[0, 2] -= x0; K[1, 2] -= y0
    if half:
        h, w = rgb.shape[:2]; size = (w//2, h//2)
        rgb = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
        labels = {k:cv2.resize(v.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST)>0 for k,v in labels.items()}
        K[:2] *= .5
    return {"rgb": tensor(rgb, device), "masks": {k:tensor(v, device).bool() for k,v in labels.items()},
            "K": tensor(K, device), "F": tensor(data["local"][name]["F"], device),
            "C": tensor(data["worlds"][name], device) if name in data["worlds"] else None,
            "mesh": tensor(data["local"][name]["mesh"], device), "rectangle": rectangle,
            "name": name, "nativeScale": 2 if half else 1,
            "fullSize": full_size, "fullK": tensor(full_K, device)}


def head_loss(rendered, frame):
    masks = frame["masks"]
    face = masks["face_core"] | masks["face_boundary"] | masks["glasses_visible"]
    hair = masks["hair_visible"]
    error = (rendered["rgb"]-frame["rgb"]).abs().mean(-1)
    # Fixed observed regions count missing pixels. No black paint outside
    # masks and no neighbourhood loss across a fabricated black boundary.
    face_rgb = masked_mean(error, face)
    hair_rgb = masked_mean(error, hair)
    coverage = masked_mean((1-rendered["alpha"]).square(), face | hair)
    safe_empty = masks["room_visible"] & ~masks["unknown_or_occluded"]
    outside = masked_mean(rendered["alpha"].square(), safe_empty)
    value = 1.5*face_rgb+hair_rgb+.06*coverage+.03*outside
    return value, {"faceRgb": float(face_rgb.detach()), "hairRgb": float(hair_rgb.detach()),
                   "missingCoverage": float(coverage.detach()), "reliableEmpty": float(outside.detach())}


def metrics(rendered, frame):
    masks = frame["masks"]; err = (rendered["rgb"]-frame["rgb"]).abs().mean(-1)
    regions = {"face": masks["face_core"] | masks["face_boundary"] | masks["glasses_visible"],
               "hair": masks["hair_visible"], "glasses": masks["glasses_visible"],
               "room": masks["room_visible"], "neckCloth": masks["neck_cloth_visible"]}
    result = {}
    for name, mask in regions.items():
        result[name] = {"pixels": int(mask.sum()), "fixedRgbL1": float(masked_mean(err, mask)),
                        "hole": float(masked_mean((rendered["alpha"]<.8).float(), mask)),
                        "contribution": [float(masked_mean(rendered["q"][:, :, i], mask)) for i in range(5)]}
    result["conservation"] = float((rendered["q"].sum(-1)-rendered["alpha"]).abs().max())
    return result


class SceneAssembly(torch.nn.Module):
    """The same portrait instance, plus measured room and garment seeds.

    Garment geometry remains explicitly a reference/quasistatic hypothesis;
    this class does not silently claim the old translation blend solved body
    motion. No extra FLAME neck duplicate is appended over the retained head.
    """
    def __init__(self, portrait, environment, scale):
        super().__init__(); self.portrait = portrait; self.scale = scale
        self.environment = torch.nn.ParameterDict({k:torch.nn.Parameter(v.detach().clone())
            for k,v in environment.items() if k in ("means", "scales", "quats", "opacities", "sh")})
        self.register_buffer("environment_parts", environment["part"][:, 0].long())
        self.register_buffer("environment_initial_means", environment["means"].detach().clone())
        self.register_buffer("environment_initial_scales", environment["scales"].detach().clone())

    def environment_state(self):
        p = self.environment
        return GaussianState(p["means"], functional.normalize(p["quats"], dim=-1), p["scales"].exp(),
                             p["opacities"].sigmoid(), p["sh"], self.environment_parts)

    def render(self, frame, stage, *, antialiased=False, absgrad=False):
        state = self.portrait.local_state(frame["mesh"])
        h, w = frame["rgb"].shape[:2]
        if stage == "T0":
            return draw(state, frame["F"], frame["K"], w, h, antialiased=antialiased, absgrad=absgrad)
        if frame["C"] is None: raise ValueError("world_render_requires_real_world_observation")
        state = state.to_world(frame["C"], frame["F"], self.scale)
        if stage != "T1": state = joined_state(state, self.environment_state())
        return draw(state, frame["C"], frame["K"], w, h, unit_scale=self.scale,
                    antialiased=antialiased, absgrad=absgrad)


def initialize_scene(data, out, device="cuda"):
    # Reuse measured room/cloth preparation, but NEVER reuse its selected
    # skin set or its replacement hair as the input portrait.
    old, sources = initialize(data, out, device)
    select = (old["part"][:, 0] == 0) | ((old["part"][:, 0] == 4) & (old["tri_id"][:, 0] < 0))
    environment = {k:v[select].detach() for k,v in old.items()}
    environment_sources = {k:v[select.cpu().numpy()] for k,v in sources.items()}
    ref = data["reference"]; prior = data["prior"]
    # Native image scale from actual positive head depths. A conservative
    # per-point median is computed across training observations only.
    z = []
    faces = data["geometry"].faces.numpy()
    for name,row in data["local"].items():
        if row["role"] != "train": continue
        tri = row["mesh"][faces[prior["surface_ids"]]]
        xyz = np.concatenate(((tri*prior["surface_bary"][:, :, None]).sum(1), prior["hair_local_points"]))
        camera = xyz@row["F"][:3, :3].T+row["F"][:3, 3]
        z.append(np.where(camera[:, 2]>.05, camera[:, 2]/data["K"][0, 0], np.nan))
    metric_px = np.nanmedian(np.stack(z), axis=0)
    model = LocalPortraitModel(prior, faces, data["local"][ref]["mesh"],
                               native_metric_per_pixel=metric_px, device=device)
    scene = SceneAssembly(model, environment, data["scale"])
    scene.environment_sources = environment_sources
    write_json(out/"portrait-import.json", {"sourceSha256": data["sourceHash"],
        "pointCount": len(model.role), "surfaceCount": model.surface_count,
        "hairCount": int((model.role==2).sum()), "discarded": 0,
        "environmentCount": int(select.sum()), "newNeckDuplicate": 0,
        "legacyHairShellRetainedForControlledTransfer": True,
        "metricPerNativePixelQuantiles": np.quantile(metric_px, [.1,.5,.9]).tolist(),
        "localTrainingFrames": [n for n,r in data["local"].items() if r["role"]=="train"],
        "worldTrainingFrames": data["train"],
        "bodyMotion": "measured_reference_garment_quasistatic_not_accepted_as_dynamic_body"})
    return scene


@torch.no_grad()
def audit_stages(scene, data, out, stages=("T0", "T1", "T2"), antialiased=False):
    out.mkdir(parents=True, exist_ok=True); report = {}
    names = [n for n,r in data["local"].items() if r["role"] == "development"]+[data["reference"]]
    for name in names:
        frame = make_frame(data, name); outputs = {}
        for stage in stages:
            if stage != "T0" and frame["C"] is None: continue
            outputs[stage] = scene.render(frame, stage, antialiased=antialiased)
        row = {stage:metrics(image, frame) for stage,image in outputs.items()}
        row["crop"] = frame["rectangle"]; row["K"] = frame["K"].cpu().tolist()
        if "T0" in outputs and "T1" in outputs:
            row["T0_T1"] = {key:{"mean": float((outputs["T0"][key]-outputs["T1"][key]).abs().mean()),
                                       "max": float((outputs["T0"][key]-outputs["T1"][key]).abs().max())}
                            for key in ("rgb", "alpha", "q", "depth")}
            state = scene.portrait.local_state(frame["mesh"])
            world = state.to_world(frame["C"], frame["F"], data["scale"])
            camera0 = state.means@frame["F"][:3,:3].T+frame["F"][:3,3]
            camera1 = (world.means@frame["C"][:3,:3].T+frame["C"][:3,3])/data["scale"]
            cov0 = frame["F"][:3,:3]@state.covariance()@frame["F"][:3,:3].T
            cov1 = frame["C"][:3,:3]@world.covariance()@frame["C"][:3,:3].T/data["scale"]**2
            row["T0_T1"]["cameraPointMax"] = float((camera0-camera1).abs().max())
            row["T0_T1"]["cameraCovarianceMax"] = float((cov0-cov1).abs().max())
        source = frame["rgb"].cpu().numpy()
        montage = [source]+[v["rgb"].cpu().numpy() for v in outputs.values()]
        cv2.imwrite(str(out/(name+"-stages.png")), cv2.cvtColor((np.concatenate(montage,1)*255).round().clip(0,255).astype(np.uint8), cv2.COLOR_RGB2BGR))
        for feature, rectangle in boxes(data,name).items():
            if rectangle is None: continue
            x0,y0,x1,y1=rectangle; ox,oy,_,_=frame["rectangle"]
            x0,x1=max(0,x0-ox),min(source.shape[1],x1-ox); y0,y1=max(0,y0-oy),min(source.shape[0],y1-oy)
            if x1<=x0 or y1<=y0: continue
            patch = np.concatenate([image[y0:y1,x0:x1] for image in montage],1)
            cv2.imwrite(str(out/(name+"-"+feature+".png")), cv2.cvtColor((patch*255).round().clip(0,255).astype(np.uint8), cv2.COLOR_RGB2BGR))
            row.setdefault("featureRgbL1", {})[feature] = {stage:float(np.abs(image["rgb"].cpu().numpy()[y0:y1,x0:x1]-source[y0:y1,x0:x1]).mean()) for stage,image in outputs.items()}
        report[name] = row
    write_json(out/"audit.json", report)
    return report


def configure_stage(scene, stage, step, soft):
    for p in scene.parameters(): p.requires_grad_(False)
    if stage == "T3":
        for p in scene.environment.parameters(): p.requires_grad_(True)
    else:
        # Alternate appearance and shared geometry. No per-frame scale/K and
        # no free simultaneous pose/shape/appearance compensation.
        geometry = step >= 80 and step % 4 == 3
        for name,p in scene.portrait.named_parameters():
            p.requires_grad_((name in (("embedding","normal_offset","surface_residual") if soft else ("embedding","normal_offset"))) if geometry else name in ("sh","opacity_logits","log_scales","quats"))
        if stage == "T4" and step % 4 == 0:
            for p in scene.environment.parameters(): p.requires_grad_(True)


def train_stage(scene, data, out, stage, steps, soft, antialiased=False):
    if stage not in ("local", "T3", "T4"): raise ValueError("invalid_training_stage")
    rates = {"sh":.002, "opacity_logits":.003, "log_scales":.0006, "quats":.0002,
             "embedding":.002, "normal_offset":.000015, "surface_residual":.000006, "hair_delta":0.}
    optim = torch.optim.Adam([{"params":[p],"lr":rates.get(n,0.),"name":n} for n,p in scene.portrait.named_parameters()], eps=1e-8)
    envopt = torch.optim.Adam([{"params":[p],"lr": {"means":.00005*scene.scale,"scales":.0006,"quats":.0002,"opacities":.003,"sh":.002}[n]} for n,p in scene.environment.items()], eps=1e-8)
    local_names = [n for n,r in data["local"].items() if r["role"]=="train"]
    world_names = data["train"]
    curve=[]; gradient_audit=[]; initial={n:p.detach().clone() for n,p in scene.portrait.named_parameters()}
    start=time.perf_counter()
    for step in range(steps):
        configure_stage(scene,stage,step,soft)
        optim.zero_grad(set_to_none=True);envopt.zero_grad(set_to_none=True)
        name=local_names[step%len(local_names)];frame=make_frame(data,name)
        local_render=scene.render(frame,"T0",antialiased=antialiased)
        local_loss,local_values=head_loss(local_render,frame)
        if stage=="T3": local_loss=local_loss.detach()*0
        image_loss=local_loss
        world_loss=local_loss*0
        if stage!="local":
            name_w=world_names[step%len(world_names)];world_frame=make_frame(data,name_w,crop=False,half=True)
            world_render=scene.render(world_frame,stage,antialiased=antialiased)
            error=(world_render["rgb"]-world_frame["rgb"]).abs().mean(-1)
            room=world_frame["masks"]["room_visible"];cloth=world_frame["masks"]["neck_cloth_visible"]
            # T3 only observed room/garment pixels. It cannot paint face
            # colors onto a room point to reduce a whole-image loss.
            world_loss=masked_mean(error,room)+.4*masked_mean(error,cloth)
            if stage=="T4":
                face=world_frame["masks"]["face_core"]|world_frame["masks"]["face_boundary"]
                world_loss=world_loss+.5*masked_mean(error,face)
            image_loss=image_loss+world_loss
        regs=scene.portrait.soft_regularization(frame["mesh"])
        regularizer=.0005*scene.portrait.sh[:,1:].square().mean()
        regularizer+=.0002*(scene.portrait.log_scales-scene.portrait.initial_log_scales).square().mean()
        if soft:
            regularizer+=.0007*regs["skinSoftBand"]+.00015*regs["sharedSurfaceSmooth"]+.00006*regs["sharedIdentityResidual"]+.00003*regs["normalOffsetChangePixels"]
        if stage=="T3": regularizer=regularizer.detach()*0
        if stage!="local":
            env=scene.environment
            regularizer+=.002*((env["means"]-scene.environment_initial_means)/(.02*scene.scale)).square().mean()
            regularizer+=.005*(env["scales"]-scene.environment_initial_scales-math.log(2)).clamp_min(0).square().mean()
        loss=image_loss+regularizer
        if not torch.isfinite(loss): raise RuntimeError(f"nonfinite_portrait_loss:{stage}:{step}")
        if stage!="T3" and soft and step>=80 and step%100==83:
            variables=[p for n,p in scene.portrait.named_parameters() if n in ("embedding","normal_offset","surface_residual") and p.requires_grad]
            labels=[n for n,p in scene.portrait.named_parameters() if n in ("embedding","normal_offset","surface_residual") and p.requires_grad]
            a=torch.autograd.grad(image_loss,variables,retain_graph=True,allow_unused=True)
            b=torch.autograd.grad(regularizer,variables,retain_graph=True,allow_unused=True)
            gradient_audit.append({"step":step+1,"parameters":{n:{"imageGradNorm":float(x.norm()) if x is not None else 0.,
                "priorGradNorm":float(y.norm()) if y is not None else 0.,
                "cosine":float(functional.cosine_similarity(x.flatten(),y.flatten(),dim=0)) if x is not None and y is not None else None} for n,x,y in zip(labels,a,b)}})
        loss.backward()
        torch.nn.utils.clip_grad_norm_(scene.portrait.parameters(),10.)
        optim.step();envopt.step()
        walk=scene.portrait.walk(optim) if stage!="T3" and soft and step>=80 and step%4==3 else {}
        if step%100==0 or step==steps-1:
            row={"step":step+1,"localFrame":name,"localOnly":name not in data["worlds"],"local":local_values,
                 "loss":float(loss.detach()),"worldLoss":float(world_loss.detach()),"walk":walk}
            curve.append(row); print(json.dumps({"stage":stage,**row}),flush=True)
    torch.cuda.synchronize()
    result={"stage":stage,"steps":steps,"soft":soft,"seconds":time.perf_counter()-start,
            "curve":curve,"gradientAttribution":gradient_audit,
            "portraitParameterChange":{n:float((p.detach()-initial[n]).abs().mean()) for n,p in scene.portrait.named_parameters()},
            "localTrainCount":len(local_names),"worldTrainCount":len(world_names),"allGroupsEveryWorldForward":True}
    if stage=="T3" and any(not torch.equal(p.detach(),initial[n]) for n,p in scene.portrait.named_parameters()):
        raise RuntimeError("frozen_portrait_changed_during_environment_fit")
    write_json(out/(stage+"-training.json"),result)
    torch.save({"engineVersion":ENGINE_VERSION,"sourceSha256":data["sourceHash"],
                "stage":stage,"soft":soft,"model":scene.state_dict(),"optimizer":optim.state_dict()},out/(stage+"-state.pt"))
    return result,optim


def export_candidate(scene,data,out):
    reference=data["reference"];frame=make_frame(data,reference)
    with torch.no_grad():
        local=scene.portrait.local_state(frame["mesh"])
        state=joined_state(local.to_world(frame["C"],frame["F"],data["scale"]),scene.environment_state())
        # The entire retained head is first. Export/source mappings are
        # explicit; no claim that the current Morton loader preserves them.
        n=len(state.means);pad=torch.zeros((n,15,3),device=state.means.device);pad[:,:3]=state.sh[:,1:]
        path=out/"portrait.gaussian.ply"
        export_splats(means=state.means,scales=state.scales.log(),quats=state.quats,opacities=torch.logit(state.opacity.clamp(1e-6,1-1e-6)),
                      sh0=state.sh[:,:1],shN=pad,format="ply",save_to=str(path))
        asset_hash=digest(path);head_count=len(scene.portrait.role)
        np.savez_compressed(out/"portrait.components.npz",asset_sha256=np.asarray(asset_hash),source_sha256=np.asarray(data["sourceHash"]),
            component=state.parts.cpu().numpy(),point_id=np.arange(n),
            source_id=np.concatenate((scene.portrait.source_index.cpu().numpy(),scene.environment_sources["id"])),
            source_kind=np.concatenate((np.where(scene.portrait.role.cpu().numpy()==2,6,2),scene.environment_sources["kind"])),
            triangle_id=np.concatenate((scene.portrait.triangle_ids.cpu().numpy(),np.full(n-scene.portrait.surface_count,-1))),
            surface_bary=scene.portrait.embedding.detach().cpu().numpy(),
            normal_offset=scene.portrait.normal_offset.detach().cpu().numpy(),
            origin_index=scene.portrait.origin_index.cpu().numpy(),generation=scene.portrait.generation.cpu().numpy(),
            confidence=scene.portrait.confidence.cpu().numpy())
        C=data["worlds"][reference];camera=np.linalg.inv(C)[:3,3]
        target=state.means[:scene.portrait.surface_count].mean(0).cpu().tolist()
        view={"schemaVersion":1,"sourceFrame":reference,"target":target,"camera":camera.tolist(),"up":(-C[:3,:3].T[:,1]).tolist(),
              "fovDegrees":math.degrees(2*math.atan(data["rgb"][reference].shape[0]/(2*data["K"][1,1]))),
              "targetFaceFraction":.5,"editableSplats":scene.portrait.surface_count,"recordedEnvironmentSplats":n-head_count,
              "reconstructionMethod":ENGINE_VERSION,"surfacePointCount":scene.portrait.surface_count,
              "researchOnly":True,"sourceSha256":data["sourceHash"],"assetSha256":asset_hash}
        write_json(out/"portrait.view.json",view)
        torch.save({"engineVersion":ENGINE_VERSION,"sourceSha256":data["sourceHash"],"model":scene.state_dict()},out/"trained-state.pt")
    return asset_hash


def run(args):
    if args.output.exists(): raise FileExistsError("each_experiment_requires_new_run_directory")
    args.output.mkdir(parents=True)
    started=time.perf_counter();torch.manual_seed(280928)
    if not torch.cuda.is_available():
        write_json(args.output/"status.json",{"status":"GPU_unavailable_not_tested"})
        raise RuntimeError("GPU_unavailable")
    torch.cuda.reset_peak_memory_stats()
    data=load_prepared(args.prepared)
    # Existing initializer reads only cloth seeds from its output argument.
    import shutil
    shutil.copyfile(args.prepared/"cloth_supported_seeds.npz",args.output/"cloth_supported_seeds.npz")
    scene=initialize_scene(data,args.output)
    scene.portrait.constraint_mode="soft" if args.soft else "strong"
    if args.resume_state is not None:
        checkpoint=torch.load(args.resume_state,map_location="cuda",weights_only=True)
        if checkpoint["sourceSha256"]!=data["sourceHash"] or checkpoint["engineVersion"]!=ENGINE_VERSION:
            raise ValueError("resume_source_or_engine_mismatch")
        scene.load_state_dict(checkpoint["model"],strict=True)
    freeze={str(path):digest(path) for path in (Path(__file__),Path(__file__).with_name("reconstruction_portrait_model.py"))}
    config={"engineVersion":ENGINE_VERSION,"sourceSha256":data["sourceHash"],"appearanceHash":data["appearanceHash"],
            "prepared":str(args.prepared),"soft":args.soft,"localSteps":args.local_steps,"roomSteps":args.room_steps,"jointSteps":args.joint_steps,
            "antialiased":args.antialiased,"sourceFiles":freeze,"finalAudit":"current_development_not_blind; cross_video_unverified",
            "resumeState":str(args.resume_state) if args.resume_state else None,
            "resumeSha256":digest(args.resume_state) if args.resume_state else None}
    write_json(args.output/"config.json",config)
    initial=audit_stages(scene,data,args.output/"initial",antialiased=args.antialiased)
    trainings=[]
    if args.local_steps:
        result,_=train_stage(scene,data,args.output,"local",args.local_steps,args.soft,args.antialiased);trainings.append(result)
        audit_stages(scene,data,args.output/"after-local",antialiased=args.antialiased)
    if args.room_steps:
        result,_=train_stage(scene,data,args.output,"T3",args.room_steps,args.soft,args.antialiased);trainings.append(result)
        audit_stages(scene,data,args.output/"after-T3",antialiased=args.antialiased)
    if args.joint_steps:
        result,_=train_stage(scene,data,args.output,"T4",args.joint_steps,args.soft,args.antialiased);trainings.append(result)
    final=audit_stages(scene,data,args.output/"final",antialiased=args.antialiased)
    asset=export_candidate(scene,data,args.output)
    torch.cuda.synchronize()
    report={**config,"status":"research_not_release_approved","plySha256":asset,"initial":initial,"final":final,
            "trainings":trainings,"seconds":time.perf_counter()-started,"allocatedPeakMiB":torch.cuda.max_memory_allocated()/1024**2,
            "reservedPeakMiB":torch.cuda.max_memory_reserved()/1024**2,"pointCount":len(scene.portrait.role)+len(scene.environment_parts),
            "limitations":["Legacy hair is retained for same-point attribution, not declared repaired",
                "Garment motion and complete neck/shoulder continuity remain unaccepted",
                "Temporary research C and global scale are not independent calibration",
                "Research candidate; full portrait and scene release quality remains unaccepted"]}
    write_json(args.output/"report.json",report)
    print(json.dumps({k:report[k] for k in ("status","plySha256","seconds","allocatedPeakMiB","reservedPeakMiB")}),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("prepared",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--soft",action="store_true");p.add_argument("--antialiased",action="store_true")
    p.add_argument("--local-steps",type=int,default=0);p.add_argument("--room-steps",type=int,default=0);p.add_argument("--joint-steps",type=int,default=0)
    p.add_argument("--resume-state",type=Path)
    run(p.parse_args())
