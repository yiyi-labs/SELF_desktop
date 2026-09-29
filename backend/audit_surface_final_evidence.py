"""Final bounded receipts: component full restore, extra fixed views, one PLY orbit."""
import argparse,json,subprocess,time
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_evidence_stage import load_stage
from reconstruction_components_v3 import FreeComponent,save_json,sha
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import make_frame,draw
from reconstruction_detail_controlled import evaluate_face
from reconstruction_research_state import FrameSampler,restore_checkpoint,save_checkpoint
from audit_portrait_priority_handoff import restore_tensors,camera_looking_at
from reconstruction_joint_visibility import load_recorded_ply
from run_haze_shared_surface import export_state

def run(root,manifest):
    root=Path(root).resolve();out=root/'final-evidence';data,plan,m,contract=load_stage(manifest,out)
    # Extend, do not replace, original 8/6 groups. These two regression frames
    # were explicitly required even if no reliable track survives.
    extra={'train':plan['train'],'development':['frame_0028.png','frame_0042.png'],'audit':[]}
    evaluate_face(m,data,extra,out/'extra-R0');candidate=torch.load(root/'F-geometry-evaluation/candidate-final.pt',map_location='cuda',weights_only=False);restore_tensors(m,candidate['model']);evaluate_face(m,data,extra,out/'extra-F')
    f=m.adjusted_frame(make_frame(data,data['reference'],crop=False));head=m.head_state(f);export_state(head,out/'fixed-F-local.ply');r=draw(head,f['F'],f['K'],1080,1920);np.savez_compressed(out/'F-local-gsplat.npz',rgb=r['rgb'].cpu().numpy(),alpha=r['alpha'].cpu().numpy());inv=torch.linalg.inv(f['F']).cpu().numpy();save_json(out/'display.json',{'assets':[{'label':'F-local','ply':str(out/'fixed-F-local.ply'),'hash':sha(out/'fixed-F-local.ply'),'count':len(head.means)}],'K':data['K'].tolist(),'C':f['F'].cpu().tolist(),'width':1080,'height':1920,'camera':inv[:3,3].tolist(),'target':(inv[:3,3]+inv[:3,2]).tolist(),'up':(-inv[:3,1]).tolist(),'near':.01,'far':1e10,'sourceHash':data['sourceHash'],'reference':data['reference']})
    # Rehydrate local garment to verify every Adam binding and sampler restore.
    folder=root/'C-training';initial=torch.load(folder/'initial.pt',map_location='cuda',weights_only=False);v=initial['model'];gs=GaussianState(v['base'],v['quats'],v['initial_scales'],v['opacity'].sigmoid(),v['sh'],v['parts']);component=FreeComponent(gs,v['source_ids'],v['support'],'upper-body-reference',v['max_offset'])
    for key in ('stable_uid','parent_uid','surface_triangle','surface_bary'):component.register_buffer(key,v[key].clone())
    ops={key:torch.optim.Adam([getattr(component,key)],lr=.001) for key in initial['optimizers']};sampler=FrameSampler(initial['samplers']['views']['names'],1)
    final=torch.load(folder/'candidate-final.pt',map_location='cuda',weights_only=False);restore_tensors(component,final['model']);restore_checkpoint(folder/'initial.pt',component,ops,{'views':sampler},contract=initial['contract'],device='cuda')
    equal=all(torch.equal(t,initial['model'][key]) for key,t in component.state_dict().items());assert equal and sampler.state_dict()==initial['samplers']['views']
    save_checkpoint(folder/'restored-complete.pt',component,ops,{'views':sampler},stage='cloth_restore_audit',step=0,contract=initial['contract'],strategy=initial['strategy'],extra=initial['extra']);restore={'modelExact':equal,'samplerExact':True,'AdamBindingsAndInitialStateRestored':True,'earlierRestoredFile':'model-only restoration; not an exact optimizer resume; retained as failed diagnostic'}
    # Same exported B asset, never a different model for each camera angle.
    spec=json.loads((root/'B-replacement/display.json').read_text());asset=Path(spec['assets'][0]['ply']);z=load_recorded_ply(asset,9053);s=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],torch.zeros(len(z['means']),dtype=torch.long,device='cuda'));K=torch.tensor(spec['K'],device='cuda');C=np.array(spec['C']);inv=np.linalg.inv(C);eye=inv[:3,3];target=s.means[:9053].mean(0).cpu().numpy();up=-inv[:3,1];right=inv[:3,0];cams=[];tic=time.perf_counter();proc=subprocess.Popen(['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','24','-i','-','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(out/'fixed-B-orbit.mp4')],stdin=subprocess.PIPE)
    with torch.no_grad():
        for i in range(48):
            phase=i/47*2*np.pi;yaw=18*np.sin(phase);pitch=6*np.sin(2*phase);R=cv2.Rodrigues(up*yaw*np.pi/180)[0]@cv2.Rodrigues(right*pitch*np.pi/180)[0];cam=camera_looking_at(target+R@(eye-target),target,up);image=draw(s,torch.tensor(cam,device='cuda',dtype=torch.float32),K,1080,1920,unit_scale=data['scale'])['rgb'];rgb=(image.clamp(0,1).cpu().numpy()*255).round().astype(np.uint8);proc.stdin.write(rgb.tobytes());cams.append({'C':cam.tolist(),'yawControl':float(yaw),'pitchControl':float(pitch)})
            if i%12==0:cv2.imwrite(str(out/f'orbit-{i:02}.png'),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
    proc.stdin.close();assert proc.wait()==0
    save_json(out/'result.json',{'garmentRestore':restore,'orbitAsset':str(asset),'orbitHash':sha(asset),'cameras':cams,'K':spec['K'],'reference':spec['reference'],'sourceHash':data['sourceHash'],'orbitSeconds':time.perf_counter()-tic,'engine':'gsplat1.5.3','scope':'rejected frozen T2; not HarmonyOS; no T3/T4','published':False})
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',required=True);a.add_argument('--manifest',required=True);s=a.parse_args();run(s.root,s.manifest)
