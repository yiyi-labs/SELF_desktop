"""Reproducible isolated research. Deliberately has no job/store/HDC dependency."""
from __future__ import annotations
import argparse,json,math,os,shutil,subprocess,threading,time
from pathlib import Path
import numpy as np
import torch
from gsplat import export_splats
from reconstruction_components_v3 import load_v3_prepared as load_prepared
from reconstruction_shared_v2 import initialize
from reconstruction_portrait_pipeline import initialize_scene,make_frame
from reconstruction_portrait_model import GaussianState
from reconstruction_components_v3 import (VERSION,FreeComponent,sha,save_json,pick,exact_state_hash,export_identity)
from reconstruction_portrait_local_v3 import train_attachments
from reconstruction_world_static_v3 import train_static
from reconstruction_compose_v3 import compose_state,audit_front_conflicts,require_joint
from audit_reconstruction_v3 import audit_observations,evaluate,compare


def block_from_old(params,sources,part,frame,offset):
    select=params['part'][:,0].long()==part
    if part==4:select &= params['tri_id'][:,0]<0  # no FLAME cloth fallback
    if not select.any():return None
    state=GaussianState(params['means'][select].detach(),params['quats'][select].detach(),
        params['scales'][select].detach().exp(),params['opacities'][select].detach().sigmoid(),
        params['sh'][select].detach(),params['part'][select,0].long())
    return FreeComponent(state,sources['id'][select.cpu().numpy()],params['support'][select,0].detach(),frame,offset)


def export_research(face,attachments,body,room,data,out):
    reference=data['reference'];frame=make_frame(data,reference)
    with torch.no_grad():state=compose_state(face,attachments,body,room,data,frame)
    n=len(state.means);surface=face.surface_count;pad=torch.zeros((n,15,3),device='cuda');pad[:,:3]=state.sh[:,1:]
    ply=out/'portrait.gaussian.ply'
    export_splats(means=state.means,scales=state.scales.log(),quats=state.quats,
        opacities=torch.logit(state.opacity.clamp(1e-6,1-1e-6)),sh0=state.sh[:,:1],shN=pad,format='ply',save_to=str(ply))
    sources=[face.source_index[:surface].cpu().numpy()];support=[face.confidence[:surface].cpu().numpy()]
    kinds=[np.full(surface,2,np.int16)]
    for block in [attachments[k] for k in ('hair','accessory') if k in attachments]+([body] if body is not None else [])+[room]:
        sources.append(block.source_ids.cpu().numpy());support.append(block.support.cpu().numpy())
        kinds.append(np.full(len(block.parts),{0:0,2:3,3:4,4:5}[int(block.parts[0])],np.int16))
    triangle=np.full(n,-1,np.int64);triangle[:surface]=face.triangle_ids.cpu().numpy()
    bary=np.zeros((n,3),np.float32);bary[:surface]=face.embedding.detach().cpu().numpy()
    offset=np.zeros(n,np.float32);offset[:surface]=face.normal_offset.detach().cpu().numpy()
    origin=np.full(n,-1,np.int64);origin[:surface]=face.origin_index[:surface].cpu().numpy()
    arrays={'point_id':np.arange(n,dtype=np.int64),'component':state.parts.cpu().numpy().astype(np.int16),
        'source_id':np.concatenate(sources).astype(np.int64),'source_kind':np.concatenate(kinds),
        'support_or_confidence':np.concatenate(support),'triangle_id':triangle,'barycentric':bary,
        'normal_offset':offset,'origin_index':origin,'generation':np.zeros(n,np.int16)}
    manifest=export_identity(out/'portrait.components.npz',ply,arrays,source_hash=data['sourceHash'],reference=reference,editable_count=surface)
    C=data['worlds'][reference];view={'schemaVersion':1,'sourceFrame':reference,
        'target':state.means[:surface].mean(0).detach().cpu().tolist(),'camera':np.linalg.inv(C)[:3,3].tolist(),
        'up':(-C[:3,:3].T[:,1]).tolist(),'fovDegrees':math.degrees(2*math.atan(data['rgb'][reference].shape[0]/(2*data['K'][1,1]))),
        'targetFaceFraction':.5,'editableSplats':surface,'recordedEnvironmentSplats':len(room.parts),
        'pointCount':n,'researchOnly':True,'sourceSha256':data['sourceHash'],'assetSha256':sha(ply)}
    save_json(out/'portrait.view.json',view);return manifest


def run(args):
    if getattr(args, 'portrait_priority_config', None) is not None:
        from reconstruction_portrait_priority import run_priority
        return run_priority(args)
    out=args.output.resolve()
    private=Path(__file__).resolve().parent/'.sources'
    if not out.is_relative_to(private):raise ValueError('output_must_be_in_this_isolated_private_sources')
    if out.exists():raise FileExistsError('new_run_id_required')
    out.mkdir(parents=True)
    if not torch.cuda.is_available():
        save_json(out/'failure.json',{'status':'GPU_unavailable_not_run'});raise RuntimeError('GPU_unavailable')
    if args.attachment_steps<1 or args.static_steps<1:raise ValueError('positive_actual_optimizer_steps_required')
    code=out/'algorithm-source';code.mkdir()
    for source in Path(__file__).parent.glob('*v3.py'):shutil.copyfile(source,code/source.name)
    start=time.perf_counter();torch.manual_seed(280929);torch.cuda.reset_peak_memory_stats()
    samples=[];stop=threading.Event()
    def telemetry():
        while not stop.is_set():
            try:
                row=subprocess.check_output(['/usr/lib/wsl/lib/nvidia-smi','--query-gpu=memory.used,utilization.gpu,temperature.gpu','--format=csv,noheader,nounits'],text=True,timeout=3).strip()
                samples.append({'seconds':time.perf_counter()-start,'device':row})
            except Exception as e:samples.append({'error':str(e)})
            stop.wait(.5)
    thread=threading.Thread(target=telemetry,daemon=True);thread.start()
    try:
        prepared=args.prepared.resolve();data=load_prepared(prepared)
        manifest=audit_observations(data,prepared,out)
        shutil.copyfile(prepared/'cloth_supported_seeds.npz',out/'cloth_supported_seeds.npz')
        # Reuse proven import and surface/SH mathematics, not its stage scheduler.
        scene=initialize_scene(data,out)
        face=scene.portrait;face.constraint_mode='soft'
        for p in face.parameters():p.requires_grad_(False)
        params,sources=initialize(data,out,'cuda')
        attachments={}
        for key,part,bound in [('hair',2,.006),('accessory',3,.002)]:
            b=block_from_old(params,sources,part,'head-local',bound)
            if b is not None:attachments[key]=b
        room=block_from_old(params,sources,0,'world-static',.01*data['scale'])
        body=block_from_old(params,sources,4,'world-reference-unaccepted-body-motion',.003*data['scale'])
        if room is None:raise ValueError('no_static_surface_seeds')
        if body is not None:
            for p in body.parameters():p.requires_grad_(False)
        del params,scene
        config={'engine':VERSION,'sourceSha256':data['sourceHash'],'prepared':str(prepared),'appearanceHash':data['appearanceHash'],
            'modelHash':data['modelHash'],'sourceFiles':{p.name:sha(p) for p in Path(__file__).parent.glob('*v3.py')},
            'steps':{'attachments':args.attachment_steps,'static':args.static_steps},
            'researchWorldCameras':args.research_cameras,'productionEntryUnchanged':True,'noPublisher':True,
            'parts':{'faceSkin':face.surface_count,'hair':len(attachments['hair'].parts) if 'hair'in attachments else 0,
                'accessory':len(attachments['accessory'].parts) if 'accessory'in attachments else 0,
                'neckShoulderCloth':len(body.parts) if body is not None else 0,'staticScene':len(room.parts)},
            'removedLegacyShellForThisTrial':int((face.role==2).sum()),'faceGeometryFrozen':True,
            'absenceOfAccessorySeeds':'unknown/not-recovered, never inferred as no glasses',
            'splitPrune':'not invoked; existing transactional regressions retained'}
        save_json(out/'config.json',config)
        initial=evaluate(face,attachments,body,room,data,out/'initial')
        local=train_attachments(face,attachments,data,out,args.attachment_steps)
        after_local=evaluate(face,attachments,body,room,data,out/'after-local')
        portrait_before=exact_state_hash(face);attach_before={k:exact_state_hash(v) for k,v in attachments.items()}
        for v in attachments.values():
            for p in v.parameters():p.requires_grad_(False)
        static=train_static(room,data,out,args.static_steps,research_cameras=args.research_cameras)
        if exact_state_hash(face)!=portrait_before or any(exact_state_hash(v)!=attach_before[k] for k,v in attachments.items()):raise RuntimeError('static_stage_modified_portrait')
        final=evaluate(face,attachments,body,room,data,out/'final')
        front=audit_front_conflicts(face,attachments,room,data,out,body=body)
        try:require_joint({},data['sourceHash'])
        except ValueError as e:joint={'executed':False,'reason':str(e)}
        else:raise RuntimeError('joint_must_not_accept_missing_quality_evidence')
        asset=export_research(face,attachments,body,room,data,out)
        torch.cuda.synchronize()
        result={'status':'research_diagnostic_not_quality_candidate','sourceSha256':data['sourceHash'],
            'asset':asset,'training':{'B':local,'C':static},'jointTraining':joint,'front':front,
            'perView':compare(initial,final),'seconds':time.perf_counter()-start,
            'torchAllocatedPeakMiB':torch.cuda.max_memory_allocated()/1024**2,'torchReservedPeakMiB':torch.cuda.max_memory_reserved()/1024**2,
            'faceAndAttachmentsExactlyFrozenDuringStatic':True,'qualityApproved':False,'published':False,
            'limitations':['E1 cameras not fully accepted','hair/accessory seed coverage inadequate','body motion missing',
                'local face retains baseline defects','development set is not blind','Harmony not tested']}
        save_json(out/'report.json',result)
        print(json.dumps({k:result[k] for k in ('status','seconds','torchAllocatedPeakMiB')}),flush=True)
    except Exception as e:
        save_json(out/'failure.json',{'exception':repr(e),'seconds':time.perf_counter()-start});raise
    finally:
        stop.set();thread.join(timeout=5);save_json(out/'gpu-telemetry.json',samples)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--attachment-steps',type=int,default=360);p.add_argument('--static-steps',type=int,default=360)
    p.add_argument('--research-cameras',action='store_true')
    p.add_argument('--portrait-priority-config',type=Path,help='Explicit isolated finite research configuration; no publishing')
    run(p.parse_args())
