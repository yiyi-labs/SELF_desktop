"""CPU room-footprint attribution on current initialization/final parameters.

Six-sigma analytic potential alpha is deliberately conservative and excludes
person occlusion. It is NOT a replacement for saved actual GPU full-frame q.
"""
from pathlib import Path
import argparse,json
import numpy as np
import torch
from scipy.spatial.transform import Rotation
from audit_live_boundary_coverage import boundary_regions,original_semantics,sha


def potential_alpha(means,scales,quats,opacity,K,C,size,groups):
    w,h=size;camera=means@C[:3,:3].T+C[:3,3]
    z=camera[:,2];x=camera[:,0];y=camera[:,1]
    projected=(camera@K.T)[:,:2]/z[:,None]
    R=Rotation.from_quat(quats[:,[1,2,3,0]]).as_matrix()
    cov=(R*scales[:,None,:]**2)@R.transpose(0,2,1)
    cov=C[:3,:3][None]@cov@C[:3,:3].T[None]
    J=np.zeros((len(z),2,3));J[:,0,0]=K[0,0]/z;J[:,1,1]=K[1,1]/z
    J[:,0,2]=-K[0,0]*x/z**2;J[:,1,2]=-K[1,1]*y/z**2
    screen=J@cov@J.transpose(0,2,1)+np.eye(2)[None]*.3
    extent=np.ceil(6*np.sqrt(np.diagonal(screen,axis1=1,axis2=2))).astype(int)
    inverse=np.linalg.inv(screen);group_names=np.unique(groups)
    logs={str(n):np.zeros((h,w),np.float32) for n in group_names}
    max_scale=[];visible={str(n):0 for n in group_names}
    for i in range(len(z)):
        if z[i]<=0 or not np.isfinite(screen[i]).all():continue
        u,v=projected[i];rx,ry=extent[i];x0=max(0,int(np.floor(u))-rx);x1=min(w,int(np.ceil(u))+rx+1)
        y0=max(0,int(np.floor(v))-ry);y1=min(h,int(np.ceil(v))+ry+1)
        if x1<=x0 or y1<=y0:continue
        yy,xx=np.mgrid[y0:y1,x0:x1];dx=xx+.5-u;dy=yy+.5-v
        power=-(inverse[i,0,0]*dx**2+2*inverse[i,0,1]*dx*dy+inverse[i,1,1]*dy**2)/2
        a=np.clip(opacity[i]*np.exp(power),0,.999)
        # No 1/255 cutoff or early stop: this includes more support than
        # the production rasterizer, useful for establishing real gaps.
        logs[str(groups[i])][y0:y1,x0:x1]+=np.log1p(-a).astype(np.float32)
        visible[str(groups[i])]+=1
    total=np.zeros((h,w),np.float32)
    for v in logs.values():total+=v
    return -np.expm1(total),{k:-np.expm1(v) for k,v in logs.items()},dict(
        visibleCentreOrFootprintCount=visible,projectedAxisSigmaQuantiles=np.quantile(np.sqrt(np.diagonal(screen,axis1=1,axis2=2)),[.5,.9,.99],axis=0).tolist())


def audit(run,output):
    from reconstruction_live_dense import read_prepared
    r=Path(run).resolve();out=Path(output)
    if out.exists():raise FileExistsError(out)
    cfg=json.loads((r/'config.json').read_text());p=Path(cfg['prepared']).resolve();d=read_prepared(p)
    b=json.loads(Path(cfg['denseSurfaces']['manifestPath']).read_text());ref=b['reference'];room_path=Path(b['components']['room']['path'])
    room=dict(np.load(room_path));old=dict(np.load(p/'rectified_observations'/(ref+'.npz')))
    c,cf,o,labels=original_semantics(p,d['metadata'],ref,d['K'],old)
    regions,radius=boundary_regions(c,labels['face_core']|labels['face_boundary'],o)
    targets={k:(v&labels['observed_room']) for k,v in regions.items() if k.startswith('room_')}
    targets['observed_room_all']=labels['observed_room']
    groups=np.asarray([str(int(i))+':'+str(n) for i,n in zip(room['source_receipt_index'],room['source_image'])])
    final=torch.load(r/'T3-state.pt',map_location='cpu',weights_only=False);state=final['model'];part=state['environment_parts'].numpy()==0
    ids=final['environmentSources']['id'].numpy()[part]
    lookup={int(uid):i for i,uid in enumerate(room['uid'])}
    if any(int(uid) not in lookup for uid in ids):raise ValueError('room_source_ancestry_missing')
    origin=np.array([lookup[int(uid)] for uid in ids])
    q=torch.nn.functional.normalize(state['environment.quats'][part],dim=-1).numpy()
    parameters={'initial':dict(means=room['means'],scales=room['scales'],quats=room['quats'],opacity=room['opacity'],groups=groups),
        'final':dict(means=state['environment.means'][part].numpy(),scales=state['environment.scales'][part].exp().numpy(),quats=q,
            opacity=state['environment.opacities'][part].sigmoid().numpy(),groups=groups[origin])}
    stats={};arrays={};h,w=c.shape
    for stage,params in parameters.items():
        actual=dict(np.load(r/('full-initial' if stage=='initial' else 'full-final')/(ref+'.npz')))
        a,by,projection=potential_alpha(**params,K=d['K'],C=actual['C'],size=(w,h))
        arrays[stage+'_potential_alpha']=a;stats[stage]={'projection':projection,'regions':{}}
        for name,mask in targets.items():
            if not mask.any():continue
            holes=mask&(actual['alpha']<.8);missing=mask&(a<.8)
            stats[stage]['regions'][name]=dict(pixels=int(mask.sum()),actualAlphaBelow08=int(holes.sum()),
                conservativeRoomPotentialBelow08=int(missing.sum()),
                actualHolesAlsoLowRoomPotential=int((holes&missing).sum()),
                conservativeRoomPotentialMean=float(a[mask].mean()),actualRoomQMean=float(actual['q'][...,0][mask].mean()),
                potentialBySource={g:dict(mean=float(v[mask].mean()),pixelsAbove08=int(((v>.8)&mask).sum())) for g,v in by.items()})
    report=dict(sourceHash=d['metadata']['sourceHash'],run=str(r),reference=ref,roomInitialHash=sha(room_path),
        finalParametersHash=sha(r/'T3-state.pt'),roomInitialCount=len(room['means']),roomFinalCount=int(part.sum()),
        sourceCounts={g:int((groups==g).sum()) for g in np.unique(groups)},nativeBandRadius=radius,results=stats,
        zeroTraining=True,modelChanged=False,
        analyticProjectionContract='Native K/C, full covariance+0.3px filter; 6 axis sigma bounds, no alpha cutoff, no other-part occlusion. Pixel centres +0.5. Diagnostic potential, not exact GPU or renderer parity.',
        limitations=['Current parameters, not the obsolete DA3 raw proposal pool.',
            'Original semantic ownership is observation, not independent depth truth.',
            'Potential alpha cannot prove correct room geometry, colour, or visibility.'])
    out.mkdir(parents=True);(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    np.savez_compressed(out/'room-potential.npz',**arrays)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();report=audit(a.run,a.output)
    print(json.dumps({k:report[k] for k in ('reference','roomInitialCount','roomFinalCount','results')},indent=2))
