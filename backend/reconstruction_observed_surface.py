"""Physical observation domains and finite surface support for any capture.

Feature extraction safety masks do not define the final object boundary.
No generated RGB, room backplates, or infinite plane extrapolation.
"""
from pathlib import Path
import json
import cv2
import numpy as np


def observation_domains(classes, certainty, outside, existing):
    valid = (~outside) & (certainty >= .70)
    # Preserve all confidently observed static pixels, including white walls.
    # No dilated person exclusion is applied to this appearance target.
    room = valid & (classes == 0) & (certainty >= .85)
    cloth = valid & (classes == 4)
    body_skin = valid & (classes == 2)
    return {**existing, "observed_room": room, "observed_cloth": cloth,
            "observed_body_skin": body_skin,
            "observed_neck_cloth": cloth | body_skin}


def rectified_domains(mask_root, name, K, distortion, existing):
    root = Path(mask_root)
    raw = cv2.imread(str(root/"labels"/(name+".png")), cv2.IMREAD_GRAYSCALE)
    certainty_path = root/"confidence"/(name+".npz")
    if raw is None or not certainty_path.is_file():
        raise ValueError("physical_observation_source_missing:"+name)
    with np.load(certainty_path) as archive:
        certainty = archive["confidence"].astype(np.float32)
    h,w = raw.shape
    if certainty.shape != raw.shape:raise ValueError("physical_observation_size")
    mx,my = cv2.initUndistortRectifyMap(K, distortion, np.eye(3), K, (w,h), cv2.CV_32FC1)
    outside = (mx<0)|(my<0)|(mx>=w)|(my>=h)
    return observation_domains(cv2.remap(raw,mx,my,cv2.INTER_NEAREST),
        cv2.remap(certainty,mx,my,cv2.INTER_LINEAR),outside,existing)


def attach_observation_domains(data, prepared):
    """Explicitly adapt an old cache; never silently assume distortion=0."""
    prepared=Path(prepared)
    if all("observed_room" in v for v in data["labels"].values()):return
    metadata=json.loads((prepared/"preparation.json").read_text())
    distortion=metadata.get("sourceDistortion")
    if distortion is None:
        audit=prepared/"pose-and-scale-audit.json"
        if audit.is_file():distortion=json.loads(audit.read_text()).get("sourceRadialDistortion")
    if distortion is None and metadata.get("staticMap"):
        # Read the actual old COLMAP camera, not today's defaults.
        import pycolmap
        from reconstruction_components_v2 import source_camera
        model=pycolmap.Reconstruction(metadata["staticMap"])
        cameras=[source_camera(c) for c in model.cameras.values()]
        if not cameras or any(not np.allclose(k,data["K"]) for k,d in cameras):
            raise ValueError("cached_camera_contract_mismatch")
        if any(not np.allclose(d,cameras[0][1]) for k,d in cameras):
            raise ValueError("cached_multiple_distortions")
        distortion=cameras[0][1]
    if distortion is None:raise ValueError("cached_source_distortion_missing")
    for name, old in data["labels"].items():
        data["labels"][name]=rectified_domains(metadata["masks"],name,data["K"],np.asarray(distortion),old)


def finite_triangle_samples(xyz, ids, views, masks, rgbs, *, stride=9., budget=10000,
                            max_edge=80., require_plane=False):
    """Densify measured garment/neck triangles, without making new evidence.

    Only a short near-rigid observation window may call this. Thin clothes
    and skin are separate masks/transactions. Each sample needs three real
    training observations and keeps its measured parent-track identities.
    """
    from scipy.spatial import Delaunay, QhullError, cKDTree
    from reconstruction_scene import surface_barycentrics, surface_sample_identity
    xyz=np.asarray(xyz,np.float64);ids=np.asarray(ids,np.int64)
    result=[];colors=[];sources=[];weights=[];supports=[];seen=set()
    if len(xyz)<6:return None,{"status":"insufficient_measured_surface_tracks","tracks":len(xyz)}
    names=list(views)
    blurred={n:cv2.GaussianBlur(rgbs[n],(3,3),0) for n in names}
    safe_masks={n:cv2.erode(masks[n].astype(np.uint8),np.ones((3,3),np.uint8))>0 for n in names}
    normals=np.zeros_like(xyz);planes=np.zeros(len(xyz),bool)
    if require_plane and len(xyz)>=12:
        neighbours=cKDTree(xyz).query(xyz,k=12)[1]
        for i,near in enumerate(neighbours):
            local=xyz[near]-xyz[near].mean(0);_,singular,V=np.linalg.svd(local,full_matrices=False)
            planes[i]=(singular[0]>1e-8 and singular[1]/singular[0]>.15 and singular[2]/singular[1]<.06)
            normals[i]=V[-1]
    for name in names:
        C,K=views[name];cam=xyz@C[:3,:3].T+C[:3,3]
        uv=cam@K.T;uv=uv[:,:2]/np.maximum(uv[:,2:],1e-8)
        inside=(cam[:,2]>.01)&np.isfinite(uv).all(1)
        selected=np.flatnonzero(inside)
        if len(selected)<6:continue
        try:triangles=selected[Delaunay(uv[selected]).simplices]
        except QhullError:continue
        for tri in triangles:
            z=cam[tri,2];edge=max(np.linalg.norm(uv[tri[i]]-uv[tri[j]]) for i,j in ((0,1),(1,2),(2,0)))
            if edge<7 or edge>max_edge or np.ptp(z)/np.median(z)>.04:continue
            normal=np.cross(xyz[tri[1]]-xyz[tri[0]],xyz[tri[2]]-xyz[tri[0]])
            if np.linalg.norm(normal)<1e-9:continue
            if require_plane:
                normal/=np.linalg.norm(normal)
                if not planes[tri].all() or (np.abs(normals[tri]@normal)<np.cos(np.deg2rad(12))).any():continue
                # A bounded triangle may cross a real opening or silhouette.
                polygon=np.zeros_like(masks[name],np.uint8)
                cv2.fillConvexPoly(polygon,np.rint(uv[tri]).astype(np.int32),1)
                if np.mean(masks[name][polygon>0])<.98:continue
            bary=surface_barycentrics(min(10,max(2,int(edge/stride))))
            points=bary@xyz[tri]; votes=np.zeros(len(points),int);conflicts=np.zeros(len(points),int)
            samples=[];source_valid=None
            for other in [name]+[n for n in names if n!=name]:
                O,OK=views[other];pc=points@O[:3,:3].T+O[:3,3];p=pc@OK.T
                u,v=np.rint(p[:,:2]/np.maximum(p[:,2:],1e-8)).astype(int).T;mask=masks[other];h,w=mask.shape
                valid=(pc[:,2]>.01)&(u>=2)&(v>=2)&(u<w-2)&(v<h-2)
                ix=u.clip(0,w-1);iy=v.clip(0,h-1);valid&=mask[iy,ix]
                # A neighbourhood crossing a semantic boundary is unknown.
                valid&=safe_masks[other][iy,ix]
                color=blurred[other][iy,ix]
                if source_valid is None:source_valid=valid.copy();ref=color.copy()
                agree=(np.abs(color-ref).mean(1)<.10)&source_valid
                votes+=valid&agree;conflicts+=valid&~agree
                samples.append((color,valid&agree))
            keep=(votes>=3)&(conflicts<=1)&source_valid
            for j in np.flatnonzero(keep):
                identity=surface_sample_identity(ids[tri],bary[j])
                if identity in seen:continue
                seen.add(identity);result.append(points[j]);sources.append(ids[tri]);weights.append(bary[j]);supports.append(votes[j])
                colors.append(np.median([c[j] for c,v in samples if v[j]],0))
                if len(result)>=budget:break
            if len(result)>=budget:break
        if len(result)>=budget:break
    if not result:return None,{"status":"no_multiview_supported_samples","tracks":len(xyz)}
    return {"xyz":np.asarray(result,np.float32),"rgb":np.asarray(colors,np.float32),
        "triangle_sources":np.asarray(sources,np.int64),"sample_bary":np.asarray(weights,np.float64),
        "source_id":np.arange(len(result),dtype=np.int64),"support":np.asarray(supports,np.int16)}, {
            "status":"finite_measured_surface_hypotheses","tracks":len(xyz),"samples":len(result),
            "views":names,"independentDenseTruth":False}


def prepare_surface_stage(data, out, *, room_budget=6000, garment_budget=5000):
    """Finite extra support, in the job directory, with legacy input intact."""
    from scipy.spatial import cKDTree
    out=Path(out);out.mkdir(exist_ok=True)
    views={n:(data["worlds"][n],data["K"]) for n in data["train"]}
    rgbs={n:data["rgb"][n] for n in views}
    room=data["room"];measured=room["source_kind"]==0
    new,room_report=finite_triangle_samples(room["xyz"][measured],room["source_id"][measured],views,
        {n:data["labels"][n]["observed_room"] for n in views},rgbs,
        budget=room_budget,max_edge=192.,require_plane=True)
    if new is not None:
        # No repeated support is rebranded as an independent measurement.
        distances=cKDTree(room["xyz"]).query(new["xyz"])[0];take=distances>data["scale"]*1e-6
        new={k:v[take] for k,v in new.items()}
        new["source_id"]=np.arange(len(new["xyz"]),dtype=np.int64)+int(room["source_id"].max())+1
        new["source_kind"]=np.ones(len(new["xyz"]),np.uint8)
        old_bary=room.get("sample_bary",np.full((len(room["xyz"]),3),np.nan))
        room={k:np.concatenate((room[k] if k in room else old_bary,new[k])) for k in new}
        np.savez_compressed(out/"room-surface-hypotheses.npz",**room)
        data["room"]=room;room_report["uniqueSamplesAdded"]=int(take.sum())
    from reconstruction_static_planes import finite_plane_support
    planar,plane_report=finite_plane_support(room,views,{n:data["labels"][n]["observed_room"] for n in views},rgbs,data["scale"])
    if planar is not None:
        distances=cKDTree(room["xyz"]).query(planar["xyz"])[0];take=distances>data["scale"]*1e-6
        planar={k:v[take] for k,v in planar.items()}
        defaults={"surface_normal":np.zeros((len(room["xyz"]),3),np.float32),
                  "plane_id":np.full(len(room["xyz"]),-1,np.int16),
                  "sample_bary":np.full((len(room["xyz"]),3),np.nan)}
        room={k:np.concatenate((room[k] if k in room else defaults[k],planar[k])) for k in planar}
        data["room"]=room;plane_report["uniqueSamplesAdded"]=int(take.sum())
        np.savez_compressed(out/"room-surface-hypotheses.npz",**room)
    # Body observations need their own motion evidence. Do not silently treat
    # a long non-rigid recording as static MVS to make a neck bridge.
    garment_report={"status":"body_local_motion_required","existingSeedsRetained":True,
                    "noHeadRigidClothingFallback":True}
    selection=Path(data["source"])/"frame_selection.json"
    audit_manifest=Path(data["source"])/"frame_manifest.audit.json"
    if selection.is_file() or audit_manifest.is_file():
        records=json.loads((selection if selection.is_file() else audit_manifest).read_text())
        timestamps={r["name"]:r.get("timestampSeconds") for r in records.get("selectedFrames",records.get("frames",[]))}
        timed=sorted((timestamps[n],n) for n in views if timestamps.get(n) is not None)
        windows=[[(t,n) for t,n in timed if 0<=t-start<=3.] for start,_ in timed]
        windows=[w for w in windows if len(w)>=6]
        if windows:
            # Window selection is based on observations, not development RGB.
            window=max(windows,key=lambda rows:sum(data["labels"][n]["observed_cloth"].sum() for t,n in rows))[:12]
            ns=[n for t,n in window];local_views={n:views[n] for n in ns}
            cloth=dict(np.load(Path(data["prepared"])/"cloth_supported_seeds.npz"))
            seed,new_report=finite_triangle_samples(cloth["xyz"],cloth["source_id"],local_views,
                {n:data["labels"][n]["observed_cloth"] for n in ns},rgbs,budget=garment_budget)
            garment_report.update(shortWindow=new_report,timestampsSeconds=[t for t,n in window],
                limitation="quasistatic short-window support; independent torso pose still required")
            if seed is not None:
                # Keep the existing measured seeds and separately labelled
                # derived samples. No skin-to-clothing welding or alpha seam.
                seed["source_id"]+=int(cloth["source_id"].max())+1
                merged={k:np.concatenate((cloth[k],seed[k])) for k in ("xyz","rgb","support","source_id")}
                np.savez_compressed(out/"cloth-supported-seeds.npz",**merged)
                np.savez_compressed(out/"cloth-sample-lineage.npz",**seed)
                data["cloth_stage_seeds"]=merged
    report={"room":room_report,"finitePlanes":plane_report,"garment":garment_report,
        "hypothesesNotMeasuredTruth":True,"appearanceTrainingUsesFullObservedRegions":True}
    (out/"stage.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report
