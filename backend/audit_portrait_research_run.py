"""Evidence assembly for one portrait-first study; never publishes assets."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from reconstruction_accessories import candidate_policy


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(x):
    return x/max(float(np.linalg.norm(x)),1e-12)


def run(prepared, prefix, output, frozen):
    roots={k:Path(str(prefix)+"-"+v) for k,v in {
        "transfer":"transfer","strong":"strong","soft":"soft-r2",
        "scene":"scene-r3","capacity":"capacity-r2","lines":"glasses-lines-anchored"}.items()}
    # The exact source hashes remain associated with each original run.
    reports={k:read(v/"report.json") for k,v in roots.items() if k!="lines"}
    line=read(roots["lines"]/"audit.json")
    geom=dict(np.load(prepared/"local_geometry.npz"));meta=read(prepared/"preparation.json")
    names=geom["names"].tolist();roles=geom["roles"].tolist()
    policy=candidate_policy({"sourceHash":meta["sourceHash"],"local":dict.fromkeys(names)},line["segments"])
    held=[n for n,r in zip(names,roles) if r=="development"]
    stages={"initial":read(roots["transfer"]/"initial/audit.json"),
            "strong900":read(roots["strong"]/"after-local/audit.json"),
            "soft900":read(roots["soft"]/"after-local/audit.json"),
            "T3":read(roots["scene"]/"after-T3/audit.json"),
            "T4":read(roots["scene"]/"final/audit.json")}
    measures={n:{k:{"localFace":v[n]["T0"]["face"],"localHair":v[n]["T0"]["hair"],
                          "features":v[n].get("featureRgbL1"),"fullFace":v[n].get("T2",{}).get("face")}
                   for k,v in stages.items()} for n in held}
    output.mkdir(parents=True,exist_ok=True)
    # Camera-identical source/initial/strong/soft/joint/full comparison.
    chosen=[held[i] for i in (min(1,len(held)-1),min(3,len(held)-1),len(held)-1)]
    for n in chosen:
        paths=[roots["transfer"]/"initial",roots["strong"]/"after-local",roots["soft"]/"after-local",roots["scene"]/"final"]
        crop=stages["initial"][n]["crop"];width=crop[2]-crop[0]
        images=[cv2.cvtColor(cv2.imread(str(p/(n+"-stages.png"))),cv2.COLOR_BGR2RGB) for p in paths]
        tiles=[images[0][:,:width]]+[im[:,width:width*2] for im in images]
        titles=["Source","Initial T0","Strong 900","Soft 900","Joint local T0"]
        if images[-1].shape[1]>=4*width:
            tiles.append(images[-1][:,3*width:4*width]);titles.append("Joint complete scene")
        montage=Image.new("RGB",(len(tiles)*width,tiles[0].shape[0]+28),(22,22,26));draw=ImageDraw.Draw(montage)
        for i,(im,title) in enumerate(zip(tiles,titles)):
            montage.paste(Image.fromarray(im),(i*width,28));draw.text((i*width+8,8),title,fill=(230,230,235))
        montage.save(output/(n+"-controlled-comparison.png"))
    ref=read(roots["scene"]/"portrait.view.json")["sourceFrame"]
    idx=names.index(ref);C=geom["C"][geom["world_names"].tolist().index(ref)]
    F=geom["F"][idx].copy();F[:3,3]*=float(geom["scale"]);H=np.linalg.solve(C,F)
    center=np.median(geom["meshes"][idx],axis=0)
    rays=[normalize(-f[:3,:3].T@f[:3,3]-center) for f in geom["F"]]
    orbit_audits={}
    for orbit_name in ("continuous-orbit","continuous-orbit-small"):
        orbit=read(roots["scene"]/orbit_name/"audit.json")
        if orbit["plySha256"]!=sha(roots["scene"]/"portrait.gaussian.ply"):
            raise ValueError("orbit_ply_changed")
        directions=[]
        for sample in orbit["samples"]:
            local_center=H[:3,:3].T@(np.asarray(sample["gsView"]["position"])-H[:3,3])/float(geom["scale"])
            ray=normalize(local_center-center)
            angles=np.degrees(np.arccos(np.clip(np.asarray(rays)@ray,-1,1)))
            nearest=int(angles.argmin())
            directions.append({"label":sample["label"],"headLocalCamera":local_center.tolist(),
                "nearestLocalFrame":names[nearest],"role":roles[nearest],"angularDistanceDegrees":float(angles[nearest]),
                "notVisibilityOrGeometryProof":True})
        orbit_audits[orbit_name]={"asset":orbit["plySha256"],"video":orbit["videoSha256"],
            "errors":orbit["browserErrors"],"directions":directions}
    old=read(frozen)["protected"]
    workspace=Path.cwd().parent
    protected={name:{"expected":r["sha256"],"current":sha(workspace/Path(name.replace("\\","/")))} for name,r in old.items()}
    for r in protected.values():r["unchanged"]=r["expected"]==r["current"]
    train=read(roots["scene"]/"T3-training.json")
    result={"sourceHash":meta["sourceHash"],"prepared":str(prepared),"model":"FLAME2023Open",
        "localTrainFrames":[n for n,r in zip(names,roles) if r=="train"],"developmentFrames":held,
        "localOnlyTrainFrames":[n for n,r in zip(names,roles) if r=="train" and n not in geom["world_names"]],
        "perFrame":measures,"T3PortraitParameterChange":train["portraitParameterChange"],
        "capacityDecision":reports["capacity"]["event"],"eyewearPolicy":policy,"orbits":orbit_audits,
        "protectedFiles":protected,"runs":{k:{"path":str(roots[k]),"seconds":r["seconds"],
            "assetHash":r.get("plySha256",r.get("assetHash")),"sourceCodeAtRun":r.get("sourceFiles"),
            "allocatedPeakMiB":r.get("allocatedPeakMiB"),"reservedPeakMiB":r.get("reservedPeakMiB")} for k,r in reports.items()},
        "releaseApproved":False,"tabletTransfer":False,"noGlassesRealVideoTest":"not_run"}
    (output/"evidence.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"localTrain":len(result["localTrainFrames"]),"development":len(held),
        "localOnlyTrain":len(result["localOnlyTrainFrames"]),"protectedUnchanged":all(r["unchanged"] for r in protected.values()),
        "T3ExactlyFrozen":all(v==0 for v in result["T3PortraitParameterChange"].values())}))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("prepared",type=Path);p.add_argument("prefix",type=Path)
    p.add_argument("output",type=Path);p.add_argument("frozen",type=Path)
    a=p.parse_args();run(a.prepared,a.prefix,a.output,a.frozen)
