"""Measured bounded body motion from the newly verified native trajectories.
No unconstrained per-frame scale, no replacement world cameras, no publishing.
"""
import json,argparse,time,hashlib
from pathlib import Path
import numpy as np
from reconstruction_components_v3 import load_v3_prepared,save_json,sha
from reconstruction_motion_geometry import measured_geometry


def run(prepared,tracks,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);start=time.perf_counter();data=load_v3_prepared(prepared)
    cache=json.loads(Path(tracks).read_text());bundle=json.loads((data['source']/'observation_bundle.json').read_text());times={r['name']:r['timestampSeconds'] for r in bundle['frames']}
    if cache['sourceHash']!=data['sourceHash']:raise ValueError('body_track_source_changed')
    results=[]
    for wi,window in enumerate(cache['windows']):
        names=[n for n in window if n in data['worlds']];records=[]
        for t in cache['tracks']:
            if t['region']!='cloth' or not t['id'].startswith(str(wi)+':'):continue
            obs=[o for o in t['observations'] if o['name'] in names]
            if len(obs)<4:continue
            source=obs[0];mask=data['labels'][source['name']]['neck_cloth_visible'];ys,xs=np.where(mask)
            if not len(xs):continue
            x,y=source['uv'];vertical='upper' if y<np.quantile(ys,.4) else 'lower';horizontal='left' if x<np.quantile(xs,.33) else 'right' if x>np.quantile(xs,.67) else 'middle'
            records.append(dict(t,region=vertical+'_'+horizontal,observations=obs))
        # Distributed bounded track budget, not a logo or only strongest corners.
        budget=[]
        for region in sorted({t['region'] for t in records}):
            group=sorted([t for t in records if t['region']==region],key=lambda t:hashlib.sha256(t['id'].encode()).hexdigest())[:16]
            budget.extend(group)
        cameras={n:data['worlds'][n] for n in names}
        if len(names)<4 or len(budget)<4:
            results.append(dict(window=wi,blocked='too_few_real_body_tracks_or_world_cameras'));continue
        result=measured_geometry(budget,cameras,data['K'],times,body=True,scale=data['scale'],max_nfev=80,motion_model='quadratic')
        save_json(out/f'window-{wi}.json',result)
        results.append(dict(window=wi,names=names,tracks=len(budget),accepted=sum(t['accepted'] for t in result.get('records',[])),motionAccepted=result['motionAccepted'],
            withheldThirdP90=result.get('withheldThirdP90'),withheldBeforeP90=result.get('withheldBeforeP90'),regions=sorted({t['region'] for t in budget})))
        print(json.dumps(results[-1]),flush=True)
    save_json(out/'result.json',dict(windows=results,trackHash=sha(tracks),sourceHash=data['sourceHash'],seconds=time.perf_counter()-start,published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepared',required=True);p.add_argument('--tracks',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.prepared,a.tracks,a.out)
