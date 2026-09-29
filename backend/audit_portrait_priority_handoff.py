"""Read-only checkpoint evaluation/export to a NEW isolated audit directory.

No optimization. One frozen reference PLY is reloaded for all orbit frames.
Uses the existing PLY parser/colour convention, not a new engine or format.
"""
from pathlib import Path
import argparse,json,shutil,math,subprocess
import cv2
import numpy as np
import torch
from gsplat import export_splats
from reconstruction_components_v3 import load_v3_prepared,save_json,sha,export_identity
from reconstruction_portrait_pipeline import initialize_scene,make_frame,draw
from reconstruction_portrait_priority import ResearchModel
from reconstruction_portrait_model import joined_state,GaussianState
from reconstruction_joint_visibility import load_recorded_ply
from reconstruction_shared_v2 import boxes


def restore_tensors(model,saved):
    current=model.state_dict()
    if current.keys()!=saved.keys():raise ValueError('full_checkpoint_fields_mismatch')
    params=dict(model.named_parameters())
    for name,value in saved.items():
        if current[name].dtype!=value.dtype:raise ValueError('checkpoint_dtype_changed:'+name)
        if current[name].shape!=value.shape:
            parent,_,leaf=name.rpartition('.');owner=model.get_submodule(parent)
            setattr(owner,leaf,torch.nn.Parameter(torch.empty_like(value)) if name in params else torch.empty_like(value))
    model.load_state_dict(saved,strict=True)


def compare_images(data,run,out):
    stages=['face-initial-images','face-final-images','face-after-joint-images']
    meta=json.loads((run/stages[0]/'metrics.json').read_text());rows={}
    for name,row in meta.items():
        x0,y0,x1,y1=row['crop'];target=data['rgb'][name][y0:y1,x0:x1]
        images=[np.load(run/stage/(name+'.npz'))['rgb'] for stage in stages]
        labels=data['labels'][name]
        mask=(labels['face_core']|labels['face_boundary']|labels['glasses_visible'])[y0:y1,x0:x1]
        local={}
        for key,box in boxes(data,name).items():
            if box is None:continue
            a,b,c,d=box;a=max(a-x0,0);b=max(b-y0,0);c=min(c-x0,x1-x0);d=min(d-y0,y1-y0)
            if a>=c or b>=d:continue
            m=labels['hair_visible'][y0+b:y0+d,x0+a:x0+c] if key=='hair' else mask[b:d,a:c]
            if not m.any():continue
            local[key]={stage:float(np.abs(image[b:d,a:c]-target[b:d,a:c]).mean(-1)[m].mean()) for stage,image in zip(stages,images)}
            if key in ('nose','lips','eyes_glasses','hair'):
                panels=[target[b:d,a:c]]+[v[b:d,a:c].clip(0,1) for v in images]
                cv2.imwrite(str(out/(name+'-'+key+'.png')),cv2.cvtColor((np.concatenate(panels,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        sheet=np.concatenate([target]+[v.clip(0,1) for v in images],1)
        cv2.imwrite(str(out/(name+'-four-panel.png')),cv2.cvtColor((sheet*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        rows[name]={'use':row['use'],'crop':row['crop'],'local':local}
    save_json(out/'local-comparison.json',{'order':['source','recoverable_old_baseline','face_900_plus_recovery','after_joint'],
        'resizedOrSharpened':False,'rows':rows})
    return rows


def camera_looking_at(position,target,up):
    front=target-position;front/=np.linalg.norm(front)
    right=np.cross(front,up);right/=np.linalg.norm(right);down=np.cross(front,right)
    C=np.eye(4);C[:3,:3]=np.stack((right,down,front));C[:3,3]=-C[:3,:3]@position
    return C


@torch.no_grad()
def run(args):
    out=args.output.resolve();base=Path(__file__).resolve().parent/'.sources'
    if not out.is_relative_to(base) or out.exists():raise ValueError('new_private_audit_directory_required')
    out.mkdir(parents=True);run=args.run.resolve();config=json.loads((run/'config.json').read_text());plan=json.loads((run/'observations.json').read_text())
    data=load_v3_prepared(args.prepared)
    for n in plan['audit']:data['local'][n]['role']='audit'
    shutil.copyfile(args.prepared/'cloth_supported_seeds.npz',out/'cloth_supported_seeds.npz')
    scene=initialize_scene(data,out);model=ResearchModel(scene,data,plan['train']);del scene
    checkpoint=torch.load(run/'T4-final.pt',map_location='cuda',weights_only=False)
    if checkpoint['contract']!=json.loads((run/'contract.json').read_text()):raise ValueError('checkpoint_contract_changed')
    for path,expected in checkpoint['contract']['observationFiles'].items():
        if sha(args.prepared/path)!=expected:raise ValueError('observation_file_changed:'+path)
    restore_tensors(model,checkpoint['model']);model.room.metadata=checkpoint['extra']['roomMetadata']
    model.body_sources=checkpoint['extra']['bodySources']
    comparisons=out/'local-comparison';comparisons.mkdir();compare_images(data,run,comparisons)
    frame=make_frame(data,data['reference'],crop=False,half=True);adjusted=model.adjusted_frame(frame)
    head=model.portrait.local_state(frame['mesh']).to_world(frame['C'],adjusted['F'],data['scale'])
    state=joined_state(head,model.room.state(),model.body_state(data['reference']))
    n=len(state.means);p=model.portrait;ns=p.surface_count;nh=len(p.role);nr=len(model.room.params['means']);nb=n-nh-nr
    pad=torch.zeros(n,15,3,device='cuda');pad[:,:3]=state.sh[:,1:]
    ply=out/'fixed-reference.gaussian.ply'
    export_splats(means=state.means,scales=state.scales.log(),quats=state.quats,
        opacities=torch.logit(state.opacity.clamp(1e-6,1-1e-6)),sh0=state.sh[:,:1],shN=pad,format='ply',save_to=str(ply))
    meta=model.room.metadata
    cloth=dict(np.load(args.prepared/'cloth_supported_seeds.npz'))
    if not np.array_equal(cloth['source_id'],model.body_sources['id']):raise ValueError('body_support_source_identity_mismatch')
    body_support=cloth['support']
    arrays={'point_id':np.arange(n,dtype=np.int64),'component':state.parts.cpu().numpy().astype(np.int16),
        'stable_uid':np.concatenate((p.stable_uid.cpu().numpy(),meta['point_uid'].cpu().numpy()+(1<<40),np.arange(nb)+(2<<40))),
        'parent_uid':np.concatenate((p.parent_uid.cpu().numpy(),np.where(meta['parent_uid'].cpu().numpy()<0,-1,meta['parent_uid'].cpu().numpy()+(1<<40)),np.full(nb,-1))),
        'source_id':np.concatenate((p.source_index.cpu().numpy(),meta['source_id'].cpu().numpy(),model.body_sources['id'])).astype(np.int64),
        'source_kind':np.concatenate((np.where(p.role.cpu().numpy()==2,6,2),meta['source_kind'].cpu().numpy(),model.body_sources['kind'])).astype(np.int16),
        'support_or_confidence':np.concatenate((p.confidence.cpu().numpy(),meta['support'].cpu().numpy(),body_support)),
        'triangle_id':np.concatenate((p.triangle_ids.cpu().numpy(),np.full(n-ns,-1,dtype=np.int64))),
        'barycentric':np.concatenate((p.embedding.cpu().numpy(),np.zeros((n-ns,3),np.float32))),
        'normal_offset':np.concatenate((p.normal_offset.cpu().numpy(),np.zeros(n-ns,np.float32))),
        'origin_index':np.concatenate((p.origin_index.cpu().numpy(),np.full(n-nh,-1))),
        'generation':np.concatenate((p.generation.cpu().numpy(),meta['generation'].cpu().numpy(),np.zeros(nb,dtype=np.int64)))}
    # Recover garment confidence by exact source identity from frozen seeds,
    # not nearest-neighbour coordinates or invented confidence.
    asset=export_identity(out/'fixed-reference.components.npz',ply,arrays,source_hash=data['sourceHash'],reference=data['reference'],editable_count=ns)
    loaded=load_recorded_ply(ply,ns);reloaded=GaussianState(loaded['means'],loaded['quats'],loaded['scales'],loaded['opacity'],loaded['sh'][:,:4],state.parts)
    h,w=frame['rgb'].shape[:2];a=draw(state,frame['C'],frame['K'],w,h,unit_scale=data['scale']);b=draw(reloaded,frame['C'],frame['K'],w,h,unit_scale=data['scale'])
    roundtrip={k:{'mean':float((a[k]-b[k]).abs().mean()),'max':float((a[k]-b[k]).abs().max())} for k in ('rgb','alpha','q')}
    cv2.imwrite(str(out/'fixed-reference.png'),cv2.cvtColor((b['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    target=reloaded.means[:ns].mean(0).cpu().numpy();C=frame['C'].cpu().numpy();position=np.linalg.inv(C)[:3,3];up=-C[:3,:3].T[:,1];right=C[:3,:3].T[:,0]
    cameras=[];frames=96;video=out/'same-ply-continuous-orbit.mp4'
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise RuntimeError('ffmpeg_missing_no_video_claim')
    proc=subprocess.Popen([ffmpeg,'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r','24','-i','-',
        '-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],stdin=subprocess.PIPE)
    for index in range(frames):
        phase=index/(frames-1)*2*np.pi;yaw=20*np.sin(phase);pitch=8*np.sin(2*phase)
        R=cv2.Rodrigues(up*(yaw*np.pi/180))[0]@cv2.Rodrigues(right*(pitch*np.pi/180))[0]
        cam=camera_looking_at(target+R@(position-target),target,up)
        camera=torch.as_tensor(cam,device='cuda',dtype=torch.float32)
        rendered=draw(reloaded,camera,frame['K'],w,h,unit_scale=data['scale'])
        pixels=(rendered['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8)
        proc.stdin.write(pixels.tobytes());cameras.append({'frame':index,'C':cam.tolist(),'K':frame['K'].cpu().tolist(),
            'orbitYawNotObservationAngle':yaw,'pitch':pitch})
        if index in (0,24,48,72):cv2.imwrite(str(out/f'orbit-{index:03d}.png'),cv2.cvtColor(pixels,cv2.COLOR_RGB2BGR))
    proc.stdin.close()
    if proc.wait()!=0:raise RuntimeError('video_encode_failed')
    if sha(ply)!=asset['assetSha256']:raise ValueError('asset_changed_during_orbit')
    save_json(out/'handoff.json',{'sourceSha256':data['sourceHash'],'run':run.name,'checkpointSha256':sha(run/'T4-final.pt'),
        'reference':data['reference'],'asset':asset,'roundtrip':roundtrip,'orbitFrames':frames,'cameras':cameras,
        'wholeDeviceTrainingNotPerformed':True,'renderEngine':'gsplat 1.5.3; not PlayCanvas or Harmony',
        'qualityApproved':False,'published':False,'bodySupportUnknownCount':0,'bodySupportRecoveredByExactSourceID':nb})
    print(json.dumps({'assetSha256':asset['assetSha256'],'points':n,'roundtrip':roundtrip,'qualityApproved':False}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('run',type=Path);p.add_argument('output',type=Path);run(p.parse_args())
