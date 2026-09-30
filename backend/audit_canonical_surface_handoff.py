"""Actual covariance export equality and immutable-asset orbit; gsplat only.
These are graphical contracts for rejected research assets, not publication.
"""
import argparse,json,shutil,time
from pathlib import Path
import numpy as np,torch,cv2
from reconstruction_evidence_stage import load_stage
from reconstruction_canonical_surface import CanonicalSurfaceModel
from reconstruction_portrait_pipeline import make_frame,draw
from reconstruction_portrait_model import GaussianState
from reconstruction_joint_visibility import load_recorded_ply
from reconstruction_components_v3 import sha,save_json

@torch.no_grad()
def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    shutil.copyfile(__file__,out/Path(__file__).name)
    data,plan,m,contract=load_stage(root/'spec.json',out/'loading',model_class=CanonicalSurfaceModel)
    result=json.loads((root/'result.json').read_text());rows={}
    for label in result['branches']:
        checkpoint=root/label/'final.pt';ck=torch.load(checkpoint,map_location='cuda',weights_only=False)
        m.load_state_dict(ck['model'],strict=True);m._transport_cache.clear()
        frame=m.adjusted_frame(make_frame(data,data['reference'],crop=False));height,width=frame['rgb'].shape[:2];asset=root/label/'fixed-research.ply'
        if sha(asset)!=result['assets'][label]['hash']:raise ValueError("asset_mutated")
        z=load_recorded_ply(asset,m.portrait.surface_count)
        state=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],
            torch.cat((m.head_state(frame).parts,m.room.state().parts,m.body_state(frame['name']).parts)))
        native=m.render(frame,'T2');back=draw(state,frame['C'],frame['K'],width,height,unit_scale=m.scale)
        errors={k:dict(maxAbs=float((native[k]-back[k]).abs().max()),meanAbs=float((native[k]-back[k]).abs().mean())) for k in ['rgb','alpha','q']}
        # Alpha inversion and float32 PLY covariance factorization can slightly affect sort/ties.
        rows[label]=dict(assetHash=sha(asset),checkpointHash=sha(checkpoint),sameCamera=frame['name'],
            nativeFullCanvas=[width,height],errors=errors,
            numericalPassed=all(v['meanAbs']<1e-5 and v['maxAbs']<.003 for v in errors.values()),
            productionViewerTested=False,HarmonyOSTested=False)
        for name in ('native','ply-reload'):
            rr=native if name=='native' else back
            cv2.imwrite(str(out/(label+'-'+name+'.png')),cv2.cvtColor((rr['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        if label=='canonical-appearance':
            frames=out/'fixed-orbit';frames.mkdir();C=frame['C'].cpu().numpy();inv=np.linalg.inv(C)
            centers=m.head_state(frame).to_world(frame['C'],frame['F'],m.scale).means
            target=centers[m.head_state(frame).parts==1].median(0).values.cpu().numpy();eye=inv[:3,3];v=eye-target
            poses=[]
            for i,yaw in enumerate(np.linspace(-.8,.8,49)):
                rot=np.array([[np.cos(yaw),0,np.sin(yaw)],[0,1,0],[-np.sin(yaw),0,np.cos(yaw)]])
                e=target+rot@v;forward=(target-e);forward/=np.linalg.norm(forward);right=np.cross(forward,-inv[:3,1]);right/=np.linalg.norm(right);down=np.cross(forward,right)
                cam=np.eye(4);cam[:3,:3]=np.stack((right,down,forward));cam[:3,3]=-cam[:3,:3]@e
                r=draw(state,torch.tensor(cam,dtype=torch.float32,device='cuda'),frame['K'],width,height,unit_scale=m.scale)
                cv2.imwrite(str(frames/f'{i:04d}.png'),cv2.cvtColor((r['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
                poses.append(dict(index=i,C=cam.tolist(),orbitYawNotMeasuredFaceObservation=float(yaw)))
            save_json(frames/'contract.json',dict(assetHash=sha(asset),sourceHash=data['sourceHash'],reference=frame['name'],K=frame['K'].cpu().tolist(),poses=poses,renderer='gsplat1.5.3',notDeviceFPS=True,releaseQualityPassed=False))
        if sha(asset)!=result['assets'][label]['hash']:raise ValueError("asset_mutated_after_render")
    # Fixed views chosen by development list position, not performance.
    names=[plan['development'][i] for i in [0,len(plan['development'])//2,len(plan['development'])-1]]
    for name in names:
        original=cv2.imread(str(root/'R0-images'/name));width=original.shape[1]//2
        source=original[:,:width];a=original[:,width:]
        control=cv2.imread(str(root/'appearance-control/final-images'/name))[:,width:]
        candidate=cv2.imread(str(root/'canonical-appearance/final-images'/name))[:,width:]
        grid=np.concatenate((source,a,control,candidate),axis=1)
        cv2.imwrite(str(out/(name+'-comparison.png')),grid)
    save_json(out/'result.json',dict(branches=rows,seconds=time.perf_counter()-start,sourceHash=data['sourceHash'],
        publicationPassed=False,onlyGsplatExportContract=True,comparisonColumns=['source','R0','appearance_control','canonical_appearance']))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.root,a.out)
