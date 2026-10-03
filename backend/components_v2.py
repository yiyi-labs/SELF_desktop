"""Research-only component observations and supported geometry in SELF.

No production job or viewer imports this module. A frozen FLAME Open fit is
an input prior; masks are observations, not measured surfaces. All association
uses names, hashes and explicit transforms. No missing camera is synthesized.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pycolmap
import torch
from scipy.spatial import cKDTree

from flame_open_model import FlameOpen, MODEL
from probe_flame_observations import root_neutral_contract
from probe_flame_real_appearance import bound_points
from face import COMPONENT_MASK_NAMES, make_component_observations
from joint_visibility import sha256_file
from observations import component_observation_record
from pose import refit_local_pose_same_camera
from scene import supported_static_surfaces


def camera_matrix(image):
    C=np.eye(4,dtype=np.float64)
    C[:3]=image.cam_from_world().matrix()
    return C


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding="utf-8")


def source_camera(camera):
    if camera.model.name not in ("SIMPLE_RADIAL","SIMPLE_PINHOLE","PINHOLE"):
        raise ValueError("v2_camera_model_not_implemented")
    K=np.asarray(camera.calibration_matrix(),np.float64)
    distortion=np.zeros(5,np.float64)
    if camera.model.name=="SIMPLE_RADIAL":
        distortion[0]=camera.params[3]
    return K,distortion


def make_masks(source,out,names):
    import mediapipe as mp
    from probe_portrait_components import (MODEL_DIR,PART_MODEL,HAIR_MODEL,
                                           PART_SHA256,HAIR_SHA256,segmenter)
    for file,expected in ((PART_MODEL,PART_SHA256),(HAIR_MODEL,HAIR_SHA256)):
        if sha256_file(file)!=expected:
            raise ValueError("component_model_hash_changed")
    masks=out/"component_masks"
    for label in COMPONENT_MASK_NAMES+("confidence","labels"):
        (masks/label).mkdir(parents=True,exist_ok=True)
    with np.load(source/"face_landmarks.npz") as marks:
        with segmenter(PART_MODEL) as parts,segmenter(HAIR_MODEL) as hair:
            for number,name in enumerate(names):
                rgb=cv2.cvtColor(cv2.imread(str(source/"frames"/name)),cv2.COLOR_BGR2RGB)
                result=parts.segment(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb))
                hair_result=hair.segment(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb))
                confidence=[layer.numpy_view().squeeze().copy() for layer in result.confidence_masks]
                probability=hair_result.confidence_masks[1].numpy_view().squeeze().copy()
                labels,classes,certainty=make_component_observations(confidence,probability,marks[name],rgb)
                for label,mask in labels.items():
                    if not cv2.imwrite(str(masks/label/(name+".png")),mask):
                        raise OSError("component_mask_write_failed")
                cv2.imwrite(str(masks/"labels"/(name+".png")),classes)
                np.savez_compressed(masks/"confidence"/(name+".npz"),confidence=certainty.astype(np.float16))
                if number%40==0:
                    print("component-observations",number+1,len(names),flush=True)
    return masks


def rectified_data(source,masks,names,K,distortion):
    rgb={}
    labels={}
    for name in names:
        image=cv2.cvtColor(cv2.imread(str(source/"frames"/name)),cv2.COLOR_BGR2RGB)
        height,width=image.shape[:2]
        mx,my=cv2.initUndistortRectifyMap(K,distortion,np.eye(3),K,(width,height),cv2.CV_32FC1)
        rgb[name]=cv2.remap(image,mx,my,cv2.INTER_LINEAR).astype(np.float32)/255
        labels[name]={}
        for label in COMPONENT_MASK_NAMES:
            raw=cv2.imread(str(masks/label/(name+".png")),cv2.IMREAD_GRAYSCALE)
            labels[name][label]=cv2.remap(raw,mx,my,cv2.INTER_NEAREST)>127
        outside=(mx<0)|(my<0)|(mx>=width)|(my>=height)
        for label in COMPONENT_MASK_NAMES[:-1]:
            labels[name][label][outside]=False
        labels[name]["unknown_or_occluded"] |= outside
        from observed_surface import rectified_domains
        labels[name]=rectified_domains(masks,name,K,distortion,labels[name])
    return rgb,labels


def local_fit_views(source,fit_root,K,distortion,enrich_neighbours=False):
    model=FlameOpen(24,12,model_path=MODEL)
    train=dict(np.load(fit_root/"private-fit-parameters.npz"))
    held=dict(np.load(fit_root/"private-held-local-parameters.npz"))
    train_indices=train["train_frame_indices"].tolist()
    held_indices=held["held_frame_indices"].tolist()
    faces=model.faces.numpy()
    data={}
    audit=[]
    with np.load(source/"face_landmarks.npz") as observed:
        for params,indices,role in ((train,train_indices,"train"),(held,held_indices,"development")):
            for row,index in enumerate(indices):
                shape=torch.from_numpy(params["shared_shape"])
                expression=torch.from_numpy(params["expressions"][row:row+1])
                pose=torch.from_numpy(params["joint_axis_angles"][row:row+1])
                mesh,F,error=root_neutral_contract(model,shape,expression,pose,params["camera_translations"][row])
                triangle=mesh[faces[model.landmark_faces.numpy()]]
                local_marks=(triangle*model.barycentric.numpy()[:,:,None]).sum(1)
                name=f"frame_{index:04d}.png"
                detection=observed[name][model.landmark_indices.numpy()]
                refined,quality=refit_local_pose_same_camera(mesh,local_marks,detection,K,distortion,F)
                if quality["rotationChangeDegrees"]>3 or quality["translationChangeModelUnits"]>.035:
                    raise ValueError(f"camera_model_local_refit_not_bounded:{name}:{quality}")
                data[name]={"mesh":mesh.astype(np.float32),"F":refined.astype(np.float32),"role":role,
                    "marks":cv2.undistortPoints(observed[name].reshape(-1,1,2),K,distortion,P=K).reshape(-1,2)}
                audit.append({"name":name,"role":role,"rootError":error,**quality})
        if enrich_neighbours:
            available={int(path.stem.split('_')[-1]) for path in (source/"frames").glob("frame_*.png")}
            extra=sorted({i+d for i in train_indices for d in (-3,-2,-1,1,2,3)} & available - set(train_indices+held_indices))
            for index in extra:
                neighbour=min(train_indices,key=lambda i:abs(i-index))
                original=data[f"frame_{neighbour:04d}.png"]
                mesh=original["mesh"].copy()
                name=f"frame_{index:04d}.png"
                triangle=mesh[faces[model.landmark_faces.numpy()]]
                local_marks=(triangle*model.barycentric.numpy()[:,:,None]).sum(1)
                detection=observed[name][model.landmark_indices.numpy()]
                refined,quality=refit_local_pose_same_camera(mesh,local_marks,detection,K,distortion,original["F"])
                accepted=(quality["rotationChangeDegrees"]<=12 and quality["translationChangeModelUnits"]<=.06
                          and quality["fitMedianPixels"]<=6.)
                audit.append({"name":name,"role":"new_neighbour_geometry_and_color_train" if accepted else "rejected_neighbour_pose",
                    "expressionPriorFrom":neighbour,"poseActuallySolved":True,**quality})
                if not accepted:
                    continue
                data[name]={"mesh":mesh,"F":refined.astype(np.float32),"role":"train",
                    "marks":cv2.undistortPoints(observed[name].reshape(-1,1,2),K,distortion,P=K).reshape(-1,2)}
    return model,data,audit


def shared_scene_scale(local,worlds,train_names):
    """One shared metric-to-map scale and center, with observability reported.

    A stationary center is used only to estimate one global gauge. Actual
    fitted F_t still supplies bounded head motion. No per-frame scale exists.
    This remains a research connection, never independent calibration.
    """
    equations=[]
    targets=[]
    for name in train_names:
        C=worlds[name]
        F=local[name]["F"]
        equations.append(np.column_stack((C[:3,:3],-F[:3,3])))
        targets.append(-C[:3,3])
    A=np.vstack(equations)
    b=np.concatenate(targets)
    solution,_,_,singular=np.linalg.lstsq(A,b,rcond=None)
    scale=float(solution[3])
    residual=(A@solution-b).reshape(-1,3)
    if not np.isfinite(scale) or scale<=0:
        raise ValueError("shared_scene_scale_unobservable_or_negative")
    return scale,{"scale":scale,"stationaryCenterWorld":solution[:3].tolist(),
        "conditionNumber":float(singular[0]/singular[-1]),
        "centerResidualMetricP50":float(np.median(np.linalg.norm(residual,axis=1))/scale),
        "centerResidualMetricP90":float(np.quantile(np.linalg.norm(residual,axis=1),.9)/scale),
        "method":"one_global_scale_and_stationary_center_from_static_research_cameras_and_local_F",
        "independentCalibration":False,"perFrameScale":False}


def project(points,F,K):
    cam=points@F[:3,:3].T+F[:3,3]
    uv=cam@K.T
    return uv[:,:2]/np.maximum(uv[:,2:],1e-8),cam[:,2]


def triangulated_component(rgb,labels,local,K,part):
    """New multiview SIFT tracks in rectified pixels and refitted local F.

    Three-view cycles and reprojection gates replace the previous two-view
    61-point optical-flow condition. No old SIFT feature index is reused.
    For glasses, line candidates remain such until track geometry passes.
    """
    names=[name for name,row in local.items() if row["role"]=="train"]
    mask_label={"hair":"hair_visible","glasses":"glasses_visible","cloth":"neck_cloth_visible"}[part]
    features={}
    parent={}
    line_support={}
    sift=cv2.SIFT_create(nfeatures=4500,contrastThreshold=.015)
    for name in names:
        image=(rgb[name]*255).round().astype(np.uint8)
        mask=labels[name][mask_label].astype(np.uint8)*255
        if part=="hair":
            mask=cv2.erode(mask,np.ones((3,3),np.uint8))
        kp,desc=sift.detectAndCompute(cv2.cvtColor(image,cv2.COLOR_RGB2GRAY),mask)
        xy=np.asarray([p.pt for p in kp],np.float32).reshape(-1,2)
        if desc is not None:
            desc=np.sqrt(desc/np.maximum(desc.sum(1,keepdims=True),1e-8)).astype(np.float32)
        features[name]=(xy,desc)
        if part=="glasses":
            lsd=cv2.createLineSegmentDetector().detect(cv2.cvtColor(image,cv2.COLOR_RGB2GRAY))[0]
            count=0
            if lsd is not None:
                for x0,y0,x1,y1 in lsd[:,0]:
                    x=int((x0+x1)/2)
                    y=int((y0+y1)/2)
                    if np.hypot(x1-x0,y1-y0)>8 and mask[y,x]>0:
                        count+=1
            line_support[name]=count
    def find(key):
        parent.setdefault(key,key)
        if parent[key]!=key:
            parent[key]=find(parent[key])
        return parent[key]
    matcher=cv2.BFMatcher(cv2.NORM_L2)
    pair_rows=[]
    for a_index,a in enumerate(names):
        for b in names[a_index+1:]:
            A,ad=features[a]
            B,bd=features[b]
            if ad is None or bd is None or len(ad)<2 or len(bd)<2:
                continue
            relative=local[a]["F"][:3,:3]@local[b]["F"][:3,:3].T
            angle=float(np.linalg.norm(cv2.Rodrigues(relative)[0])*180/np.pi)
            number_a=int(Path(a).stem.split('_')[-1])
            number_b=int(Path(b).stem.split('_')[-1])
            if not 1<=angle<=28 or (abs(number_a-number_b)>9 and angle>12):
                continue
            forward=matcher.knnMatch(ad,bd,k=2)
            reverse=matcher.knnMatch(bd,ad,k=2)
            backwards={m.queryIdx:m.trainIdx for m,n in reverse if m.distance<.8*n.distance}
            accepted=0
            for m,n in forward:
                if m.distance>=.8*n.distance or backwards.get(m.trainIdx)!=m.queryIdx:
                    continue
                fa=local[a]["F"]
                fb=local[b]["F"]
                h=cv2.triangulatePoints(K@fa[:3],K@fb[:3],A[m.queryIdx].reshape(2,1),B[m.trainIdx].reshape(2,1))
                if abs(h[3,0])<1e-8:
                    continue
                xyz=(h[:3,0]/h[3,0])[None]
                ua,za=project(xyz,fa,K)
                ub,zb=project(xyz,fb,K)
                if min(za[0],zb[0])<.05 or max(np.linalg.norm(ua[0]-A[m.queryIdx]),np.linalg.norm(ub[0]-B[m.trainIdx]))>2.2:
                    continue
                if part!="cloth" and np.linalg.norm(xyz[0])>.4:
                    continue
                ka=(a,m.queryIdx)
                kb=(b,m.trainIdx)
                parent[find(kb)]=find(ka)
                accepted+=1
            pair_rows.append({"a":a,"b":b,"relativeRotationDegrees":angle,"geometricPairs":accepted})
    tracks={}
    for key in list(parent):
        tracks.setdefault(find(key),[]).append(key)
    xyz_all=[]
    colors=[]
    support=[]
    source_views=[]
    reproj=[]
    measurements=[]
    rejected={"shortOrCycleConflict":0,"reprojection":0,"occlusion":0}
    for keys in tracks.values():
        if len(keys)<3 or len(set(k[0] for k in keys))!=len(keys):
            rejected["shortOrCycleConflict"]+=1
            continue
        rows=[]
        for name,index in keys:
            P=K@local[name]["F"][:3]
            u,v=features[name][0][index]
            rows.extend((u*P[2]-P[0],v*P[2]-P[1]))
        _,_,vh=np.linalg.svd(np.stack(rows))
        h=vh[-1]
        if abs(h[3])<1e-8:
            continue
        xyz=h[:3]/h[3]
        errors=[]
        samples=[]
        bad=False
        for name,index in keys:
            uv,depth=project(xyz[None],local[name]["F"],K)
            error=np.linalg.norm(uv[0]-features[name][0][index])
            errors.append(error)
            u,v=uv[0].round().astype(int)
            if depth[0]<.05 or not(0<=u<rgb[name].shape[1] and 0<=v<rgb[name].shape[0]):
                bad=True
                break
            if not labels[name][mask_label][v,u]:
                bad=True
                break
            samples.append(rgb[name][v,u])
        if bad or max(errors,default=999)>2.2:
            rejected["reprojection"]+=1
            continue
        centers=np.stack([-local[name]["F"][:3,:3].T@local[name]["F"][:3,3] for name,_ in keys])
        rays=xyz-centers
        rays/=np.linalg.norm(rays,axis=1,keepdims=True)
        baseline=np.degrees(np.arccos(np.clip(rays@rays.T,-1,1))).max()
        if baseline<2:
            continue
        # Actual local thickness is preserved. A sample deep inside the
        # FLAME skin cannot explain an exterior hair or frame observation.
        distance=cKDTree(local[keys[0][0]]["mesh"]).query(xyz)[0] if part!="cloth" else 0.
        if part=="hair" and not .002<distance<.085:
            rejected["occlusion"]+=1
            continue
        if part=="glasses" and not .001<distance<.045:
            rejected["occlusion"]+=1
            continue
        xyz_all.append(xyz)
        colors.append(np.median(samples,axis=0))
        support.append(len(keys))
        source_views.append([names.index(name) for name,_ in keys])
        reproj.append(max(errors))
        observed=np.full((len(names),2),np.nan,np.float32)
        for name,index in keys:
            observed[names.index(name)]=features[name][0][index]
        measurements.append(observed)
    n=len(xyz_all)
    padded=np.full((n,len(names)),-1,np.int16)
    for i,row in enumerate(source_views):
        padded[i,:len(row)]=row
    result={"xyz":np.asarray(xyz_all,np.float32).reshape(-1,3),
        "rgb":np.asarray(colors,np.float32).reshape(-1,3),"support":np.asarray(support,np.int16),
        "views":padded,"names":np.asarray(names),"reprojection":np.asarray(reproj,np.float32),
        "observed_pixels":np.asarray(measurements,np.float32).reshape(n,len(names),2)}
    report={"component":part,"method":"new_rectified_RootSIFT_three_view_cycle_DLT",
        "featureCounts":{name:len(features[name][0]) for name in names},"pairs":pair_rows,
        "acceptedSeeds":n,"rejected":rejected,"lineCandidatesByView":line_support,
        "limitations":["No volume from unknown silhouettes","No fabricated nose pads or temples",
                         "Sparse independent geometry can still be insufficient for complete hair/frame coverage"]}
    return result,report


def triangulated_garment(data,out):
    # New feature namespace and real static cameras, never legacy mixed-map
    # point coordinates smuggled into the room. This is a simplified-body
    # research representation: nonrigid cloth motion remains unverified.
    local={name:{"F":data["worlds"][name],"role":"train","mesh":np.zeros((1,3),np.float32)} for name in data["train"]}
    seeds,audit=triangulated_component(data["rgb"],data["labels"],local,data["K"],"cloth")
    seeds["source_id"]=np.arange(len(seeds["xyz"]),dtype=np.int64)
    np.savez_compressed(out/"cloth_supported_seeds.npz",**seeds)
    audit["motionAssumption"]="body_reference_quasistatic; measured head-neck translation blend only"
    write_json(out/"cloth-new-multiview-audit.json",audit)
    return audit


def prepare(source,out,fit_root,appearance,static_map,trust_path,*,enrich_neighbours=False,masks_from=None):
    source_hash=sha256_file(source/"capture.mp4")
    prior=dict(np.load(appearance))
    if str(prior["source_sha256"])!=source_hash or str(prior["color_mode"])!="head-local-sh1":
        raise ValueError("v2_source_or_direction_contract_mismatch")
    model=pycolmap.Reconstruction(static_map)
    images={im.name:im for im in model.images.values() if im.has_pose}
    trust=json.loads(trust_path.read_text())
    trusted={r["name"] for r in trust["frames"] if r["researchTrusted"]}
    selected=sorted(path.name for path in (source/"frames").glob("*.png"))
    if masks_from is not None:
        previous=json.loads((masks_from/"preparation.json").read_text())
        if previous["sourceHash"]!=source_hash:
            raise ValueError("reused_component_mask_source_mismatch")
        masks=out/"component_masks"
        masks.symlink_to((masks_from/"component_masks").resolve(),target_is_directory=True)
    else:
        masks=make_masks(source,out,selected)
    first=next(iter(model.cameras.values()))
    K,distortion=source_camera(first)
    if any(not np.allclose(source_camera(c)[0],K) for c in model.cameras.values()):
        raise ValueError("v2_multiple_camera_intrinsics_require_adapter")
    geometry,local,pose_audit=local_fit_views(source,fit_root,K,distortion,enrich_neighbours)
    names=list(local)
    rgb,labels=rectified_data(source,masks,names,K,distortion)
    worlds={name:camera_matrix(images[name]) for name in names if name in trusted and name in images}
    train_names=[name for name in worlds if local[name]["role"]=="train"]
    development=[name for name in worlds if local[name]["role"]=="development"]
    if len(train_names)<4 or len(development)<2:
        raise ValueError("v2_research_static_local_overlap_insufficient")
    scale,scale_audit=shared_scene_scale(local,worlds,train_names)
    write_json(out/"pose-and-scale-audit.json",{"localRefits":pose_audit,"sharedScale":scale_audit,
        "worldFrames":list(worlds),"localOnlyFrames":[n for n in names if n not in worlds],
        "trustedFinalWorldCount":0,"temporaryStaticResearchSubset":len(worlds),
        "K":K.tolist(),"sourceRadialDistortion":distortion.tolist(),
        "rectification":"OpenCV native remap to same K; no resize; pose fit includes source distortion"})
    observation=[]
    for name in names:
        C=worlds.get(name)
        observation.append(component_observation_record(source,name,masks,
            {"C":C.tolist(),"colmapImageId":images[name].image_id,"staticModel":str(static_map)} if C is not None else None,
            {"F":local[name]["F"].tolist(),"K":K.tolist(),"confidence":"fixed-shape_PnP_development_errors_in_pose_audit"},
            local[name]["role"],"temporary_static_research_not_release_trusted" if C is not None else "no_world_connection"))
    write_json(out/"component_observations.json",{"sourceSha256":source_hash,"frames":observation,
        "parts":["room_static","skin_face_head","hair","glasses","neck_shoulder_cloth"],
        "featureMasksUsedByStaticMap":"existing_E1_full_person_exclusion_before_SIFT; new_masks_audit_not_remapped_feature_indices"})
    room,room_audit=supported_static_surfaces(model,{n:(worlds[n],K) for n in train_names},
        {n:labels[n]["room_visible"] for n in train_names},{n:rgb[n] for n in train_names},out/"static_surface_seeds.npz")
    write_json(out/"static-surface-audit.json",room_audit)
    seed_data={}
    component_audit={}
    for part in ("hair","glasses"):
        seed_data[part],component_audit[part]=triangulated_component(rgb,labels,local,K,part)
        np.savez_compressed(out/(part+"_multiview_seeds.npz"),**seed_data[part])
    write_json(out/"component-seed-audit.json",component_audit)
    cache=out/"rectified_observations"
    cache.mkdir()
    for name in names:
        cv2.imwrite(str(cache/name),cv2.cvtColor((rgb[name]*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        np.savez_compressed(cache/(name+".npz"),**labels[name])
    np.savez_compressed(out/"local_geometry.npz",names=np.asarray(names),
        meshes=np.stack([local[n]["mesh"] for n in names]),
        F=np.stack([local[n]["F"] for n in names]),
        roles=np.asarray([local[n]["role"] for n in names]),
        marks=np.stack([local[n]["marks"] for n in names]),K=K,
        world_names=np.asarray(list(worlds)),C=np.stack(list(worlds.values())),scale=np.asarray(scale))
    write_json(out/"preparation.json",{"sourceHash":source_hash,"source":str(source),
        "appearance":str(appearance),"appearanceHash":sha256_file(appearance),
        "staticMap":str(static_map),"train":train_names,"development":development,
        "modelPath":str(MODEL),"modelHash":geometry.model_sha256,"masks":str(masks),
        "poseAudit":scale_audit,"enrichedLocalNeighbours":enrich_neighbours,
        "status":"isolated_preparation_not_release"})
    return {"sourceHash":source_hash,"geometry":geometry,"prior":prior,"local":local,"worlds":worlds,
        "rgb":rgb,"labels":labels,"K":K,"scale":scale,"train":train_names,"development":development,
        "room":room,"components":seed_data,"source":source,"masks":masks,"poseAudit":scale_audit}


def load_prepared(out):
    metadata=json.loads((out/"preparation.json").read_text())
    source=Path(metadata["source"])
    appearance=Path(metadata["appearance"])
    if sha256_file(source/"capture.mp4")!=metadata["sourceHash"] or sha256_file(appearance)!=metadata["appearanceHash"]:
        raise ValueError("prepared_input_hash_changed")
    data=dict(np.load(out/"local_geometry.npz"))
    names=[str(n) for n in data["names"]]
    local={n:{"mesh":data["meshes"][i],"F":data["F"][i],"role":str(data["roles"][i]),"marks":data["marks"][i]} for i,n in enumerate(names)}
    worlds={str(n):data["C"][i] for i,n in enumerate(data["world_names"])}
    scene_path=out/"scene_observations.npz"
    scene_names=[]
    if scene_path.is_file():
        # Layered observation validity: scene-valid frames (face PnP failed)
        # ride along with a fitted head proxy. The fitted identity chain above
        # (local_geometry names/roles == fit checkpoint) stays byte-exact.
        with np.load(scene_path,allow_pickle=False) as scene:
            scene_names=[str(n) for n in scene["names"]]
            for i,name in enumerate(scene_names):
                local[name]={"mesh":scene["meshes"][i],"F":scene["F"][i],
                    "marks":scene["marks"][i],"role":"scene",
                    "headProxy":str(scene["proxies"][i])}
            for i,name in enumerate(map(str,scene["worldNames"])):
                worlds[name]=scene["worldC"][i]
    rgb={n:cv2.cvtColor(cv2.imread(str(out/"rectified_observations"/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255 for n in names}
    labels={n:dict(np.load(out/"rectified_observations"/(n+".npz"))) for n in names}
    if scene_names:
        rgb.update({n:cv2.cvtColor(cv2.imread(str(out/"rectified_observations"/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255 for n in scene_names})
        labels.update({n:dict(np.load(out/"rectified_observations"/(n+".npz"))) for n in scene_names})
    result={**metadata,"source":source,"prepared":out,"geometry":FlameOpen(24,12,model_path=MODEL),
        "prior":dict(np.load(appearance)),"local":local,"worlds":worlds,"rgb":rgb,"labels":labels,
        "K":data["K"],"scale":float(data["scale"]),"room":dict(np.load(out/"static_surface_seeds.npz")),
        "components":{part:dict(np.load(out/(part+"_multiview_seeds.npz"))) for part in ("hair","glasses")}}
    from observed_surface import attach_observation_domains
    attach_observation_domains(result,out)
    from live_hair_motion import load_prepared_fit
    result['hair_fit']=load_prepared_fit(out,metadata,data,result['geometry'])
    result['prepared_geometry_contract']=data
    return result


def supported_cloth(source,static_map,data):
    """Separate measured collar/body tracks; no clothing relabelled as room.

    The legacy map is aligned once via common camera centers, then every
    candidate must reproject into observed garment pixels in >=3 new static
    research views. A poor alignment cannot be hidden by per-frame scale.
    """
    old=pycolmap.Reconstruction(source/"sparse/0")
    static=pycolmap.Reconstruction(static_map)
    alignment=pycolmap.align_reconstructions_via_proj_centers(old,static,.05)
    if alignment is None:
        raise ValueError("cloth_map_common_gauge_alignment_failed")
    R=np.asarray(alignment.rotation.matrix())
    t=np.asarray(alignment.translation)
    s=float(alignment.scale)
    xyz=[]
    rgb=[]
    ids=[]
    counts=[]
    errors=[]
    old_images=old.images
    for point_id,point in old.points3D.items():
        if point.error>2.5 or point.track.length()<3:
            continue
        world=s*R@np.asarray(point.xyz)+t
        support=0
        color=[]
        residual=[]
        conflict=False
        for element in point.track.elements:
            im=old_images[element.image_id]
            name=im.name
            if name not in data["train"]:
                continue
            uv,z=project(world[None],data["worlds"][name],data["K"])
            u,v=uv[0].round().astype(int)
            h,w=data["rgb"][name].shape[:2]
            if z[0]<=.01 or not (0<=u<w and 0<=v<h):
                continue
            if data["labels"][name]["face_core"][v,u]:
                conflict=True
                break
            if not data["labels"][name]["neck_cloth_visible"][v,u]:
                continue
            observed=im.points2D[element.point2D_idx].xy
            camera=old.cameras[im.camera_id]
            OK,dist=source_camera(camera)
            rect=cv2.undistortPoints(np.asarray(observed).reshape(1,1,2),OK,dist,P=data["K"])[0,0]
            error=np.linalg.norm(rect-uv[0])
            residual.append(error)
            if error<4:
                support+=1
                color.append(data["rgb"][name][v,u])
        if support>=3 and not conflict:
            xyz.append(world)
            rgb.append(np.median(color,axis=0))
            ids.append(int(point_id))
            counts.append(support)
            errors.append(max(residual))
    return ({"xyz":np.asarray(xyz,np.float32).reshape(-1,3),"rgb":np.asarray(rgb,np.float32).reshape(-1,3),
        "source_id":np.asarray(ids,np.int64),"support":np.asarray(counts,np.int16)},
        {"points":len(xyz),"commonMapScale":s,"method":"one_Sim3_plus_three_static_view_garment_reprojection",
         "reprojectionMaxPxP90":float(np.quantile(errors,.9)) if errors else None,
         "motion":"simplified_reference_body_with_bounded_neck_head_blend_not_independent_body_truth"})
