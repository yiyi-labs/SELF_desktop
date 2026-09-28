"""One bounded, photo-supported capacity experiment with full rollback."""
import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np
import torch

from reconstruction_components_v2 import load_prepared, write_json
from reconstruction_portrait_model import CandidateTransaction
from reconstruction_portrait_pipeline import (initialize_scene,make_frame,head_loss,
    audit_stages,export_candidate,digest,ENGINE_VERSION)


@torch.no_grad()
def observation_support(scene,data,triangle_ids,bary):
    model=scene.portrait;device=model.role.device
    votes=torch.zeros(len(triangle_ids),device=device)
    for name,row in data["local"].items():
        if row["role"]!="train":continue
        mesh=torch.as_tensor(row["mesh"],device=device)+model.surface_residual
        triangles=mesh[model.faces[triangle_ids]]
        normal=torch.nn.functional.normalize(torch.linalg.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),dim=-1)
        points=(triangles*bary[:,:,None]).sum(1)
        F=torch.as_tensor(row["F"],device=device);K=torch.as_tensor(data["K"],device=device,dtype=points.dtype)
        cam=points@F[:3,:3].T+F[:3,3];uv=cam@K.T
        pixel=(uv[:,:2]/uv[:,2:].clamp_min(.01)).round().long();u,v=pixel.unbind(1)
        h,w=data["rgb"][name].shape[:2]
        valid=(cam[:,2]>.05)&(u>=0)&(v>=0)&(u<w)&(v<h)
        valid&=((normal@F[:3,:3].T)*(-cam)).sum(1)>0
        mask=data["labels"][name]["face_core"]|data["labels"][name]["face_boundary"]
        observed=torch.as_tensor(mask[v.clamp(0,h-1).cpu().numpy(),u.clamp(0,w-1).cpu().numpy()],device=device)
        votes+=(valid&observed).float()
    return votes>=3


def run(args):
    if args.output.exists():raise FileExistsError(args.output)
    args.output.mkdir(parents=True);start=time.perf_counter()
    data=load_prepared(args.prepared)
    shutil.copyfile(args.prepared/"cloth_supported_seeds.npz",args.output/"cloth_supported_seeds.npz")
    scene=initialize_scene(data,args.output);scene.portrait.constraint_mode="soft"
    checkpoint=torch.load(args.state,map_location="cuda",weights_only=True)
    if checkpoint["sourceSha256"]!=data["sourceHash"]:raise ValueError("capacity_source_changed")
    scene.load_state_dict(checkpoint["model"])
    model=scene.portrait
    for p in scene.parameters():p.requires_grad_(False)
    for key in ("sh","opacity_logits","log_scales"):getattr(model,key).requires_grad_(True)
    opt=torch.optim.Adam([{"params":[p],"lr":{"sh":.004,"opacity_logits":.008,"log_scales":.002}.get(n,0.),"name":n}
                          for n,p in model.named_parameters()],eps=1e-8)
    # A new fixed recovery optimizer; its exact pre-transaction state is
    # snapshotted. Existing completed training Adam is not falsely claimed.
    names=[n for n,r in data["local"].items() if r["role"]=="train"]
    checks=[n for n,r in data["local"].items() if r["role"]=="development"]
    checks+=list(dict.fromkeys((names[0],names[len(names)//2],names[-1])))
    before=audit_stages(scene,data,args.output/"before",stages=("T0",))
    selected=torch.where((model.role[:model.surface_count]==0)&(model.confidence[:model.surface_count]>=3))[0]
    supported=observation_support(scene,data,model.triangle_ids[selected],model.embedding[selected].detach())
    selected=selected[supported]
    # Exactly one bounded proposal, never repeated tolerance/threshold tuning.
    def mutate():
        return model.replace_skin_parents(selected,opt,lambda ids,bary:observation_support(scene,data,ids,bary))
    @torch.no_grad()
    def audit():
        result={}
        for name in checks:
            frame=make_frame(data,name);rendered=scene.render(frame,"T0")
            mask=frame["masks"]["face_core"]|frame["masks"]["face_boundary"]
            error=(rendered["rgb"]-frame["rgb"]).abs().mean(-1)
            result[name]={"hole":float(((rendered["alpha"]<.8)*mask).sum()/mask.sum().clamp_min(1)),
                          "rgb":float((error*mask).sum()/mask.sum().clamp_min(1))}
        return result
    def recover(step):
        opt.zero_grad(set_to_none=True)
        frame=make_frame(data,names[step%len(names)])
        rendered=scene.render(frame,"T0");loss,_=head_loss(rendered,frame)
        loss.backward();opt.step()
        with torch.no_grad():
            # Recovery may adjust coverage but cannot recreate a giant parent.
            model.log_scales.copy_(torch.minimum(model.log_scales,model.initial_log_scales+np.log(1.15)))
        if step == 47:
            # Save the actual rejected candidate too, before the transaction
            # restores the original model. A rollback image is not evidence
            # of how the split looked.
            audit_stages(scene,data,args.output/"candidate-before-decision",stages=("T0",))
    with CandidateTransaction(model,opt) as transaction:
        try:
            event=transaction.run(mutate,recover,audit,recovery_steps=48)
        except ValueError as error:
            transaction.rollback()
            event={"accepted":False,"reason":str(error),"recoverySteps":0}
    after=audit_stages(scene,data,args.output/"after",stages=("T0",))
    asset=export_candidate(scene,data,args.output)
    report={"engineVersion":ENGINE_VERSION,"sourceHash":data["sourceHash"],"inputStateHash":digest(args.state),
            "selectedParents":len(selected),"event":event,"before":before,"after":after,
            "pointCount":len(model.role),"seconds":time.perf_counter()-start,"assetHash":asset,
            "status":"capacity_diagnostic_not_release_approved","recoveryUsesPhotographsNotOldRender":True}
    write_json(args.output/"report.json",report)
    print(json.dumps({k:report[k] for k in ("selectedParents","event","pointCount","seconds")}),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("prepared",type=Path);p.add_argument("state",type=Path);p.add_argument("output",type=Path)
    run(p.parse_args())
