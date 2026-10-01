"""Reusable conditional multi-window hair surface and footprint-safe retirement.
Never changes frozen input, production, cameras, scale or publisher.
"""
from pathlib import Path
import json
import cv2,numpy as np,torch
from reconstruction_components_v3 import sha,save_json,pick
from reconstruction_mvs_contract import read_mvs_cloud
from reconstruction_room_surface_repair import validate_imported_native_intrinsics
from reconstruction_dense_contract import project
from reconstruction_portrait_pipeline import make_frame,draw
from reconstruction_surface_patch import weights
from reconstruction_surface_consensus import (contract_compatible,consensus_status,
    representative_samples,surface_gaussians,covered_retirement,new_uid)
from reconstruction_portrait_model import GaussianState


def collect_window(folder,data,plan,base,window,part='hair'):
    folder=Path(folder);meta=json.loads((folder/'contract.json').read_text())
    names=meta['names']
    if meta['sourceHash']!=data['sourceHash'] or meta['cameraFrame']!='head-local':raise ValueError('head_surface_source')
    if set(names)&set(plan['development']+plan['audit']) or any(data['local'][n]['role']!='train' for n in names):raise ValueError('head_surface_role_leak')
    validate_imported_native_intrinsics(folder,meta,meta['nativeK'])
    np.testing.assert_allclose(meta['fullK'],data['K'],atol=1e-6,rtol=0)
    cameras={n:base.baseline.adjusted_frame(make_frame(data,n,crop=False))['F'].detach().cpu().numpy() for n in names}
    for n in names:np.testing.assert_allclose(cameras[n],meta['contract']['cameras'][n],atol=1e-6,rtol=0)
    cloud=read_mvs_cloud(folder/'dense.ply');x=cloud['xyz'];norm=np.linalg.norm(cloud['normal'],axis=1)
    good=np.isfinite(x).all(1)&np.isfinite(cloud['normal']).all(1)&(norm>.8)
    counts=np.zeros(len(x),int);colors=np.zeros((len(x),3));squares=colors.copy()
    sources=np.full(len(x),'',dtype='U64');source_uv=np.zeros((len(x),2))
    for vi,n in enumerate(names):
        uv,z=project(x,data['K'],cameras[n]);xy=np.rint(np.nan_to_num(uv)).astype(int);h,w=data['rgb'][n].shape[:2]
        inside=good&(z>0)&(xy[:,0]>1)&(xy[:,0]<w-2)&(xy[:,1]>1)&(xy[:,1]<h-2)&np.array([vi in v for v in cloud['views']])
        lab=data['labels'][n];region=lab['hair_visible'] if part=='hair' else lab['face_core']&~lab['glasses_visible']
        mask=cv2.erode((region&~lab['unknown_or_occluded']).astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)
        clip=xy.clip([0,0],[w-1,h-1]);inside&=mask[clip[:,1],clip[:,0]];ii=np.flatnonzero(inside)
        if not len(ii):continue
        rgb=np.array([np.median(data['rgb'][n][y-1:y+2,u-1:u+2],axis=(0,1)) for u,y in xy[ii]])
        first=counts[ii]==0;sources[ii[first]]=n;source_uv[ii[first]]=uv[ii[first]]
        colors[ii]+=rgb;squares[ii]+=rgb*rgb;counts[ii]+=1
    ids=np.flatnonzero(counts>=3);_,z=project(x[ids],data['K'],cameras[names[len(names)//2]])
    if np.any(z<=0):raise ValueError('surface_positive_depth')
    digest=sha(folder/'dense.ply');count=counts[ids,None];rgb=colors[ids]/count
    return dict(means=x[ids],normal=cloud['normal'][ids]/norm[ids,None],
        pixel=z/data['K'][0,0],rgb=rgb,variance=np.maximum(squares[ids]/count-rgb*rgb,0),
        support=counts[ids],uid=np.array([new_uid(digest,int(i)) for i in ids],np.int64),
        source_index=ids,source_image=sources[ids],source_uv=source_uv[ids],
        window=np.full(len(ids),window,int)),meta,dict(folder=str(folder),cloudHash=digest,contractHash=sha(folder/'contract.json'),raw=len(x),supported=len(ids),names=names)


def build_surface(folders,data,plan,base,out,budget=6000,part='hair'):
    pieces=[];records=[];first=None
    for i,folder in enumerate(folders):
        a,m,r=collect_window(folder,data,plan,base,i,part)
        if first is not None:contract_compatible(first,m)
        else:first=m
        pieces.append(a);records.append(r)
    a={k:np.concatenate([p[k] for p in pieces],0) for k in pieces[0]}
    if len(a['means'])<32:raise ValueError('insufficient_multiview_hair')
    status=consensus_status(a['means'],a['normal'],a['pixel'],a['window'])
    # Close geometrically inconsistent sheets are withheld, not averaged or aligned.
    usable=np.flatnonzero(status['conflict']==0)
    chosen,thinning=representative_samples(a['means'][usable],a['normal'][usable],a['pixel'][usable],
        a['support'][usable]+status['agreement'][usable],a['uid'][usable],budget=budget)
    ii=usable[chosen];arrays={k:v[ii] for k,v in a.items()}
    arrays.update(surface_gaussians(arrays['means'],arrays['normal'],arrays['pixel'],arrays['rgb']))
    arrays['cross_window_agreement']=status['agreement'][ii]
    report=dict(windows=records,rawSupported=len(a['means']),agreement=int(status['agreement'].sum()),
        closeNormalConflict=int(status['conflict'].sum()),unknown=int(status['unknown'].sum()),
        thinning=thinning,thresholds=dict(support=3,distancePixels=2.5,unsignedNormalDegrees=30),
        conditionalOnRecordedF=True,unknownIsNotEmpty=True,geometryAveraged=False,published=False)
    save_json(out/'surface-proposal.json',report);np.savez_compressed(out/'surface.npz',**arrays)
    return arrays,report


def retirement(arrays,data,plan,base,out):
    t=lambda a:torch.as_tensor(a,device='cuda',dtype=torch.float32)
    proposal=GaussianState(t(arrays['means']),t(arrays['quats']),t(arrays['scales']),t(arrays['opacity']),t(arrays['sh']),torch.full((len(arrays['means']),),2,device='cuda',dtype=torch.long))
    f=base.baseline.adjusted_frame(make_frame(data,data['reference'],crop=False))
    ids=torch.where(base.keep_head&(base.baseline.head_state(f).parts==2))[0]
    names=list(dict.fromkeys(n for n in plan['train'] if n in data['local']))
    total=[];covered=[];coverage=[]
    for n in names:
        f=base.baseline.adjusted_frame(make_frame(data,n,crop=False));h,w=f['rgb'].shape[:2]
        head=base.baseline.head_state(f);keep=torch.where(base.keep_head)[0]
        mask=torch.as_tensor(data['labels'][n]['hair_visible']&~data['labels'][n]['unknown_or_occluded'],device='cuda')
        with torch.no_grad():new=draw(proposal,f['F'],f['K'],w,h);support=(new['q'][...,2]>=.45)&mask
        # Old full-head visibility and exact footprint; centre proximity is not used.
        a,_=weights(pick(head,keep),f['F'],f['K'],w,h,mask)
        b,_=weights(pick(head,keep),f['F'],f['K'],w,h,support)
        rows=torch.searchsorted(keep,ids);total.append(a[rows].cpu().numpy());covered.append(b[rows].cpu().numpy())
        coverage.append(dict(name=n,observedHairPixels=int(mask.sum()),proposalCoveredPixels=int(support.sum())))
    a=np.array(total);b=np.array(covered);accept,fraction=covered_retirement(a,b)
    retired=ids[torch.as_tensor(accept,device='cuda')].cpu().numpy()
    np.savez_compressed(out/'retirement-contributions.npz',names=names,head_ids=ids.cpu().numpy(),total=a,covered=b,fraction=fraction,accepted=accept)
    result=dict(views=coverage,retired=retired.tolist(),retiredCount=len(retired),unknownRetained=int((~accept).sum()),
        rule='actual old full-head alpha*T; minimum 2 pixel responsibility in 3 training views; replacement covers >=92% in every significant view',
        proposalThreshold=.45,developmentRGBUsed=False)
    save_json(out/'retirement.json',result)
    if len(retired)<8:raise ValueError('insufficient_all_angle_replacement:'+str(len(retired)))
    return retired
