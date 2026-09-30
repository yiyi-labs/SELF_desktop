"""Pinned BootsTAPIR proposals, independent body windows, native measurements.
One track identity across views; visibility is a proposal, not geometry truth.
No worker, device, publisher or production configuration imports.
"""
import argparse,json,time,sys,shutil,gc
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_dense_contract import digest,write_json
from reconstruction_tracker_decode import decode_window
from reconstruction_temporal_observations import select_windows,crop_transform,pixels,source_indices,bounded_native_affine,affine_center_delta
from run_complete_observations import distributed_queries

def select_part_windows(prep,raw,plan,identity,part,limit=1):
    forbidden=set(plan['development'])|set(plan['audit']); world={str(n):raw['C'][i] for i,n in enumerate(raw['world_names'])}
    breaks=sorted(identity[n]['timestampSeconds'] for n in forbidden if n in identity);rows=[]
    for i,v in enumerate(raw['names']):
        n=str(v)
        if str(raw['roles'][i])!='train' or n in forbidden or part=='body' and n not in world:continue
        lab=dict(np.load(prep/'rectified_observations'/(n+'.npz')))
        mask=(lab['neck_cloth_visible'] if part=='body' else lab['face_core']|lab['hair_visible']|lab['glasses_visible'])&~lab['unknown_or_occluded']
        if mask.sum()<1000:continue
        im=cv2.imread(str(prep/'rectified_observations'/n));gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
        # Body quality uses every cloth band, including collar/shoulder band.
        ys,xs=np.where(mask);upper=mask.copy();upper[int(np.quantile(ys,.4))+1:]=False
        quality=(lab['face_core']&~lab['glasses_visible']&~lab['unknown_or_occluded']) if part=='head' else upper
        if int(quality.sum())<1000:continue
        sharp=float(np.mean(cv2.Laplacian(gray,cv2.CV_32F)[quality]**2))
        T=raw['F'][i] if part=='head' else world[n]
        row={**identity[n],'sharpness':sharp,'coverage':int(quality.sum()),'cameraCenter':(-T[:3,:3].T@T[:3,3]).tolist(),'segment':int(np.searchsorted(breaks,identity[n]['timestampSeconds']))}
        rows.append(row)
    candidates=[]
    for seg in sorted({r['segment'] for r in rows}):candidates.extend(select_windows([r for r in rows if r['segment']==seg],limit=1))
    candidates.sort(key=lambda b:-np.log1p(np.median([r['sharpness'] for r in b]))*np.sqrt(min(r['coverage'] for r in b)))
    return candidates[:limit]

def run(prepared,split,tool,out,limit=1,parts=('head','body')):
    start=time.perf_counter();out=Path(out);out.mkdir(parents=True,exist_ok=False);prep=Path(prepared);tool=Path(tool)
    src=out/'algorithm-source';src.mkdir()
    for n in ('run_tapir_surface_observations.py','reconstruction_temporal_observations.py','run_complete_observations.py','reconstruction_tracker_decode.py'):
        shutil.copyfile(Path(__file__).with_name(n),src/n)
    meta=json.loads((prep/'preparation.json').read_text());raw=dict(np.load(prep/'local_geometry.npz'));plan=json.loads(Path(split).read_text());root=(prep.parent.parent/meta['source']).resolve()
    if digest(root/'capture.mp4')!=meta['sourceHash']:raise ValueError('capture_hash_changed')
    fm=json.loads((root/'frame_manifest.audit.json').read_text());identity={r['name']:r for r in fm['frames']}
    if fm['captureSha256']!=meta['sourceHash']:raise ValueError('frame_source_mismatch')
    lock=json.loads((tool/'lock.json').read_text(encoding='utf-8-sig'))
    if digest(tool/'bootstapir_checkpoint_v2.pt')!=lock['checkpointSHA256']:raise ValueError('weight_changed')
    sys.path.insert(0,str(tool/'source'/('tapnet-'+lock['codeCommit'])))
    from tapnet.torch.tapir_model import TAPIR
    model=TAPIR(pyramid_level=1,feature_extractor_chunk_size=4).cuda().eval()
    model.load_state_dict(torch.load(tool/'bootstapir_checkpoint_v2.pt',map_location='cpu',weights_only=True),strict=True)
    choices=[(part,block) for part in parts for block in select_part_windows(prep,raw,plan,identity,part,limit)]
    report=[];torch.cuda.reset_peak_memory_stats()
    for wi,(part,block) in enumerate(choices):
        names=[r['name'] for r in block];dest=out/f'{part}-{wi}';dest.mkdir();ims={n:cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB) for n in names};labs={n:dict(np.load(prep/'rectified_observations'/(n+'.npz'))) for n in names}
        masks=[(labs[n]['neck_cloth_visible'] if part=='body' else labs[n]['face_core']|labs[n]['hair_visible']|labs[n]['glasses_visible'])&~labs[n]['unknown_or_occluded'] for n in names]
        ys,xs=np.where(np.logical_or.reduce(masks));h,w=ims[names[0]].shape[:2];pad=24;rect=(max(0,int(xs.min())-pad),max(0,int(ys.min())-pad),min(w,int(xs.max())+pad+1),min(h,int(ys.max())+pad+1))
        decoded,positions,indices,source_times=decode_window(prep,root/'capture.mp4',identity,names,ims)
        frames=[]
        for native_frame in decoded:
            canvas,mapping=crop_transform(native_frame,rect,(512,512));frames.append(canvas)
        q=[];roles=[];seeds=[]
        for seed in (0,len(names)//2):
            points,rr=distributed_queries(ims[names[seed]],labs[names[seed]],{'face':96,'hair':96,'glasses':32,**{k:64 for k in ('upper_left','upper_middle','upper_right','lower_left','lower_middle','lower_right')}})
            for p,r in zip(points,rr):
                if (r in ('face','hair','glasses'))==(part=='head'):q.append(p);roles.append(r);seeds.append(seed)
        q=np.asarray(q,np.float32);network=pixels(q,mapping);query_times=[positions[names[s]] for s in seeds];queries=np.c_[query_times,network[:,1],network[:,0]]
        video=torch.tensor(np.stack(frames),dtype=torch.float32,device='cuda')[None]/127.5-1
        def infer(v,qq):
            with torch.inference_mode():z=model(v,torch.as_tensor(qq,device='cuda',dtype=torch.float32)[None],query_chunk_size=32)
            positions=z['tracks'][0].permute(1,0,2).cpu().numpy();visible=((1-z['occlusion'][0].sigmoid())*(1-z['expected_dist'][0].sigmoid())>.5).T.cpu().numpy()
            return positions,visible
        pred,vis=infer(video,queries)
        last=np.array([np.flatnonzero(vis[:,j])[-1] if vis[:,j].any() else query_times[j] for j in range(len(q))]);revq=np.c_[len(frames)-1-last,pred[last,np.arange(len(q)),1],pred[last,np.arange(len(q)),0]]
        back,rv=infer(video.flip(1),revq);native=pixels(pred,mapping,True);reverse=pixels(back[::-1],mapping,True);fb=np.linalg.norm(native-reverse,axis=-1)
        np.savez_compressed(dest/'proposals.npz',native=native,reverse=reverse,visible=vis,reverseVisible=rv[::-1],fb=fb,queries=q,seeds=seeds,roles=roles)
        gray={n:cv2.cvtColor(ims[n],cv2.COLOR_RGB2GRAY) for n in names};tracks=[];reject={};counts={}
        for j,role in enumerate(roles):
            seed=seeds[j];n0=names[seed];template=cv2.getRectSubPix(gray[n0],(25,25),tuple(q[j])).astype(np.float32)/255;obs=[]
            for ai,n in enumerate(names):
                ti=positions[n]
                uv=native[ti,j];x,y=np.rint(uv).astype(int)
                try:
                    if not(vis[ti,j] and rv[::-1][ti,j]) or fb[ti,j]>2:raise ValueError('network_visibility_or_FB')
                    if not(16<x<w-17 and 16<y<h-17):raise ValueError('boundary')
                    key='face_core' if role=='face' else 'hair_visible' if role=='hair' else 'glasses_visible' if role=='glasses' else 'neck_cloth_visible'
                    if not labs[n][key][y,x] or labs[n]['unknown_or_occluded'][y,x]:raise ValueError('mask_or_unknown')
                    if ai==seed:refined=q[j];corr=1.;cycle=0.
                    else:
                        patch=cv2.getRectSubPix(gray[n],(25,25),tuple(uv.astype(np.float32))).astype(np.float32)/255
                        warp,corr,cycle=bounded_native_affine(template,patch);refined=uv+affine_center_delta(warp,template.shape)
                    xx,yy=np.rint(refined).astype(int)
                    if not(0<=xx<w and 0<=yy<h) or not labs[n][key][yy,xx] or labs[n]['unknown_or_occluded'][yy,xx]:raise ValueError('refined_mask')
                    obs.append(dict(name=n,uv=refined.tolist(),sigma=float(np.clip(.5+.4*fb[ti,j]+2*(1-corr),.5,2)),fb=float(fb[ti,j]),correlation=corr,cycle=cycle))
                except (ValueError,cv2.error) as e:reject[str(e).split('\n')[0][:80]]=reject.get(str(e).split('\n')[0][:80],0)+1
            if len(obs)>=4 and any(o['name']==n0 for o in obs):
                tracks.append(dict(id=f'{part}:{n0}:{j}',region=role,sourceName=n0,observations=obs));counts[role]=counts.get(role,0)+1
        write_json(dest/'tracks.json',dict(sourceHash=meta['sourceHash'],names=names,timestamps={r['name']:r['timestampSeconds'] for r in block},coordinateGroup=part,tracks=tracks,forbidden=plan['development']+plan['audit'],published=False))
        row=dict(group=part,folder=dest.name,names=names,rectangle=rect,sourceIndices=indices.tolist(),sourceTimes=source_times.tolist(),queries=len(q),tracks=len(tracks),byRegion=counts,rejections=reject);report.append(row);print(json.dumps(row),flush=True)
        del video;gc.collect();torch.cuda.empty_cache()
    write_json(out/'result.json',dict(sourceHash=meta['sourceHash'],lock=lock,windows=report,seconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,knownCameraOverwrite=False,roles='training anchors only; no heldout RGB',published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','split','tool','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--windows',type=int,default=1);p.add_argument('--parts',nargs='+',choices=('head','body'),default=['head','body']);a=p.parse_args();run(a.prepared,a.split,a.tool,a.out,a.windows,tuple(a.parts))
