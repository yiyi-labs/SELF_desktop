"""Physical-layer surface candidates from frozen depth and original pixels.
No new depth inference, guessed camera, generated background or publishing.
"""
from pathlib import Path
import argparse,json,hashlib,shutil,time
import cv2,numpy as np
from scipy.spatial.transform import Rotation
from reconstruction_dense_contract import project,bilinear,digest,write_json
from reconstruction_dense_surfaces import native_uv,surface_samples
from reconstruction_continuity_surface import physical_masks,spatial_neighbours
from reconstruction_components_v3 import load_v3_prepared


def inside_mask(mask,uv):
    h,w=mask.shape;finite=np.isfinite(uv).all(1);xy=np.rint(np.nan_to_num(uv)).astype(int)
    valid=finite&(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
    xy=xy.clip([0,0],[w-1,h-1]);return valid&mask[xy[:,1],xy[:,0]]


def collect(prepared,depth,out,component,budget,*,save_pool=False):
    start=time.perf_counter();out=Path(out);out.mkdir(parents=True,exist_ok=False)
    prep=Path(prepared);depth=Path(depth);spec=json.loads((depth/'manifest.json').read_text());data=load_v3_prepared(prep)
    if data['sourceHash']!=spec['sourceHash']:raise ValueError('depth_source_changed')
    group='head-local' if component=='hair' else 'world'
    rows=[r for r in spec['observations'] if r['group']==group and r['scaleGatePassed']]
    if any(r['role']!='train' or r['imageName'] in spec['forbidden'] for r in rows):raise ValueError('role_leak')
    # Body motion has a finite, train-only short window selected by actual time.
    if component=='body':
        blocks=[]
        for wi in sorted({r['window'] for r in rows}):
            a=sorted([r for r in rows if r['window']==wi],key=lambda r:r['timestampSeconds'])
            for first in a:
                b=[r for r in a if 0<=r['timestampSeconds']-first['timestampSeconds']<=3.5]
                if len(b)>=4:blocks.append(b)
        if not blocks:raise ValueError('no_observed_short_body_window')
        rows=max(blocks,key=lambda b:(len(b),-b[0]['timestampSeconds']))
    names=list(dict.fromkeys(r['imageName'] for r in rows));masks=physical_masks(prep,data,names)
    groups={}
    for r in rows:groups.setdefault(r['window'],[]).append(r)
    cache={};pieces=[];counts=[]
    for r in rows:
        if digest(prep/'rectified_observations'/r['imageName'])!=r['imageHash']:raise ValueError('image_changed')
        a=dict(np.load(depth/r['file']));expected=data['local'][r['imageName']]['F'] if group=='head-local' else data['worlds'][r['imageName']]
        np.testing.assert_allclose(a['W2C'],expected,rtol=0,atol=1e-5);cache[r['file']]=a
    for r in rows:
        a=cache[r['file']];n=r['imageName'];uv,xyz,basis,scales,good=surface_samples(a['depth'],a['K'],a['W2C'],stride=2)
        nuv=native_uv(uv,a['nativeToProcessed']);cf=bilinear(a['confidence'],uv)
        good&=cf>=np.quantile(a['confidence'],.2)
        layers=('neck','cloth') if component=='body' else (component,)
        for layer in layers:
            ids=np.flatnonzero(good&inside_mask(masks[n][layer],nuv));support=np.zeros(len(ids),np.int16);free=np.zeros(len(ids),np.int16)
            # Distinct real views within a prediction window; no self vote duplication.
            seen=set()
            for t in groups[r['window']]:
                tn=t['imageName']
                if tn in seen:continue
                seen.add(tn);b=cache[t['file']];p,z=project(xyz[ids],b['K'],b['W2C']);h,w=b['depth'].shape
                obs=bilinear(b['depth'],p);co=bilinear(b['confidence'],p)
                valid=(z>0)&(p[:,0]>=0)&(p[:,0]<w-1)&(p[:,1]>=0)&(p[:,1]<h-1)&np.isfinite(obs)&(obs>0)
                valid&=inside_mask(masks[tn][layer],native_uv(p,b['nativeToProcessed']))&(co>=np.quantile(b['confidence'],.2))
                support+=(valid&(np.abs(z-obs)<=.03*obs)).astype(np.int16)
                free+=(valid&(z<obs-.03*obs)).astype(np.int16)
            accepted=(support>=3)&(free<=1);ix=ids[accepted]
            counts.append(dict(name=n,window=r['window'],layer=layer,proposed=len(ids),accepted=len(ix)))
            if not len(ix):continue
            colour=bilinear(data['rgb'][n],nuv[ix]);valid=np.isfinite(colour).all(1);ix=ix[valid];colour=colour[valid]
            sh=np.zeros((len(ix),4,3),np.float32);sh[:,0]=(colour-.5)/.28209479177387814
            uid=np.array([int.from_bytes(hashlib.sha256(f'continuity:{spec["sourceHash"]}:{group}:{r["window"]}:{n}:{layer}:{i}'.encode()).digest()[:8],'little')&((1<<63)-1) for i in ix],np.int64)
            part={'neck':4,'cloth':4,'hair':2,'room':0}[layer]
            pieces.append(dict(means=xyz[ix],quats=Rotation.from_matrix(basis[ix]).as_quat()[:,[3,0,1,2]],scales=scales[ix],opacity=np.full(len(ix),.6),sh=sh,parts=np.full(len(ix),part,np.int64),layer=np.full(len(ix),layer),uid=uid,support=support[accepted][valid],confidence=cf[ix],source_image=np.full(len(ix),n),source_uv=nuv[ix]))
    if not pieces:raise ValueError('no_supported_surface')
    arrays={k:np.concatenate([p[k] for p in pieces]) for k in pieces[0]};before=len(arrays['means'])
    step=float(np.median(arrays['scales'][:,:2]));order=np.lexsort((arrays['uid'],-arrays['confidence'],-arrays['support']))
    _,layerids=np.unique(arrays['layer'],return_inverse=True);key=np.c_[layerids,np.floor(arrays['means']/step).astype(np.int64)]
    _,which=np.unique(key[order],axis=0,return_index=True);ids=order[which];after=len(ids)
    if save_pool:
        # Optional isolated research cache, before the existing quota sampler.
        # No new geometry or colour is inferred and the default result is unchanged.
        np.savez_compressed(out/'supported-pool.npz',**{k:v[ids] for k,v in arrays.items()},source_hash=np.array(data['sourceHash']))
    # Reserve separate physical layer coverage; no dense cloth can consume neck quota.
    selected=[]
    for layer in np.unique(arrays['layer']):
        ii=ids[arrays['layer'][ids]==layer];quota=budget if len(np.unique(arrays['layer']))==1 else (min(len(ii),max(1000,budget//4)) if layer=='neck' else budget-min(len(ids[arrays['layer'][ids]=='neck']),max(1000,budget//4)))
        ii=ii[np.argsort(arrays['uid'][ii])]
        selected.extend(ii[np.rint(np.linspace(0,len(ii)-1,min(len(ii),quota))).astype(int)].tolist())
    arrays={k:v[np.asarray(selected,int)] for k,v in arrays.items()}
    edges=spatial_neighbours(arrays['means'],arrays['quats'],arrays['scales'],np.where(arrays['layer']=='neck',5,arrays['parts']))
    np.savez_compressed(out/'surface.npz',**arrays,source_hash=np.array(data['sourceHash']),edges=edges)
    src=out/'algorithm-source';src.mkdir()
    for f in ('build_continuity_candidates.py','reconstruction_continuity_surface.py'):shutil.copyfile(Path(__file__).with_name(f),src/f)
    result=dict(component=component,sourceHash=data['sourceHash'],depthHash=digest(depth/'manifest.json'),names=names,timestamps={r['imageName']:r['timestampSeconds'] for r in rows},counts=counts,beforeDedup=before,afterDedup=after,count=len(selected),layers={k:int((arrays['layer']==k).sum()) for k in np.unique(arrays['layer'])},coordinateGroup=group,geometrySupported=False,supervision='camera-conditioned depth consensus; hypothesis not independent measurement',seconds=time.perf_counter()-start,published=False)
    write_json(out/'result.json',result);print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','depth','out','component'):p.add_argument('--'+k,required=True)
    p.add_argument('--budget',type=int,default=12000);a=p.parse_args();collect(a.prepared,a.depth,a.out,a.component,a.budget)
