"""Exact same PLY, camera and pixels: crop vs full projection diagnostics."""
from pathlib import Path
import json,argparse
import numpy as np
import torch
import cv2
from reconstruction_components_v3 import save_json,sha
from reconstruction_portrait_pipeline import draw,masked_mean
from reconstruction_portrait_model import GaussianState
from reconstruction_joint_visibility import load_recorded_ply

@torch.no_grad()
def run(a):
    if a.output.exists() or not a.output.resolve().is_relative_to(Path(__file__).resolve().parent/'.sources'):raise ValueError('new_audit_only')
    a.output.mkdir();manifest=json.loads((a.asset/'asset.json').read_text());ply=a.asset/'fixed-diagnostic-T2.ply';arrays=dict(np.load(a.asset/'fixed-diagnostic-T2.components.npz'))
    if sha(ply)!=manifest['asset']['assetSha256']:raise ValueError('frozen_asset_changed')
    raw=load_recorded_ply(ply,manifest['asset']['editableSplats']);fine=torch.tensor(arrays['fine_component'],device='cuda',dtype=torch.long);mapping=torch.tensor([1,2,3,4,4,0],device='cuda')
    s=GaussianState(raw['means'],raw['quats'],raw['scales'],raw['opacity'],raw['sh'][:,:4],mapping[fine])
    g=dict(np.load(a.prepared/'local_geometry.npz'));worlds={str(n):g['C'][i] for i,n in enumerate(g['world_names'])};records={}
    for name in [manifest['reference'],'frame_0115.png']:
        labels=dict(np.load(a.prepared/'rectified_observations'/(name+'.npz')));h,w=labels['face_core'].shape
        visible=labels['face_core']|labels['face_boundary']|labels['hair_visible']|labels['glasses_visible'];ys,xs=np.where(visible)
        x0=max(0,int(xs.min())-24);y0=max(0,int(ys.min())-24);x1=min(w,int(xs.max())+25);y1=min(h,int(ys.max())+25)
        K=torch.tensor(g['K'],device='cuda',dtype=torch.float32);C=torch.tensor(worlds[name],device='cuda',dtype=torch.float32);cropK=K.clone();cropK[0,2]-=x0;cropK[1,2]-=y0
        mask=torch.tensor((labels['face_core']|labels['face_boundary']|labels['glasses_visible'])[y0:y1,x0:x1],device='cuda')
        full=draw(s,C,K,w,h,unit_scale=float(g['scale']));crop=draw(s,C,cropK,x1-x0,y1-y0,unit_scale=float(g['scale']))
        fi=full['info'];ci=crop['info'];lookup=torch.full((len(s.means),),-1,device='cuda',dtype=torch.long);lookup[fi['gaussian_ids']]=torch.arange(len(fi['gaussian_ids']),device='cuda')
        ids=ci['gaussian_ids'];common=lookup[ids]>=0;ic=torch.where(common)[0];jf=lookup[ids[common]];sameids=ids[common]
        conic=(fi['conics'][jf]-ci['conics'][ic]).abs().max(-1).values;centers=(fi['means2d'][jf]-torch.tensor([x0,y0],device='cuda')-ci['means2d'][ic]).abs().max(-1).values
        changed=conic>1e-5;isroom=s.parts[sameids]==0
        relative=(fi['conics'][jf]-ci['conics'][ic]).norm(dim=-1)/fi['conics'][jf].norm(dim=-1).clamp_min(1e-12)
        all_ids=fi['gaussian_ids'];exists=torch.zeros(len(s.means),device='cuda',dtype=torch.bool);exists[ci['gaussian_ids']]=True
        means=fi['means2d'];rad=fi['radii'].float()
        overlap=(means[:,0]+rad[:,0]>x0)&(means[:,0]-rad[:,0]<x1)&(means[:,1]+rad[:,1]>y0)&(means[:,1]-rad[:,1]<y1)
        lost=overlap&~exists[all_ids];lost_room=lost&(s.parts[all_ids]==0)
        m=s.means@C[:3,:3].T+C[:3,3];z=m[:,2];fx=K[0,0];fy=K[1,1];px=cropK[0,2];py=cropK[1,2];cw=x1-x0;ch=y1-y0
        outside=(m[:,0]/z>((cw-px)/fx+.15*cw/fx))|(m[:,0]/z<-(px/fx+.15*cw/fx))|(m[:,1]/z>((ch-py)/fy+.15*ch/fy))|(m[:,1]/z<-(py/fy+.15*ch/fy))
        row={'crop':[x0,y0,x1,y1],'sharedVisiblePoints':len(sameids),'conicChanged':int(changed.sum()),'changedRoom':int((changed&isroom).sum()),
            'conicRelativeChangeOver10Pct':int((relative>.1).sum()),'relativeChangeRoom':int(((relative>.1)&isroom).sum()),
            'fullFootprintOverlapsCropButAbsent':int(lost.sum()),'lostRoom':int(lost_room.sum()),
            'changedOutsideCropProjectionClamp':int((changed&outside[sameids]).sum()),'maxCenterDifferencePx':float(centers.max()),
            'conicAbsDifferenceQuantiles':torch.quantile(conic,torch.tensor([.5,.9,.99,1.],device='cuda')).cpu().tolist(),
            'fullThenCropQRoom':float(masked_mean(full['q'][y0:y1,x0:x1,0],mask)),'croppedViewportQRoom':float(masked_mean(crop['q'][...,0],mask)),
            'faceRGBDifference':float(masked_mean((full['rgb'][y0:y1,x0:x1]-crop['rgb']).abs().mean(-1),mask))}
        rad=fi['radii'].float().max(-1).values
        row['visibleRadiusPx']={str(part):torch.quantile(rad[s.parts[fi['gaussian_ids']]==part],torch.tensor([.5,.9,.99],device='cuda')).cpu().tolist() for part in s.parts.unique().tolist() if (s.parts[fi['gaussian_ids']]==part).any()}
        records[name]=row
        im=np.concatenate((full['rgb'][y0:y1,x0:x1].clamp(0,1).cpu().numpy(),crop['rgb'].clamp(0,1).cpu().numpy()),1)
        cv2.imwrite(str(a.output/(name+'-full-vs-crop.png')),cv2.cvtColor((im*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    checkpoints={}
    for label,path in [('original',a.baseline/'face-initial.pt'),('previous',a.baseline/'face-final.pt'),('candidate',a.run/'portrait_refine_v1/final.pt')]:
        ck=torch.load(path,map_location='cpu',weights_only=False)['model'];sc=ck['portrait.log_scales'].exp();role=ck['portrait.role'];px=ck['portrait.metric_per_pixel']
        checkpoints[label]={}
        for part in [0,1,2]:
            q=sc[role==part];ratio=q.max(-1).values/px[role==part]
            checkpoints[label][str(part)]={'count':len(q),'anyAxisBelowClamp':int((q<.00045).any(-1).sum()),'allAxesBelowClamp':int((q<.00045).all(-1).sum()),
                'maxAxisNativePixelQuantiles':torch.quantile(ratio,torch.tensor([.5,.9,.99])).tolist()}
    utils=Path('/opt/self-reconstruction/venv/lib/python3.10/site-packages/gsplat/cuda/include/Utils.cuh')
    save_json(a.output/'report.json',{'assetSha256':sha(ply),'frozenReference':manifest['reference'],'records':records,'checkpointScales':checkpoints,
        'installedProjectionSource':str(utils),'projectionSha256':sha(utils),'note':'fixed-reference geometry in all views; not a source-pose reconstruction quality test',
        'jointTrainingPerformed':False,'engineModified':False})
    print(json.dumps(records),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','baseline','run','asset','output'):p.add_argument(k,type=Path)
    run(p.parse_args())
