"""Head-local measured attachments, separated from the retained face optimizer."""
from __future__ import annotations
import time
import numpy as np
import torch
from reconstruction_components_v3 import pick,exact_state_hash,save_json
from reconstruction_portrait_model import joined_state
from reconstruction_portrait_pipeline import draw,make_frame,masked_mean

def head_state(face,attachments,mesh):
    # Every real attachment participates in one visibility pass, even when frozen.
    states=[pick(face.local_state(mesh),slice(0,face.surface_count))]
    states += [attachments[k].state() for k in ('hair','accessory') if k in attachments]
    return joined_state(*states)

def draw_head(face,attachments,frame):
    h,w=frame['rgb'].shape[:2]
    return draw(head_state(face,attachments,frame['mesh']),frame['F'],frame['K'],w,h)

def train_attachments(face,attachments,data,out,steps):
    """Structural representation trial, not a rerun of FLAME version selection.

    Face is bit-identical throughout: this diagnoses how much supported hair/
    accessory seeds can explain without sacrificing the face to fill coverage.
    """
    before=exact_state_hash(face)
    for p in face.parameters():p.requires_grad_(False)
    if not attachments:raise ValueError('no_measured_attachment_seeds')
    initial={k:exact_state_hash(v) for k,v in attachments.items()}
    opts={k:torch.optim.Adam([{'params':[p],'lr':dict(offset=.005,log_scales=.001,quats=.0003,opacity=.004,sh=.003)[n],'name':n}
          for n,p in block.named_parameters()]) for k,block in attachments.items()}
    names=[n for n,r in data['local'].items() if r['role']=='train']
    curve=[];start=time.perf_counter()
    for step in range(steps):
        frame=make_frame(data,names[step%len(names)])
        for k,block in attachments.items():
            for n,p in block.named_parameters():p.requires_grad_(n!='offset' or step>=40)
            opts[k].zero_grad(set_to_none=True)
        render=draw_head(face,attachments,frame);m=frame['masks']
        error=(render['rgb']-frame['rgb']).abs().mean(-1)
        loss=masked_mean(error,m['face_core'])
        values={}
        for key,code,label in [('hair',2,'hair_visible'),('accessory',3,'glasses_visible')]:
            if key not in attachments:continue
            positive=m[label]
            # A missing label is not empty. Only confident room/face core away
            # from the ambiguous boundary is safe negative supervision.
            safe=(m['room_visible']|m['face_core']) & ~m['unknown_or_occluded'] & ~m['face_boundary'] & ~m['glasses_visible'] & ~m['hair_visible']
            q=render['q'][...,code]
            photometric=masked_mean(error,positive)
            missing=masked_mean((1-q).square(),positive)
            conflict=masked_mean(q.square(),safe)
            loss=loss+photometric+.06*missing+.08*conflict+attachments[key].regularizer()
            values[key]={'rgb':float(photometric.detach()),'missing':float(missing.detach()),'conflict':float(conflict.detach())}
        if not torch.isfinite(loss):raise RuntimeError('nonfinite_local_component_loss')
        loss.backward()
        for k,block in attachments.items():
            torch.nn.utils.clip_grad_norm_(block.parameters(),5.);opts[k].step()
        if step%60==0 or step==steps-1:
            curve.append({'step':step+1,'frame':frame['name'],'loss':float(loss.detach()),'parts':values})
            print('v3-local',curve[-1],flush=True)
    torch.cuda.synchronize()
    unchanged=before==exact_state_hash(face)
    if not unchanged:raise RuntimeError('face_modified_during_attachment_trial')
    result={'steps':steps,'seconds':time.perf_counter()-start,'curve':curve,'faceExactlyFrozen':unchanged,
        'changedComponents':{k:initial[k]!=exact_state_hash(v) for k,v in attachments.items()},
        'status':'measured_seed_capacity_trial_not_complete_portrait','allHeadPartsEveryForward':True}
    torch.save({'components':{k:v.state_dict() for k,v in attachments.items()},'optimizers':{k:v.state_dict() for k,v in opts.items()}},out/'B-attachments.pt')
    save_json(out/'B-training.json',result);return result
