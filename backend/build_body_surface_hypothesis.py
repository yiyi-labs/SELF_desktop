"""Short-window body depth hypothesis; real pixels, frozen measured world C.
Does not claim DA3 consensus measures body motion. Geometry remains unaccepted
until independent upper-body tracking supports it. No head F clothing warp.
"""
from pathlib import Path
import argparse,json,hashlib,shutil
import cv2,numpy as np
from scipy.spatial.transform import Rotation
from reconstruction_dense_contract import project,bilinear,digest,write_json
from reconstruction_dense_surfaces import native_uv,surface_samples
from reconstruction_motion_patches import coverage_budget


def body_at(labels,uv):
    h,w=labels['neck_cloth_visible'].shape;xy=np.rint(np.nan_to_num(uv)).astype(int)
    inside=np.isfinite(uv).all(1)&(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
    xy=xy.clip([0,0],[w-1,h-1])
    return inside&labels['neck_cloth_visible'][xy[:,1],xy[:,0]]&~labels['unknown_or_occluded'][xy[:,1],xy[:,0]]


def build(prepared,depth_dir,out,budget=12000):
    prep=Path(prepared);depth=Path(depth_dir);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    src=out/'algorithm-source';src.mkdir()
    for n in ('build_body_surface_hypothesis.py','reconstruction_dense_surfaces.py','reconstruction_motion_patches.py'):
        shutil.copyfile(Path(__file__).with_name(n),src/n)
    spec=json.loads((depth/'manifest.json').read_text());meta=json.loads((prep/'preparation.json').read_text())
    if spec['sourceHash']!=meta['sourceHash']:raise ValueError('source_mismatch')
    # Pre-existing camera-conditioned predictions, no new inference or selecting
    # against dev/audit RGB. Candidate windows are bounded by actual timestamps.
    candidates=[]
    for wi in sorted({r['window'] for r in spec['observations'] if r['group']=='world'}):
        rows=sorted([r for r in spec['observations'] if r['group']=='world' and r['window']==wi and r['scaleGatePassed']],key=lambda r:r['timestampSeconds'])
        for first in rows:
            block=[r for r in rows if 0<=r['timestampSeconds']-first['timestampSeconds']<=3.5]
            if len(block)<4:continue
            score=[]
            for r in block:
                lab=dict(np.load(prep/'rectified_observations'/(r['imageName']+'.npz')))
                score.append(int((lab['neck_cloth_visible']&~lab['unknown_or_occluded']).sum()))
            candidates.append((min(score),block))
    if not candidates:raise ValueError('no_four_view_short_body_window')
    rows=max(candidates,key=lambda x:(x[0],-x[1][0]['timestampSeconds']))[1]
    cache={};labels={};images={};C={};masks={};pieces=[];counts=[]
    for r in rows:
        n=r['imageName']
        if r['role']!='train' or n in spec['forbidden']:raise ValueError('role_leak')
        if digest(prep/'rectified_observations'/n)!=r['imageHash']:raise ValueError('image_changed')
        cache[n]=dict(np.load(depth/r['file']));labels[n]=dict(np.load(prep/'rectified_observations'/(n+'.npz')))
        images[n]=cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        C[n]=cache[n]['W2C'];masks[n]=labels[n]['neck_cloth_visible']&~labels[n]['unknown_or_occluded']
    raw=dict(np.load(prep/'local_geometry.npz'));world={str(n):raw['C'][i] for i,n in enumerate(raw['world_names'])}
    for r in rows:
        n=r['imageName'];a=cache[n]
        np.testing.assert_allclose(C[n],world[n],rtol=0,atol=1e-5)
        uv,xyz,basis,scales,good=surface_samples(a['depth'],a['K'],a['W2C'],stride=2)
        nuv=native_uv(uv,a['nativeToProcessed']);cf=bilinear(a['confidence'],uv)
        good&=body_at(labels[n],nuv)&(cf>=np.quantile(a['confidence'],.2));ix=np.flatnonzero(good)
        support=np.zeros(len(ix),np.int16);free=np.zeros(len(ix),np.int16);occluded=np.zeros(len(ix),np.int16)
        for t in rows:
            b=cache[t['imageName']];p,z=project(xyz[ix],b['K'],b['W2C']);h,w=b['depth'].shape
            valid=(z>0)&(p[:,0]>=0)&(p[:,0]<w-1)&(p[:,1]>=0)&(p[:,1]<h-1)
            observed=bilinear(b['depth'],p);conf=bilinear(b['confidence'],p)
            valid&=body_at(labels[t['imageName']],native_uv(p,b['nativeToProcessed']))&(observed>0)&np.isfinite(observed)&(conf>=np.quantile(b['confidence'],.2))
            support+=(valid&(np.abs(z-observed)<=.03*observed)).astype(np.int16)
            free+=(valid&(z<observed-.03*observed)).astype(np.int16)
            occluded+=(valid&(z>observed+.03*observed)).astype(np.int16)
        accept=(support>=3)&(free<=1);selected=ix[accept]
        counts.append(dict(name=n,proposed=len(ix),accepted=len(selected),occludedObservations=int(occluded.sum())))
        if not len(selected):continue
        colour=bilinear(images[n],nuv[selected]);sh=np.zeros((len(selected),4,3),np.float32);sh[:,0]=(colour-.5)/.28209479177387814
        uid=np.array([int.from_bytes(hashlib.sha256(f'body-depth:{spec["sourceHash"]}:{n}:{int(i)}'.encode()).digest()[:8],'little')&((1<<63)-1) for i in selected],np.int64)
        pieces.append(dict(means=xyz[selected],quats=Rotation.from_matrix(basis[selected]).as_quat()[:,[3,0,1,2]],scales=scales[selected],opacity=np.full(len(selected),.6),sh=sh,parts=np.full(len(selected),4,np.int64),uid=uid,confidence=cf[selected],support=support[accept],source_image=np.full(len(selected),n),source_uv=nuv[selected]))
    if not pieces:raise ValueError('no_multiview_supported_body_proposal')
    arrays={k:np.concatenate([p[k] for p in pieces]) for k in pieces[0]};before=len(arrays['means']);voxel=float(np.median(arrays['scales'][:,:2]))
    order=np.lexsort((arrays['uid'],-arrays['confidence'],-arrays['support']));key=np.floor(arrays['means']/voxel).astype(np.int64);_,which=np.unique(key[order],axis=0,return_index=True);arrays={k:v[order[which]] for k,v in arrays.items()}
    after=len(arrays['means']);selected=coverage_budget(arrays,C,raw['K'],masks,budget,4);arrays={k:v[selected] for k,v in arrays.items()}
    np.savez_compressed(out/'body-world.npz',**arrays,source_hash=np.array(spec['sourceHash']))
    write_json(out/'result.json',dict(sourceHash=spec['sourceHash'],depthManifestHash=digest(depth/'manifest.json'),modelLock=spec['modelLock'],names=[r['imageName'] for r in rows],reference=rows[len(rows)//2]['imageName'],counts=counts,beforeDedup=before,afterDedup=after,count=len(selected),budget=budget,coordinateGroup='world-reference',motion='static short-window hypothesis only; new measured motion did not pass',geometrySupported=False,knownCameraOverwrite=False,published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','depth','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();build(a.prepared,a.depth,a.out)
