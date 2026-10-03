"""Automatic per-capture observations for portrait-first test reconstruction.

No identity, camera or colour is borrowed from another recording. Static
camera recovery excludes the full person; local FLAME observations do not
need a world camera. Results remain explicitly unaccepted research assets.
"""
from pathlib import Path
import json
import random
import shutil
import time

import cv2
import numpy as np
import pycolmap
import torch
import torch.nn.functional as fn

from appearance_direction_contract import C0
from flame_open_model import FlameOpen, MODEL
from probe_flame_observations import root_neutral_contract
from probe_flame_real_appearance import barycentric_samples, bound_points
from components_v2 import (camera_matrix, make_masks, rectified_data,
    shared_scene_scale, source_camera, triangulated_component, write_json)
from joint_visibility import sha256_file
from scene import supported_static_surfaces


def selected_names(names, limit=32):
    names=sorted(names)
    return [names[i] for i in np.unique(np.linspace(0,len(names)-1,min(limit,len(names))).round().astype(int))]


def capture_observation_names(names, landmarks, limit=32, neighbours=4):
    """Global viewing coverage plus a short contiguous frontal body window.

    The old uniform-only sample can leave two seconds between neighbours and
    thus no usable near-rigid clothing window. These are real named source
    observations, not interpolated cameras. SfM/PnP may still reject any one.
    """
    names=sorted(names)
    chosen=set(selected_names(names,limit))
    def score(name):
        m=np.asarray(landmarks[name])
        if m.ndim!=2 or len(m)<=454 or not np.isfinite(m).all():
            return -np.inf
        return float(np.linalg.norm(m[234]-m[454])/max(np.linalg.norm(m[10]-m[152]),1.))
    reference=max(names,key=score)
    at=names.index(reference)
    chosen.update(names[max(0,at-neighbours):min(len(names),at+neighbours+1)])
    return [n for n in names if n in chosen],reference


def recover_static(source,names,out):
    database=out/"static.db"
    sparse=out/"sparse"
    sparse.mkdir()
    reader=pycolmap.ImageReaderOptions(mask_path=source/"static_feature_masks")
    extract=pycolmap.FeatureExtractionOptions(num_threads=6,max_image_size=1600)
    extract.sift.max_num_features=4500
    pycolmap.extract_features(database,source/"frames",image_names=names,
        camera_mode=pycolmap.CameraMode.SINGLE,reader_options=reader,
        extraction_options=extract,device=pycolmap.Device.cpu)
    pycolmap.match_sequential(database,pairing_options=pycolmap.SequentialPairingOptions(
        overlap=10,quadratic_overlap=True,num_threads=6),device=pycolmap.Device.cpu)
    options=pycolmap.IncrementalPipelineOptions(num_threads=6,max_runtime_seconds=180)
    models=pycolmap.incremental_mapping(database,source/"frames",sparse,options=options)
    if not models:
        raise ValueError("portrait_test_static_map_not_recovered")
    model=max(models.values(),key=lambda m:(m.num_reg_images(),m.num_points3D()))
    if model.num_reg_images()<6:
        raise ValueError("portrait_test_static_views_insufficient")
    model.write(sparse/"0")
    return model


def fit_local(rgb,labels,marks,K,steps=260,checkpoint_path=None,source_hash=None,development_names=None):
    model=FlameOpen(24,12,model_path=MODEL).cuda()
    zeros=torch.zeros(1,5,3,device="cuda")
    with torch.no_grad():
        _,neutral=model(torch.zeros(1,24,device="cuda"),torch.zeros(1,12,device="cuda"),zeros)
    neutral=neutral[0].cpu().numpy()
    indices=model.landmark_indices.cpu().numpy()
    fit=np.arange(len(indices))%5!=0
    records={}
    rejected={}
    for name in rgb:
        observed=marks[name][indices].astype(np.float64)
        ok,r,t,inliers=cv2.solvePnPRansac(neutral[fit].astype(np.float64),observed[fit],K,np.zeros(5),
            iterationsCount=250,reprojectionError=12.,confidence=.999,flags=cv2.SOLVEPNP_EPNP)
        if not ok or inliers is None or len(inliers)<35:
            rejected[name]="local_landmark_pnp_support"
            continue
        r,t=cv2.solvePnPRefineLM(neutral[fit][inliers[:,0]].astype(np.float64),observed[fit][inliers[:,0]],K,np.zeros(5),r,t)
        root=(model.joint_regressor@model.template)[0].detach().cpu().numpy()
        translation=t[:,0]+cv2.Rodrigues(r)[0]@root-root
        records[name]=(observed,r[:,0],translation)
    names=list(records)
    if len(names)<8:
        raise ValueError("portrait_test_local_views_insufficient")
    development=set(names[3::5] if development_names is None else development_names)&set(names)
    train=[n for n in names if n not in development]
    # Shared shape uses training observations only. All local poses are
    # independently solved; missing frames are omitted with a reason.
    shape=torch.nn.Parameter(torch.zeros(1,24,device="cuda"))
    expression=torch.nn.Parameter(torch.zeros(len(names),12,device="cuda"))
    pose=torch.nn.Parameter(torch.zeros(len(names),5,3,device="cuda"))
    translation=torch.nn.Parameter(torch.tensor(np.stack([records[n][2] for n in names]),device="cuda",dtype=torch.float32))
    with torch.no_grad():
        pose[:,0]=torch.tensor(np.stack([records[n][1] for n in names]),device="cuda")
    init_pose=pose.detach().clone()
    init_t=translation.detach().clone()
    target=torch.tensor(np.stack([records[n][0] for n in names]),device="cuda",dtype=torch.float32)
    train_rows=torch.tensor([names.index(n) for n in train],device="cuda")
    subset=torch.tensor(fit,device="cuda")
    intrinsic=torch.tensor(K,device="cuda",dtype=torch.float32)
    opt=torch.optim.Adam([{"params":[shape],"lr":.012},{"params":[expression],"lr":.018},
        {"params":[pose],"lr":.0012},{"params":[translation],"lr":.0007}])
    history=[]
    def save_fit_state(path,completed):
        if path is None:
            return
        def cpu(value):
            if isinstance(value,torch.Tensor):
                return value.detach().cpu().clone()
            if isinstance(value,dict):
                return {key:cpu(item) for key,item in value.items()}
            if isinstance(value,list):
                return [cpu(item) for item in value]
            if isinstance(value,tuple):
                return tuple(cpu(item) for item in value)
            return value
        torch.save(cpu({"schemaVersion":1,"kind":"capture-local-landmark-fit-state",
            "sourceHash":source_hash,"modelPath":str(MODEL),"modelSha256":model.model_sha256,
            "stepsCompleted":completed,"stepsPlanned":steps,"names":names,
            "roles":["development" if n in development else "train" for n in names],
            "shape":shape,"expression":expression,"pose":pose,"translation":translation,
            "initPose":init_pose,"initTranslation":init_t,"K":intrinsic,
            "targetLandmarks":target,"fitLandmarkMask":subset,"sourceLandmarkIndices":indices,
            "optimizer":opt.state_dict(),"history":history,
            "rng":{"python":random.getstate(),"numpy":np.random.get_state(),
                "torch":torch.get_rng_state(),"cuda":torch.cuda.get_rng_state_all()},
            "resumeBoundary":"landmark_fit_after_recorded_pnp_not_original_ransac_replay",
            "colourTraining":False}),Path(path))
    if checkpoint_path is not None:
        checkpoint_path=Path(checkpoint_path)
        save_fit_state(checkpoint_path.with_name("local-fit-init.pt"),0)
    for step in range(steps):
        # Development shape is detached, while its own pose/expression may
        # use landmarks. Its colour is never used for appearance training.
        shapes=shape.expand(len(names),-1).clone()
        held_rows=[i for i,n in enumerate(names) if n in development]
        shapes[held_rows]=shape.detach()
        _,points=model(shapes,expression,pose)
        cam=points+translation[:,None]
        uv=cam@intrinsic.T
        prediction=uv[...,:2]/uv[...,2:].clamp_min(.05)
        error=torch.linalg.vector_norm(prediction[:,subset]-target[:,subset],dim=-1)
        loss=fn.smooth_l1_loss(error,torch.zeros_like(error),beta=4.)+.12*shape.square().mean()
        loss+=.08*expression.square().mean()+.4*pose[:,1:].square().mean()
        loss+=.04*(pose[:,0]-init_pose[:,0]).square().mean()+10*(translation-init_t).square().mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        if step%50==0:
            history.append({"step":step+1,"medianPx":float(error.detach().median())})
        if checkpoint_path is not None and step+1==steps//2:
            save_fit_state(checkpoint_path.with_name("local-fit-mid.pt"),step+1)
    save_fit_state(checkpoint_path,steps)
    local={}
    audit=[]
    for i,n in enumerate(names):
        mesh,F,root_error=root_neutral_contract(model,shape.detach(),expression[i:i+1].detach(),
                                               pose[i:i+1].detach(),translation[i].detach().cpu().numpy())
        local[n]={"mesh":mesh.astype(np.float32),"F":F.astype(np.float32),
                  "marks":marks[n],"role":"development" if n in development else "train"}
        audit.append({"name":n,"rootError":root_error,"role":local[n]["role"]})
    return model.cpu(),local,{"rejected":rejected,"history":history,"views":audit,
        "K":K.tolist(),"intrinsics":"estimated_from_static_map_not_independent_calibration"}


def initial_appearance(data,count=20000):
    model=data["geometry"]
    faces=model.faces.numpy()
    train=[n for n,r in data["local"].items() if r["role"]=="train"]
    ids,bary,spacing=barycentric_samples(data["local"][train[0]]["mesh"],faces,count)
    colors=np.zeros((count,3),np.float64)
    support=np.zeros(count,np.int32)
    detail=np.zeros(count,np.int32)
    for name in train:
        row=data["local"][name]
        points,normals=bound_points(row["mesh"],faces,ids,bary)
        camera=points@row["F"][:3,:3].T+row["F"][:3,3]
        uv=camera@data["K"].T
        pixel=np.rint(uv[:,:2]/np.maximum(uv[:,2:],.01)).astype(int)
        u,v=pixel.T
        h,w=data["rgb"][name].shape[:2]
        valid=(camera[:,2]>.05)&(u>=0)&(u<w)&(v>=0)&(v<h)
        valid&=((normals@row["F"][:3,:3].T)*(-camera)).sum(1)>0
        x=u.clip(0,w-1)
        y=v.clip(0,h-1)
        depth=np.full(((h+1)//2,(w+1)//2),np.inf)
        np.minimum.at(depth,(y[valid]//2,x[valid]//2),camera[valid,2])
        valid&=camera[:,2]<=depth[y//2,x//2]+.0035
        labels=data["labels"][name]
        colour_mask=labels.get('training_face',labels["face_core"]|labels["face_boundary"])
        valid&=colour_mask[y,x]&~labels["hair_visible"][y,x]
        colors[valid]+=data["rgb"][name][y[valid],x[valid]]
        support[valid]+=1
        # Generic edge details remain details, never called eyewear geometry.
        detail+=(valid&labels["glasses_visible"][y,x]).astype(int)
    keep=np.flatnonzero(support>0)
    if len(keep)<1000:
        raise ValueError("portrait_test_direct_color_support_insufficient")
    role=(detail[keep]>0).astype(np.int64)
    keep=keep[np.argsort(role,kind="stable")]
    role=(detail[keep]>0).astype(np.int64)
    hair=data["components"]["hair"]
    hn=len(hair["xyz"])
    rgb=np.concatenate((colors[keep]/support[keep,None],hair["rgb"])).astype(np.float32)
    coeff=np.zeros((len(rgb),4,3),np.float32)
    coeff[:,0]=(rgb-.5)/C0
    size=np.concatenate((spacing[keep],np.full(hn,.003,np.float32)))
    quats=np.tile(np.array([1.,0.,0.,0.],np.float32),(len(rgb),1))
    return {"color_mode":np.asarray("head-local-sh1"),"source_sha256":np.asarray(data["sourceHash"]),
        "model_sha256":np.asarray(model.model_sha256),"role":np.concatenate((role,np.full(hn,2,np.int64))),
        "surface_ids":ids[keep],"surface_bary":bary[keep],"hair_local_points":hair["xyz"],
        "source_index":np.concatenate((keep,np.arange(hn))),"origin_index":np.arange(len(rgb)),
        "source_confidence":np.concatenate((support[keep],hair["support"])),
        "local_offsets":np.zeros((len(rgb),3),np.float32),"sh_coeff":coeff,
        "log_scales":np.log(np.stack((size,size,size*.75),1)),"local_quats":quats,
        "opacity_logits":np.zeros(len(rgb),np.float32)}


def prepare_capture(source,out,frames,faces,*,base_prepared=None):
    started=time.perf_counter()
    out.mkdir()
    development_names=None
    with np.load(source/'face_landmarks.npz') as available:
        names,capture_reference=capture_observation_names(faces,available)
    if base_prepared is None:
        static=recover_static(source,names,out)
    else:
        base_prepared=Path(base_prepared)
        original=json.loads((base_prepared/'preparation.json').read_text())
        if original['sourceHash']!=sha256_file(source/'capture.mp4'):
            raise ValueError('registration_prepared_source_hash_mismatch')
        prior=json.loads((base_prepared/'automatic-prepare-audit.json').read_text())
        names=prior['observationSelection']['actualNames']
        capture_reference=prior['observationSelection']['referenceProposal']
        development_names={row['name'] for row in prior['localFit']['views'] if row['role']=='development'}
        shutil.copyfile(base_prepared/'static.db',out/'static.db')
        shutil.copytree(base_prepared/'sparse',out/'sparse')
        static=pycolmap.Reconstruction(out/'sparse/0')
    if development_names is None:
        development_names=set(names[3::5])
    from capture_registration import extend_static_short_windows
    added_worlds,registration_audit=extend_static_short_windows(source,out/'static.db',static,names,
        out/'short-window-registration',development_names=development_names)
    names=sorted(set(names)|set(added_worlds))
    camera=next(iter(static.cameras.values()))
    K,distortion=source_camera(camera)
    if any(not np.allclose(source_camera(c)[0],K) for c in static.cameras.values()):
        raise ValueError("portrait_test_multiple_intrinsics_need_adapter")
    masks=make_masks(source,out,names)
    rgb,labels=rectified_data(source,masks,names,K,distortion)
    with np.load(source/"face_landmarks.npz") as detected:
        marks={n:cv2.undistortPoints(detected[n].reshape(-1,1,2),K,distortion,P=K).reshape(-1,2) for n in names}
    source_hash=sha256_file(source/"capture.mp4")
    geometry,local,fit_audit=fit_local(rgb,labels,marks,K,
        checkpoint_path=out/"local-fit-state.pt",source_hash=source_hash,development_names=development_names)
    fit_audit["stateCheckpoint"]={"file":"local-fit-state.pt",
        "sha256":sha256_file(out/"local-fit-state.pt"),"optimizerRetained":True,
        "sourceHash":source_hash,"stepsCompleted":260}
    rgb={n:rgb[n] for n in local}
    labels={n:labels[n] for n in local}
    images={im.name:im for im in static.images.values() if im.has_pose}
    worlds={n:camera_matrix(images[n]) for n in local if n in images}
    worlds.update({n:C for n,C in added_worlds.items() if n in local})
    train=[n for n in worlds if local[n]["role"]=="train"]
    if len(train)<4:
        raise ValueError("portrait_test_world_local_overlap_insufficient")
    scale,gauge=shared_scene_scale(local,worlds,train)
    data={"sourceHash":source_hash,"geometry":geometry,"local":local,
          "worlds":worlds,"rgb":rgb,"labels":labels,"K":K,"scale":scale,"train":train,
          "development":[n for n in worlds if local[n]["role"]=="development"],"source":str(source.resolve())}
    from capture_reference import choose_capture_reference,CaptureReferenceUnavailable
    try:
        _,reference_receipt=choose_capture_reference(data)
        registration_audit['postFitReferenceStatus']='eligible'
        registration_audit['postFitReference']=reference_receipt
    except CaptureReferenceUnavailable as error:
        registration_audit['postFitReferenceStatus']='blocked'
        registration_audit['postFitReferenceFailure']=str(error)
        registration_audit['postFitReference']=error.receipt
    room,room_audit=supported_static_surfaces(static,{n:(worlds[n],K) for n in train},
        {n:labels[n]["room_visible"] for n in train},{n:rgb[n] for n in train},out/"static_surface_seeds.npz")
    components={}
    for part in ("hair","glasses"):
        components[part],audit=triangulated_component(rgb,labels,local,K,part)
        np.savez_compressed(out/(part+"_multiview_seeds.npz"),**components[part])
        write_json(out/(part+"-audit.json"),audit)
    data["room"]=room
    data["components"]=components
    # Eye-edge tracks are not instantiated as an independent glasses mesh.
    empty=dict(components["glasses"])
    for key,value in empty.items():
        if isinstance(value,np.ndarray) and value.ndim:
            empty[key]=value[:0]
    data["components"]["glasses"]=empty
    np.savez_compressed(out/"glasses_multiview_seeds.npz",**empty)
    prior=initial_appearance(data)
    appearance=out/"initial-appearance.npz"
    np.savez_compressed(appearance,**prior)
    cloth_local={n:{"F":worlds[n],"role":"train","mesh":np.zeros((1,3),np.float32)} for n in train}
    cloth,cloth_audit=triangulated_component(rgb,labels,cloth_local,K,"cloth")
    cloth["source_id"]=np.arange(len(cloth["xyz"]))
    np.savez_compressed(out/"cloth_supported_seeds.npz",**cloth)
    cache=out/"rectified_observations"
    cache.mkdir()
    for n in local:
        cv2.imwrite(str(cache/n),cv2.cvtColor((rgb[n]*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        np.savez_compressed(cache/(n+".npz"),**labels[n])
    ns=list(local)
    np.savez_compressed(out/"local_geometry.npz",names=np.asarray(ns),meshes=np.stack([local[n]["mesh"] for n in ns]),
        F=np.stack([local[n]["F"] for n in ns]),roles=np.asarray([local[n]["role"] for n in ns]),
        marks=np.stack([local[n]["marks"] for n in ns]),K=K,world_names=np.asarray(list(worlds)),
        C=np.stack(list(worlds.values())),scale=np.asarray(scale))
    write_json(out/"preparation.json",{"sourceHash":data["sourceHash"],"source":str(source.resolve()),
        "appearance":str(appearance.resolve()),"appearanceHash":sha256_file(appearance),
        "staticMap":str((out/"sparse/0").resolve()),"train":train,"development":data["development"],
        "modelPath":str(MODEL),"modelHash":geometry.model_sha256,"masks":str(masks.resolve()),
        "poseAudit":gauge,"sourceDistortion":distortion.tolist(),
        "observationSchema":2,"status":"automatic_test_preparation_not_quality_approved"})
    write_json(out/"automatic-prepare-audit.json",{"sourceHash":data["sourceHash"],"seconds":time.perf_counter()-started,
        "observationSelection":{"globalBudget":32,"referenceProposal":capture_reference,
            "actualNames":names,"contiguousBodyNeighbours":4,"cameraInterpolation":False},
        "localFit":fit_audit,"room":room_audit,"cloth":cloth_audit,"worldCameraStatus":"estimated_static_research_not_release_trusted",
        "shortWindowRegistration":registration_audit,
        "fullPersonExcludedFromStaticFeatures":True,"unknownEyewearNotInstantiated":True,
        "hair":"actual_multiview_seeds_no_generated_shell","geometryApproved":False})
    return out
