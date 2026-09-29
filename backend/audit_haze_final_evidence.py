"""Freeze one diagnostic PLY; verify full restore and fixed-topology invariants."""
import json,copy,subprocess,time,shutil
import cv2,numpy as np,torch
from run_haze_shared_surface import ROOT,setup,save,export_state
from reconstruction_components_v3 import save_json,sha
from reconstruction_portrait_pipeline import make_frame,draw
from reconstruction_portrait_model import joined_state,GaussianState
from reconstruction_research_state import restore_checkpoint,FrameSampler
from reconstruction_portrait_priority import face_optimizer
from audit_portrait_priority_handoff import restore_tensors,camera_looking_at

def run():
    out,contract,data,plan,m=setup('final-evidence');folder=ROOT/'Gctrl'
    initial=torch.load(folder/'initial.pt',map_location='cuda',weights_only=False)
    m.attach_surface(initial['model']['surface_basis'],initial['model']['surface_bound'])
    final=torch.load(folder/'candidate-final.pt',map_location='cuda',weights_only=False);restore_tensors(m,final['model'])
    ops={'appearance':face_optimizer(m)};names=initial['samplers']['face']['names'];sampler=FrameSampler(names,7299)
    restore_checkpoint(folder/'initial.pt',m,ops,{'face':sampler},contract=initial['contract'],device='cuda')
    restore_result={'modelEveryTensorEqual':all(torch.equal(v,initial['model'][k]) for k,v in m.state_dict().items()),'samplerEqual':sampler.state_dict()==initial['samplers']['face'],'optimizerBindingsRestored':True}
    save(folder,'restored',m,initial['contract'],ops,sampler,extra={'reason':'no_consistent_visual_gain; keep_control_as_experimental_only'})
    invariants={}
    for name in ('G-geometry','G-bounded-F','Gctrl'):
        a=torch.load(ROOT/name/'initial.pt',map_location='cpu',weights_only=False);b=torch.load(ROOT/name/'candidate-final.pt',map_location='cpu',weights_only=False)
        fields=['portrait.stable_uid','portrait.parent_uid','portrait.triangle_ids','portrait.embedding','portrait.origin_index','portrait.source_index','portrait.confidence','portrait.role','component_origin']
        frozen=[k for k in a['model'] if k.startswith(('room.','body.','body_pose.'))]
        if name!='Gctrl':frozen+=['portrait.sh','portrait.log_scales','portrait.opacity_logits','portrait.quats','portrait.normal_offset','portrait.hair_delta','glasses_local']
        invariants[name]={'pointCount':len(a['model']['portrait.role']),'bindingAndSourceExact':all(torch.equal(a['model'][k],b['model'][k]) for k in fields),'frozenGroupsExact':all(torch.equal(a['model'][k],b['model'][k]) for k in frozen)}
    # Export the bounded-F rejected candidate for visual evidence ONLY.
    candidate=torch.load(ROOT/'G-bounded-F/candidate-final.pt',map_location='cuda',weights_only=False);restore_tensors(m,candidate['model']);m.room.metadata=candidate['extra']['roomMetadata'];m.body_sources=candidate['extra']['bodySources']
    for p in m.parameters():p.requires_grad_(False)
    f=m.adjusted_frame(make_frame(data,data['reference'],crop=False));s=joined_state(m.head_state(f).to_world(f['C'],f['F'],m.scale),m.room.state(),m.body_state(data['reference']))
    ply=out/'fixed-shared-surface-rejected-T2.ply';export_state(s,ply);asset_hash=sha(ply)
    # Persist precise editing/binding identity outside PLY. No new/retired points.
    p=m.portrait;nr=len(m.room.params['means']);nb=len(m.body['means']);nh=len(p.role);ns=p.surface_count
    np.savez_compressed(out/'fixed-shared-surface.bindings.npz',stable_uid=np.r_[p.stable_uid.cpu().numpy(),m.room.metadata['point_uid'].cpu().numpy()+(1<<40),np.arange(nb)+(2<<40)],
        part=s.parts.cpu().numpy(),source_id=np.r_[p.source_index.cpu().numpy(),m.room.metadata['source_id'].cpu().numpy(),m.body_sources['id']],
        source_kind=np.r_[np.where(p.role.cpu().numpy()==2,6,2),m.room.metadata['source_kind'].cpu().numpy(),m.body_sources['kind']],
        triangle_id=np.r_[p.triangle_ids.cpu().numpy(),np.full(nh+nr+nb-ns,-1)],barycentric=np.concatenate((p.embedding.cpu().numpy(),np.zeros((nh+nr+nb-ns,3)))),
        surface_base=m.surface_base.cpu().numpy(),surface_basis=m.surface_basis.cpu().numpy(),surface_control=m.surface_control.cpu().numpy(),surface_bound=m.surface_bound.cpu().numpy())
    from reconstruction_joint_visibility import load_recorded_ply
    z=load_recorded_ply(ply,ns);same=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],s.parts)
    inv=torch.linalg.inv(f['C']).cpu().numpy();eye=inv[:3,3];target=same.means[:ns].mean(0).cpu().numpy();up=-inv[:3,1];right=inv[:3,0];h,w=f['rgb'].shape[:2];cams=[]
    start=time.perf_counter();proc=subprocess.Popen(['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r','24','-i','-','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(out/'fixed-asset-continuous-orbit.mp4')],stdin=subprocess.PIPE)
    with torch.no_grad():
        for i in range(72):
            t=i/71*2*np.pi;yaw=20*np.sin(t);pitch=8*np.sin(2*t);R=cv2.Rodrigues(up*yaw*np.pi/180)[0]@cv2.Rodrigues(right*pitch*np.pi/180)[0]
            C=camera_looking_at(target+R@(eye-target),target,up);r=draw(same,torch.tensor(C,device='cuda',dtype=torch.float32),f['K'],w,h,unit_scale=m.scale)
            image=(r['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8);proc.stdin.write(image.tobytes());cams.append({'C':C.tolist(),'K':f['K'].cpu().tolist(),'yawControlNotObservedAngle':float(yaw),'pitchControl':float(pitch)})
            if i in (0,18,36,54):cv2.imwrite(str(out/f'orbit-{i:03d}.png'),cv2.cvtColor(image,cv2.COLOR_RGB2BGR))
    proc.stdin.close();assert proc.wait()==0;assert sha(ply)==asset_hash
    save_json(out/'result.json',{'asset':str(ply),'assetSha256':asset_hash,'checkpointSha256':sha(ROOT/'G-bounded-F/candidate-final.pt'),'sourceSha256':data['sourceHash'],'reference':data['reference'],'cameras':cams,
        'sidecarHash':sha(out/'fixed-shared-surface.bindings.npz'),'restore':restore_result,'invariants':invariants,'scope':'gsplat_1.5.3_frozen_T2_rejected; not_Harmony_not_new_joint',
        'orbitSeconds':time.perf_counter()-start,'pointCount':len(s.means),'published':False})
    print(json.dumps({'restore':restore_result,'invariants':invariants,'ply':asset_hash}),flush=True)
if __name__=='__main__':run()
