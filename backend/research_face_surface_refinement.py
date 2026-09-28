"""Isolated E2 nose/lip surface-capacity experiment from frozen head-local SH1.

One source video, fixed train/development split, no product asset replacement.
The full existing head (including unmodified hair/eyewear) remains in every
forward pass.  Training views can receive only a bounded rigid head-pose
correction; all surface corrections are shared across source views.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch

from flame_open_model import FlameOpen, MODEL
from probe_flame_hair_hull import local_observations
from probe_flame_open_fit import HELD, SOURCE_SHA256, TRAIN
from train_flame_local_appearance import (TrainablePortrait, build_candidates,
                                          make_view, quat_multiply, score)


PARAMETERS = ("base_rgb_logits", "sh1", "sh_coeff", "opacity_logits",
              "log_scales", "local_quats", "local_offsets")


def choose_training_views(views: dict[int, object], train_frames: tuple[int, ...],
                          maximum: int = 18) -> tuple[tuple[int, ...], int, dict]:
    """Deterministic pose/clarity selection without capture-specific frame IDs.

    Time-spaced candidates preserve observed directional diversity.  Quality
    gates discard empty, tiny or badly blurred feature regions; the anchor
    favours a large, sharp face for stable source-supported local binding.
    """
    candidates=[]
    for index in train_frames:
        view=views[index]
        mask=feature_mask(view).cpu().numpy().astype(np.uint8)
        gray=cv2.cvtColor(np.uint8(np.clip(view.rgb.cpu().numpy()*255,0,255)),cv2.COLOR_RGB2GRAY)
        lap=cv2.Laplacian(gray,cv2.CV_32F)
        sharp=float(np.median(np.abs(lap[mask>0]))) if mask.any() else 0.
        usable=int(mask.sum())>=180 and view.face_width_px>=100 and sharp>=.25
        candidates.append({"frame":int(index),"noseLipPixels":int(mask.sum()),
                           "faceWidthPx":int(view.face_width_px),"medianLaplacian":sharp,
                           "usable":usable})
    available=[r["frame"] for r in candidates if r["usable"]]
    if len(available)<3:
        raise RuntimeError(f"too_few_clear_source_views_for_surface_refinement:{len(available)}")
    take=np.unique(np.rint(np.linspace(0,len(available)-1,min(maximum,len(available)))).astype(int))
    selected=tuple(available[i] for i in take)
    quality={r["frame"]:r for r in candidates}
    # The anchor is used only to parameterize shared 3D offsets; source
    # support below is voted across all selected observations, so a single
    # favourable angle cannot decide which face points gain capacity.
    anchor=selected[len(selected)//2]
    return selected,anchor,{"candidates":candidates,"selection":selected,"anchor":anchor}


def load_params(model: TrainablePortrait, params: dict,
                order: np.ndarray | None = None) -> None:
    with torch.no_grad():
        for key in PARAMETERS:
            array = params[key] if order is None else params[key][order]
            getattr(model, key).copy_(torch.from_numpy(array).to(model.role.device))
        model.initial_log_scales.copy_(model.log_scales)
        model.initial_rgb.copy_(model.base_rgb_logits)
        model.initial_opacity.copy_(model.opacity_logits)


def feature_mask(view) -> torch.Tensor:
    mask = torch.zeros_like(view.face_skin)
    for name in ("nose", "lips"):
        x0, y0, x1, y1 = view.feature_boxes[name]
        mask[y0:y1, x0:x1] = True
    return mask & view.face_skin


def masked_l1(image: torch.Tensor, source: torch.Tensor,
              mask: torch.Tensor) -> torch.Tensor:
    return ((image-source).abs().mean(2)*mask).sum()/mask.sum().clamp_min(1)


def source_edge_l1(image:torch.Tensor,source:torch.Tensor,
                   mask:torch.Tensor)->torch.Tensor:
    """Compare native source edge gradients without sharpening the output."""
    xm=mask[:,1:]&mask[:,:-1]
    ym=mask[1:,:]&mask[:-1,:]
    dx=((image[:,1:]-image[:,:-1])-(source[:,1:]-source[:,:-1])).abs().mean(2)
    dy=((image[1:]-image[:-1])-(source[1:]-source[:-1])).abs().mean(2)
    return .5*((dx*xm).sum()/xm.sum().clamp_min(1)+
               (dy*ym).sum()/ym.sum().clamp_min(1))


def outside_preservation(image:torch.Tensor,old_image:torch.Tensor,
                         region:torch.Tensor,foreground:torch.Tensor)->torch.Tensor:
    ring=(torch.nn.functional.max_pool2d(region.float()[None,None],
        kernel_size=23,stride=1,padding=11)[0,0]>.5)&~region&foreground
    farther=foreground&~region&~ring
    delta=(image-old_image).abs().mean(2)
    return .55*(delta*ring).sum()/ring.sum().clamp_min(1)+\
           .25*(delta*farther).sum()/farther.sum().clamp_min(1)


def small_rotation(vector: torch.Tensor) -> torch.Tensor:
    theta = torch.linalg.vector_norm(vector).clamp_min(1e-9)
    unit = vector/theta
    x,y,z = unit.unbind()
    zero = x*0
    skew = torch.stack((zero,-z,y,z,zero,-x,-y,x,zero)).reshape(3,3)
    eye = torch.eye(3,device=vector.device)
    return eye+torch.sin(theta)*skew+(1-torch.cos(theta))*(skew@skew)


def posed_view(view, pose: torch.Tensor):
    # pose is unconstrained; tanh keeps <= 1 degree and <= 1.5 mm.  The
    # operation is differentiable through all existing Gaussian parameters.
    rot = torch.tanh(pose[:3])*math.radians(1.)
    shift = torch.tanh(pose[3:])*.0015
    R = small_rotation(rot)
    pivot = view.base[view.base[:,2]>.04].median(dim=0).values.detach()
    base = (view.base-pivot)@R.T+pivot+shift
    normals = view.normals@R.T
    theta = torch.linalg.vector_norm(rot).clamp_min(1e-9)
    q = torch.cat((torch.cos(theta/2)[None], rot/theta*torch.sin(theta/2)))
    return replace(view, base=base, normals=normals,
                   root_rotation=R@view.root_rotation,
                   root_quat=quat_multiply(q, view.root_quat))


def fit_bounded_poses(portrait, views: dict[int, object],
                      pose_frames: tuple[int, ...]) -> tuple[dict[int, object],dict]:
    result = dict(views)
    changes = {}
    for index in pose_frames:
        view = views[index]
        mask = feature_mask(view)
        if int(mask.sum()) < 100:
            continue
        raw = torch.nn.Parameter(torch.zeros(6,device=view.rgb.device))
        optimizer = torch.optim.Adam([raw],lr=.11)
        with torch.no_grad():
            initial_img, _, _ = portrait.raster(view)
            before = float(masked_l1(initial_img[:,:,:3],view.rgb,mask))
        for _ in range(16):
            variant = posed_view(view, raw)
            image, alpha, _ = portrait.raster(variant)
            loss = masked_l1(image[:,:,:3],view.rgb,mask)
            loss += .12*(raw[:3].tanh().square().mean()+raw[3:].tanh().square().mean())
            loss += .03*((1-alpha).square()*mask).sum()/mask.sum()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        final = posed_view(view,raw.detach())
        with torch.no_grad():
            final_img,_,_ = portrait.raster(final)
            after = float(masked_l1(final_img[:,:,:3],view.rgb,mask))
        # Failure is explicit; never let a fit deteriorating the measured
        # stable skin region contaminate the shared geometry stage.
        accepted = after < before-.0001
        if accepted:
            result[index] = replace(final, base=final.base.detach(),
                normals=final.normals.detach(), root_rotation=final.root_rotation.detach(),
                root_quat=final.root_quat.detach())
        changes[str(index)]={"before":before,"after":after,"accepted":accepted,
            "rotationDegrees":(torch.tanh(raw[:3]).detach().cpu().numpy()*1.).tolist(),
            "translationMm":(torch.tanh(raw[3:]).detach().cpu().numpy()*1.5).tolist()}
    return result,changes


def region_indices(candidate:dict,view)->tuple[np.ndarray,dict]:
    base=view.base.cpu().numpy(); K=view.K.cpu().numpy(); z=base[:,2]
    xy=base[:,:2]/np.maximum(z[:,None],1e-6)*np.array([K[0,0],K[1,1]])+np.array([K[0,2],K[1,2]])
    selected=np.zeros(len(z),bool); per_region={}
    for label in ("nose","lips"):
        x0,y0,x1,y1=view.feature_boxes[label]
        inside=(candidate["roles"]==0)&(candidate["confidence"]>=2)&(z>.04)&(
            xy[:,0]>=x0)&(xy[:,0]<x1)&(xy[:,1]>=y0)&(xy[:,1]<y1)
        xi=np.clip(np.rint(xy[:,0]).astype(int),0,view.rgb.shape[1]-1)
        yi=np.clip(np.rint(xy[:,1]).astype(int),0,view.rgb.shape[0]-1)
        inside &= view.face_skin.cpu().numpy()[yi,xi]
        selected |= inside
        per_region[label]=int(inside.sum())
    return np.flatnonzero(selected),per_region


def source_residual_priority(candidate:dict,views:dict[int,object],
                             frames:tuple[int,...],images:dict[int,torch.Tensor])->np.ndarray:
    """Give capacity to supported native-image residuals and real edges."""
    n=len(candidate["roles"])
    score=np.zeros(n,np.float32)
    votes=np.zeros(n,np.uint16)
    for frame in frames:
        view=views[frame]
        ids,_=region_indices(candidate,view)
        if not len(ids):continue
        xyz=view.base[ids].cpu().numpy();K=view.K.cpu().numpy()
        xy=xyz[:,:2]/np.maximum(xyz[:,2:],1e-8)*np.array([K[0,0],K[1,1]])+np.array([K[0,2],K[1,2]])
        x=np.clip(np.rint(xy[:,0]).astype(int),1,view.rgb.shape[1]-2)
        y=np.clip(np.rint(xy[:,1]).astype(int),1,view.rgb.shape[0]-2)
        source=view.rgb.cpu().numpy();baseline=images[frame][:,:,:3].cpu().numpy()
        residual=np.abs(source[y,x]-baseline[y,x]).mean(1)
        source_edge=.5*(np.abs(source[y,x+1]-source[y,x-1]).mean(1)+
                        np.abs(source[y+1,x]-source[y-1,x]).mean(1))
        score[ids]+=np.minimum(residual,.12)+.2*np.minimum(source_edge,.08)
        votes[ids]+=1
    result=score/np.maximum(votes,1)
    result*=np.sqrt(np.maximum(votes,1))*np.sqrt(candidate["confidence"].astype(np.float32))
    return result


def split_surface(candidate:dict,params:dict,picked:np.ndarray,
                  priority:np.ndarray,max_new:int,
                  replace_parent:bool=False)->tuple[dict,dict,dict,np.ndarray]:
    """One local child per source-supported parent; all indexing survives."""
    old_surface=int(candidate["surface_count"]); n=len(candidate["roles"])
    picked=picked[picked<old_surface]
    # Fair bounded allocation: strongest direct source support, deterministic.
    picked=picked[np.argsort(priority[picked])[::-1]][:max_new]
    picked=np.sort(picked).astype(np.int64)
    if len(picked)<25:
        raise RuntimeError(f"insufficient_two_view_supported_skin:{len(picked)}")
    order=np.concatenate((np.arange(old_surface),picked,np.arange(old_surface,n)))
    new={key:value for key,value in candidate.items()}
    new["surface_count"]=old_surface+len(picked)
    new["surface_ids"]=candidate["surface_ids"][np.concatenate((np.arange(old_surface),picked))].copy()
    old_bary=candidate["surface_bary"][picked].copy()
    # Both children stay on the same observed FLAME triangle.  In the new
    # ablation the original coarse parent basis is replaced by two symmetric
    # child bases; retaining it would let the old wide footprint keep hiding
    # high-frequency source pixels.  Existing research runs keep old logic.
    def shifted(bary:np.ndarray,delta:float)->np.ndarray:
        out=bary.copy()
        out[:,0]=np.clip(out[:,0]+delta,.003,1)
        out[:,1]=np.clip(out[:,1]-delta,.003,1)
        return out/out.sum(axis=1,keepdims=True)
    moved=shifted(old_bary,.022)
    main_bary=candidate["surface_bary"].copy()
    if replace_parent:
        main_bary[picked]=shifted(old_bary,-.022)
    new["surface_bary"]=np.concatenate((main_bary,moved))
    for key in ("roles","initial_rgb","initial_scale","source_index","origin_index","confidence"):
        new[key]=candidate[key][order].copy()
    new["counts"]={**candidate["counts"],"skin":int((new["roles"]==0).sum())}
    expanded={key:params[key][order].copy() for key in PARAMETERS}
    parent_pos=picked
    child_pos=old_surface+np.arange(len(picked))
    original_alpha=1/(1+np.exp(-params["opacity_logits"][picked]))
    # Equal centre transmittance is only an initialization.  Pixelwise alpha
    # is not equivalent away from the centre, so later optimize alpha against
    # both the source foreground and the frozen pre-split coverage map.
    half=1-np.sqrt(1-original_alpha)
    logit=np.log(np.clip(half,1e-5,1-1e-5)/np.clip(1-half,1e-5,1-1e-5))
    expanded["opacity_logits"][parent_pos]=logit
    expanded["opacity_logits"][child_pos]=logit
    extra={"oldPoints":n,"newPoints":len(order),"newSkin":len(picked),
        "maxBarycentricChildShift":float(np.abs(old_bary-moved).max()),
        "coarseParentBasisReplaced":replace_parent,
        "sourceIdsPreserved":bool(np.array_equal(new["source_index"][child_pos],
                                                   candidate["source_index"][picked])),
        "originIdsPreserved":bool(np.array_equal(new["origin_index"][child_pos],
                                                   candidate["origin_index"][picked])),
        "opacityCenterTransmittanceInitialization":True,
        "optimizerState":"fresh Adam from frozen checkpoint; no inherited state to reorder"}
    return new,expanded,extra,picked


def add_shared_field(portrait,view,selected,old_surface)->dict:
    # Local-centre coordinates are a deterministic source-index support set.
    base=view.base.cpu().numpy()
    centers=base[selected[np.linspace(0,len(selected)-1,12,dtype=int)]]
    d=np.linalg.norm(base[:,None,:]-centers[None,:,:],axis=2)
    basis=np.exp(-.5*(d/.012)**2).astype(np.float32)
    region=np.zeros(len(base),np.float32)
    region[selected]=1
    # The compact support field is confined to the new split parents and
    # immediate skin neighbours.  Wide feature boxes are *observation*
    # regions, not permission to reshape half the face.
    surface_count=int((portrait.role!=2).sum())
    neighbour=np.exp(-.5*(d[:surface_count].min(axis=1)/.008)**2).astype(np.float32)
    neighbour[d[:surface_count].min(axis=1)>.016]=0
    region[:surface_count]=np.maximum(region[:surface_count],neighbour)
    region[portrait.role.cpu().numpy()!=0]=0
    basis*=region[:,None]
    basis/=np.maximum(basis.sum(axis=1,keepdims=True),1)
    portrait.register_buffer("research_surface_basis",torch.from_numpy(basis).to(view.rgb.device))
    portrait.research_surface_controls=torch.nn.Parameter(torch.zeros(12,device=view.rgb.device))
    return {"controlCount":12,"maximumPerControlNormalMm":1.5,
            "affectedSkinPoints":int((basis.sum(1)>.01).sum())}


def fold_shared_field(portrait)->dict:
    with torch.no_grad():
        role=portrait.role
        limits=torch.where(role==0,.006,torch.where(role==1,.012,.018))
        before=torch.tanh(portrait.local_offsets[:,0])*limits
        residual=.0015*(portrait.research_surface_basis@torch.tanh(portrait.research_surface_controls))
        merged=(before+residual).clamp(-.97*limits,.97*limits)
        portrait.local_offsets[:,0]=torch.atanh(merged/limits)
        result={"meanAbsoluteNormalChangeMm":float(residual.abs().mean()*1000),
                "maximumAbsoluteNormalChangeMm":float(residual.abs().max()*1000),
                "controlValues":portrait.research_surface_controls.detach().cpu().tolist()}
        del portrait.research_surface_basis
        del portrait.research_surface_controls
    return result


def roi_metrics(model,view)->dict:
    with torch.no_grad():
        rgb,alpha,_=model.raster(view)
        mask=feature_mask(view)
        return {"noseLipFixedSkinRgbL1":float(masked_l1(rgb[:,:,:3],view.rgb,mask)),
                "noseLipNativeEdgeL1":float(source_edge_l1(rgb[:,:,:3],view.rgb,mask)),
                "noseLipAlphaCoverageAbove02":float(((alpha>.2)&mask).sum()/mask.sum()),
                "noseLipMeanAlpha":float((alpha*mask).sum()/mask.sum()),
                "full":score(model,view)}


def save_pair(out:Path,frame:int,view,baseline,candidate)->None:
    src=(view.rgb.cpu().numpy()*255).clip(0,255).astype(np.uint8)
    a=(baseline[:,:,:3].cpu().numpy()*255).clip(0,255).astype(np.uint8)
    b=(candidate[:,:,:3].cpu().numpy()*255).clip(0,255).astype(np.uint8)
    for label in ("nose","lips"):
        x0,y0,x1,y1=view.feature_boxes[label]
        strip=np.concatenate((src[y0:y1,x0:x1],a[y0:y1,x0:x1],b[y0:y1,x0:x1]),axis=1)
        cv2.imwrite(str(out/f"private-frame-{frame:04d}-{label}-source-baseline-candidate.png"),
                    cv2.cvtColor(strip,cv2.COLOR_RGB2BGR))


def run(job:Path,baseline_path:Path,run_id:str,steps:int,
        edge_weight:float=0.,geometry_warmup:int=0,
        max_new_skin:int=220,replace_parent:bool=False)->dict:
    start=time.perf_counter()
    with np.load(baseline_path) as data:
        params={k:data[k] for k in data.files}
    source_hash=hashlib.sha256((job/"capture.mp4").read_bytes()).hexdigest()
    if source_hash!=str(params["source_sha256"]):
        raise ValueError("candidate_source_does_not_match_capture")
    if str(params["color_mode"])!="head-local-sh1":
        raise ValueError("corrected_color_baseline_required")
    if not 0<=edge_weight<=.25 or not 0<=geometry_warmup<=200:
        raise ValueError("refinement_budget_out_of_range")
    if not 50<=max_new_skin<=1200:
        raise ValueError("local_split_budget_out_of_range")
    root=job/"flame_open_e2_20260927"
    out=root/f"private-face-surface-{run_id}"
    if out.exists():
        raise FileExistsError(out)
    out.mkdir()
    torch.manual_seed(260927)
    np.random.seed(260927)
    if not torch.cuda.is_available():
        raise RuntimeError("cuda_unavailable")
    torch.cuda.reset_peak_memory_stats()
    device=torch.device("cuda")
    geometry=FlameOpen(24,12,model_path=MODEL).to(device)
    candidate=build_candidates(job,geometry,device)
    for a,b in (("role","roles"),("surface_ids","surface_ids"),("surface_bary","surface_bary")):
        if not np.array_equal(params[a],candidate[b]):
            raise ValueError(f"binding_changed:{a}")
    fit=dict(np.load(root/"private-fit-parameters.npz"))
    held=dict(np.load(root/"private-held-local-parameters.npz"))
    observations=local_observations(root)
    train_frames=tuple(int(v) for v in fit["train_frame_indices"])
    held_frames=tuple(int(v) for v in held["held_frame_indices"])
    if train_frames!=TRAIN or held_frames!=HELD:
        raise ValueError("current_E2_source_adapter_frame_contract_changed")
    frames=set(train_frames)|set(held_frames)
    views={i:make_view(job,geometry,fit,held,candidate,i,observations[i],device) for i in frames}
    selected_frames,anchor,view_selection=choose_training_views(views,train_frames)
    pose_frames=selected_frames
    detail_frames=selected_frames
    baseline=TrainablePortrait(candidate,device,"head-local-sh1").to(device)
    load_params(baseline,params)
    before={i:roi_metrics(baseline,views[i]) for i in held_frames}
    baseline_images={}
    baseline_alpha={}
    with torch.no_grad():
        for i in frames:
            image,alpha,_=baseline.raster(views[i])
            baseline_images[i]=image.detach()
            baseline_alpha[i]=alpha.detach()
    posed,pose_log=fit_bounded_poses(baseline,views,pose_frames)
    with torch.no_grad():
        for i in pose_frames:
            if pose_log.get(str(i),{}).get("accepted"):
                image,alpha,_=baseline.raster(posed[i])
                baseline_images[i]=image.detach()
                baseline_alpha[i]=alpha.detach()
    # A face point must lie in the feature region under >=2 distinct source
    # views.  This is a reusable multi-view visibility rule, independent of
    # any frame number or one chosen capture direction.
    region_votes=np.zeros(len(candidate["roles"]),np.uint16)
    per_view_regions={}
    for i in detail_frames:
        local_indices,local_counts=region_indices(candidate,views[i])
        region_votes[local_indices]+=1
        per_view_regions[str(i)]=local_counts
    selected=np.flatnonzero(region_votes>=2)
    region_counts={"multiViewSupportedPoints":int(len(selected)),
                   "perTrainingView":per_view_regions}
    residual_priority=source_residual_priority(candidate,views,detail_frames,baseline_images)
    candidate2,expanded,split_event,split_parents=split_surface(
        candidate,params,selected,residual_priority,max_new_skin,
        replace_parent=replace_parent)
    views2={i:make_view(job,geometry,fit,held,candidate2,i,observations[i],device) for i in frames}
    # Apply the accepted small camera correction to both original and child
    # means by its recorded pose; the correction is fitted on TRAIN only.
    for i in pose_frames:
        if pose_log.get(str(i),{}).get("accepted"):
            raw=np.arctanh(np.clip(np.radians(pose_log[str(i)]["rotationDegrees"])/math.radians(1.),-.999,.999))
            tran=np.arctanh(np.clip(np.array(pose_log[str(i)]["translationMm"])/1.5,-.999,.999))
            v=posed_view(views2[i],torch.tensor(np.concatenate((raw,tran)),device=device,dtype=torch.float32))
            views2[i]=replace(v,base=v.base.detach(),normals=v.normals.detach(),
                root_rotation=v.root_rotation.detach(),root_quat=v.root_quat.detach())
    candidate_model=TrainablePortrait(candidate2,device,"head-local-sh1").to(device)
    load_params(candidate_model,expanded)
    # A source-driven local split receives a local footprint, selected with
    # training images alone.  Reject sizes that lose alpha coverage or make
    # the full training ROI materially worse *before* colour optimization.
    affected=np.concatenate((split_parents,
        candidate["surface_count"]+np.arange(len(split_parents))))
    scale_trials=[]
    chosen_factor=1.
    train_baseline={i:roi_metrics(baseline,posed[i]) for i in detail_frames}
    for factor in (.70,.80,.90,1.):
        with torch.no_grad():
            candidate_model.log_scales.copy_(torch.from_numpy(expanded["log_scales"]).to(device))
            candidate_model.log_scales[affected]+=math.log(factor)
        trial=[roi_metrics(candidate_model,views2[i]) for i in detail_frames]
        alpha_delta=float(np.mean([trial[j]["noseLipMeanAlpha"]-
                   train_baseline[i]["noseLipMeanAlpha"] for j,i in enumerate(detail_frames)]))
        coverage_delta=float(np.mean([trial[j]["full"]["fixedRoiAlphaCoverage"]-
                   train_baseline[i]["full"]["fixedRoiAlphaCoverage"] for j,i in enumerate(detail_frames)]))
        rgb_delta=float(np.mean([trial[j]["full"]["fixedRoiRgbL1IncludingMissing"]-
                   train_baseline[i]["full"]["fixedRoiRgbL1IncludingMissing"] for j,i in enumerate(detail_frames)]))
        accepted=alpha_delta>=-.02 and coverage_delta>=-.001 and rgb_delta<=.0015
        scale_trials.append({"factor":factor,"trainMeanAlphaDelta":alpha_delta,
            "trainFullCoverageDelta":coverage_delta,"trainFullRgbL1Delta":rgb_delta,
            "accepted":accepted})
        if accepted:
            chosen_factor=factor
            break
    with torch.no_grad():
        candidate_model.log_scales.copy_(torch.from_numpy(expanded["log_scales"]).to(device))
        candidate_model.log_scales[affected]+=math.log(chosen_factor)
    expanded["log_scales"][affected]+=math.log(chosen_factor)
    split_event["trainingOnlyFootprintTrials"]=scale_trials
    split_event["selectedLocalScaleFactor"]=chosen_factor
    split_metrics={i:roi_metrics(candidate_model,views2[i]) for i in held_frames}
    shared=add_shared_field(candidate_model,views2[anchor],split_parents,candidate2["surface_count"])
    # Appearance stays fixed while the low-dimensional shared surface first
    # explains source gradients.  This separates geometric alignment from
    # later colour fitting and remains bounded by the same normal field.
    warmup_curve=[]
    if geometry_warmup:
        for name in PARAMETERS:
            getattr(candidate_model,name).requires_grad_(False)
        geo_opt=torch.optim.Adam([candidate_model.research_surface_controls],lr=.035)
        for step in range(geometry_warmup):
            i=detail_frames[step%len(detail_frames)]
            view=views2[i]
            image,alpha,_=candidate_model.raster(view)
            region=feature_mask(view)
            color=masked_l1(image[:,:,:3],view.rgb,region)
            edge=source_edge_l1(image[:,:,:3],view.rgb,region)
            preserve=outside_preservation(image[:,:,:3],baseline_images[i][:,:,:3],
                                          region,view.foreground)
            cover=((alpha-baseline_alpha[i]).square()*region).sum()/region.sum()
            shape=.008*candidate_model.research_surface_controls.square().mean()
            loss=color+edge_weight*edge+.22*cover+preserve+shape
            geo_opt.zero_grad(set_to_none=True)
            loss.backward()
            geo_opt.step()
            if step%max(1,geometry_warmup//8)==0 or step==geometry_warmup-1:
                warmup_curve.append({"step":step+1,"frame":i,"loss":float(loss.detach()),
                                     "sourceRgb":float(color.detach()),"sourceEdge":float(edge.detach())})
    train_mask=np.zeros(len(candidate2["roles"]),bool)
    train_mask[split_parents]=True
    train_mask[candidate["surface_count"]:candidate2["surface_count"]]=True
    mask=torch.from_numpy(train_mask).to(device)
    for name in PARAMETERS:
        p=getattr(candidate_model,name)
        if name in ("sh_coeff","opacity_logits","log_scales"):
            p.requires_grad_(True)
            p.register_hook(lambda grad,m=mask:grad*m.reshape((-1,)+(1,)*(grad.ndim-1)))
        else:
            p.requires_grad_(False)
    opt=torch.optim.Adam([
        {"params":[candidate_model.sh_coeff],"lr":.0015},
        {"params":[candidate_model.opacity_logits],"lr":.004},
        {"params":[candidate_model.log_scales],"lr":.0005},
        {"params":[candidate_model.research_surface_controls],"lr":.025},
    ])
    curve=[]
    for step in range(steps):
        i=detail_frames[step%len(detail_frames)]
        view=views2[i]
        image,alpha,_=candidate_model.raster(view)
        mask_roi=feature_mask(view)
        color=masked_l1(image[:,:,:3],view.rgb,mask_roi)
        edge=source_edge_l1(image[:,:,:3],view.rgb,mask_roi)
        preserve=outside_preservation(image[:,:,:3],baseline_images[i][:,:,:3],
                                      mask_roi,view.foreground)
        # The pre-split alpha map is fixed, and retains the old full-person
        # rasterization; it guards against numerical improvement via pinholes.
        cover=((alpha-baseline_alpha[i]).square()*mask_roi).sum()/mask_roi.sum()
        source_cover=(((1-alpha).square())*mask_roi).sum()/mask_roi.sum()
        shape=.003*candidate_model.research_surface_controls.square().mean()
        scale=.0005*(candidate_model.log_scales[mask]-
                       torch.from_numpy(expanded["log_scales"][mask.cpu().numpy()]).to(device)).square().mean()
        loss=color+edge_weight*edge+.22*cover+.035*source_cover+preserve+shape+scale
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        if step%max(1,steps//12)==0 or step==steps-1:
            curve.append({"step":step+1,"frame":i,"loss":float(loss.detach()),
                          "sourceRgb":float(color.detach()),"sourceEdge":float(edge.detach()),
                          "outsideBaselinePreservation":float(preserve.detach()),
                          "preSplitAlphaPenalty":float(cover.detach()),
                          "normalControlsL2":float(shape.detach())})
    normal_event=fold_shared_field(candidate_model)
    after={i:roi_metrics(candidate_model,views2[i]) for i in held_frames}
    visual_frames=tuple(dict.fromkeys((selected_frames[0],selected_frames[len(selected_frames)//2],
                                       selected_frames[-1],held_frames[0],
                                       held_frames[len(held_frames)//2],held_frames[-1])))
    for i in visual_frames:
        with torch.no_grad():
            image,_,_=candidate_model.raster(views2[i])
        save_pair(out,i,views[i],baseline_images[i],image)
    np.savez_compressed(out/"private-candidate-parameters.npz",
        source_sha256=np.asarray(source_hash),model_sha256=np.asarray(geometry.model_sha256),
        model_variant=np.asarray("open"),color_mode=np.asarray("head-local-sh1"),
        role=candidate2["roles"],source_index=candidate2["source_index"],
        origin_index=candidate2["origin_index"],source_confidence=candidate2["confidence"],
        surface_ids=candidate2["surface_ids"],surface_bary=candidate2["surface_bary"],
        hair_local_points=candidate2["hair_points"],
        **{k:getattr(candidate_model,k).detach().cpu().numpy() for k in PARAMETERS})
    torch.cuda.synchronize()
    summary={"status":"isolated_local_face_research_candidate_not_for_delivery",
        "runId":run_id,"sourceSha256":source_hash,
        "baselineSha256":hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        "modelSha256":geometry.model_sha256,"trainPoseFrames":pose_frames,
        "trainDetailFrames":detail_frames,"developmentFrames":held_frames,
        "viewSelection":view_selection,"visualFrames":visual_frames,
        "regionPointCounts":region_counts,"pose":pose_log,"split":split_event,
        "sharedField":{**shared,**normal_event},"actualDetailOptimizerSteps":steps,
        "actualGeometryWarmupSteps":geometry_warmup,"edgeWeight":edge_weight,
        "maxNewSkinBudget":max_new_skin,
        "coarseParentBasisReplaced":replace_parent,
        "baselineDevelopment":before,"afterSplitDevelopment":split_metrics,
        "finalDevelopment":after,"curve":curve,"geometryWarmupCurve":warmup_curve,
        "elapsedSeconds":time.perf_counter()-start,
        "peakAllocatedMiB":torch.cuda.max_memory_allocated()/1024**2,
        "peakReservedMiB":torch.cuda.max_memory_reserved()/1024**2,
        "candidateSha256":hashlib.sha256((out/"private-candidate-parameters.npz").read_bytes()).hexdigest(),
        "limits":["E2 head-only; no neck/shoulder/room", "Held images contribute no gradient, pose fit, color or source selection",
                  "Held development frames have already informed prior method choices",
                  "Shape field is shared and bounded, not measured skin microgeometry",
                  "A full-scene release or device transfer is prohibited without E1-E5 gates"]}
    (out/"audit.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps({"status":summary["status"],"candidateSha256":summary["candidateSha256"],
        "split":split_event,"meanHeldRoiBefore":float(np.mean([v["noseLipFixedSkinRgbL1"] for v in before.values()])),
        "meanHeldRoiAfter":float(np.mean([v["noseLipFixedSkinRgbL1"] for v in after.values()])),
        "elapsedSeconds":summary["elapsedSeconds"],"peakAllocatedMiB":summary["peakAllocatedMiB"]},indent=2))
    return summary


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("job",type=Path)
    p.add_argument("baseline",type=Path)
    p.add_argument("--run-id",required=True)
    p.add_argument("--steps",type=int,default=260)
    p.add_argument("--edge-weight",type=float,default=0.)
    p.add_argument("--geometry-warmup",type=int,default=0)
    p.add_argument("--max-new-skin",type=int,default=220)
    p.add_argument("--replace-parent",action="store_true")
    a=p.parse_args()
    run(a.job,a.baseline,a.run_id,a.steps,a.edge_weight,a.geometry_warmup,
        a.max_new_skin,a.replace_parent)
