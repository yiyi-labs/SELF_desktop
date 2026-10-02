"""Locked CoTracker3 proposals, refined and checked in native training RGB.
Research adapter only (upstream CC-BY-NC-4.0); no production imports/install.
No network coordinate, visibility score or mask alone is a geometry truth.
"""
from pathlib import Path
import argparse,json,sys,time,shutil
import numpy as np,torch,cv2
from reconstruction_components_v3 import load_v3_prepared,save_json,sha
from reconstruction_continuity_surface import physical_masks
from reconstruction_native_measurements import native_measurement
from reconstruction_ray_surface import sample_mask


def spatial_seeds(gray,mask,maximum=128):
    valid=cv2.erode(mask.astype(np.uint8),np.ones((7,7),np.uint8))
    pts=cv2.goodFeaturesToTrack(gray,1024,.008,5,mask=valid*255,blockSize=5)
    if pts is None:return np.empty((0,2),np.float32)
    cv2.cornerSubPix(gray,pts,(3,3),(-1,-1),(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.01))
    y,x=np.where(mask);bounds=(x.min(),y.min(),x.max()+1,y.max()+1);cells={}
    for p in pts[:,0]:
        cell=(min(7,int((p[0]-bounds[0])/(bounds[2]-bounds[0])*8)),min(7,int((p[1]-bounds[1])/(bounds[3]-bounds[1])*8)))
        cells.setdefault(cell,[]).append(p)
    selected=[]
    for rank in range(16):
        for cell in sorted(cells):
            if rank<len(cells[cell]):selected.append(cells[cell][rank])
            if len(selected)>=maximum:return np.asarray(selected,np.float32)
    return np.asarray(selected,np.float32)


def coordinate_scale(points,source_size,target_size):
    # Locked tracker uses align_corners=True; native pixel centres are retained.
    return np.asarray(points)*((np.asarray(target_size)-1)/(np.asarray(source_size)-1))


def online_chunk(model,video,queries):
    # This locked online model runs no update windows for offline T<=S/2.
    # Use its documented short-chunk mode and clear state between directions.
    if not 1<=video.shape[1]<=model.window_len:raise ValueError('tracker_chunk_length')
    model.init_video_online_processing()
    tracks,visible,confidence,extra=model(video,queries,iters=6,is_online=True)
    if not torch.isfinite(tracks).all() or tracks.abs().sum()==0:raise ValueError('tracker_empty_forward')
    return tracks,visible,confidence,extra

@torch.no_grad()
def run(prepared,window_result,tool,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);start=time.perf_counter()
    tool=Path(tool);lock=json.loads((tool/'manifest.json').read_text());weight=tool/'scaled_online.pth'
    if sha(weight)!=lock['sha256']:raise ValueError('tracker_weight_changed')
    source=tool/'source'/('co-tracker-'+lock['codeCommit'])
    license_text=(source/'LICENSE.md').read_text()
    if 'NonCommercial' not in license_text and 'noncommercial' not in license_text.lower():raise ValueError('tracker_license_changed')
    sys.path.insert(0,str(source))
    from cotracker.models.build_cotracker import build_cotracker
    data=load_v3_prepared(prepared);window=json.loads(Path(window_result).read_text())
    if window['sourceHash']!=data['sourceHash']:raise ValueError('tracker_source_changed')
    names=window['names']
    if not 4<=len(names)<=12 or any(n not in data['train'] for n in names):raise ValueError('tracker_window_roles')
    masks=physical_masks(prepared,data,names);images={n:(data['rgb'][n]*255).round().astype(np.uint8) for n in names}
    gray={n:cv2.cvtColor(images[n],cv2.COLOR_RGB2GRAY) for n in names}
    h,w=gray[names[0]].shape;points=spatial_seeds(gray[names[0]],masks[names[0]]['cloth'])
    if len(points)<12:raise ValueError('tracker_spatial_seeds')
    (out/'algorithm-source').mkdir();shutil.copyfile(__file__,out/'algorithm-source'/Path(__file__).name)
    model=build_cotracker(str(weight),offline=False,window_len=16).eval().cuda()
    from cotracker.models.core.model_utils import get_points_on_a_grid
    mh,mw=model.model_resolution
    # Exact same coordinate convention as the locked predictor source.
    video=torch.tensor(np.stack([images[n] for n in names]),device='cuda',dtype=torch.float32).permute(0,3,1,2)
    video=torch.nn.functional.interpolate(video,(mh,mw),mode='bilinear',align_corners=True)[None]
    native_to_net=coordinate_scale(points,[w,h],[mw,mh])
    queries=torch.tensor(np.c_[np.zeros(len(points)),native_to_net],device='cuda',dtype=torch.float32)[None]
    support=get_points_on_a_grid(6,(mh,mw),device='cuda')
    support=torch.cat([torch.zeros_like(support[...,:1]),support],-1)
    queries=torch.cat([queries,support],1)
    torch.cuda.reset_peak_memory_stats();begin=time.perf_counter()
    forward,visible,confidence,_=online_chunk(model,video,queries)
    forward=forward[:,:,:len(points)];visible=visible[:,:,:len(points)];confidence=confidence[:,:,:len(points)]
    if not torch.isfinite(forward).all() or forward.abs().sum()==0:raise ValueError('tracker_empty_forward')
    forward=coordinate_scale(forward[0].cpu().numpy(),[mw,mh],[w,h]);prob=(visible*confidence)[0].cpu().numpy()
    reverse_queries=torch.tensor(np.c_[np.zeros(len(points)),coordinate_scale(forward[-1],[w,h],[mw,mh])],device='cuda',dtype=torch.float32)[None]
    reverse_queries=torch.cat([reverse_queries,support],1)
    backward,bvis,bconf,_=online_chunk(model,video.flip(1),reverse_queries)
    backward=backward[:,:,:len(points)];bvis=bvis[:,:,:len(points)];bconf=bconf[:,:,:len(points)]
    backward=coordinate_scale(backward[0].cpu().numpy()[::-1],[mw,mh],[w,h]);backprob=(bvis*bconf)[0].cpu().numpy()[::-1]
    proposal_seconds=time.perf_counter()-begin;peak=torch.cuda.max_memory_allocated()/1048576
    if peak>6144:raise ValueError('tracker_resource_budget')
    np.savez_compressed(out/'network-proposals.npz',nativeForward=forward,nativeBackward=backward,probability=prob,reverseProbability=backprob,seeds=points,names=np.asarray(names))
    tracks=[];reject={};seeds=names[0]
    for i,p in enumerate(points):
        obs=[dict(name=seeds,uv=p.tolist(),sigma=.5,networkProposal=False)]
        for t,n in enumerate(names[1:],1):
            try:
                if prob[t,i]<.6 or backprob[t,i]<.6:raise ValueError('network_visibility_confidence')
                if np.linalg.norm(forward[t,i]-backward[t,i])>2:raise ValueError('native_scaled_network_cycle')
                uv,checks=native_measurement(gray[seeds],gray[n],p,forward[t,i])
                if not sample_mask(masks[n]['cloth'],uv[None])[0]:raise ValueError('target_cloth_observation')
                # Third image comparison on the same measured texture, not model projection.
                if len(obs)>1:
                    previous=obs[-1];cycle,_=native_measurement(gray[previous['name']],gray[n],previous['uv'],uv)
                    if np.linalg.norm(cycle-uv)>1.2:raise ValueError('native_third_cycle')
                obs.append(dict(name=n,uv=uv.tolist(),sigma=float(np.clip(.4+checks['fb']+.3*checks['affineCycle'],.4,1.5)),**checks))
            except (ValueError,cv2.error) as e:
                key=str(e).split('\n')[0];reject[key]=reject.get(key,0)+1
        if len(obs)>=4:tracks.append(dict(id='cotracker-native:'+str(i),region='cloth',observations=obs))
    report=dict(sourceHash=data['sourceHash'],tracks=tracks,windows=[names],trainOnly=True,independentDepthSensor=False)
    save_json(out/'tracks.json',report)
    save_json(out/'result.json',dict(sourceHash=data['sourceHash'],window=names,queries=len(points),nativeTracks=len(tracks),rejections=reject,
        inputHashes=dict(window=sha(window_result),weights=sha(weight),predictor=sha(source/'cotracker/predictor.py'),builder=sha(source/'cotracker/models/build_cotracker.py'),license=sha(source/'LICENSE.md')),
        tool=lock,license='CC-BY-NC-4.0 noncommercial isolated research; not product default',
        nativeSize=[w,h],networkSize=[mw,mh],pixelCenters='align_corners_true proposals; independent native refinement',
        upstreamPadding='online short-chunk path; repeated final frame internal to model, not extra measured observations',
        upstreamSupportGrid=36,onlineStateResetBeforeEachDirection=True,
        inferenceSeconds=proposal_seconds,seconds=time.perf_counter()-start,allocatedMiB=peak,published=False))
    print(json.dumps(dict(queries=len(points),nativeTracks=len(tracks),rejections=reject,seconds=time.perf_counter()-start,allocatedMiB=peak)),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','window-result','tool','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args()
    try:run(a.prepared,a.window_result,a.tool,a.out)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise