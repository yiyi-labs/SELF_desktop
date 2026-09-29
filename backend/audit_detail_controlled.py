"""Freeze, compare, export one research-only PLY. No optimizer or publication."""
from pathlib import Path
import argparse,json,shutil,subprocess
import cv2
import numpy as np
import torch
from gsplat import export_splats
from gsplat.rendering import rasterization
from reconstruction_components_v3 import load_v3_prepared,save_json,sha,export_identity
from reconstruction_portrait_pipeline import initialize_scene,make_frame,draw,metrics,masked_mean
from reconstruction_portrait_priority import ResearchModel
from reconstruction_detail_controlled import DetailModel,evaluate_face,evaluate_room,pixel_structure
from reconstruction_portrait_model import GaussianState,joined_state,evaluate_sh1
from reconstruction_joint_visibility import load_recorded_ply
from reconstruction_shared_v2 import boxes
from audit_portrait_priority_handoff import restore_tensors,camera_looking_at


def png(path,images):
    im=np.concatenate([v.clip(0,1) for v in images],1)
    cv2.imwrite(str(path),cv2.cvtColor((im*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))


def summary(rows):
    out={}
    for use in sorted({r['use'] for r in rows.values()}):
        sel=[r for r in rows.values() if r['use']==use]
        out[use]={key:float(np.mean([r[key]['fixedRgbL1'] for r in sel])) for key in ('face','hair','glasses')}
        out[use]['faceEdge']=float(np.mean([r['face']['edgeError'] for r in sel]));out[use]['faceStructure']=float(np.mean([r['face']['structure'] for r in sel]))
        out[use]['local']={k:float(np.mean([r['local'][k] for r in sel if k in r['local']])) for k in ('nose','lips','eyes_glasses')}
    return out


@torch.no_grad()
def run(args):
    out=args.output.resolve();base=Path(__file__).resolve().parent/'.sources'
    if out.exists() or not out.is_relative_to(base):raise ValueError('new_output_required')
    out.mkdir(parents=True);data=load_v3_prepared(args.prepared);run=args.run;old=args.baseline
    plan=json.loads((run/'observations.json').read_text());contract=json.loads((run/'contract.json').read_text())
    for n in plan['audit']+plan.get('new_audit',[]):data['local'][n]['role']='audit'
    init=out/'load';init.mkdir();shutil.copyfile(args.prepared/'cloth_supported_seeds.npz',init/'cloth_supported_seeds.npz')
    scene=initialize_scene(data,init);model=DetailModel(scene,data,plan['train']);del scene
    model.enable_components(data,plan['train'])
    ck=torch.load(run/'portrait_refine_v1/final.pt',map_location='cuda',weights_only=False)
    if ck['contract']!=contract:raise ValueError('candidate_checkpoint_contract')
    restore_tensors(model,ck['model']);model.body_sources=ck['extra']['bodySources']
    rows=json.loads((run/'portrait_refine_v1/final-images/metrics.json').read_text());results={'candidate':summary(rows)}
    init2=out/'baseline-load';init2.mkdir();shutil.copyfile(args.prepared/'cloth_supported_seeds.npz',init2/'cloth_supported_seeds.npz')
    scene=initialize_scene(data,init2);baseline=ResearchModel(scene,data,plan['train']);del scene
    for label,path in [('original',old/'face-initial.pt'),('previousFace',old/'face-final.pt')]:
        cc=torch.load(path,map_location='cuda',weights_only=False);restore_tensors(baseline,cc['model']);values=evaluate_face(baseline,data,plan,out/(label+'-images'));results[label]=summary(values)
    comparisons=out/'portrait-comparisons';comparisons.mkdir()
    for name,row in rows.items():
        x0,y0,x1,y1=row['crop'];src=data['rgb'][name][y0:y1,x0:x1]
        imgs=[src,np.load(out/'original-images'/(name+'.npz'))['rgb'],np.load(out/'previousFace-images'/(name+'.npz'))['rgb'],np.load(run/'portrait_refine_v1/final-images'/(name+'.npz'))['rgb']]
        png(comparisons/(name+'-four-panel.png'),imgs)
        for key,box in boxes(data,name).items():
            if box is None:continue
            a,b,c,d=box;a=max(0,a-x0);b=max(0,b-y0);c=min(x1-x0,c-x0);d=min(y1-y0,d-y0)
            if a<c and b<d:png(comparisons/(name+'-'+key+'.png'),[im[b:d,a:c] for im in imgs])
    # Room comparison is at ONE native resolution, mask and K, including
    # previous pre-joint and post-joint states. No subtraction across metrics.
    roomrows={}
    for label,path in [('previousRoom',old/'room-final.pt'),('previousJoint',old/'T4-final.pt')]:
        cc=torch.load(path,map_location='cuda',weights_only=False);restore_tensors(baseline,cc['model'])
        roomrows[label]=evaluate_room(baseline,data,out/(label+'-images'))
    roomck=torch.load(run/'room_fullimg_v1/final.pt',map_location='cuda',weights_only=False)
    for name,value in roomck['model'].items():
        if name.startswith('room.'):
            parent,_,leaf=name.rpartition('.');owner=model.get_submodule(parent)
            if getattr(owner,leaf).shape!=value.shape:setattr(owner,leaf,torch.nn.Parameter(value.clone(),requires_grad=False))
            else:getattr(owner,leaf).copy_(value)
    model.room.metadata=roomck['extra']['roomMetadata']
    roomrows['candidate']=json.loads((run/'room_fullimg_v1/final-images/metrics.json').read_text())
    roomdir=out/'room-comparisons';roomdir.mkdir()
    for name in data['development']:
        src=data['rgb'][name];imgs=[src,np.load(run/'room_fullimg_v1/initial-images'/(name+'.npz'))['rgb'],np.load(out/'previousRoom-images'/(name+'.npz'))['rgb'],np.load(run/'room_fullimg_v1/final-images'/(name+'.npz'))['rgb']]
        # Generic static tile rule, evaluated after training only. Prefer valid,
        # low-texture non-flat-static windows, never used to select training.
        m=data['labels'][name]['room_visible']&~data['labels'][name]['unknown_or_occluded'];h,w=m.shape;candidates=[]
        gray=cv2.cvtColor(src,cv2.COLOR_RGB2GRAY);grad=cv2.Sobel(gray,cv2.CV_32F,1,0)**2+cv2.Sobel(gray,cv2.CV_32F,0,1)**2
        size=192
        for y in range(0,h-size,96):
            for x in range(0,w-size,96):
                region=m[y:y+size,x:x+size]
                if region.mean()>.97:
                    texture=float(grad[y:y+size,x:x+size].mean());spread=float(gray[y:y+size,x:x+size].std())
                    if spread>.015:candidates.append((texture,x,y))
        selected=sorted(candidates)[:1]
        if selected:
            _,x,y=selected[0];png(roomdir/(name+'-low-texture.png'),[im[y:y+size,x:x+size] for im in imgs]);roomrows['candidate'][name]['diagnosticCrop']=[x,y,x+size,y+size]
        png(roomdir/(name+'-four-panel.png'),imgs)
    results['room']=roomrows
    # Fixed-state resolution/AA diagnostic. Same asset, camera, mask. AA is
    # a diagnostic only; it is not silently enabled in the production viewer.
    handoff={};frozen={};componentdir=out/'components';componentdir.mkdir()
    for name in data['development']:
        f=make_frame(data,name);stages={k:model.render(f,k) for k in ('T0','T1','T2')}
        handoff[name]={k:metrics(r,f) for k,r in stages.items()}
        handoff[name]['T01Mean']=float((stages['T0']['rgb']-stages['T1']['rgb']).abs().mean())
        png(out/(name+'-handoff.png'),[f['rgb'].cpu().numpy()]+[r['rgb'].cpu().numpy() for r in stages.values()])
        if name==data['development'][0]:
            s=model.head_state(model.adjusted_frame(f));center=torch.linalg.inv(model.adjusted_frame(f)['F'])[:3,3]
            color=evaluate_sh1(s.sh,s.means-center);groups=torch.nn.functional.one_hot(s.parts.long(),5)
            features=(groups[:,:,None]*color[:,None,:]).reshape(len(color),15)
            rr,_,_=rasterization(s.means,s.quats,s.scales,s.opacity,features,model.adjusted_frame(f)['F'][None],f['K'][None],f['rgb'].shape[1],f['rgb'].shape[0],packed=True,sh_degree=None,rasterize_mode='classic',near_plane=.01)
            png(componentdir/(name+'.png'),[f['rgb'].cpu().numpy()]+[rr[0,...,i*3:(i+1)*3].cpu().numpy() for i in (1,2,3,4)])
        full=make_frame(data,name,crop=False);small=make_frame(data,name,crop=False,half=True)
        state=joined_state(model.head_state(model.adjusted_frame(full)).to_world(full['C'],model.adjusted_frame(full)['F'],data['scale']),model.room.state(),model.body_state(name))
        frozen[name]={}
        for aa in (False,True):
            a=draw(state,full['C'],full['K'],full['rgb'].shape[1],full['rgb'].shape[0],unit_scale=data['scale'],antialiased=aa)
            b=draw(state,small['C'],small['K'],small['rgb'].shape[1],small['rgb'].shape[0],unit_scale=data['scale'],antialiased=aa)
            down=torch.nn.functional.avg_pool2d(a['q'].permute(2,0,1)[None],2,2)[0].permute(1,2,0)
            mask=small['masks']['face_core']|small['masks']['glasses_visible']|small['masks']['face_boundary']
            frozen[name]['AA' if aa else 'classic']={'nativeDownQRoom':float(masked_mean(down[...,0],mask)),
                'halfQRoom':float(masked_mean(b['q'][...,0],mask)),'faceQRoomAbsDiff':float(masked_mean((down[...,0]-b['q'][...,0]).abs(),mask))}
    results['handoff']=handoff;results['resolution']=frozen
    results['jointExecuted']=False;results['jointDecision']='portrait review gate pending; no T3/T4 optimizer invoked'
    save_json(out/'evaluation.json',results)
    # One full frozen asset for continuous orbit, explicitly diagnostic T2.
    f=make_frame(data,data['reference'],crop=False);head=model.head_state(model.adjusted_frame(f)).to_world(f['C'],model.adjusted_frame(f)['F'],data['scale'])
    s=joined_state(head,model.room.state(),model.body_state(data['reference']));p=model.portrait;n=len(s.means);ns=p.surface_count;nh=len(p.role);nr=len(model.room.params['means']);nb=n-nh-nr
    pad=torch.zeros(n,15,3,device='cuda');pad[:,:3]=s.sh[:,1:];ply=out/'fixed-diagnostic-T2.ply'
    export_splats(means=s.means,scales=s.scales.log(),quats=s.quats,opacities=torch.logit(s.opacity.clamp(1e-6,1-1e-6)),sh0=s.sh[:,:1],shN=pad,format='ply',save_to=str(ply))
    meta=model.room.metadata;legacy=torch.cat((torch.where(p.role==2,2,1),torch.zeros(nr,device='cuda',dtype=torch.long),torch.full((nb,),4,device='cuda',dtype=torch.long)))
    arrays={'point_id':np.arange(n,dtype=np.int64),'component':legacy.cpu().numpy().astype(np.int16),
        'fine_component':np.concatenate((model.component_origin[p.origin_index].cpu().numpy(),np.full(nr,5),np.full(nb,4))).astype(np.int16),
        'stable_uid':np.concatenate((p.stable_uid.cpu().numpy(),meta['point_uid'].cpu().numpy()+(1<<40),np.arange(nb)+(2<<40))),
        'parent_uid':np.concatenate((p.parent_uid.cpu().numpy(),np.where(meta['parent_uid'].cpu().numpy()<0,-1,meta['parent_uid'].cpu().numpy()+(1<<40)),np.full(nb,-1))),
        'source_id':np.concatenate((p.source_index.cpu().numpy(),meta['source_id'].cpu().numpy(),model.body_sources['id'])),
        'source_kind':np.concatenate((np.where(p.role.cpu().numpy()==2,6,2),meta['source_kind'].cpu().numpy(),model.body_sources['kind'])),
        'triangle_id':np.concatenate((p.triangle_ids.cpu().numpy(),np.full(n-ns,-1))),
        'barycentric':np.concatenate((p.embedding.cpu().numpy(),np.zeros((n-ns,3),np.float32))),
        'normal_offset':np.concatenate((p.normal_offset.cpu().numpy(),np.zeros(n-ns))),
        'confidence':np.concatenate((p.confidence.cpu().numpy(),meta['support'].cpu().numpy(),np.load(args.prepared/'cloth_supported_seeds.npz')['support'])),
        'origin_index':np.concatenate((p.origin_index.cpu().numpy(),np.full(n-nh,-1))),
        'generation':np.concatenate((p.generation.cpu().numpy(),meta['generation'].cpu().numpy(),np.zeros(nb,dtype=np.int64)))}
    asset=export_identity(out/'fixed-diagnostic-T2.components.npz',ply,arrays,source_hash=data['sourceHash'],reference=data['reference'],editable_count=ns)
    loaded=load_recorded_ply(ply,ns);same=GaussianState(loaded['means'],loaded['quats'],loaded['scales'],loaded['opacity'],loaded['sh'][:,:4],s.parts)
    a=draw(s,f['C'],f['K'],f['rgb'].shape[1],f['rgb'].shape[0],unit_scale=data['scale']);b=draw(same,f['C'],f['K'],f['rgb'].shape[1],f['rgb'].shape[0],unit_scale=data['scale'])
    diff={k:{'mean':float((a[k]-b[k]).abs().mean()),'max':float((a[k]-b[k]).abs().max())} for k in ('rgb','alpha','q')}
    h,w=f['rgb'].shape[:2];position=torch.linalg.inv(f['C'])[:3,3].cpu().numpy();C=f['C'].cpu().numpy();up=-C[:3,:3].T[:,1];right=C[:3,:3].T[:,0];target=same.means[:ns].mean(0).cpu().numpy()
    ffmpeg=shutil.which('ffmpeg')
    if not ffmpeg:raise RuntimeError('no_encoder')
    proc=subprocess.Popen([ffmpeg,'-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r','24','-i','-','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(out/'fixed-ply-orbit.mp4')],stdin=subprocess.PIPE)
    cams=[]
    for i in range(72):
        phase=i/71*2*np.pi; yaw=20*np.sin(phase);pitch=8*np.sin(phase*2)
        R=cv2.Rodrigues(up*yaw*np.pi/180)[0]@cv2.Rodrigues(right*pitch*np.pi/180)[0]
        cam=camera_looking_at(target+R@(position-target),target,up);r=draw(same,torch.as_tensor(cam,device='cuda',dtype=torch.float32),f['K'],w,h,unit_scale=data['scale'])
        im=(r['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8);proc.stdin.write(im.tobytes());cams.append({'C':cam.tolist(),'K':f['K'].cpu().tolist(),'yawControlNotObservedAngle':yaw,'pitch':pitch})
        if i in (0,18,36,54):cv2.imwrite(str(out/f'orbit-{i:03d}.png'),cv2.cvtColor(im,cv2.COLOR_RGB2BGR))
    proc.stdin.close()
    if proc.wait()!=0:raise RuntimeError('encode_failed')
    if sha(ply)!=asset['assetSha256']:raise ValueError('asset_mutated')
    save_json(out/'asset.json',{'asset':asset,'roundtrip':diff,'run':run.name,'sourceSha256':data['sourceHash'],
        'reference':data['reference'],'portraitCheckpointSha256':sha(run/'portrait_refine_v1/final.pt'),'roomCheckpointSha256':sha(run/'room_fullimg_v1/final.pt'),
        'cameras':cams,'stage':'T2 diagnostic; not joint-trained final result','engine':'gsplat1.5.3, not PlayCanvas/Harmony','published':False})
    print(json.dumps({k:v for k,v in results.items() if k in ('original','previousFace','candidate')}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('baseline',type=Path);p.add_argument('run',type=Path);p.add_argument('output',type=Path);run(p.parse_args())
