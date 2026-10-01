"""Native measured short-window trajectories for head/neck/clothing surfaces.
Training frames are selected by timestamps, not IDs or one video's coordinates.
Existing calibrated observations are read only. No network/weight downloads.
"""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,cv2
from reconstruction_components_v3 import load_v3_prepared,save_json,sha
from reconstruction_continuity_surface import physical_masks
from reconstruction_surface_evidence import measured_tracks,triangulate_track,project
from reconstruction_motion_geometry import deduplicate_tracks

def choose_windows(data,times,maximum_seconds=4.,limit=3):
    names=sorted([n for n in data['train'] if n in times],key=lambda n:(times[n],n));chains=[]
    for n in names:
        if not chains or times[n]-times[chains[-1][-1]]>.8:chains.append([])
        chains[-1].append(n)
    proposals=[]
    for chain in chains:
        for i in range(len(chain)):
            a=[n for n in chain[i:] if times[n]-times[chain[i]]<=maximum_seconds]
            if len(a)>=5:proposals.append(a)
    result=[]
    for a in sorted(proposals,key=lambda a:(-len(a),times[a[0]])):
        if any(len(set(a)&set(b))>len(a)*.4 for b in result):continue
        result.append(a)
        if len(result)==limit:break
    return result

def run(prepared,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);start=time.perf_counter();data=load_v3_prepared(prepared)
    bundle_path=data['source']/'observation_bundle.json';bundle=json.loads(bundle_path.read_text())
    if bundle['sourceSha256']!=data['sourceHash']:raise ValueError('source_timestamp_identity_changed')
    times={r['name']:r['timestampSeconds'] for r in bundle['frames']};windows=choose_windows(data,times)
    names=list(dict.fromkeys(n for block in windows for n in block));masks=physical_masks(prepared,data,names)
    save_json(out/'config.json',dict(windows=windows,maximumSeconds=4.,maximumGapSeconds=.8,seedPositions='first,middle,last chronological training observations',
        nativeResolution=True,sourceTimestampHash=sha(bundle_path),geometryUses='existing local F, no guessed world C',published=False))
    (out/'algorithm-source').mkdir();shutil.copyfile(__file__,out/'algorithm-source'/Path(__file__).name)
    alltracks=[];summaries=[]
    for wi,block in enumerate(windows):
        images={n:(data['rgb'][n]*255).round().astype(np.uint8) for n in block}
        for role,quota in [('face',160),('hair',400),('neck',128),('cloth',300)]:
            proposed=[];logs=[]
            for anchor in (0,len(block)//2,len(block)-1):
                sequences=[block[anchor:]] if anchor==0 else [list(reversed(block[:anchor+1]))] if anchor==len(block)-1 else [block[anchor:],list(reversed(block[:anchor+1]))]
                for sequence in sequences:
                    if len(sequence)<4:continue
                    group={n:masks[n][role] for n in sequence}
                    tracks,quality=measured_tracks(images,group,sequence,max_corners=quota,refine=True)
                    for t in tracks:
                        t['id']=f'{wi}:{role}:{t["id"]}';t['region']=role
                    proposed.extend(tracks);logs.append(dict(source=sequence[0],names=sequence,**quality))
            unique,duplicates=deduplicate_tracks(proposed);records=[];reasons={}
            for t in unique:
                obs=sorted(t['observations'],key=lambda o:times[o['name']])
                t['observations']=obs
                if role=='cloth':records.append(dict(t,geometryStatus='body motion not assumed rigid for head fitting'));continue
                if len(obs)<4:reasons['fewer_than_four_observations']=reasons.get('fewer_than_four_observations',0)+1;continue
                F={o['name']:data['local'][o['name']]['F'] for o in obs}
                x,q=triangulate_track(dict(t,observations=obs[:-1]),F,data['K'])
                uv,z=project(x[None],F[obs[-1]['name']],data['K']);third=float(np.linalg.norm(uv[0]-obs[-1]['uv']))
                if not(q['positive'] and q['p90Error']<=2.5 and q['maxAngleDegrees']>=1. and z[0]>0 and third<=3):
                    reasons['local_F_geometry_or_third_rejected']=reasons.get('local_F_geometry_or_third_rejected',0)+1;continue
                # Check data-only depth information. The soft geometric prior
                # cannot make a weak measurement become well-conditioned.
                metric=max(float((x@F[obs[0]['name']][:3,:3].T+F[obs[0]['name']][:3,3])[2]/data['K'][0,0]),1e-8)
                def residual(p):return np.concatenate([(project(p[None],F[o['name']],data['K'])[0][0]-o['uv'])/o['sigma'] for o in obs[:-1]])
                eps=metric*.001;J=np.stack([(residual(x+np.eye(3)[k]*eps)-residual(x-np.eye(3)[k]*eps))/(2*eps) for k in range(3)],1);sv=np.linalg.svd(J,compute_uv=False)
                if sv[-1]/sv[0]<.01:reasons['weak_depth_mode']=reasons.get('weak_depth_mode',0)+1;continue
                records.append(dict(t,xyz=x.tolist(),quality=q,thirdError=third,dataSingularValues=sv.tolist(),conditionalOnExistingF=True))
            alltracks.extend(records);summaries.append(dict(window=wi,role=role,uniqueTracks=len(unique),geometryAccepted=len(records),duplicates=len(duplicates),rejections=reasons,measurement=logs))
            print(json.dumps({k:summaries[-1][k] for k in ('window','role','uniqueTracks','geometryAccepted','rejections')}),flush=True)
    save_json(out/'tracks.json',dict(sourceHash=data['sourceHash'],tracks=alltracks,windows=windows,trainOnly=True,independentDepthSensor=False))
    save_json(out/'result.json',dict(sourceHash=data['sourceHash'],summaries=summaries,seconds=time.perf_counter()-start,published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepared',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.prepared,a.out)
