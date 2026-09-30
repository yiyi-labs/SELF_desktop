"""Continuous source-video, high-effective-resolution regional observations.
Pinned CoTracker proposes only; native anchors alone become measured geometry.
"""
import argparse,json,sys,time,subprocess,gc,shutil
from pathlib import Path
import numpy as np,cv2,torch
from reconstruction_components_v3 import sha,save_json
from reconstruction_temporal_observations import select_windows,source_indices,crop_transform,pixels
from run_complete_observations import distributed_queries,regional_masks,propose


from reconstruction_temporal_observations import bounded_native_affine as bounded_affine,affine_center_delta


def run(prepared,split,tool,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    source=out/'algorithm-source';source.mkdir()
    for f in [Path(__file__),Path(__file__).with_name('reconstruction_temporal_observations.py'),Path(__file__).with_name('run_complete_observations.py')]:shutil.copyfile(f,source/f.name)
    prep=Path(prepared);meta=json.loads((prep/'preparation.json').read_text());plan=json.loads(Path(split).read_text())
    raw=dict(np.load(prep/'local_geometry.npz'));source_root=(prep.parent.parent/meta['source']).resolve()
    video_path=source_root/'capture.mp4'
    if sha(video_path)!=meta['sourceHash']:raise ValueError("source_hash_changed")
    index=json.loads((source_root/'frame_manifest.audit.json').read_text());byname={r['name']:r for r in index['frames']}
    if index['captureSha256']!=meta['sourceHash']:raise ValueError("timestamp_manifest_source_mismatch")
    frozen=set(plan['development'])|set(plan['audit']);blocked=sorted(byname[n]['timestampSeconds'] for n in frozen if n in byname)
    labels={};images={};rows=[];K=raw['K']
    for i,n in enumerate(raw['names']):
        n=str(n)
        if str(raw['roles'][i])!='train' or n in frozen:continue
        im=cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB)
        lab=dict(np.load(prep/'rectified_observations'/(n+'.npz')))
        valid=(lab['face_core']|lab['hair_visible']|lab['neck_cloth_visible'])&~lab['unknown_or_occluded']
        if not valid.any():continue
        gray=cv2.cvtColor(im,cv2.COLOR_RGB2GRAY);sharp=float(np.mean(cv2.Laplacian(gray,cv2.CV_32F)[valid]**2))
        F=raw['F'][i];center=-F[:3,:3].T@F[:3,3];ts=byname[n]['timestampSeconds']
        rows.append({**byname[n],'sharpness':sharp,'coverage':int(valid.sum()),'cameraCenter':center.tolist(),
            'segment':int(np.searchsorted(blocked,ts))})
        images[n]=im;labels[n]=lab
    windows=[]
    # Never use held-out RGB as even an intermediate tracking proposal.
    for segment in sorted(set(r['segment'] for r in rows)):
        windows.extend(select_windows([r for r in rows if r['segment']==segment],limit=1))
    windows=sorted(windows,key=lambda b:-np.median([r['sharpness'] for r in b]))[:2]
    if not windows:raise ValueError("no_continuous_training_window")
    times=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(video_path)],text=True))
    times=np.array([float(r['best_effort_timestamp_time']) for r in times['frames']])
    sequences=[source_indices(times,b) for b in windows];needed=set(int(i) for seq in sequences for i in seq)
    camera_audit=json.loads((prep/'pose-and-scale-audit.json').read_text());dist=np.array(camera_audit['sourceRadialDistortion'])
    native=images[windows[0][0]['name']].shape[:2];h,w=native
    if np.max(np.abs(np.asarray(camera_audit['K'])-K))>1e-7:raise ValueError("rectification_K_changed")
    mx,my=cv2.initUndistortRectifyMap(K,dist,np.eye(3),K,(w,h),cv2.CV_32FC1)
    capture=cv2.VideoCapture(str(video_path));decoded={};i=0
    while i<=max(needed):
        ok,im=capture.read()
        if not ok:raise ValueError("source_decode_incomplete")
        if i in needed:
            im=cv2.cvtColor(im,cv2.COLOR_BGR2RGB)
            if im.shape[:2]!=(h,w):raise ValueError("source_orientation_or_dimensions_changed")
            decoded[i]=cv2.remap(im,mx,my,cv2.INTER_LINEAR)
        i+=1
    capture.release();anchor_diff={}
    for b in windows:
        for r in b:
            im=decoded[r['sourceIndexZeroBased']];diff=float(np.abs(im.astype(float)-images[r['name']]).mean()/255)
            anchor_diff[r['name']]=diff
            if diff>.005:raise ValueError("decoded_source_anchor_mismatch:"+r['name'])
            decoded[r['sourceIndexZeroBased']]=images[r['name']]
    tool=Path(tool);manifest=json.loads((tool/'manifest.json').read_text(encoding='utf-8-sig'))
    if sha(tool/'scaled_online.pth')!=manifest['sha256']:raise ValueError("weight_hash_changed")
    sys.path.insert(0,str(tool/'source'/('co-tracker-'+manifest['codeCommit'])))
    from cotracker.predictor import CoTrackerOnlinePredictor
    model=CoTrackerOnlinePredictor(checkpoint=str(tool/'scaled_online.pth'),v2=False).cuda().eval()
    save_json(out/'config.json',dict(sourceHash=meta['sourceHash'],windows=[[r['name'] for r in b] for b in windows],
        sourceTimes=[times[idx].tolist() for idx in sequences],heldoutExcluded=sorted(frozen),
        localObservationsRequireWorld=False,nativeSize=[w,h],networkCanvas=[512,384],
        codeCommit=manifest['codeCommit'],weightHash=manifest['sha256'],decodedAnchorMeanDifferences=anchor_diff,
        seedPolicy="first and middle measured anchor; new visible regions can reseed",
        measurements="native bounded affine plus forward/reverse network visibility",published=False))
    report=[]
    for wi,(block,idx) in enumerate(zip(windows,sequences)):
        names=[r['name'] for r in block];destination=out/f'window-{wi}';destination.mkdir();alltracks=[];details=[]
        for group in ['head','body']:
            masks=[(labels[n]['face_core']|labels[n]['hair_visible']|labels[n]['glasses_visible']) if group=='head' else labels[n]['neck_cloth_visible'] for n in names]
            union=np.logical_or.reduce(masks);ys,xs=np.where(union)
            if not len(xs):continue
            margin=max(24,int(.08*max(np.ptp(xs),np.ptp(ys))))
            rect=(max(0,int(xs.min())-margin),max(0,int(ys.min())-margin),min(w,int(xs.max())+margin+1),min(h,int(ys.max())+margin+1))
            frames=[];mapping=None
            for si in idx:
                canvas,mapping=crop_transform(decoded[int(si)],rect);frames.append(canvas)
            query=[];roles=[];qtimes=[];seeds=[]
            for ai in [0,len(block)//2]:
                n=names[ai];q,role=distributed_queries(images[n],labels[n])
                use=[j for j,r in enumerate(role) if (r in ['face','hair','glasses'])==(group=='head')]
                for j in use:
                    query.append(q[j]);roles.append(role[j]);qtimes.append(int(np.where(idx==block[ai]['sourceIndexZeroBased'])[0][0]));seeds.append(ai)
            if not query:continue
            query=np.array(query);netquery=pixels(query,mapping)
            v=torch.as_tensor(np.stack(frames)).permute(0,3,1,2)[None].float().cuda();torch.cuda.reset_peak_memory_stats()
            with torch.inference_mode():
                pred,vis=propose(model,v,netquery,qtimes)
                last=np.array([np.where(vis[:,j])[0][-1] if vis[:,j].any() else qtimes[j] for j in range(len(query))])
                reverse,rvis=propose(model,v.flip(1),pred[last,np.arange(len(query))].copy(),len(idx)-1-last)
            observed=pixels(pred,mapping,True);back=pixels(reverse[::-1],mapping,True);fb=np.linalg.norm(observed-back,axis=-1)
            np.savez_compressed(destination/(group+'-proposals.npz'),native=observed,visible=vis,reverseVisible=rvis[::-1],fb=fb,sourceIndices=idx,query=query,queryTime=qtimes)
            rejected={};counts={};gray={n:cv2.cvtColor(images[n],cv2.COLOR_RGB2GRAY) for n in names}
            for j,role in enumerate(roles):
                seed=seeds[j];n0=names[seed];patch=cv2.getRectSubPix(gray[n0],(25,25),tuple(query[j].astype(np.float32))).astype(np.float32)/255;obs=[]
                for ai in range(seed,len(names)):
                    n=names[ai];ti=int(np.where(idx==block[ai]['sourceIndexZeroBased'])[0][0]);p=observed[ti,j];x,y=np.rint(p).astype(int)
                    try:
                        if not(vis[ti,j] and rvis[::-1][ti,j]) or fb[ti,j]>2:raise ValueError("visibility_or_reverse")
                        if not(15<x<w-16 and 15<y<h-16):raise ValueError("native_boundary")
                        key='face_core' if role=='face' else 'hair_visible' if role=='hair' else 'glasses_visible' if role=='glasses' else 'neck_cloth_visible'
                        if not labels[n][key][y,x] or labels[n]['unknown_or_occluded'][y,x]:raise ValueError("measured_component_or_occlusion")
                        target=cv2.getRectSubPix(gray[n],(25,25),tuple(p.astype(np.float32))).astype(np.float32)/255
                        warp,corr,cycle=bounded_affine(patch,target);uv=p+affine_center_delta(warp,patch.shape)
                        xx,yy=np.rint(uv).astype(int)
                        if not(0<=xx<w and 0<=yy<h) or not labels[n][key][yy,xx] or labels[n]['unknown_or_occluded'][yy,xx]:raise ValueError("refined_component_boundary")
                        obs.append(dict(name=n,uv=uv.tolist(),sigma=float(np.clip(.5+fb[ti,j]*.4+(1-corr)*2,.5,2.)),
                            fb=float(fb[ti,j]),correlation=corr,affine=warp.tolist(),affineCycle=cycle,visibleMeasured=True))
                    except (ValueError,cv2.error) as exc:
                        reason=str(exc)[:100];rejected[reason]=rejected.get(reason,0)+1
                if len(obs)>=3 and obs[0]['name']==n0:
                    alltracks.append(dict(id=f"{n0}:{group}:{j}",region=role,observations=obs));counts[role]=counts.get(role,0)+1
            details.append(dict(group=group,rectangle=list(rect),sourceFrameCount=len(idx),queries=len(query),tracksByRegion=counts,
                rejectionReasons=rejected,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576))
            del v;torch.cuda.empty_cache();print(wi,group,json.dumps(details[-1]),flush=True)
        save_json(destination/'tracks.json',dict(sourceHash=meta['sourceHash'],names=names,tracks=alltracks,
            intermediateFrames="tracking proposals only; no copied masks/F/C and no train colours",published=False))
        save_json(destination/'result.json',details);report.append(details)
    del model;gc.collect();torch.cuda.empty_cache()
    save_json(out/'result.json',dict(windows=report,seconds=time.perf_counter()-start,published=False,
        sourceHash=meta['sourceHash'],usedWorldCameraFilter=False,modelUnloaded=True))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ['prepared','split','tool','out']:p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.prepared,a.split,a.tool,a.out)
