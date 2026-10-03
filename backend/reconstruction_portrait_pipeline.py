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

# Stable asset contract; actual implementation changes are identified by Git
# and the complete imported-source hash, not another dated engine fork.
ENGINE_VERSION = "portrait-native-fullframe-20261002-research"


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
    if crop:
        observed = labels["face_core"] | labels["face_boundary"] | labels["hair_visible"] | labels["glasses_visible"]
        if 'training_face' in labels:observed=observed|labels['training_face']
        y, x = np.where(observed)
        if not len(x): raise ValueError(f"missing_head_observation:{name}")
        rectangle = (max(0, int(x.min())-24), max(0, int(y.min())-24), min(w, int(x.max())+25), min(h, int(y.max())+25))
        x0, y0, x1, y1 = rectangle
        rgb = rgb[y0:y1, x0:x1]; labels = {k:v[y0:y1, x0:x1] for k,v in labels.items()}
        K[0, 2] -= x0; K[1, 2] -= y0
    return {"rgb": tensor(rgb, device), "masks": {k:tensor(v, device).bool() for k,v in labels.items()},
            "K": tensor(K, device), "F": tensor(data["local"][name]["F"], device),
            "C": tensor(data["worlds"][name], device) if name in data["worlds"] else None,
            "mesh": tensor(data["local"][name]["mesh"], device), "rectangle": rectangle,
            "name": name, "nativeScale": 1, "fullSize":(w,h),
            "fullK":tensor(data["K"],device), "requestedHalfIgnored":bool(half)}


def full_frame_draw(state, C, frame, *, unit_scale=1., antialiased=False, absgrad=False, person_channels=False):
    w,h=frame["fullSize"];x0,y0,x1,y1=frame["rectangle"]
    K=frame["fullK"];cropK=K.clone();cropK[0,2]-=x0;cropK[1,2]-=y0
    if not torch.allclose(cropK,frame["K"],atol=1e-5,rtol=0):raise ValueError("native_crop_intrinsics_changed")
    if frame["nativeScale"]!=1 or frame["rgb"].shape[:2]!=(y1-y0,x1-x0):raise ValueError("native_canvas_contract")
    center=torch.linalg.inv(C)[:3,3];rgb=evaluate_sh1(state.sh,state.means-center)
    groups=functional.one_hot(state.parts.long(),5).to(rgb.dtype)
    depth=(state.means@C[:3,:3].T+C[:3,3])[:,2]
    features=torch.cat((rgb,groups,groups*depth[:,None]),1)
    if person_channels:
        # Same visibility, sorting and transmittance as the full scene. An
        # independent person render cannot measure room leaking through it.
        opaque_parts=(state.parts==1)|(state.parts==4)
        features=torch.cat((features,rgb*opaque_parts[:,None]),1)
    image,alpha,info=rasterization(state.means,None,None,state.opacity,features,C[None],K[None],w,h,
        covars=state.covariance(),packed=True,sh_degree=None,render_mode="RGB+D",absgrad=absgrad,
        rasterize_mode="antialiased" if antialiased else "classic",near_plane=.01*unit_scale,far_plane=1e10*unit_scale)
    info["width"]=w;info["height"]=h
    if info["means2d"].requires_grad:info["means2d"].retain_grad()
    full={"rgb":image[0,:,:,:3],"alpha":alpha[0,:,:,0],"q":image[0,:,:,3:8],
          "q_depth":image[0,:,:,8:13]/unit_scale,"depth":image[0,:,:,-1]/unit_scale}
    if person_channels:full['person_rgb']=image[0,:,:,13:16]
    return {**{k:v[y0:y1,x0:x1] for k,v in full.items()},"info":info}


def head_loss(rendered, frame):
    masks = frame["masks"]
    face = masks.get('training_face',masks["face_core"] | masks["face_boundary"] | masks["glasses_visible"])
    hair = masks["hair_visible"]
    error = (rendered["rgb"]-frame["rgb"]).abs().mean(-1)
    # Fixed observed regions count missing pixels. No black paint outside
    # masks and no neighbourhood loss across a fabricated black boundary.
    face_rgb = masked_mean(error, face)
    hair_rgb = masked_mean(error, hair)
    coverage = masked_mean((1-rendered["alpha"]).square(), face | hair)
    safe_empty = masks.get('training_empty',masks["room_visible"] & ~masks["unknown_or_occluded"])
    outside = masked_mean(rendered["alpha"].square(), safe_empty)
    value = 1.5*face_rgb+hair_rgb+.06*coverage+.03*outside
    return value, {"faceRgb": float(face_rgb.detach()), "hairRgb": float(hair_rgb.detach()),
                   "missingCoverage": float(coverage.detach()), "reliableEmpty": float(outside.detach())}


def metrics(rendered, frame):
    masks = frame["masks"]; err = (rendered["rgb"]-frame["rgb"]).abs().mean(-1)
    regions = {"face": masks["face_core"] | masks["face_boundary"] | masks["glasses_visible"],
               "hair": masks["hair_visible"], "glasses": masks["glasses_visible"],
               "room": masks["room_visible"], "neckCloth": masks["neck_cloth_visible"]}
    for label,key in (("roomObserved","observed_room"),("clothObserved","observed_cloth"),
                      ("skinNeckObserved","observed_body_skin")):
        if key in masks:regions[label]=masks[key]
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
        count=len(environment["means"])
        self.register_buffer("environment_uid",torch.arange(count,device=environment["means"].device))
        self.register_buffer("environment_parent_uid",torch.full((count,),-1,device=environment["means"].device,dtype=torch.long))
        self.register_buffer("environment_generation",torch.zeros(count,device=environment["means"].device,dtype=torch.long))
        self.register_buffer("environment_initial_quats",environment["quats"].detach().clone())
        self.dense_surface=False
        self.body_train_names=set()

    def environment_state(self, frame=None):
        p = self.environment
        state=GaussianState(p["means"], functional.normalize(p["quats"], dim=-1), p["scales"].exp(),
                            p["opacities"].sigmoid(), p["sh"], self.environment_parts)
        if frame is not None and hasattr(self,'neck_binding') and frame['name'] in self.body_train_names:
            state=self.neck_binding.deform(state,frame['C'],frame['F'])
        return state

    def render(self, frame, stage, *, antialiased=False, absgrad=False):
        state = self.portrait_state(frame)
        if stage == "T0":
            return full_frame_draw(state,frame["F"],frame,antialiased=antialiased,absgrad=absgrad,
                person_channels=getattr(self,'opaque_person',False))
        if frame["C"] is None: raise ValueError("world_render_requires_real_world_observation")
        state = state.to_world(frame["C"], frame["F"], self.scale)
        if stage != "T1":
            if getattr(self,'dense_surface',False):
                from reconstruction_live_neck_motion import joined_covariant
                state=joined_covariant(state,self.environment_state(frame))
            else:state = joined_state(state, self.environment_state())
        return full_frame_draw(state, frame["C"], frame, unit_scale=self.scale,
                    antialiased=antialiased, absgrad=absgrad,
                    person_channels=getattr(self,'opaque_person',False))

    def portrait_state(self,frame):
        state=self.portrait.local_state(frame['mesh'])
        if hasattr(self,'hair_motion'):
            state=self.hair_motion.deform(frame['name'],state,self.portrait.surface_count)
        return state


def initialize_scene(data, out, device="cuda"):
    # Reuse measured room/cloth preparation, but NEVER reuse its selected
    # skin set or its replacement hair as the input portrait.
    if "cloth_stage_seeds" in data:
        np.savez_compressed(out/"cloth_supported_seeds.npz",**data["cloth_stage_seeds"])
    old, sources = initialize(data, out, device)
    select = (old["part"][:, 0] == 0) | ((old["part"][:, 0] == 4) & (old["tri_id"][:, 0] < 0))
    environment = {k:v[select].detach() for k,v in old.items()}
    environment_sources = {k:v[select.cpu().numpy()] for k,v in sources.items()}
    ref = data["reference"]; prior = data["prior"]
    from reconstruction_live_hair_motion import prepared_hair_motion,write_motion_contract,legacy_hair_motion
    hair_motion=prepared_hair_motion(data['prepared'],data,data['prepared_geometry_contract'],
        ref,model=data['geometry'],fit=data.get('hair_fit'))
    if not data.get('dense_manifest'):
        hair_motion=legacy_hair_motion(list(data['local']),ref)
        hair_motion.metadata['reason']='sparse_initial_hair_seed_was_triangulated_in_legacy_root_local_frame'
    data['hair_motion']=hair_motion
    dense_meta=None; dense_components={}
    if data.get("dense_manifest"):
        from reconstruction_live_surface_binding import (load_surface_bundle,
            environment_from_components,replace_hair_prior)
        dense_meta,dense_components=load_surface_bundle(data["dense_manifest"],data)
        if "room" not in dense_components or "body" not in dense_components:
            raise ValueError("dense_scene_missing_supported_room_or_body")
        environment,environment_sources,layers=environment_from_components(
            {k:dense_components[k] for k in ("room","body")},device)
        if "hair" in dense_components:prior=replace_hair_prior(prior,dense_components["hair"])
        elif hair_motion.receipt()['status']!='explicit_legacy_root_local':
            raise ValueError('motion_corrected_hair_requires_matching_dense_surface')
    # Native image scale from actual positive head depths. A conservative
    # per-point median is computed across training observations only.
    z = []
    faces = data["geometry"].faces.numpy()
    for name,row in data["local"].items():
        if row["role"] != "train": continue
        tri = row["mesh"][faces[prior["surface_ids"]]]
        xyz = np.concatenate(((tri*prior["surface_bary"][:, :, None]).sum(1), prior["hair_local_points"]))
        D=hair_motion.transforms[hair_motion.names.index(name)].numpy()
        surface_count=len(prior['surface_ids'])
        xyz[surface_count:]=xyz[surface_count:]@D[:3,:3].T+D[:3,3]
        camera = xyz@row["F"][:3, :3].T+row["F"][:3, 3]
        z.append(np.where(camera[:, 2]>.05, camera[:, 2]/data["K"][0, 0], np.nan))
    metric_px = np.nanmedian(np.stack(z), axis=0)
    model = LocalPortraitModel(prior, faces, data["local"][ref]["mesh"],
                               native_metric_per_pixel=metric_px, device=device)
    scene = SceneAssembly(model, environment, data["scale"])
    scene.hair_motion=hair_motion
    scene.hair_motion_receipt=write_motion_contract(hair_motion,out)
    scene.environment_sources = environment_sources
    if dense_meta:
        scene.dense_surface=True;scene.dense_metadata=dense_meta
        scene.body_train_names=set(dense_meta["components"]["body"]["trainNames"])
        scene.environment_layers=layers
        scene.dense_hair="hair" in dense_components
        model.observed_hair_surface=scene.dense_hair
        scene.register_buffer("hair_initial",model.hair_base+model.hair_delta.detach())
        scene.register_buffer("hair_support_scale",model.metric_per_pixel[model.surface_count:].clone())
        from reconstruction_live_neck_motion import build_neck_binding
        scene.neck_binding=build_neck_binding(environment['means'],layers,
            data['worlds'][ref],data['local'][ref]['F'],data['scale'])
    write_json(out/"portrait-import.json", {"sourceSha256": data["sourceHash"],
        "pointCount": len(model.role), "surfaceCount": model.surface_count,
        "hairCount": int((model.role==2).sum()), "discarded": 0,
        "environmentCount": len(scene.environment_parts), "newNeckDuplicate": 0,
        "denseSurfaceManifest":dense_meta,
        "neckMotion":scene.neck_binding.receipt() if hasattr(scene,'neck_binding') else None,
        "hairMotion":scene.hair_motion_receipt,
        "legacyHairShellRetainedForControlledTransfer": bool(data.get("observationSchema",1)<2),
        "metricPerNativePixelQuantiles": np.quantile(metric_px, [.1,.5,.9]).tolist(),
        "localTrainingFrames": [n for n,r in data["local"].items() if r["role"]=="train"],
        "worldTrainingFrames": data["train"],
        "bodyMotion": "short_window_reference_surface_not_verified_dynamic_body" if dense_meta else "measured_reference_garment_quasistatic_not_accepted_as_dynamic_body"})
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
            state = scene.portrait_state(frame)
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


@torch.no_grad()
def audit_full_scene(scene,data,out):
    out.mkdir(exist_ok=True);report={}
    names=[n for n in data["development"] if n in data["worlds"]]+[data["reference"]]
    for name in dict.fromkeys(names):
        frame=make_frame(data,name,crop=False);r=scene.render(frame,"T2")
        report[name]=metrics(r,frame)
        # These float tensors are the audit data; preview PNGs do not replace
        # linear/native pixel comparisons or manufacture camera truth.
        np.savez_compressed(out/(name+".npz"),rgb=r["rgb"].cpu().numpy(),alpha=r["alpha"].cpu().numpy(),
            q=r["q"].cpu().numpy(),K=data["K"],C=data["worlds"][name],F=data["local"][name]["F"])
        pair=np.concatenate((frame["rgb"].cpu().numpy(),r["rgb"].cpu().numpy()),1)
        cv2.imwrite(str(out/(name+".png")),cv2.cvtColor((pair*255).round().clip(0,255).astype(np.uint8),cv2.COLOR_RGB2BGR))
    write_json(out/"metrics.json",report)
    return report


def configure_stage(scene, stage, step, soft):
    for p in scene.parameters(): p.requires_grad_(False)
    if stage == "T3":
        for n,p in scene.environment.items():
            p.requires_grad_(not scene.dense_surface or step>=80 or n in ("sh","opacities"))
        if hasattr(scene,'neck_sh_editable') and scene.neck_sh_editable.any():scene.portrait.sh.requires_grad_(True)
    else:
        # Alternate appearance and shared geometry. No per-frame scale/K and
        # no free simultaneous pose/shape/appearance compensation.
        geometry = step >= 80 and step % 4 == 3
        for name,p in scene.portrait.named_parameters():
            p.requires_grad_((name in (("embedding","normal_offset","surface_residual") if soft else ("embedding","normal_offset"))) if geometry else name in ("sh","opacity_logits","log_scales","quats"))
        if getattr(scene,"dense_hair",False) and geometry:scene.portrait.hair_delta.requires_grad_(True)
        if stage == "T4" and step % 4 == 0:
            for p in scene.environment.parameters(): p.requires_grad_(True)


def train_stage(scene, data, out, stage, steps, soft, antialiased=False):
    if stage not in ("local", "T3", "T4"): raise ValueError("invalid_training_stage")
    rates = {"sh":.002, "opacity_logits":.003, "log_scales":.0006, "quats":.0002,
             "embedding":.002, "normal_offset":.000015, "surface_residual":.000006,
             "hair_delta":.000015 if getattr(scene,"dense_hair",False) else 0.}
    optim = torch.optim.Adam([{"params":[p],"lr":rates.get(n,0.),"name":n} for n,p in scene.portrait.named_parameters()], eps=1e-8)
    envopt = torch.optim.Adam([{"params":[p],"name":n,"lr": {"means":.00005*scene.scale,"scales":.0006,"quats":.0002,"opacities":.003,"sh":.002}[n]} for n,p in scene.environment.items()], eps=1e-8)
    bodyopt=torch.optim.Adam([{"params":[p],"name":n,"lr": {"means":.00005*scene.scale,"scales":.0006,"quats":.0002,"opacities":.003,"sh":.002}[n]} for n,p in scene.environment.items()],eps=1e-8) if scene.dense_surface else None
    neckopt=torch.optim.Adam([scene.portrait.sh],lr=.002,eps=1e-8) if stage=='T3' and hasattr(scene,'neck_sh_editable') and scene.neck_sh_editable.any() else None
    local_names = [n for n,r in data["local"].items() if r["role"]=="train"]
    from reconstruction_local_sampling import scheduled_local_name,schedule_receipt
    sampling=schedule_receipt(local_names,steps) if stage!='T3' else None
    world_names = data["train"]
    curve=[]; gradient_audit=[]; density_events=[]; initial={n:p.detach().clone() for n,p in scene.portrait.named_parameters()}
    protected={}
    if stage=="T3" and (getattr(scene,"surface_refine",False) or scene.dense_surface):
        with torch.no_grad():
            for n in world_names:
                f=make_frame(data,n,crop=False);r=scene.render(f,"T2")
                mask=f['masks']['face_core']|f['masks']['face_boundary']|f['masks']['hair_visible']|f['masks']['glasses_visible']
                protected[n]=(r['q'][...,0][mask].cpu(),r['q'][...,1:4].sum(-1)[mask].cpu())
    def checkpoint(label,completed):
        torch.save({"engineVersion":ENGINE_VERSION,"sourceSha256":data["sourceHash"],
            "stage":stage,"step":completed,"soft":soft,"model":scene.state_dict(),
            "optimizer":optim.state_dict(),"environmentOptimizer":envopt.state_dict(),
            "bodyOptimizer":bodyopt.state_dict() if bodyopt else None,
            "neckAppearanceOptimizer":neckopt.state_dict() if neckopt else None,
            "surfaceContract":surface_contract(scene,data),
            "personSupervision":{"opaqueHead":bool(getattr(scene,'opaque_person',False)),
                                 "opaqueBody":bool(getattr(scene,'opaque_body',False)),
                                 "appearanceSha256":data['appearanceHash']},
            "environmentSources":{k:torch.as_tensor(v) for k,v in scene.environment_sources.items()},
            "rng":torch.get_rng_state(),"cudaRng":torch.cuda.get_rng_state(),
            "sampler":{"localNames":local_names,"worldNames":world_names,"nextStep":completed,
                       "localPhaseSchedule":sampling['method'] if sampling else 'frozen_head_no_local_update'},
            "density":{"events":density_events,"finalRecoverySteps":max(0,steps-100)}},out/(stage+"-"+label+".pt"))
    checkpoint("init",0)
    start=time.perf_counter()
    for step in range(steps):
        configure_stage(scene,stage,step,soft)
        optim.zero_grad(set_to_none=True);envopt.zero_grad(set_to_none=True)
        name=scheduled_local_name(local_names,step) if stage!='T3' else local_names[step%len(local_names)]
        frame=make_frame(data,name)
        if stage=='T3':
            local_loss=scene.portrait.sh.new_zeros(())
            local_values={'frozenHeadLocalForwardSkipped':True}
        else:
            local_render=scene.render(frame,"T0",antialiased=antialiased)
            local_loss,local_values=head_loss(local_render,frame)
            if getattr(scene,'opaque_person',False):
                from reconstruction_live_opaque_person import opaque_person_loss
                person_loss,person_values=opaque_person_loss(local_render,frame,scope='head')
                local_loss=local_loss+person_loss
                local_values['opaquePerson']=person_values
        image_loss=local_loss
        world_loss=local_loss*0
        if stage!="local":
            if scene.dense_surface and step%2:
                body_names=sorted(scene.body_train_names);name_w=body_names[(step//2)%len(body_names)]
            else:name_w=world_names[(step//2 if scene.dense_surface else step)%len(world_names)]
            world_frame=make_frame(data,name_w,crop=False,half=True)
            world_render=scene.render(world_frame,stage,antialiased=antialiased)
            error=(world_render["rgb"]-world_frame["rgb"]).abs().mean(-1)
            room=world_frame["masks"].get("observed_room",world_frame["masks"]["room_visible"])
            cloth=world_frame["masks"].get("observed_neck_cloth",world_frame["masks"]["neck_cloth_visible"])
            # T3 only observed room/garment pixels. It cannot paint face
            # colors onto a room point to reduce a whole-image loss.
            body_observed=not scene.dense_surface or name_w in scene.body_train_names
            if not body_observed:cloth=torch.zeros_like(cloth)
            world_loss=masked_mean(error,room)+.7*masked_mean(error,cloth)
            if getattr(scene,'opaque_person',False) and getattr(scene,'opaque_body',False) and body_observed:
                from reconstruction_live_opaque_person import opaque_person_loss
                person_loss,person_values=opaque_person_loss(world_render,world_frame,scope='body')
                world_loss=world_loss+person_loss
                local_values['opaqueBody']=person_values
            if scene.dense_surface:
                # Real static/garment pixels include low-texture surfaces.
                # Adjacent-pixel structure never crosses invalid/mask edges.
                observed=room|cloth
                world_loss+=.04*masked_mean((1-world_render["alpha"]).square(),observed)
                for axis in (0,1):
                    pred=world_render["rgb"].diff(dim=axis);truth=world_frame["rgb"].diff(dim=axis)
                    valid=(observed[1:]&observed[:-1]) if axis==0 else (observed[:,1:]&observed[:,:-1])
                    world_loss+=.08*masked_mean((pred-truth).abs().mean(-1),valid)
            if name_w in protected:
                room_before,person_before=protected[name_w]
                mask=world_frame["masks"]["face_core"]|world_frame["masks"]["face_boundary"]|world_frame["masks"]["hair_visible"]|world_frame["masks"]["glasses_visible"]
                # Retained person stays in the same alpha composition. This
                # guards against reducing room RGB by letting it cover skin.
                world_loss+=4*(world_render['q'][...,0][mask]-room_before.to(error.device)-.005).clamp_min(0).square().mean()
                world_loss+=4*(person_before.to(error.device)-world_render['q'][...,1:4].sum(-1)[mask]-.005).clamp_min(0).square().mean()
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
            if scene.dense_surface:
                from reconstruction_portrait_model import quaternion_matrix
                basis=quaternion_matrix(scene.environment_initial_quats)
                delta=torch.einsum("ni,nij->nj",env["means"]-scene.environment_initial_means,basis)
                extent=scene.environment_initial_scales.exp()
                regularizer+=.004*(delta/(extent*2).clamp_min(1e-7)).square().mean()
                regularizer+=.008*(env["scales"]-scene.environment_initial_scales-math.log(1.8)).clamp_min(0).square().mean()
                regularizer+=.0005*env["sh"][:,1:].square().mean()
            else:
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
        body_grad={}
        if stage!="local" and scene.dense_surface:
            # Separate Adam clocks. Zeroing a gradient alone would still move
            # unsupported body rows via stale optimizer momentum.
            body_rows=scene.environment_parts==4
            for key,value in scene.environment.items():
                if value.grad is not None:
                    if body_observed:
                        body_grad[key]=value.grad.clone();body_grad[key][~body_rows]=0
                    value.grad[body_rows]=0
        if torch.cuda.max_memory_allocated()/1048576>6656:raise RuntimeError("complete_backward_resource_budget_exceeded")
        if stage=='T3' and neckopt and scene.portrait.sh.grad is not None:
            scene.portrait.sh.grad[~scene.neck_sh_editable]=0
        torch.nn.utils.clip_grad_norm_(scene.portrait.parameters(),10.)
        if stage!='T3':optim.step()
        elif neckopt and body_observed and scene.portrait.sh.grad is not None:
            scene.portrait.sh.grad[~scene.neck_sh_editable]=0
            neckopt.step()
            with torch.no_grad():scene.portrait.sh[~scene.neck_sh_editable]=initial['sh'][~scene.neck_sh_editable]
        envopt.step()
        if body_grad:
            for key,value in scene.environment.items():value.grad=body_grad.get(key)
            bodyopt.step()
        if scene.dense_surface:
            with torch.no_grad():
                if getattr(scene,"dense_hair",False):
                    limit=scene.hair_support_scale[:,None]*3
                    scene.portrait.hair_delta.copy_(scene.portrait.hair_delta.clamp(-limit,limit))
                    s=scene.portrait.surface_count
                    scene.portrait.log_scales[s:].clamp_(min=scene.portrait.initial_log_scales[s:]+math.log(.4),max=scene.portrait.initial_log_scales[s:]+math.log(1.8))
                if stage!="local":
                    # Surface footprint caps are per-seed evidence, never a
                    # global world scale or viewer-radius workaround.
                    scene.environment["scales"].clamp_(min=scene.environment_initial_scales+math.log(.4),
                        max=scene.environment_initial_scales+math.log(1.8))
        if stage=="T3" and getattr(scene,"surface_refine",False) and step==99 and steps>=200:
            from reconstruction_surface_density import select_surface_parents,split_surface_parameters
            selected=select_surface_parents(scene,world_render["info"])
            if len(selected):density_events.append({"step":step+1,**split_surface_parameters(scene,envopt,selected)})
        walk=scene.portrait.walk(optim) if stage!="T3" and soft and step>=80 and step%4==3 else {}
        if step%100==0 or step==steps-1:
            row={"step":step+1,"localFrame":name,"localOnly":name not in data["worlds"],"local":local_values,
                 "loss":float(loss.detach()),"worldLoss":float(world_loss.detach()),"walk":walk}
            curve.append(row); print(json.dumps({"stage":stage,**row}),flush=True)
        elif (step+1)%20==0:
            print(json.dumps({'stage':stage,'step':step+1,'loss':float(loss.detach())}),flush=True)
        if (step+1)%100==0:checkpoint('latest',step+1)
        if step+1==max(1,steps//2):checkpoint("mid",step+1)
    torch.cuda.synchronize()
    result={"stage":stage,"steps":steps,"soft":soft,"seconds":time.perf_counter()-start,
            "curve":curve,"gradientAttribution":gradient_audit,"densityEvents":density_events,
            "portraitParameterChange":{n:float((p.detach()-initial[n]).abs().mean()) for n,p in scene.portrait.named_parameters()},
            "localTrainCount":len(local_names),"worldTrainCount":len(world_names),"allGroupsEveryWorldForward":True,
            "localPhaseSchedule":sampling}
    if bodyopt:result['bodyOptimizerSteps']=int(max((float(v['step']) for v in bodyopt.state.values() if 'step' in v),default=0))
    if neckopt:result['neckAppearanceSteps']=int(neckopt.state.get(scene.portrait.sh,{}).get('step',0))
    if stage=="T3":
        for n,p in scene.portrait.named_parameters():
            if n=='sh' and neckopt:
                if not torch.equal(p.detach()[~scene.neck_sh_editable],initial[n][~scene.neck_sh_editable]):raise RuntimeError('protected_face_SH_changed')
            elif not torch.equal(p.detach(),initial[n]):raise RuntimeError("frozen_portrait_changed_during_environment_fit:"+n)
    write_json(out/(stage+"-training.json"),result)
    checkpoint("state",steps)
    return result,optim


def export_candidate(scene,data,out):
    reference=data["reference"];frame=make_frame(data,reference)
    with torch.no_grad():
        local=scene.portrait_state(frame)
        state=joined_state(local.to_world(frame["C"],frame["F"],data["scale"]),scene.environment_state(frame))
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
            confidence=scene.portrait.confidence.cpu().numpy(),
            environment_uid=scene.environment_uid.cpu().numpy(),
            environment_parent_uid=scene.environment_parent_uid.cpu().numpy(),
            environment_generation=scene.environment_generation.cpu().numpy())
        C=data["worlds"][reference];camera=np.linalg.inv(C)[:3,3]
        target=state.means[:scene.portrait.surface_count].mean(0).cpu().tolist()
        view={"schemaVersion":1,"sourceFrame":reference,"target":target,"camera":camera.tolist(),"up":(-C[:3,:3].T[:,1]).tolist(),
              "fovDegrees":math.degrees(2*math.atan(data["rgb"][reference].shape[0]/(2*data["K"][1,1]))),
              "targetFaceFraction":.5,"editableSplats":scene.portrait.surface_count,"recordedEnvironmentSplats":n-head_count,
              "reconstructionMethod":ENGINE_VERSION,"surfacePointCount":scene.portrait.surface_count,
              "researchOnly":True,"sourceSha256":data["sourceHash"],"assetSha256":asset_hash}
        write_json(out/"portrait.view.json",view)
        torch.save({"engineVersion":ENGINE_VERSION,"sourceSha256":data["sourceHash"],"model":scene.state_dict(),
                    "surfaceContract":surface_contract(scene,data),
                    "personSupervision":{"opaqueHead":bool(getattr(scene,'opaque_person',False)),
                                         "opaqueBody":bool(getattr(scene,'opaque_body',False)),
                                         "appearanceSha256":data['appearanceHash']}},out/"trained-state.pt")
    return asset_hash


def surface_contract(scene,data):
    return {"reference":data['reference'],"scale":float(data['scale']),
        "manifestSha256":digest(data['dense_manifest']) if data.get('dense_manifest') else None,
        "bodyTrainNames":sorted(scene.body_train_names),"denseHair":bool(getattr(scene,'dense_hair',False)),
        "layers":scene.environment_layers.tolist() if hasattr(scene,'environment_layers') else None,
        "hairMotion":scene.hair_motion.receipt() if hasattr(scene,'hair_motion') else None,
        "hairReferenceTransforms":scene.hair_motion.transforms.tolist() if hasattr(scene,'hair_motion') else None}


def surface_contract_matches(actual,expected):
    # The immutable transport matrices/digest and input identities remain exact.
    # A diagnostic joint-regression pivot can differ by a few float64 ULPs
    # between CPU reduction thread counts; it is not another learned state.
    a,b=copy.deepcopy(actual),copy.deepcopy(expected)
    for value in (a,b):
        if not isinstance(value,dict):return False
    am,bm=a.get('hairMotion'),b.get('hairMotion')
    if isinstance(am,dict) and isinstance(bm,dict) and 'pivotRootLocal' in am and 'pivotRootLocal' in bm:
        av,bv=np.asarray(am.pop('pivotRootLocal')),np.asarray(bm.pop('pivotRootLocal'))
        if av.shape!=(3,) or bv.shape!=(3,) or not np.allclose(av,bv,atol=1e-12,rtol=0):return False
    return a==b


def prepare_neck_appearance(scene,data,out):
    from reconstruction_live_neck_appearance import select_neck_sh_points
    from reconstruction_live_neck_motion import joined_covariant
    def observations():
        for name,row in data['local'].items():
            if row['role']!='train':continue
            frame=make_frame(data,name,crop=False)
            with torch.no_grad():
                local=scene.portrait_state(frame)
                if name in scene.body_train_names:
                    state=joined_covariant(local.to_world(frame['C'],frame['F'],scene.scale),scene.environment_state(frame))
                    yield dict(frame=frame,state=state,unit_scale=scene.scale,support=True,full_scene=True)
                else:
                    yield dict(frame={**frame,'C':frame['F']},state=local,unit_scale=1.,support=False,full_scene=False)
    selected,receipt=select_neck_sh_points(observations(),len(scene.portrait.role),scene.portrait.surface_count)
    scene.register_buffer('neck_sh_editable',selected.to(scene.portrait.sh.device))
    write_json(out/'neck-appearance-selection.json',receipt)
    return receipt


def warm_start_portrait(scene,data,state_path,manifest_path):
    """Reuse a trained head when only its measured environment is replaced.

    This is a model warm-start, never an exact optimizer resume. Source,
    geometry, the complete hair input and every head state field must agree.
    """
    checkpoint=torch.load(state_path,map_location=scene.portrait.sh.device,weights_only=True)
    if checkpoint.get('sourceSha256')!=data['sourceHash'] or checkpoint.get('engineVersion')!=ENGINE_VERSION:
        raise ValueError('portrait_warm_start_source_or_engine_mismatch')
    contract=checkpoint.get('surfaceContract',{})
    if contract.get('hairMotion')!=surface_contract(scene,data).get('hairMotion'):
        raise ValueError('portrait_warm_start_hair_motion_mismatch')
    if contract.get('manifestSha256')!=digest(manifest_path):raise ValueError('portrait_warm_start_manifest_mismatch')
    old=json.loads(Path(manifest_path).read_text());new=scene.dense_metadata
    for key in ('sourceSha256','preparedSha256','localGeometrySha256','K','headToWorldScale'):
        if old.get(key)!=new.get(key):raise ValueError('portrait_warm_start_geometry_mismatch:'+key)
    if old['components']['hair']['sha256']!=new['components']['hair']['sha256']:
        raise ValueError('portrait_warm_start_hair_mismatch')
    state={k[len('portrait.'):]:v for k,v in checkpoint['model'].items() if k.startswith('portrait.')}
    current=scene.portrait.state_dict()
    if set(state)!=set(current):raise ValueError('portrait_warm_start_incomplete_state')
    for key in ('role','source_index','origin_index','generation','hair_base','faces'):
        if not torch.equal(state[key],current[key]):raise ValueError('portrait_warm_start_binding_mismatch:'+key)
    # A trained movable embedding may legitimately walk to an adjacent
    # triangle. Restore the COMPLETE learned chart rather than forcing its
    # initialization IDs back onto the optimized barycentric coordinates.
    ids=state['triangle_ids'];bary=state['embedding']
    if ids.shape!=current['triangle_ids'].shape or ((ids<0)|(ids>=len(state['faces']))).any():
        raise ValueError('portrait_warm_start_invalid_learned_chart')
    if bary.shape!=current['embedding'].shape or not torch.isfinite(bary).all():
        raise ValueError('portrait_warm_start_invalid_embedding')
    scene.portrait.load_state_dict(state,strict=True)
    return {'kind':'complete_head_model_warm_start_new_Adam','sha256':digest(state_path),
            'sourceManifestSha256':digest(manifest_path),'step':checkpoint.get('step')}


def run(args):
    if (getattr(args,'observed_empty_space',False) and not getattr(args,'observed_face_domain',False)
            and args.resume_state is None and not getattr(args,'portrait_state',None)):
        raise ValueError('observed_empty_space_requires_observed_face_domain')
    if args.output.exists(): raise FileExistsError("each_experiment_requires_new_run_directory")
    args.output.mkdir(parents=True)
    started=time.perf_counter();torch.manual_seed(280928)
    torch.set_num_threads(min(6,torch.get_num_threads()))
    if not torch.cuda.is_available():
        write_json(args.output/"status.json",{"status":"GPU_unavailable_not_tested"})
        raise RuntimeError("GPU_unavailable")
    torch.cuda.reset_peak_memory_stats()
    data=load_prepared(args.prepared)
    resume_config=None;checkpoint=None;person_restore=None
    if args.resume_state is not None and getattr(args,'portrait_state',None):
        raise ValueError('resume_cannot_also_warm_start_portrait')
    state_path=args.resume_state or getattr(args,'portrait_state',None)
    if state_path is not None:
        resume_parent=Path(state_path).resolve().parent
        config_file=resume_parent/'config.json'
        if not config_file.is_file():raise ValueError('resume_complete_config_required')
        resume_config=json.loads(config_file.read_text())
        checkpoint=torch.load(state_path,map_location='cpu',weights_only=True)
        for source in (resume_config,checkpoint):
            if source.get('sourceSha256')!=data['sourceHash'] or source.get('engineVersion')!=ENGINE_VERSION:
                raise ValueError('resume_source_or_engine_mismatch')
        # Store-true CLI defaults cannot turn an existing contract off. An
        # explicit true cannot silently enable a new factor in a warm-start.
        for attribute,key,recorded in (
                ('opaque_person','opaquePerson',resume_config.get('opaquePerson',False)),
                ('opaque_body','opaqueBody',resume_config.get('opaqueBody',False)),
                ('observed_face_domain','observedFaceDomain',resume_config.get('observedFaceDomain') is not None),
                ('observed_empty_space','observedEmptySpace',resume_config.get('observedEmptySpace',False)),
                ('surface_footprint','surfaceFootprint',resume_config.get('surfaceFootprint') is not None),
                ('room_window_recovery','roomWindowRecovery',resume_config.get('roomWindowRecovery',False)),
                ('surface_refine','surfaceRefine',resume_config.get('surfaceRefine',False)),
                ('soft','soft',resume_config.get('soft')),
                ('antialiased','antialiased',resume_config.get('antialiased'))):
            # Complete head warm-start may replace only the environment via
            # its already strict geometry/hair contract. Environment stages
            # are explicit new choices, not inherited from the old room.
            if args.resume_state is None and attribute in ('room_window_recovery','surface_refine'):
                continue
            if not isinstance(recorded,bool):raise ValueError('resume_recorded_flag_invalid:'+key)
            if getattr(args,attribute,False) and not recorded:
                raise ValueError('resume_cannot_change_recorded_flag:'+key)
            setattr(args,attribute,recorded)
        from reconstruction_live_face_domain import restore_recorded
        from reconstruction_person_supervision_state import copy_person_supervision_files
        restore_recorded(data,resume_parent,resume_config)
        if data['appearanceHash']!=resume_config.get('appearanceHash'):
            raise ValueError('resume_recorded_appearance_mismatch')
        copy_config=resume_config if args.resume_state is not None else {**resume_config,'roomWindowRecovery':False}
        copy_person_supervision_files(resume_parent,args.output,copy_config)
        original_dense=resume_config.get('denseSurfaces')
        if original_dense:
            manifest=Path(original_dense['manifestPath'])
            if (not manifest.is_file() or digest(manifest)!=checkpoint.get('surfaceContract',{}).get('manifestSha256')
                    or json.loads(manifest.read_text())!=original_dense):
                raise ValueError('resume_original_dense_manifest_missing_or_changed')
            if args.resume_state is not None:
                if getattr(args,'dense_manifest',None) and digest(args.dense_manifest)!=digest(manifest):
                    raise ValueError('resume_cannot_replace_dense_manifest')
                args.dense_manifest=manifest
            elif (not getattr(args,'portrait_manifest',None) or
                  digest(args.portrait_manifest)!=digest(manifest)):
                raise ValueError('portrait_warm_start_original_manifest_required')
            elif not (getattr(args,'dense_manifest',None) or getattr(args,'dense_surfaces',False)):
                raise ValueError('portrait_warm_start_new_environment_manifest_required')
            if args.resume_state is not None and args.room_window_recovery:
                recovery=resume_config.get('roomWindowRecoveryReceipt')
                saved=resume_parent/'room-window-recovery.json'
                if (not isinstance(recovery,dict) or not saved.is_file() or
                        json.loads(saved.read_text())!=recovery or
                        recovery.get('manifestSha256')!=digest(manifest) or
                        recovery.get('result')!=original_dense.get('roomWindowRecovery')):
                    raise ValueError('resume_room_window_recovery_receipt_changed')
        elif args.resume_state is None:
            raise ValueError('portrait_warm_start_original_dense_contract_required')
        elif getattr(args,'dense_manifest',None) or getattr(args,'dense_surfaces',False):
            raise ValueError('resume_cannot_add_dense_initialization')
    elif getattr(args,'observed_face_domain',False):
        if getattr(args,'portrait_state',None):
            raise ValueError('changed_initial_colour_domain_requires_explicit_new_initialization')
        from reconstruction_live_face_domain import activate
        activate(data,args.output,observed_empty_space=bool(getattr(args,'observed_empty_space',False)))
    data["reference"]=max(data["train"],key=lambda n:np.linalg.norm(data["local"][n]["marks"][234]-data["local"][n]["marks"][454])/
        max(np.linalg.norm(data["local"][n]["marks"][10]-data["local"][n]["marks"][152]),1))
    if resume_config is not None:
        reference=checkpoint.get('surfaceContract',{}).get('reference')
        if reference not in data['local'] or reference not in data['worlds']:
            raise ValueError('resume_reference_observation_missing')
        data['reference']=reference
    elif getattr(args,'dense_surfaces',False) or getattr(args,'dense_manifest',None):
        from reconstruction_capture_reference import choose_capture_reference
        data['reference'],reference_receipt=choose_capture_reference(data)
        write_json(args.output/'capture-reference.json',reference_receipt)
    footprint_receipt=resume_config.get('surfaceFootprint') if resume_config is not None else None
    if getattr(args,'surface_footprint',False) and resume_config is None:
        if not getattr(args,'observed_face_domain',False) or args.resume_state or getattr(args,'portrait_state',None):
            raise ValueError('surface_footprint_requires_fresh_observed_face_prior')
        from reconstruction_live_surface_footprint import adapt_observed_surface_footprints
        data['prior'],footprint_receipt,diagnostics=adapt_observed_surface_footprints(
            data['prior'],data,data['geometry'].faces.numpy(),prior_stage='fresh_initialization')
        np.savez_compressed(args.output/'surface-footprint-diagnostics.npz',**diagnostics)
        write_json(args.output/'surface-footprint.json',footprint_receipt)
        # This run's complete fresh prior is authoritative for exact replay;
        # preserve old colour-mask/source identities in its existing receipt.
        prior_path=args.output/'observed-face-initial-appearance.npz'
        np.savez_compressed(prior_path,**data['prior']);data['appearanceHash']=digest(prior_path)
        data['face_domain_receipt']['appearanceSha256']=data['appearanceHash']
        data['face_domain_receipt']['surfaceFootprintSha256']=digest(args.output/'surface-footprint.json')
        write_json(args.output/'observed-face-domain.json',data['face_domain_receipt'])
    if getattr(args,"dense_manifest",None):data["dense_manifest"]=args.dense_manifest
    elif getattr(args,"dense_surfaces",False):
        from reconstruction_live_dense import augment_prepared
        dense_result=augment_prepared(args.prepared,args.output/"dense-surfaces",reference=data["reference"],
            shared_room_surface=bool(getattr(args,'shared_room_surface',False)))
        data["dense_manifest"]=Path(dense_result["manifestPath"])
    recovery_receipt=resume_config.get('roomWindowRecoveryReceipt') if args.resume_state is not None else None
    if getattr(args,'room_window_recovery',False) and args.resume_state is None:
        if 'dense_manifest' not in data:
            raise ValueError('room_window_recovery_requires_dense_surface_contract')
        from reconstruction_live_room_window_recovery import recover_static_window_surfaces
        parent=json.loads(Path(data['dense_manifest']).read_text())
        if 'roomWindowRecovery' in parent:
            recovered=parent
        else:
            recovered=recover_static_window_surfaces(data['dense_manifest'],
                args.output/'room-window-recovery',allow_typed_conditional=True)
            data['dense_manifest']=Path(recovered['manifestPath'])
        from reconstruction_live_room_self_reference import apply_self_reference_correction,AUTHORIZED_POLICY
        recovered=apply_self_reference_correction(data['dense_manifest'],args.output/'room-self-reference',
            authorized_policy=AUTHORIZED_POLICY)
        data['dense_manifest']=Path(recovered['manifestPath'])
        recovery_receipt={'manifestPath':str(data['dense_manifest']),
                          'manifestSha256':digest(data['dense_manifest']),
                          'result':recovered['roomWindowRecovery'],
                          'selfReferenceCorrection':recovered.get('roomSelfReferenceCorrection')}
        write_json(args.output/'room-window-recovery.json',recovery_receipt)
    if args.resume_state is not None:
        surface_report=resume_config.get('surfaceStage',{'status':'recorded_model_only_warm_start'})
    elif getattr(args,"surface_refine",False):
        from reconstruction_observed_surface import prepare_surface_stage
        surface_report=prepare_surface_stage(data,args.output/"surface-support")
    else:surface_report={"status":"control_same_observation_contract"}
    # Existing initializer reads only cloth seeds from its output argument.
    import shutil
    shutil.copyfile(args.prepared/"cloth_supported_seeds.npz",args.output/"cloth_supported_seeds.npz")
    scene=initialize_scene(data,args.output)
    scene.opaque_person=bool(getattr(args,'opaque_person',False))
    # Head supervision passed the fixed-view trial; body supervision is a
    # separate, opt-in experiment because its shared appearance regressed.
    scene.opaque_body=bool(getattr(args,'opaque_body',False))
    if scene.opaque_body and not scene.opaque_person:
        raise ValueError('opaque_body_requires_person_channels')
    opaque_receipts={}
    if scene.opaque_person and resume_config is None:
        from reconstruction_live_opaque_person import prepare_opaque_interiors
        for name,labels in data['labels'].items():
            masks,receipt=prepare_opaque_interiors(labels)
            labels.update(masks);opaque_receipts[name]=receipt
        write_json(args.output/'opaque-interiors.json',opaque_receipts)
    scene.surface_refine=bool(getattr(args,"surface_refine",False))
    if scene.surface_refine and scene.dense_surface:raise ValueError('independent_dense_and_legacy_split_transactions_required')
    scene.portrait.constraint_mode="soft" if args.soft else "strong"
    portrait_start=None
    if getattr(args,'portrait_state',None):
        if not getattr(args,'portrait_manifest',None) or args.resume_state is not None:
            raise ValueError('portrait_warm_start_requires_manifest_and_no_scene_resume')
        portrait_start=warm_start_portrait(scene,data,args.portrait_state,args.portrait_manifest)
    if args.resume_state is not None:
        if scene.dense_surface and not surface_contract_matches(surface_contract(scene,data),checkpoint.get('surfaceContract')):
            raise ValueError('resume_dense_surface_contract_mismatch')
        if 'neck_sh_editable' in checkpoint['model']:
            mask=checkpoint['model']['neck_sh_editable']
            if mask.dtype!=torch.bool or mask.shape!=(len(scene.portrait.role),):raise ValueError('resume_neck_selection_contract')
            scene.register_buffer('neck_sh_editable',mask.to(scene.portrait.sh.device).clone())
        scene.load_state_dict(checkpoint["model"],strict=True)
    if state_path is not None:
        from reconstruction_person_supervision_state import restore_person_supervision
        person_restore=restore_person_supervision(scene,data,resume_parent,resume_config,checkpoint)
    from reconstruction_code_identity import source_identity
    identity=source_identity();freeze=identity["sourceFiles"]
    snapshot=args.output/"algorithm-source";snapshot.mkdir()
    for name in freeze:shutil.copyfile(Path(__file__).parent/name,snapshot/name)
    config={"engineVersion":ENGINE_VERSION,"sourceSha256":data["sourceHash"],"appearanceHash":data["appearanceHash"],
            "prepared":str(args.prepared),"soft":args.soft,"localSteps":args.local_steps,"roomSteps":args.room_steps,"jointSteps":args.joint_steps,
            "antialiased":args.antialiased,"sourceFiles":freeze,"finalAudit":"current_development_not_blind; cross_video_unverified",
            "resumeState":str(args.resume_state) if args.resume_state else None,
            "resumeSha256":digest(args.resume_state) if args.resume_state else None,
            "resumeKind":("model_only_warm_start" if args.resume_state else
                          "complete_head_model_warm_start_new_Adam" if getattr(args,'portrait_state',None) else "new_optimizer"),
            "implementation":identity,"surfaceStage":surface_report,"surfaceRefine":scene.surface_refine,
            "portraitWarmStart":portrait_start,
            "personSupervisionRestore":person_restore,
            "observedFaceDomain":data.get('face_domain_receipt'),
            "observedEmptySpace":bool(getattr(args,'observed_empty_space',False)),
            "hairCompositeSteps":int(getattr(args,'hair_steps',0)),
            "skinCompositingSteps":int(getattr(args,'skin_steps',0)),
            "opaquePerson":scene.opaque_person,
            "opaqueBody":scene.opaque_body,
            "surfaceFootprint":footprint_receipt,
            "roomWindowRecovery":bool(getattr(args,'room_window_recovery',False)),
            "roomWindowRecoveryReceipt":recovery_receipt,
            "opaqueInteriorsReceiptSha256":digest(args.output/'opaque-interiors.json') if scene.opaque_person else None,
            "denseSurfaces":getattr(scene,"dense_metadata",None)}
    write_json(args.output/"config.json",config)
    initial=audit_stages(scene,data,args.output/"initial",antialiased=args.antialiased)
    full_initial=audit_full_scene(scene,data,args.output/"full-initial")
    trainings=[]
    if args.local_steps:
        result,_=train_stage(scene,data,args.output,"local",args.local_steps,args.soft,args.antialiased);trainings.append(result)
        audit_stages(scene,data,args.output/"after-local",antialiased=args.antialiased)
    if args.room_steps:
        if scene.dense_surface:prepare_neck_appearance(scene,data,args.output)
        result,_=train_stage(scene,data,args.output,"T3",args.room_steps,args.soft,args.antialiased);trainings.append(result)
        audit_stages(scene,data,args.output/"after-T3",antialiased=args.antialiased)
    if args.joint_steps:
        result,_=train_stage(scene,data,args.output,"T4",args.joint_steps,args.soft,args.antialiased);trainings.append(result)
    if getattr(args,'hair_steps',0):
        from reconstruction_live_hair_composite import restore_hair_in_scene
        trainings.append(restore_hair_in_scene(scene,data,args.output,args.hair_steps))
    if getattr(args,'skin_steps',0):
        from reconstruction_live_skin_compositing import restore_skin_compositing
        trainings.append(restore_skin_compositing(scene,data,args.output,args.skin_steps))
    final=audit_stages(scene,data,args.output/"final",antialiased=args.antialiased)
    full_final=audit_full_scene(scene,data,args.output/"full-final")
    asset=export_candidate(scene,data,args.output)
    torch.cuda.synchronize()
    report={**config,"status":"research_not_release_approved","plySha256":asset,"initial":initial,"final":final,
            "fullInitial":full_initial,"fullFinal":full_final,
            "trainings":trainings,"seconds":time.perf_counter()-started,"allocatedPeakMiB":torch.cuda.max_memory_allocated()/1024**2,
            "reservedPeakMiB":torch.cuda.max_memory_reserved()/1024**2,"pointCount":len(scene.portrait.role)+len(scene.environment_parts),
            "limitations":["Observed hair surface remains subject to multiview quality checks" if getattr(scene,'dense_hair',False) else "Legacy hair shell remains unaccepted",
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
    p.add_argument("--surface-refine",action="store_true")
    p.add_argument("--dense-surfaces",action="store_true");p.add_argument("--dense-manifest",type=Path)
    p.add_argument('--portrait-state',type=Path);p.add_argument('--portrait-manifest',type=Path)
    p.add_argument('--shared-room-surface',action='store_true');p.add_argument('--hair-steps',type=int,default=0)
    p.add_argument('--observed-face-domain',action='store_true');p.add_argument('--observed-empty-space',action='store_true')
    p.add_argument('--skin-steps',type=int,default=0)
    p.add_argument('--opaque-person',action='store_true')
    p.add_argument('--opaque-body',action='store_true')
    p.add_argument('--surface-footprint',action='store_true')
    p.add_argument('--room-window-recovery',action='store_true')
    run(p.parse_args())
