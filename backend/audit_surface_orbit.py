"""Orbit a single hashed research PLY through gsplat; no model per view."""
import argparse,json,time,subprocess
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_joint_visibility import load_recorded_ply
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import draw
from reconstruction_components_v3 import sha,save_json
from audit_portrait_priority_handoff import camera_looking_at

def run(display,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);spec=json.loads(Path(display).read_text());asset=Path(spec['assets'][0]['ply']);h=sha(asset);assert h==spec['assets'][0]['hash'];z=load_recorded_ply(asset,9053);state=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],torch.zeros(len(z['means']),device='cuda',dtype=torch.long));K=torch.tensor(spec['K'],device='cuda',dtype=torch.float32);C=np.array(spec['C']);inv=np.linalg.inv(C);eye=inv[:3,3];target=state.means[:9053].mean(0).cpu().numpy();up=-inv[:3,1];right=inv[:3,0];cams=[];start=time.perf_counter();proc=subprocess.Popen(['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1080x1920','-r','24','-i','-','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(out/'fixed-asset-orbit.mp4')],stdin=subprocess.PIPE)
    with torch.no_grad():
        for i in range(48):
            a=i/47*2*np.pi;yaw=18*np.sin(a);pitch=6*np.sin(2*a);rot=cv2.Rodrigues(up*yaw*np.pi/180)[0]@cv2.Rodrigues(right*pitch*np.pi/180)[0];cam=camera_looking_at(target+rot@(eye-target),target,up);r=draw(state,torch.tensor(cam,device='cuda',dtype=torch.float32),K,1080,1920,unit_scale=spec['near']/.01);rgb=(r['rgb'].cpu().numpy().clip(0,1)*255).round().astype(np.uint8);proc.stdin.write(rgb.tobytes());cams.append({'C':cam.tolist(),'yawControl':float(yaw),'pitchControl':float(pitch)})
    proc.stdin.close();assert proc.wait()==0 and sha(asset)==h;save_json(out/'contract.json',{'assetHash':h,'sourceHash':spec['sourceHash'],'reference':spec['reference'],'cameras':cams,'K':spec['K'],'seconds':time.perf_counter()-start,'renderer':'gsplat1.5.3','notHarmonyOS':True,'notViewerFPS':True,'publication':False})
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--display',required=True);a.add_argument('--out',required=True);s=a.parse_args();run(s.display,s.out)
