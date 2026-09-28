"""Bounded, known-F line reconstruction for the glasses component.

This minimal line-plane implementation consumes current rectified photographs
and measured local poses. It does not join sparse points into a guessed frame,
does not use room C for moving glasses, and does not claim reflective lenses
are rigid lines. All endpoints, observation IDs and rejection counts survive.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

from reconstruction_components_v2 import load_prepared, project, write_json
from reconstruction_accessories import candidate_policy


def line_equation(segment):
    a,b=np.column_stack((segment,np.ones(2)))
    line=np.cross(a,b)
    return line/max(np.linalg.norm(line[:2]),1e-10)


def triangulate_segment(a,b,F_a,F_b,K):
    """Intersect endpoint rays from a with the interpretation plane of b."""
    plane=(K@F_b[:3]).T@line_equation(b)
    origin=-F_a[:3,:3].T@F_a[:3,3]
    rays=(np.linalg.inv(K)@np.column_stack((a,np.ones(2))).T).T@F_a[:3,:3]
    denom=rays@plane[:3]
    if np.min(np.abs(denom))<1e-7:return None
    t=-(np.dot(origin,plane[:3])+plane[3])/denom
    if (t<=0).any():return None
    return origin+rays*t[:,None]


def segment_distance(projected,observed):
    direction=observed[1]-observed[0];length=np.linalg.norm(direction)
    if length<1e-6:return 1e6,0.,180.
    direction/=length
    cross=np.array([-direction[1],direction[0]])
    perpendicular=float(np.abs((projected-observed[0])@cross).max())
    extent=np.sort((projected-observed[0])@direction)
    overlap=max(0.,min(length,extent[1])-max(0.,extent[0]))/max(min(length,extent[1]-extent[0]),1e-8)
    d=projected[1]-projected[0]
    angle=np.degrees(np.arccos(np.clip(abs(d@direction)/max(np.linalg.norm(d),1e-8),0,1)))
    return perpendicular,overlap,float(angle)


def profile(image,segment):
    direction=segment[1]-segment[0];normal=np.array([-direction[1],direction[0]])
    normal/=max(np.linalg.norm(normal),1e-8)
    sample=segment[0]+np.linspace(.1,.9,16)[:,None]*direction
    sample=sample[:,None,:]+np.linspace(-2,2,5)[None,:,None]*normal
    return cv2.remap(image,sample[:,:,0].astype(np.float32),sample[:,:,1].astype(np.float32),cv2.INTER_LINEAR)


def extract_lines(rgb,mask):
    gray=cv2.cvtColor((rgb*255).round().astype(np.uint8),cv2.COLOR_RGB2GRAY)
    raw=cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    if raw is None:return np.empty((0,2,2),np.float64),[]
    observed=cv2.dilate(mask.astype(np.uint8),np.ones((5,5),np.uint8))>0
    segments=[];profiles=[]
    for values in raw[:,0]:
        segment=values.reshape(2,2).astype(np.float64);length=np.linalg.norm(segment[1]-segment[0])
        if not 8<=length<=160:continue
        samples=segment[0]+np.linspace(0,1,20)[:,None]*(segment[1]-segment[0])
        u,v=np.rint(samples).astype(int).T;h,w=observed.shape
        if (u<0).any() or (u>=w).any() or (v<0).any() or (v>=h).any():continue
        if observed[v,u].mean()<.65:continue
        p=profile(rgb,segment)
        # Bright isolated reflections have no stable opaque-line claim.
        if p[:,2].mean()>.86 or float(p.max()-p.min())<.08:continue
        segments.append(segment);profiles.append(p)
    return np.asarray(segments).reshape(-1,2,2),profiles


def reconstruct(data,out,max_pairs=160,require_anchor_support=False):
    start=time.perf_counter();out.mkdir(parents=True,exist_ok=False)
    names=sorted(n for n,r in data["local"].items() if r["role"]=="train")
    features={n:extract_lines(data["rgb"][n],data["labels"][n]["glasses_visible"]) for n in names}
    pairs=[]
    for i,a in enumerate(names):
        for b in names[i+1:i+5]:
            R=data["local"][a]["F"][:3,:3]@data["local"][b]["F"][:3,:3].T
            angle=np.linalg.norm(cv2.Rodrigues(R)[0])*180/np.pi
            if 2<=angle<=18:pairs.append((a,b,angle))
    pairs=sorted(pairs,key=lambda p:p[2],reverse=True)[:max_pairs]
    rejected={k:0 for k in ("ambiguousAppearance","twoViewGeometry","thirdView","duplicate","pointLineDisagreement")}
    accepted=[];K=data["K"]
    for a,b,angle in pairs:
        seg_a,pa=features[a];seg_b,pb=features[b]
        Fa,Fb=data["local"][a]["F"],data["local"][b]["F"]
        mesh=data["local"][a]["mesh"];tree=cKDTree(mesh)
        for ai,line_a in enumerate(seg_a):
            matches=[]
            for bi,line_b in enumerate(seg_b):
                colour=min(np.abs(pa[ai]-pb[bi]).mean(),np.abs(pa[ai]-pb[bi][::-1,::-1]).mean())
                if colour>.10:continue
                xyz=triangulate_segment(line_a,line_b,Fa,Fb,K)
                if xyz is None or not np.isfinite(xyz).all():continue
                length=np.linalg.norm(xyz[1]-xyz[0])
                if not .002<=length<=.09 or (tree.query(xyz)[0]>.065).any():continue
                uv,z=project(xyz,Fb,K)
                distance,overlap,theta=segment_distance(uv,line_b)
                if (z<.05).any() or overlap<.5 or theta>3 or distance>1.5:continue
                matches.append((float(colour),bi,xyz))
            matches.sort(key=lambda x:x[0])
            if not matches:rejected["twoViewGeometry"]+=1;continue
            if len(matches)>1 and matches[0][0]>.85*matches[1][0]:
                rejected["ambiguousAppearance"]+=1;continue
            colour,bi,xyz=matches[0];support=[(a,ai,0.),(b,bi,0.)]
            for c in names:
                if c in (a,b):continue
                Fc=data["local"][c]["F"]
                uv,z=project(xyz,Fc,K)
                if (z<.05).any():continue
                best=None
                for ci,line_c in enumerate(features[c][0]):
                    dist,overlap,theta=segment_distance(uv,line_c)
                    if dist>2 or overlap<.55 or theta>8:continue
                    p=features[c][1][ci]
                    similarity=min(np.abs(pa[ai]-p).mean(),np.abs(pa[ai]-p[::-1,::-1]).mean())
                    if similarity>.10:continue
                    score=dist+similarity*10
                    if best is None or score<best[0]:best=(score,ci,dist)
                if best is not None:support.append((c,best[1],float(best[2])))
            if len(support)<3:rejected["thirdView"]+=1;continue
            anchor_support=[]
            if require_anchor_support:
                # Additional independent point-track depth, not guessed
                # edges connecting the 16 sparse points. The line itself
                # must still be observed and triangulated in three views.
                anchors=data["components"]["glasses"]["xyz"]
                edge=xyz[1]-xyz[0];denom=max(float(edge@edge),1e-12)
                position=(anchors-xyz[0])@edge/denom
                projected=xyz[0]+position[:,None]*edge
                near=(np.linalg.norm(anchors-projected,axis=1)<.0025)&(position>=-.1)&(position<=1.1)
                anchor_support=np.flatnonzero(near).tolist()
                if len(anchor_support)<2:
                    rejected["pointLineDisagreement"]+=1;continue
            # Repeated hypotheses are not independent geometric evidence.
            mid=xyz.mean(0);direction=(xyz[1]-xyz[0])/np.linalg.norm(xyz[1]-xyz[0])
            if any(np.linalg.norm(mid-r["xyz"].mean(0))<.003 and abs(direction@r["direction"])>.97 for r in accepted):
                rejected["duplicate"]+=1;continue
            accepted.append({"xyz":xyz,"direction":direction,"support":support,"appearanceResidual":colour,"pointAnchorIndices":anchor_support})
    segments=np.stack([r["xyz"] for r in accepted]) if accepted else np.empty((0,2,3))
    # This input has generic eye-edge masks, not an eyewear classifier.
    # Keep candidate lines separate from an instantiated glasses component.
    policy=candidate_policy(data,accepted)
    np.savez_compressed(out/"glasses_lines.npz",segments=segments,source_sha256=np.asarray(data["sourceHash"]),
                        semantics=np.asarray("eye_band_line_candidates"),automatic_promotion=np.asarray(False))
    report={"sourceSha256":data["sourceHash"],"coordinateSystem":"head_local_F_not_world_C",
        "method":"LSD_profiles_known_pose_interpretation_plane_intersection_plus_third_view_validation",
        "lineCandidates":{n:len(features[n][0]) for n in names},"pairsTested":len(pairs),
        "acceptedSegmentCount":len(segments),"rejected":rejected,"seconds":time.perf_counter()-start,
        "requiresIndependentPointLineDepth":require_anchor_support,
        "accessoryPolicy":policy,
        "segments":[{**r,"xyz":r["xyz"].tolist(),"direction":r["direction"].tolist()} for r in accepted],
        "status":"candidate_geometry_requires_visual_audit_not_complete_glasses",
        "limitations":["Known F uncertainty propagates to depth; no pose refinement performed",
                       "No artificial connection between independently observed short segments",
                       "No reflective lens solid geometry; no publication"]}
    write_json(out/"audit.json",report)
    for name in names[::max(1,len(names)//6)]:
        image=(data["rgb"][name]*255).round().astype(np.uint8)
        for r in accepted:
            uv,z=project(r["xyz"],data["local"][name]["F"],K)
            if (z>0).all():cv2.line(image,tuple(uv[0].round().astype(int)),tuple(uv[1].round().astype(int)),(0,220,160),1,cv2.LINE_AA)
        marks=data["local"][name]["marks"][[33,133,263,362,168,6]]
        x0,y0=np.maximum(marks.min(0).astype(int)-70,0);x1,y1=np.minimum(marks.max(0).astype(int)+70,[image.shape[1],image.shape[0]])
        cv2.imwrite(str(out/(name+"-line-audit.png")),cv2.cvtColor(image[y0:y1,x0:x1],cv2.COLOR_RGB2BGR))
    print(json.dumps({k:report[k] for k in ("acceptedSegmentCount","pairsTested","rejected","seconds")}),flush=True)
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("prepared",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--anchor-support",action="store_true")
    args=p.parse_args();reconstruct(load_prepared(args.prepared),args.output,require_anchor_support=args.anchor_support)
