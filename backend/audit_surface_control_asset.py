"""Small analytic finite surfaces for renderer contract, not portrait quality."""
from pathlib import Path
import argparse,json,numpy as np,torch
from scipy.spatial.transform import Rotation
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import draw
from reconstruction_components_v3 import save_json,sha
from run_haze_shared_surface import export_state

def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);K=np.array([[1189.,0,540.],[0,1189.,960.],[0,0,1.]],np.float32);C=np.eye(4,dtype=np.float32);xyz=[];scales=[];color=[];quat=[]
    for y in np.linspace(-.55,.55,55):
        for x in np.linspace(-.65,.65,65):
            z=3.+max(x,0)*.4;xyz.append([x,y,z]);scales.append([.014,.014,.0008]);color.append([.25+.25*(x>.0),.4,.55]);q=Rotation.from_rotvec([0,-np.arctan(.4) if x>0 else 0,0]).as_quat();quat.append(q[[3,0,1,2]])
    for y in np.linspace(-.4,.4,200):xyz.append([-.05,y,2.7]);scales.append([.001,.004,.0005]);color.append([.8,.15,.12]);quat.append([1,0,0,0])
    assets=[]
    for label,wide in [('normal',False),('wide',True)]:
        X=xyz+([[.6,0,2.5]] if wide else []);S=scales+([[4,2,.03]] if wide else []);rgb=color+([[.5,.5,.5]] if wide else []);Q=quat+([[1,0,0,0]] if wide else []);n=len(X)
        sh=torch.zeros(n,4,3,device='cuda');sh[:,0]=(torch.tensor(rgb,device='cuda')-.5)/.28209479177387814
        state=GaussianState(torch.tensor(X,device='cuda',dtype=torch.float32),torch.tensor(Q,device='cuda',dtype=torch.float32),torch.tensor(S,device='cuda',dtype=torch.float32),torch.full((n,),.8,device='cuda'),sh,torch.zeros(n,dtype=torch.long,device='cuda'))
        export_state(state,out/(label+'.ply'));r=draw(state,torch.tensor(C,device='cuda'),torch.tensor(K,device='cuda'),1080,1920);np.savez_compressed(out/(label+'-gsplat.npz'),rgb=r['rgb'].cpu().numpy(),alpha=r['alpha'].cpu().numpy());assets.append({'label':label,'ply':str(out/(label+'.ply')),'hash':sha(out/(label+'.ply')),'count':n})
    save_json(out/'display.json',{'assets':assets,'K':K.tolist(),'C':C.tolist(),'width':1080,'height':1920,'camera':[0,0,0],'target':[0,0,1],'up':[0,-1,0],'near':.01,'far':1e10,'reference':'analytic_contract_only','sourceHash':'synthetic_not_a_person'})
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--out',required=True);s=a.parse_args();run(Path(s.out).resolve())
