"""Pinned DA3 depth-only inference into the SELF observation contract.
Known cameras are retained. Predicted poses are only used for ONE scale check.
No GS exporter or optional renderer from the upstream project is imported.
"""
import argparse,json,time,sys,shutil,gc
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_dense_contract import *
def select_names(raw,plan,limit,source_frames):
    index={str(n):i for i,n in enumerate(raw["names"])}
    forbidden=set(plan["development"])|set(plan["audit"])
    train=[n for n in plan["train"] if n in index and n not in forbidden]
    if len(train)<3:raise ValueError("insufficient_training_observations")
    # Uniform time coverage, independent of development RGB, plus readable metadata.
    if any(n not in source_frames for n in train):raise ValueError("missing_capture_identity")
    train=sorted(train,key=lambda n:(source_frames[n]["timestampSeconds"],source_frames[n]["sourceIndexZeroBased"]))
    if len(train)>limit:train=[train[i] for i in np.unique(np.rint(np.linspace(0,len(train)-1,limit)).astype(int))]
    return train,index
def run(prepared,split,tool,out,limit=24,batch=8,resolution=504):
    start=time.perf_counter();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    source=out/"algorithm-source";source.mkdir()
    for p in [Path(__file__),Path(__file__).with_name("reconstruction_dense_contract.py")]:shutil.copyfile(p,source/p.name)
    prep=Path(prepared);tool=Path(tool);lock=json.loads((tool/"weights-lock.json").read_text())
    for row in lock["files"]:
        if digest(tool/"model"/row["name"])!=row["sha256"]:raise ValueError("depth_weight_hash_changed")
    src=tool/"source"/("Depth-Anything-3-"+lock["codeCommit"])/"src";sys.path.insert(0,str(src))
    from depth_anything_3.cfg import create_object,load_config
    from depth_anything_3.utils.io.input_processor import InputProcessor
    from safetensors.torch import load_file
    net=create_object(load_config("depth_anything_3.configs.da3-base"))
    weights=load_file(tool/"model/model.safetensors")
    if not all(k.startswith("model.") for k in weights):raise ValueError("unexpected_checkpoint_namespace")
    loaded={k[len("model."):]:v for k,v in weights.items()}
    # Official auxiliary projections SHARE LayerNorm objects across levels.
    # HF serializes one alias; only verified identical Parameter objects may
    # populate aliases. Missing independent weights still fail strict loading.
    required=net.state_dict(keep_vars=True)
    loaded,aliases=complete_parameter_aliases(required,loaded)
    net.load_state_dict(loaded,strict=True);del loaded,weights,required
    write_json(out/"checkpoint-aliases.json",aliases)
    net=net.cuda().eval();processor=InputProcessor()
    meta=json.loads((prep/"preparation.json").read_text());raw=dict(np.load(prep/"local_geometry.npz"))
    plan=json.loads(Path(split).read_text())
    world={str(n):raw["C"][i] for i,n in enumerate(raw["world_names"])}
    source_root=(prep.parent.parent/meta["source"]).resolve()
    frames=json.loads((source_root/"frame_manifest.audit.json").read_text())
    if digest(source_root/"capture.mp4")!=meta["sourceHash"] or frames["captureSha256"]!=meta["sourceHash"]:
        raise ValueError("source_identity_changed")
    by={r["name"]:r for r in frames["frames"]};K=raw["K"]
    names,index=select_names(raw,plan,limit,by)
    rgb={n:cv2.cvtColor(cv2.imread(str(prep/"rectified_observations"/n)),cv2.COLOR_BGR2RGB) for n in names}
    labels={n:dict(np.load(prep/"rectified_observations"/(n+".npz"))) for n in names}
    h,w=rgb[names[0]].shape[:2]
    manifest=dict(schema=SCHEMA,sourceHash=meta["sourceHash"],colour="original_srgb_rgb",
        depthMeaning="camera_z",matrixMeaning="W2C",coordinateGroups=["world","head-local"],
        modelLock=lock,knownCameraOverwrite=False,inferGS=False,nativeSize=[w,h],
        forbidden=plan["development"]+plan["audit"],observations=[],published=False)
    details=[];torch.cuda.reset_peak_memory_stats()
    for group in ["world","head-local"]:
        selected=[n for n in names if group=="head-local" or n in world]
        if len(selected)<3:continue
        # Consecutive overlapping windows; depth layers NEVER fused by row order.
        blocks=[selected[i:i+batch] for i in range(0,len(selected),batch-2) if len(selected[i:i+batch])>=3]
        for bi,block in enumerate(blocks):
            if group=="head-local":
                mask=np.logical_or.reduce([labels[n]["face_core"]|labels[n]["face_boundary"]|labels[n]["hair_visible"]|labels[n]["glasses_visible"] for n in block])
                yy,xx=np.where(mask);pad=int(.10*max(np.ptp(xx),np.ptp(yy)))+8
                rect=[max(0,int(xx.min())-pad),max(0,int(yy.min())-pad),min(w,int(xx.max())+pad+1),min(h,int(yy.max())+pad+1)]
            else:rect=[0,0,w,h]
            x0,y0,x1,y1=rect;rw,rh=x1-x0,y1-y0
            size=(max(14,round(rw/max(rw,rh)*resolution/14)*14),max(14,round(rh/max(rw,rh)*resolution/14)*14))
            Ks,A=resized_camera(K,rect,(w,h),size)
            images=[cv2.resize(rgb[n][y0:y1,x0:x1],size,interpolation=cv2.INTER_AREA) for n in block]
            ex=np.stack([world[n] if group=="world" else raw["F"][index[n]] for n in block])
            normalized,normalization_radius=normalize_cameras(ex)
            tensor,_,_=processor(images,None,None,resolution,"upper_bound_resize",num_workers=1)
            if tensor.shape[-2:]!=(size[1],size[0]):raise ValueError("unexpected_second_resize")
            inp=tensor[None].cuda();camera=torch.tensor(normalized,dtype=torch.float32,device="cuda")[None]
            intrinsic=torch.tensor(np.repeat(Ks[None],len(block),0),dtype=torch.float32,device="cuda")[None]
            t0=time.perf_counter()
            with torch.inference_mode(),torch.autocast("cuda",dtype=torch.bfloat16):
                pred=net(inp,camera,intrinsic,infer_gs=False,ref_view_strategy="first")
            depth=pred["depth"][0].float().cpu().numpy();conf=pred["depth_conf"][0].float().cpu().numpy()
            if depth.ndim==4 and depth.shape[-1]==1:depth=depth[...,0]
            if conf.ndim==4 and conf.shape[-1]==1:conf=conf[...,0]
            if depth.shape!=(len(block),size[1],size[0]) or conf.shape!=depth.shape:raise ValueError("depth_shape_contract")
            proposed=pred["extrinsics"][0].float().cpu().numpy()
            if proposed.shape[-2:]==(3,4):proposed=np.concatenate([proposed,np.tile([[[0,0,0,1]]],(len(block),1,1))],axis=1)
            try:scale,alignment=align_camera_scale(proposed,ex)
            except ValueError as e:
                details.append(dict(group=group,batch=bi,names=block,rejected=str(e)));del inp,camera,intrinsic,pred;torch.cuda.empty_cache();continue
            depth*=scale
            quality=bool(alignment["cameraCentreRmsRelative"]<=.25)
            folder=out/f"{group}-{bi}";folder.mkdir()
            details.append(dict(group=group,batch=bi,names=block,inputNormalizationRadius=normalization_radius,
                alignment=alignment,scaleGatePassed=quality,inferenceSeconds=time.perf_counter()-t0,
                depthRange=[float(np.nanquantile(depth,.01)),float(np.nanquantile(depth,.99))],
                processedSize=list(size),rectangle=rect))
            for j,n in enumerate(block):
                path=folder/(n+".npz")
                np.savez_compressed(path,depth=depth[j],confidence=conf[j],K=Ks,W2C=ex[j],nativeToProcessed=A,
                    proposedW2C=proposed[j],rectangle=rect,sourceHash=np.array(meta["sourceHash"]),imageName=np.array(n))
                identity=dict(imageName=n,group=group,window=bi,file=str(path.relative_to(out)),role="train",
                    sourceHash=meta["sourceHash"],imageHash=digest(prep/"rectified_observations"/n),
                    sourceIndexZeroBased=int(by[n]["sourceIndexZeroBased"]),timestampSeconds=float(by[n]["timestampSeconds"]),
                    W2C=ex[j].tolist(),K=Ks.tolist(),rectangle=rect,processedSize=list(size),scaleGatePassed=quality)
                manifest["observations"].append(identity)
            del inp,camera,intrinsic,pred;gc.collect();torch.cuda.empty_cache()
            print(json.dumps(details[-1]),flush=True)
    # Repeated image/window entries are explicitly namespaced, not silently joined.
    manifest["observationIdentity"]="(group,window,imageName)"
    unique={};seen=set()
    for r in manifest["observations"]:
        key=(r["group"],r["window"],r["imageName"])
        if key in seen:raise ValueError("duplicate_window_identity")
        seen.add(key);unique.setdefault(r["group"],[]).append(r)
    for group,rows in unique.items():
        for bi in set(r["window"] for r in rows):
            validate_manifest({**manifest,"observations":[r for r in rows if r["window"]==bi]})
    manifest["seconds"]=time.perf_counter()-start
    manifest["allocatedMiB"]=torch.cuda.max_memory_allocated()/1048576
    manifest["reservedMiB"]=torch.cuda.max_memory_reserved()/1048576
    write_json(out/"manifest.json",manifest);write_json(out/"batches.json",details)
    del net;gc.collect();torch.cuda.empty_cache()
    print("DEPTH_PROPOSALS_COMPLETE_NOT_ACCEPTED_GEOMETRY",flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ["prepared","split","tool","out"]:p.add_argument("--"+k,required=True)
    p.add_argument("--limit",type=int,default=24);p.add_argument("--batch",type=int,default=8)
    a=p.parse_args();existed=Path(a.out).exists()
    try:run(a.prepared,a.split,a.tool,a.out,a.limit,a.batch)
    except Exception as error:
        # Save failed evidence; never manufacture a usable manifest or retry
        # under weaker thresholds. A new invocation requires a new run directory.
        failed=Path(a.out)/'failure.json'
        if not existed and Path(a.out).is_dir() and not failed.exists():
            import traceback
            write_json(failed,{'status':'failed','type':type(error).__name__,'message':str(error),
                'traceback':traceback.format_exc(),'published':False})
        raise
