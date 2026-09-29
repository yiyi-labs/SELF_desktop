"""Short-window selection and actual independent MVS input. No learned depth.
Caller supplies prepared data and a NEW output directory. Body identity motion
is only retained if calibrated short-window static-body tests pass; it remains
an explicitly limited hypothesis, not a minute-long head-bound body.
"""
import argparse,json,time
from pathlib import Path
import cv2,numpy as np
from reconstruction_surface_evidence import measured_tracks,triangulate_track,export_colmap,project
from reconstruction_components_v3 import save_json,sha


def run(prepared,out):
    started=time.perf_counter();out=Path(out);out.mkdir(parents=True,exist_ok=False)
    prepared=Path(prepared);z=dict(np.load(prepared/'local_geometry.npz'));meta=json.loads((prepared/'preparation.json').read_text());names=[str(n) for n in z['names']];K=z['K'];C={str(n):z['C'][i] for i,n in enumerate(z['world_names'])}
    training=set(meta['train']);world=sorted(training&set(C));chunks=[]
    for n in world:
        if not chunks or int(n[6:10])-int(chunks[-1][-1][6:10])>4:chunks.append([])
        chunks[-1].append(n)
    proposals=[]
    for ch in chunks:
        for start in range(0,max(len(ch)-5,0),6):
            group=ch[start:start+8]
            if len(group)>=6 and int(group[-1][6:10])-int(group[0][6:10])<=15:proposals.append(group)
    proposals=proposals[:8];images={};masks={};rows=[];candidates=[]
    for group in proposals:
        for n in group:
            if n in images:continue
            im=cv2.cvtColor(cv2.imread(str(prepared/'rectified_observations'/n)),cv2.COLOR_BGR2RGB);lab=dict(np.load(prepared/'rectified_observations'/(n+'.npz')))
            images[n]=im;masks[n]=lab['neck_cloth_visible']&~lab['unknown_or_occluded'];marks=z['marks'][names.index(n)];chin=marks[152,1]
            if chin<=1.5:chin*=im.shape[0]
            masks[n][:int(chin),:]=False
        tracks,stats=measured_tracks(images,masks,group,max_corners=600,refine=True);valid=[];metrics=[]
        for t in tracks:
            x,r=triangulate_track(t,C,K);metrics.append(r)
            if not r['positive'] or r['p90Error']>2.5 or r['maxAngleDegrees']<1.0:continue
            o=t['observations'][0];u,v=np.rint(o['uv']).astype(int);valid.append({**t,'xyz':x.tolist(),'color':images[o['name']][v,u].tolist(),'error':r['medianError'],'quality':r})
        row={'names':group,'tracking':stats,'acceptedGeometry':len(valid),'allTrackMedianError':float(np.median([r['medianError'] for r in metrics])) if metrics else None,'allTrackP90Error':float(np.quantile([r['p90Error'] for r in metrics],.9)) if metrics else None,'medianParallax':float(np.median([r['maxAngleDegrees'] for r in metrics])) if metrics else None}
        row['rigidWindowGate']=bool(len(valid)>=60 and row['allTrackMedianError']<1.5 and row['allTrackP90Error']<4.)
        rows.append(row);candidates.append(valid);print(json.dumps(row),flush=True)
    save_json(out/'window-candidates.json',rows)
    passing=[i for i,r in enumerate(rows) if r['rigidWindowGate']]
    if not passing:save_json(out/'result.json',{'blocked':'no_supported_short_rigid_upper_body_window','windows':rows,'seconds':time.perf_counter()-started});return
    # Selection uses training geometry coverage/consistency, not dev RGB.
    chosen=max(passing,key=lambda i:len(candidates[i]));group=rows[chosen]['names'];pts=candidates[chosen]
    contract=export_colmap(out/'colmap',images,masks,group,C,K,pts)
    save_json(out/'tracks.json',pts)
    save_json(out/'contract.json',{'schema':'self.surface-window.v1','sourceHash':meta['sourceHash'],'prepared':str(prepared),'preparedHash':sha(prepared/'preparation.json'),'names':group,'use':'training-only','cameraFrame':'upper-body-local','B':{n:np.eye(4).tolist() for n in group},'bodyMotion':'bounded short-window identity hypothesis supported by calibrated cloth tracks; independent of head F','allWindowTests':rows,'contract':contract,'seconds':time.perf_counter()-started})
    # Evidence contact sheet: full source, true garment mask, actual tracks.
    panels=[]
    for n in group:
        im=images[n].copy()
        for p in pts:
            for o in p['observations']:
                if o['name']==n:cv2.circle(im,tuple(np.rint(o['uv']).astype(int)),3,(40,220,190),1)
        panels.append(cv2.resize(im,(270,480)))
    cv2.imwrite(str(out/'training-window.png'),cv2.cvtColor(np.concatenate(panels,1),cv2.COLOR_RGB2BGR))
    print('MVS_INPUT_READY',flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--prepared',required=True);ap.add_argument('--out',required=True);a=ap.parse_args();run(a.prepared,a.out)
