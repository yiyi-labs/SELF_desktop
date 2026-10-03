"""SELF isolated five-part, shared-forward, native-ROI reconstruction trial.

The production trainer is unchanged. Every image/crop rasterizes all groups;
metadata follows actual parent replacement through the installed gsplat ops.
This prototype does not turn temporary E1 research cameras into release truth.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as functional
from gsplat import export_splats
from gsplat.strategy import DefaultStrategy
from gsplat.strategy.ops import _update_param_with_optimizer,remove
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from appearance_direction_contract import C0
from probe_flame_real_appearance import bound_points
from reconstruction_components_v2 import project,write_json
from reconstruction_joint_visibility import (COMPONENTS,render_components,
    component_conservation_error,quaternion_multiply,sha256_file)


def torch_sh_rotate(coeff,R):
    vector=torch.stack((-coeff[:,3],-coeff[:,1],coeff[:,2]),1)
    moved=torch.einsum("ij,njc->nic",R,vector)
    return torch.stack((coeff[:,0],-moved[:,1],moved[:,2],-moved[:,0]),1)


def mesh_depth(mesh,F,K,width,height):
    """Perspective-correct FLAME prior depth, not observed depth truth."""
    vertices,faces=mesh
    cam=vertices@F[:3,:3].T+F[:3,3]
    uv=cam@K.T;uv=uv[:,:2]/np.maximum(uv[:,2:],1e-8)
    depth=np.full((height,width),np.inf,np.float32)
    for tri in faces:
        xy=uv[tri];z=cam[tri,2]
        if (z<=.01).any():continue
        left=max(0,int(np.floor(xy[:,0].min())));right=min(width-1,int(np.ceil(xy[:,0].max())))
        top=max(0,int(np.floor(xy[:,1].min())));bottom=min(height-1,int(np.ceil(xy[:,1].max())))
        if left>right or top>bottom:continue
        den=(xy[1,1]-xy[2,1])*(xy[0,0]-xy[2,0])+(xy[2,0]-xy[1,0])*(xy[0,1]-xy[2,1])
        if abs(den)<1e-8:continue
        yy,xx=np.mgrid[top:bottom+1,left:right+1]
        a=((xy[1,1]-xy[2,1])*(xx-xy[2,0])+(xy[2,0]-xy[1,0])*(yy-xy[2,1]))/den
        b=((xy[2,1]-xy[0,1])*(xx-xy[2,0])+(xy[0,0]-xy[2,0])*(yy-xy[2,1]))/den
        c=1-a-b;inside=(a>=0)&(b>=0)&(c>=0)
        inverse=a/z[0]+b/z[1]+c/z[2]
        candidate=np.where(inside,1/np.maximum(inverse,1e-8),np.inf)
        depth[top:bottom+1,left:right+1]=np.minimum(depth[top:bottom+1,left:right+1],candidate)
    return depth


def initialization_reference(data):
    """Preserve a validated capture-wide reference chosen by the caller."""
    eligible=[n for n in data['train'] if n in data['local'] and n in data['worlds']
              and data['local'][n].get('role')=='train']
    if 'reference' in data:
        if data['reference'] not in eligible:
            raise ValueError('initialization_reference_not_actual_world_local_training')
        return data['reference']
    if not eligible:raise ValueError('initialization_no_world_local_training_reference')
    return max(eligible,key=lambda n:np.linalg.norm(data['local'][n]['marks'][234]-data['local'][n]['marks'][454]) /
        max(np.linalg.norm(data['local'][n]['marks'][10]-data['local'][n]['marks'][152]),1))


def initialize(data,out,device):
    p=data["prior"];faces=data["geometry"].faces.numpy()
    surface=len(p["surface_ids"])
    if surface!=int((p["role"]!=2).sum()):raise ValueError("prior_surface_binding_mismatch")
    votes={key:np.zeros(surface,np.int16) for key in ("skin","hair","glasses","cloth")}
    for name,row in data["local"].items():
        if row["role"]!="train":continue
        pts,normals=bound_points(row["mesh"],faces,p["surface_ids"],p["surface_bary"])
        uv,z=project(pts,row["F"],data["K"]);u,v=uv.round().astype(int).T
        h,w=data["rgb"][name].shape[:2];inside=(z>.05)&(u>=0)&(v>=0)&(u<w)&(v<h)
        ix=u.clip(0,w-1);iy=v.clip(0,h-1)
        camera_normals=normals@row["F"][:3,:3].T
        front=(camera_normals*(-(pts@row["F"][:3,:3].T+row["F"][:3,3]))).sum(1)>0
        inside &= front
        labels=data["labels"][name]
        votes["skin"] += (inside & (labels["face_core"][iy,ix]|labels["face_boundary"][iy,ix])).astype(np.int16)
        for key,label in (("hair","hair_visible"),("glasses","glasses_visible"),("cloth","neck_cloth_visible")):
            votes[key] += (inside & labels[label][iy,ix]).astype(np.int16)
    skin=(votes["skin"]>=3)&(votes["hair"]==0)&(votes["glasses"]<3)
    neck=(votes["cloth"]>=3)&~skin&(votes["hair"]==0)&(votes["glasses"]==0)
    chosen=np.flatnonzero(skin|neck)
    if skin.sum()<1000:raise ValueError("conservative_supported_skin_missing")
    # A capture-wide body/neck/dense reference must not be replaced by a
    # second independent max-width choice during legacy seed initialization.
    ref=initialization_reference(data)
    data["reference"]=ref
    s=data["scale"];ref_mesh=data["local"][ref]["mesh"]
    base,normals=bound_points(ref_mesh,faces,p["surface_ids"][chosen],p["surface_bary"][chosen])
    normal_offset=np.tanh(p["local_offsets"][chosen,0])*np.where(p["role"][chosen]==0,.006,.012)
    base += normals*normal_offset[:,None]
    part=np.where(neck[chosen],4,1).astype(np.int16)
    point_chunks=[base];color_chunks=[p["sh_coeff"][chosen]];scale_chunks=[np.exp(p["log_scales"][chosen])]
    quat_chunks=[p["local_quats"][chosen]];opacity_chunks=[p["opacity_logits"][chosen]]
    part_chunks=[part];tri=[p["surface_ids"][chosen]];bary=[p["surface_bary"][chosen]]
    offset=[normal_offset];support=[np.maximum(votes["skin"][chosen],votes["cloth"][chosen])]
    source_kind=[np.full(len(chosen),2,np.int16)];source_id=[p["source_index"][chosen].astype(np.int64)]
    for label,code in (("hair",2),("glasses",3),("cloth",4),("room",0)):
        seed=data["components"][label] if label in data["components"] else dict(np.load(out/"cloth_supported_seeds.npz")) if label=="cloth" else data["room"]
        xyz=seed["xyz"];n=len(xyz)
        if not n:continue
        point_chunks.append(xyz)
        coeff=np.zeros((n,4,3),np.float32);coeff[:,0]=(seed["rgb"]-.5)/C0;color_chunks.append(coeff)
        spacing=cKDTree(xyz).query(xyz,k=min(4,n))[0]
        nearest=np.maximum(spacing[:,1:].mean(1),.0008) if n>1 else np.full(n,.001)
        limits={"hair":(.001,.005),"glasses":(.0007,.0025),"cloth":(.003*s,.03*s),"room":(.003*s,.10*s)}
        low,high=limits[label];nearest=np.clip(nearest,low,high)
        initial_scale=np.stack((nearest,nearest,nearest*.65),1).astype(np.float32)
        initial_quat=np.tile([1.,0.,0.,0.],(n,1)).astype(np.float32)
        if label=="room":
            # A measured wall patch is a thin supported surface, not an
            # isotropic room volume. Triangle source IDs survive sampling.
            measured={int(i):point for i,point,kind in zip(seed["source_id"],xyz,seed["source_kind"]) if kind==0}
            normal_list=np.zeros((n,3),np.float32)
            for j,(kind,triangle) in enumerate(zip(seed["source_kind"],seed["triangle_sources"])):
                if kind!=1:continue
                triangle_xyz=np.stack([measured[int(i)] for i in triangle])
                normal=np.cross(triangle_xyz[1]-triangle_xyz[0],triangle_xyz[2]-triangle_xyz[0])
                normal/=max(np.linalg.norm(normal),1e-8);normal_list[j]=normal
            tree=cKDTree(xyz)
            for j in np.flatnonzero(seed["source_kind"]==0):
                _,indices=tree.query(xyz[j],k=min(12,n));near=xyz[indices]-xyz[j]
                covariance=near.T@near
                eigen,vectors=np.linalg.eigh(covariance)
                if eigen[0]<.15*max(eigen[1],1e-8):normal_list[j]=vectors[:,0]
            if "surface_normal" in seed:
                observed=seed["surface_normal"]
                good=np.linalg.norm(observed,axis=1)>.5
                normal_list[good]=observed[good]
            for j in np.flatnonzero(np.linalg.norm(normal_list,axis=1)>.5):
                normal=normal_list[j]
                axis=np.array([1.,0.,0.]) if abs(normal[0])<.8 else np.array([0.,1.,0.])
                first_axis=np.cross(axis,normal);first_axis/=np.linalg.norm(first_axis)
                second_axis=np.cross(normal,first_axis)
                initial_quat[j]=Rotation.from_matrix(np.stack((first_axis,second_axis,normal),1)).as_quat()[[3,0,1,2]]
                initial_scale[j,2]=nearest[j]*.10
        scale_chunks.append(initial_scale)
        quat_chunks.append(initial_quat)
        opacity_chunks.append(np.full(n,0. if code in (2,3) else -1.,np.float32))
        part_chunks.append(np.full(n,code,np.int16));tri.append(np.full(n,-1,np.int32));bary.append(np.zeros((n,3),np.float32));offset.append(np.zeros(n,np.float32))
        support.append(seed["support"]);source_kind.append(seed["source_kind"] if label=="room" else np.full(n,{"hair":3,"glasses":4,"cloth":5}[label],np.int16))
        source_id.append(seed["source_id"] if label in ("cloth","room") else np.arange(n,dtype=np.int64))
    xyz=np.concatenate(point_chunks);n=len(xyz)
    parts=np.concatenate(part_chunks);tri_ids=np.concatenate(tri)
    values={"means":xyz,"base_xyz":xyz.copy(),"scales":np.log(np.concatenate(scale_chunks)),
        "quats":np.concatenate(quat_chunks),"opacities":np.concatenate(opacity_chunks),
        "sh":np.concatenate(color_chunks),"part":parts[:,None].astype(np.float32),
        "tri_id":tri_ids[:,None].astype(np.float32),"bary":np.concatenate(bary),
        "normal_offset":np.concatenate(offset)[:,None].astype(np.float32),
        "support":np.concatenate(support)[:,None].astype(np.float32),
        "source_index":np.arange(n,dtype=np.float32)[:,None],
        "family_id":np.arange(n,dtype=np.float32)[:,None],"generation":np.zeros((n,1),np.float32),
        "initial_scales":np.log(np.concatenate(scale_chunks)).astype(np.float32)}
    params=torch.nn.ParameterDict({key:torch.nn.Parameter(torch.as_tensor(value,dtype=torch.float32,device=device)) for key,value in values.items()})
    source_table={"kind":np.concatenate(source_kind),"id":np.concatenate(source_id)}
    counts={name:int((parts==i).sum()) for i,name in enumerate(COMPONENTS)}
    write_json(out/"initialization.json",{"counts":counts,"reference":ref,"excludedPriorHairShell":int((p["role"]==2).sum()),
        "excludedSurfaceNoIndependentSemanticSupport":surface-len(chosen),"sharedScale":s,
        "glassesRepresentation":"independent_three_view_seed_geometry_no_face_surface_fallback",
        "neckRepresentation":"FLAME_observed_neck_skin_plus_separate_measured_garment_tracks"})
    return params,source_table


def posed(params,data,name):
    device=params["means"].device;dtype=params["means"].dtype;s=data["scale"]
    parts=params["part"][:,0].long();bound=params["tri_id"][:,0]>=0
    row=data["local"][name];C=data["worlds"][name];F=row["F"]
    H=np.linalg.inv(C)@np.block([[F[:3,:3],(F[:3,3]*s)[:,None]],[np.zeros((1,3)),np.ones((1,1))]])
    R=torch.as_tensor(H[:3,:3],device=device,dtype=dtype);t=torch.as_tensor(H[:3,3],device=device,dtype=dtype)
    base=params["base_xyz"]
    head=(parts==1)|(parts==2)|(parts==3)|bound
    limits=torch.where((parts==1)|bound,.0035,torch.where(parts==2,.004,torch.where(parts==3,.002,.02*s)))
    delta=limits[:,None]*torch.tanh((params["means"]-base)/limits[:,None])
    local=base+delta
    if bound.any():
        faces=data["geometry"].faces.to(device)
        mesh=torch.as_tensor(row["mesh"],device=device,dtype=dtype)
        ids=params["tri_id"][bound,0].long()
        triangles=mesh[faces[ids]]
        normal=functional.normalize(torch.linalg.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),dim=-1)
        skin=(triangles*params["bary"][bound,:,None]).sum(1)+normal*params["normal_offset"][bound]
        # Small surface-normal and tighter tangent correction. FLAME stays a
        # geometry prior; no unlimited free skin shell can explain room.
        d=delta[bound];nd=(normal*d).sum(1,keepdim=True)*normal
        local=local.clone();local[bound]=skin+nd+.35*(d-nd)
    means=torch.where(head[:,None],local@R.T*s+t,local)
    scales=params["scales"].exp()*torch.where(head,s,1.)[:,None]
    root=Rotation.from_matrix(H[:3,:3]).as_quat()[[3,0,1,2]].astype(np.float32)
    rq=torch.as_tensor(root,device=device)
    quats=torch.where(head[:,None],quaternion_multiply(rq,params["quats"]),params["quats"])
    sh=torch.where(head[:,None,None],torch_sh_rotate(params["sh"],R),params["sh"])
    # A measured garment stays distinct from room. Approximate body motion
    # blends only translation below the neck, without inventing rigid head
    # rotation for shoulders. This limitation remains a release blocker.
    cloth=(parts==4)&~bound
    if cloth.any():
        ref=data["reference"];rC=data["worlds"][ref];rF=data["local"][ref]["F"]
        ref_t=np.linalg.inv(rC)[:3,:3]@(rF[:3,3]*s)+np.linalg.inv(rC)[:3,3]
        displacement=t-torch.as_tensor(ref_t,device=device,dtype=dtype)
        ref_cam=base@torch.as_tensor(rC[:3,:3].T,device=device,dtype=dtype)+torch.as_tensor(rC[:3,3],device=device,dtype=dtype)
        y=data["K"][1,1]*ref_cam[:,1]/ref_cam[:,2].clamp_min(.01)+data["K"][1,2]
        jaw=data["local"][ref]["marks"][152,1]
        weight=(1-(y-jaw)/350).clamp(0,.65)
        means=means+cloth[:,None]*weight[:,None]*displacement
    return means,quats,scales,sh,parts


def boxes(data,name):
    marks=data["local"][name]["marks"];labels=data["labels"][name];h,w=labels["face_core"].shape
    def label_box(mask,margin=20):
        y,x=np.where(mask)
        if not len(x):return None
        return (max(0,int(x.min())-margin),max(0,int(y.min())-margin),min(w,int(x.max())+margin+1),min(h,int(y.max())+margin+1))
    def features(indices,margin):
        xy=marks[indices];return (max(0,int(xy[:,0].min())-margin),max(0,int(xy[:,1].min())-margin),
                               min(w,int(xy[:,0].max())+margin),min(h,int(xy[:,1].max())+margin))
    return {"face":label_box(labels["face_core"]|labels["face_boundary"]),
        "hair":label_box(labels["hair_visible"]),"nose":features([1,2,4,98,327],28),
        "lips":features([61,291,13,14,0,17],30),"eyes_glasses":features([33,133,263,362,168,6],45)}


def make_frame(data,name,box=None,half=False,device="cuda"):
    rgb=data["rgb"][name];labels=data["labels"][name];K=data["K"].copy()
    depth=data["depths"][name]
    if box is not None:
        x0,y0,x1,y1=box;rgb=rgb[y0:y1,x0:x1];depth=depth[y0:y1,x0:x1]
        labels={key:mask[y0:y1,x0:x1] for key,mask in labels.items()};K[0,2]-=x0;K[1,2]-=y0
    if half:
        h,w=rgb.shape[:2];size=(w//2,h//2)
        rgb=cv2.resize(rgb,size,interpolation=cv2.INTER_AREA)
        labels={key:cv2.resize(mask.astype(np.uint8),size,interpolation=cv2.INTER_NEAREST)>0 for key,mask in labels.items()}
        depth=cv2.resize(depth,size,interpolation=cv2.INTER_NEAREST);K[:2]*=.5
    return {"rgb":torch.as_tensor(np.ascontiguousarray(rgb),device=device),
        "masks":{key:torch.as_tensor(np.ascontiguousarray(mask),device=device) for key,mask in labels.items()},
        "depth":torch.as_tensor(np.ascontiguousarray(depth),device=device),
        "K":torch.as_tensor(K,dtype=torch.float32,device=device),"C":torch.as_tensor(data["worlds"][name],dtype=torch.float32,device=device)}


def draw(params,data,name,frame,antialiased,absgrad=False):
    means,quats,scales,sh,parts=posed(params,data,name)
    h,w=frame["rgb"].shape[:2]
    return render_components(means,quats,scales,torch.sigmoid(params["opacities"]),sh,parts,
        frame["C"],frame["K"],w,h,degree=1,absgrad=absgrad,antialiased=antialiased)


def average(value,mask):
    return (value*mask).sum()/mask.sum().clamp_min(1)


def losses(rendered,frame,scale,roi=False):
    masks=frame["masks"];error=(rendered["rgb"]-frame["rgb"]).abs().mean(-1)
    weights=torch.ones_like(error)
    weights=torch.where(masks["unknown_or_occluded"],.15,weights)
    weights+=masks["face_core"]*2.+masks["hair_visible"]*1.5+masks["glasses_visible"]*3.
    rgb=(error*weights).sum()/weights.sum().clamp_min(1)
    core=masks["face_core"];q=rendered["q"];d=frame["depth"]
    valid=core & torch.isfinite(d)
    contamination=rgb*0
    for part in (0,4):
        gap=(d-rendered["component_expected_depth"][:,:,part]) / scale
        in_front=(gap-.012).clamp(0,.04)/.04
        in_front=torch.where(valid,in_front,torch.zeros_like(in_front))
        contamination+=average(q[:,:,part]*in_front,valid)
    # Actual contributions and prior depth jointly gate only confident core.
    # No full-image room opacity suppression and no viewer-time clipping.
    face_coverage=average((.96-q[:,:,1]-q[:,:,3]).clamp_min(0),core)
    room_coverage=average((1-rendered["alpha"]).abs(),masks["room_visible"])
    loss=rgb+.18*contamination+.025*face_coverage+.012*room_coverage
    return loss,{"rgb":float(rgb.detach()),"coreWrongForeground":float(contamination.detach()),
                 "coreCoverageLoss":float(face_coverage.detach()),"roomCoverageLoss":float(room_coverage.detach())}


class ComponentStrategy(DefaultStrategy):
    """AbsGS gradients plus supported, bounded real parent replacement.

    Installed gsplat optimizer update primitive is used; all frozen binding,
    origin and confidence fields follow it. Replacement does not retain the
    wide parent. New child evidence is rechecked before accepting topology.
    """
    def __init__(self,data,max_steps):
        super().__init__(absgrad=True,grow_grad2d=.0008,refine_start_iter=220,
            refine_stop_iter=max_steps-200,refine_every=120,reset_every=max_steps+1,
            refine_scale2d_stop_iter=max_steps,prune_scale2d=.15)
        self.data=data;self.events=[]
        self.policies={0:(.0018,.07,.20,12),1:(.0008,.018,.07,48),
                       2:(.0010,.025,.10,12),3:(.0007,.009,.035,4),4:(.0015,.05,.16,12)}
        self.native_budgets={0:42.,1:9.,2:14.,3:5.,4:32.}

    def _update_state(self,params,state,info,packed=False):
        super()._update_state(params,state,info,packed)
        if state.get("native_radii") is None:
            state["native_radii"]=torch.zeros(len(params["means"]),device=params["means"].device)
            state["residual_sum"]=torch.zeros_like(state["native_radii"])
            state["residual_count"]=torch.zeros_like(state["native_radii"])
        ids=info["gaussian_ids"]
        radius=info["radii"].max(-1).values*info.get("native_pixel_scale",1.)
        state["native_radii"].scatter_reduce_(0,ids,radius.float(),reduce="amax",include_self=True)
        error=info.get("source_residual")
        if error is not None:
            pixels=info["means2d"].detach().round().long();u,v=pixels.unbind(-1)
            h,w=error.shape;valid=(u>=0)&(v>=0)&(u<w)&(v<h)
            seen=ids[valid];values=error[v[valid],u[valid]]
            state["residual_sum"].index_add_(0,seen,values)
            state["residual_count"].index_add_(0,seen,torch.ones_like(values))

    @torch.no_grad()
    def _grow_gs(self,params,optimizers,state,step):
        before=len(params["means"]);parts=params["part"][:,0].long()
        grads=state["grad2d"]/state["count"].clamp_min(1)
        radii=state["radii"];selected=[];by_part={}
        for code,(threshold,budget,prune_budget,quota) in self.policies.items():
            eligible=(parts==code)&(params["support"][:,0]>=3)&(state["count"]>=3)
            native=state["native_radii"]
            residual=state["residual_sum"]/state["residual_count"].clamp_min(1)
            native_budget=self.native_budgets[code]
            candidate=eligible & (native>native_budget) & (residual>.018) & (grads>threshold*.25)
            ids=torch.where(candidate)[0]
            if len(ids)>quota:ids=ids[torch.topk(grads[ids]*(1+radii[ids]/budget),quota).indices]
            selected.extend(ids.tolist());by_part[COMPONENTS[code]]={"replaceParentsProposed":len(ids),"duplicate":0,"prune":0}
        if not selected:return 0,0
        sel=torch.as_tensor(selected,device=params["means"].device)
        bound=params["tri_id"][sel,0]>=0
        first={key:value[sel].detach().clone() for key,value in params.items()}
        second={key:value.clone() for key,value in first.items()}
        # Split along the actual largest covariance axis. Reducing all three
        # axes and halving peak opacity loses integrated coverage. This
        # mixture instead matches parent covariance along one axis and keeps
        # the other two unchanged; the full-scene coverage guard still decides.
        child_ratio=.80
        local_scale=first["scales"].exp().cpu().numpy()
        axis=local_scale.argmax(1)
        matrices=Rotation.from_quat(first["quats"].cpu().numpy()[:,[1,2,3,0]]).as_matrix()
        direction=matrices[np.arange(len(sel)),:,axis]
        displacement=direction*local_scale[np.arange(len(sel)),axis,None]*math.sqrt(1-child_ratio**2)
        ref=self.data["reference"];mesh=torch.as_tensor(self.data["local"][ref]["mesh"],device=sel.device)
        faces=self.data["geometry"].faces.to(sel.device)
        for child,sign in ((first,-1),(second,1)):
            if bound.any():
                ids=child["tri_id"][bound,0].long();triangles=mesh[faces[ids]]
                # A .03 barycentric nudge was much smaller than the coarse
                # footprint. Walk to nearby real triangles, preserving an
                # explicit new binding instead of keeping colocated children.
                target=child["base_xyz"][bound].cpu().numpy().copy()
                target+=displacement[bound.cpu().numpy()]*sign
                tri_ids,bary_np=closest_surface_binding(ref_mesh=self.data["local"][ref]["mesh"],
                    faces=faces.cpu().numpy(),targets=target)
                child["tri_id"][bound,0]=torch.as_tensor(tri_ids,device=sel.device,dtype=child["tri_id"].dtype)
                bary=torch.as_tensor(bary_np,device=sel.device)
                triangles=mesh[faces[torch.as_tensor(tri_ids,device=sel.device).long()]]
                child["bary"][bound]=bary
                normal=functional.normalize(torch.linalg.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),dim=-1)
                new_base=(triangles*bary[:,:,None]).sum(1)+normal*child["normal_offset"][bound]
                prior_delta=child["means"][bound]-child["base_xyz"][bound]
                child["base_xyz"][bound]=new_base;child["means"][bound]=new_base+prior_delta
            if (~bound).any():
                # Bounded local child footprint; room children remain inside
                # their support patch. It is not arbitrary volume noise.
                move=torch.as_tensor(displacement,device=sel.device,dtype=child["means"].dtype)[~bound]*sign
                child["means"][~bound]+=move;child["base_xyz"][~bound]+=move
            shrink=torch.zeros_like(child["scales"])
            shrink[torch.arange(len(sel),device=sel.device),torch.as_tensor(axis,device=sel.device)]=math.log(child_ratio)
            child["scales"]+=shrink
            child["initial_scales"]+=shrink
            alpha=child["opacities"].sigmoid()
            # Projected optical-density mass is approximately conserved for
            # this two-child, single-axis mixture. Not a claim of exact alpha
            # equality: measured before/after coverage is required.
            optical_depth=-torch.log1p(-alpha.clamp_max(.999))
            child["opacities"]=torch.logit((-torch.expm1(-optical_depth/(2*child_ratio))).clamp(.001,.999))
            child["generation"]+=1
        # Revalidate real mask support of each new geometry in training
        # views; descendants cannot simply inherit a "3 views" claim.
        accepted=self.child_support(first)&self.child_support(second)
        sel=sel[accepted]
        if not len(sel):return 0,0
        for child in (first,second):
            for key in child:child[key]=child[key][accepted]
        keep=torch.ones(before,dtype=torch.bool,device=sel.device);keep[sel]=False
        rest=torch.where(keep)[0]
        coverage_frames=self.data.get("coverage_frames",{})
        def coverage():
            result={}
            for name,frame in coverage_frames.items():
                image=draw(params,self.data,name,frame,True)
                core=frame["masks"]["face_core"];room=frame["masks"]["room_visible"]
                result[name]={"hole":float(average((image["q"][:,:,1]+image["q"][:,:,3]<.8).float(),core)),
                              "roomAlpha":float(average(image["alpha"],room))}
            return result
        coverage_before=coverage()
        backup_params=dict(params.items())
        backup_optimizer={key:{name:value.clone() if isinstance(value,torch.Tensor) else value
            for name,value in optimizer.state[params[key]].items()} for key,optimizer in optimizers.items()}
        backup_state={key:value.clone() if isinstance(value,torch.Tensor) else value for key,value in state.items()}
        def parameter(key,value):
            new=torch.cat((value[rest],first[key],second[key]))
            return torch.nn.Parameter(new,requires_grad=value.requires_grad)
        def optimizer(key,value):
            return torch.cat((value[rest],torch.zeros((2*len(sel),*value.shape[1:]),device=value.device,dtype=value.dtype)))
        _update_param_with_optimizer(parameter,optimizer,params,optimizers)
        for key,value in list(state.items()):
            if isinstance(value,torch.Tensor):state[key]=torch.cat((value[rest],value[sel],value[sel]))
        coverage_after=coverage()
        coverage_rejected=any(coverage_after[name]["hole"]>row["hole"]+.005 or
            coverage_after[name]["roomAlpha"]<row["roomAlpha"]-.005 for name,row in coverage_before.items())
        if coverage_rejected:
            for key,value in backup_params.items():
                params[key]=value;optimizers[key].param_groups[0]["params"]=[value]
                optimizers[key].state.clear();optimizers[key].state[value]=backup_optimizer[key]
            state.clear();state.update(backup_state)
            self.events.append({"step":step,"before":before,"after":before,"rejectedCoverage":True,
                "beforeCoverage":coverage_before,"proposedCoverage":coverage_after})
            return 0,0
        for code,name in enumerate(COMPONENTS):by_part[name]["replaceParentsAccepted"]=int((parts[sel]==code).sum())
        self.events.append({"step":step,"before":before,"after":len(params["means"]),"parts":by_part,
            "beforeCoverage":coverage_before,"afterCoverage":coverage_after})
        return 0,len(sel)

    def step_post_backward(self,params,optimizers,state,step,info,packed=False):
        super().step_post_backward(params,optimizers,state,step,info,packed)
        if self.refine_start_iter<step<self.refine_stop_iter and step%self.refine_every==0:
            for key in ("native_radii","residual_sum","residual_count"):state[key].zero_()

    def child_support(self,child):
        support=torch.zeros(len(child["means"]),device=child["means"].device)
        fake=dict(child)
        for name in self.data["train"]:
            means,_,_,_,parts=posed(fake,self.data,name)
            C=torch.as_tensor(self.data["worlds"][name],device=means.device,dtype=means.dtype)
            K=torch.as_tensor(self.data["K"],device=means.device,dtype=means.dtype)
            camera=means@C[:3,:3].T+C[:3,3];uv=camera@K.T
            uv=(uv[:,:2]/uv[:,2:].clamp_min(.01)).round().long();u,v=uv.unbind(1)
            h,w=self.data["rgb"][name].shape[:2];inside=(camera[:,2]>.01)&(u>=0)&(v>=0)&(u<w)&(v<h)
            ix=u.clamp(0,w-1).cpu().numpy();iy=v.clamp(0,h-1).cpu().numpy()
            labels=self.data["labels"][name];good=torch.zeros_like(inside)
            for code,label in ((0,"room_visible"),(1,"face_core"),(2,"hair_visible"),(3,"glasses_visible"),(4,"neck_cloth_visible")):
                evidence=labels[label][iy,ix]
                if code==1:evidence |= labels["face_boundary"][iy,ix]
                good |= (parts==code)&torch.as_tensor(evidence,device=means.device)
            support+=(inside&good).float()
        child["support"]=support[:,None]
        return support>=3

    @torch.no_grad()
    def _prune_gs(self,params,optimizers,state,step):
        # Large but visible coverage is replaced, not blindly deleted.
        # Only negligible-alpha descendants with no meaningful coverage are
        # eligible for pruning; no uncertain hair exterior is carved.
        parts=params["part"][:,0].long()
        thresholds=torch.as_tensor([self.policies[int(part)][2] for part in parts],device=parts.device)
        mask=(params["opacities"].sigmoid()<.002)&(params["generation"][:,0]>0)&(state["radii"]>thresholds)
        n=int(mask.sum())
        if n:
            counts={name:int((mask&(parts==i)).sum()) for i,name in enumerate(COMPONENTS)}
            remove(params,optimizers,state,mask)
            self.events.append({"step":step,"prune":counts,"after":len(params["means"])})
        return n


def train(data,out,steps=1800,antialiased=True):
    if steps<400:raise ValueError("v2_training_steps_below_representative_minimum")
    if (out/"portrait.gaussian.ply").exists():raise FileExistsError("candidate_already_exists")
    start=time.perf_counter();device="cuda";torch.manual_seed(280926)
    torch.cuda.reset_peak_memory_stats();free,total=torch.cuda.mem_get_info()
    params,source_table=initialize(data,out,device)
    faces=data["geometry"].faces.numpy()
    data["depths"]={name:mesh_depth((row["mesh"],faces),row["F"],data["K"],
        data["rgb"][name].shape[1],data["rgb"][name].shape[0])*data["scale"]
        for name,row in data["local"].items() if name in data["worlds"]}
    rates={"means":.00012,"scales":.0015,"quats":.0004,"opacities":.008,"sh":.002}
    optimizers={key:torch.optim.Adam([value],lr=rates.get(key,0.),eps=1e-15) for key,value in params.items()}
    strategy=ComponentStrategy(data,steps);strategy.check_sanity(params,optimizers);state=strategy.initialize_state(scene_scale=data["scale"])
    full={name:make_frame(data,name,half=True) for name in data["worlds"]}
    coverage_names=list(dict.fromkeys([data["reference"],data["train"][0],data["train"][-1]]))
    data["coverage_frames"]={name:full[name] for name in coverage_names}
    initial=audit(params,data,out/"initial-audit",antialiased,full)
    patch_scores={name:{key:1. for key in boxes(data,name) if boxes(data,name)[key] is not None} for name in data["train"]}
    snapshots=[];max_conservation=0.;start_params={key:value.detach().cpu().numpy().copy() for key,value in params.items() if key in rates}
    for step in range(steps):
        name=data["train"][step%len(data["train"])];frame=full[name]
        rendered=draw(params,data,name,frame,antialiased,absgrad=True)
        rendered["projection"]["native_pixel_scale"]=2.
        rendered["projection"]["source_residual"]=(rendered["rgb"]-frame["rgb"]).abs().mean(-1).detach()
        strategy.step_pre_backward(params,optimizers,state,step,rendered["projection"])
        full_loss,components=losses(rendered,frame,data["scale"])
        choices=patch_scores[name];feature=max(choices,key=lambda key:choices[key])
        patch=make_frame(data,name,box=boxes(data,name)[feature])
        roi=draw(params,data,name,patch,antialiased,absgrad=True)
        roi["projection"]["native_pixel_scale"]=1.
        roi["projection"]["source_residual"]=(roi["rgb"]-patch["rgb"]).abs().mean(-1).detach()
        roi["projection"]["means2d"].retain_grad()
        roi_loss,roi_components=losses(roi,patch,data["scale"],roi=True)
        part=params["part"][:,0].long()
        radius=torch.where((part==1)|(params["tri_id"][:,0]>=0),.0035,torch.where(part==2,.004,torch.where(part==3,.002,.02*data["scale"])))
        geometry_penalty=((params["means"]-params["base_xyz"])/radius[:,None]).square().mean()
        sh_penalty=params["sh"][:,1:].square().mean()
        # Prevent one wall/cloth sample becoming a huge fog ellipse to fill
        # unsupported room; positive growth up to 2x its support stays free.
        excess=(params["scales"]-params["initial_scales"]-math.log(2.)).clamp_min(0)
        scale_support_penalty=excess.square().mean()
        loss=full_loss+1.8*roi_loss+.0003*geometry_penalty+.0003*sh_penalty+.01*scale_support_penalty
        if not torch.isfinite(loss):raise RuntimeError(f"v2_nonfinite_loss:{step}")
        loss.backward()
        if step<100:params["means"].grad.zero_();params["quats"].grad.zero_()
        for optimizer in optimizers.values():optimizer.step();optimizer.zero_grad(set_to_none=True)
        # Accumulate both projections' absolute screen gradients before one
        # supported topology update. All five groups were visible in both.
        strategy._update_state(params,state,roi["projection"],packed=True)
        strategy.step_post_backward(params,optimizers,state,step,rendered["projection"],packed=True)
        for key in choices:choices[key]*=1.03
        choices[feature]=max(roi_components["rgb"],.005)
        if step%100==0 or step==steps-1:
            max_conservation=max(max_conservation,component_conservation_error(rendered))
            row={"step":step+1,"frame":name,"patch":feature,"loss":float(loss.detach()),"full":components,"roi":roi_components,"points":len(params["means"])}
            snapshots.append(row);print(json.dumps(row),flush=True)
    final=audit(params,data,out/"final-audit",antialiased,full)
    reference=data["reference"];means,quats,scales,sh,part=posed(params,data,reference)
    # Preserve existing editable-prefix viewer convention. Only supported
    # skin is editable; hair, glasses, neck and room remain outside it.
    order=torch.cat((torch.where(part==1)[0],torch.where(part!=1)[0]))
    pad=torch.zeros((len(means),15,3),device=device);pad[:,:3]=sh[:,1:]
    ply=out/"portrait.gaussian.ply"
    export_splats(means=means[order],scales=scales[order].log(),quats=functional.normalize(quats[order],dim=-1),
        opacities=params["opacities"][order],sh0=sh[order,:1],shN=pad[order],format="ply",save_to=str(ply))
    digest=sha256_file(ply);idx=order.cpu().numpy();origin=params["source_index"][order,0].round().long().cpu().numpy()
    np.savez_compressed(out/"portrait.components.npz",asset_sha256=np.asarray(digest),source_sha256=np.asarray(data["sourceHash"]),
        component=part[order].cpu().numpy(),source_kind=source_table["kind"][origin],source_id=source_table["id"][origin],
        **{key:value[order].detach().cpu().numpy() for key,value in params.items() if key not in rates})
    np.savez_compressed(out/"trained_parameters.npz",**{key:value.detach().cpu().numpy() for key,value in params.items()})
    C=data["worlds"][reference];camera=np.linalg.inv(C)[:3,3]
    head_center=means[part==1].mean(0).detach().cpu().numpy()
    view={"schemaVersion":1,"sourceFrame":reference,"target":head_center.tolist(),"camera":camera.tolist(),
        "up":(-C[:3,:3].T[:,1]).tolist(),"fovDegrees":math.degrees(2*math.atan(1920/(2*data["K"][1,1]))),
        "targetFaceFraction":.5,"editableSplats":int((part==1).sum()),"researchOnly":True,
        "recordedEnvironmentSplats":int((part!=1).sum()),
        "sourceSha256":data["sourceHash"],"assetSha256":digest}
    write_json(out/"portrait.view.json",view)
    torch.cuda.synchronize()
    report={"status":"isolated_research_not_publishable","engine":"gsplat-1.5.3","sourceSha256":data["sourceHash"],
        "plySha256":digest,"referenceFrame":reference,"steps":steps,"train":data["train"],"development":data["development"],
        "excludedWorldMissingLocalViews":[name for name in data["local"] if name not in data["worlds"]],
        "antialiased":antialiased,"absgradRasterAndStrategy":True,"allComponentsEveryForward":True,
        "initial":initial,"final":final,"curve":snapshots,"topologyEvents":strategy.events,
        "pointCount":len(means),"counts":{name:int((part==i).sum()) for i,name in enumerate(COMPONENTS)},
        "seconds":time.perf_counter()-start,"cudaAllocatedPeakMiB":torch.cuda.max_memory_allocated()/1024**2,
        "cudaReservedPeakMiB":torch.cuda.max_memory_reserved()/1024**2,"cudaFreeStartMiB":free/1024**2,"cudaTotalMiB":total/1024**2,
        "conservationMaximum":max_conservation,"independentFinalAudit":False,
        "parameterUpdateMeanAbsoluteByOrigin":{key:float(np.abs(params[key].detach().cpu().numpy()-start_params[key][params["source_index"][:,0].round().long().cpu().numpy()]).mean()) for key in rates},
        "limitations":["Temporary static cameras and one inferred global scale are not independent world calibration",
            "Glasses candidate seeds can be sparse; no fabricated lens/temple/nose-pad geometry",
            "Neck/collar motion is simplified; complete scene continuity still requires visual audit",
            "No candidate sent to tablet; local and browser evidence do not establish Harmony device quality"]}
    write_json(out/"research-audit.json",report)
    print(json.dumps({key:report[key] for key in ("status","plySha256","pointCount","counts","seconds","cudaAllocatedPeakMiB","cudaReservedPeakMiB")}),flush=True)
    return report


def closest_surface_binding(ref_mesh,faces,targets):
    """Nearest projection on local neighbouring measured-prior triangles.

    Snapping only changes geometry ownership; it does not invent texture or
    claim FLAME is measured detail. Exact barycentric bindings are retained.
    """
    triangles=ref_mesh[faces];centers=triangles.mean(1)
    nearby=np.asarray(cKDTree(centers).query(targets,k=min(24,len(triangles)))[1]).reshape(len(targets),-1)
    chosen=[];bary_all=[]
    for target,indices in zip(targets,nearby):
        T=triangles[indices];a=T[:,0];v0=T[:,1]-a;v1=T[:,2]-a;v2=target-a
        d00=(v0*v0).sum(1);d01=(v0*v1).sum(1);d11=(v1*v1).sum(1)
        d20=(v2*v0).sum(1);d21=(v2*v1).sum(1);den=d00*d11-d01*d01
        u=(d11*d20-d01*d21)/np.maximum(den,1e-12)
        v=(d00*d21-d01*d20)/np.maximum(den,1e-12)
        bary=np.stack((1-u-v,u,v),1).clip(.001,1.)
        bary/=bary.sum(1,keepdims=True)
        point=(T*bary[:,:,None]).sum(1);index=np.argmin(np.linalg.norm(point-target,axis=1))
        chosen.append(indices[index]);bary_all.append(bary[index])
    return np.asarray(chosen,np.int32),np.asarray(bary_all,np.float32)


def audit(params,data,out,antialiased,full):
    out.mkdir(parents=True,exist_ok=True);results={}
    with torch.no_grad():
        for name in data["development"]+ [data["reference"]]:
            frame=full[name];rendered=draw(params,data,name,frame,antialiased)
            core=frame["masks"]["face_core"];room=frame["masks"]["room_visible"]
            error=(rendered["rgb"]-frame["rgb"]).abs().mean(-1);q=rendered["q"]
            row={"faceCoreRgbL1":float(average(error,core)),"roomRgbL1":float(average(error,room)),
                "roomCoverage":float(average(rendered["alpha"],room)),
                "faceHoleRatio":float(average((q[:,:,1]+q[:,:,3]<.80).float(),core)),
                "coreContribution":{component:float(average(q[:,:,i],core)) for i,component in enumerate(COMPONENTS)},
                "conservation":component_conservation_error(rendered),"features":{}}
            row["visiblePartCoverageProxy"]={
                "hairMaskPixels":int(frame["masks"]["hair_visible"].sum()),
                "hairContributionMean":float(average(q[:,:,2],frame["masks"]["hair_visible"])),
                "hairMaskRecallAboveQ03":float(average((q[:,:,2]>.3).float(),frame["masks"]["hair_visible"])),
                "glassesLineCandidatePixels":int(frame["masks"]["glasses_visible"].sum()),
                "glassesContributionMean":float(average(q[:,:,3],frame["masks"]["glasses_visible"])),
                "glassesLineRecallAboveQ01":float(average((q[:,:,3]>.1).float(),frame["masks"]["glasses_visible"])),
                "hairInReliableRoom":float(average(q[:,:,2],room)),
                "glassesInReliableRoom":float(average(q[:,:,3],room)),
                "meaning":"Parsing/edge observation proxies, not independently annotated hair/glasses geometry truth"}
            depth_valid=core & torch.isfinite(frame["depth"])
            row["coreUnexpectedForegroundProxy"]={}
            for component_index,mask_name in ((0,"room_visible"),(4,"neck_cloth_visible"),
                                             (2,"hair_visible"),(3,"glasses_visible")):
                in_front=(rendered["component_expected_depth"][:,:,component_index]<frame["depth"]-.012*data["scale"])
                test=depth_valid if component_index in (0,4) else depth_valid & ~frame["masks"][mask_name]
                row["coreUnexpectedForegroundProxy"][COMPONENTS[component_index]]=float(average(
                    q[:,:,component_index]*in_front,test))
            for feature,box in boxes(data,name).items():
                if box is None:continue
                native=make_frame(data,name,box=box);local=draw(params,data,name,native,antialiased)
                truth=native["rgb"].cpu().numpy();actual=local["rgb"].cpu().numpy()
                t=cv2.cvtColor(truth,cv2.COLOR_RGB2GRAY);a=cv2.cvtColor(actual,cv2.COLOR_RGB2GRAY)
                edge=np.abs(np.diff(t,axis=1)-np.diff(a,axis=1)).mean()
                row["features"][feature]={"fixedPatchRgbL1IncludingMissing":float(np.abs(truth-actual).mean()),
                    "signedHorizontalEdgeL1":float(edge),"sourceGradientMean":float(np.abs(np.diff(t,axis=1)).mean()),
                    "renderGradientMean":float(np.abs(np.diff(a,axis=1)).mean())}
                pair=np.concatenate((truth,actual),1)
                cv2.imwrite(str(out/(name+"-"+feature+".jpg")),cv2.cvtColor((pair*255).round().clip(0,255).astype(np.uint8),cv2.COLOR_RGB2BGR))
            ids=rendered["projection"]["gaussian_ids"];radii=rendered["projection"]["radii"].max(-1).values*2
            point_parts=params["part"][ids,0].long()
            row["nativePixelFootprintRadius"]={component:[float(x) for x in torch.quantile(radii[point_parts==i].float(),torch.tensor([.5,.9,.99],device=radii.device))] if (point_parts==i).any() else [] for i,component in enumerate(COMPONENTS)}
            actual=rendered["rgb"].cpu().numpy();truth=frame["rgb"].cpu().numpy()
            cv2.imwrite(str(out/(name+"-full.jpg")),cv2.cvtColor((np.concatenate((truth,actual),1)*255).round().clip(0,255).astype(np.uint8),cv2.COLOR_RGB2BGR))
            pollution=q[:,:,[0,4]].sum(-1).cpu().numpy()*core.cpu().numpy()
            heat=cv2.applyColorMap((pollution.clip(0,1)*255).astype(np.uint8),cv2.COLORMAP_INFERNO)
            cv2.imwrite(str(out/(name+"-face-core-pollution.png")),heat)
            results[name]=row
    write_json(out/"audit.json",results)
    return results
