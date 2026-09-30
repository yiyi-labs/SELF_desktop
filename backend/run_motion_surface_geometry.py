"""Reusable finite motion/track-surface stage. No publishing side effects."""
import argparse,json,shutil,time
from pathlib import Path
import numpy as np
from reconstruction_dense_contract import write_json,digest
from reconstruction_motion_geometry import measured_geometry
from reconstruction_motion_patches import build_track_patch

def run(prepared,measurements,out):
    start=time.perf_counter();prep=Path(prepared);measurements=Path(measurements);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    src=out/'algorithm-source';src.mkdir()
    for name in ('run_motion_surface_geometry.py','reconstruction_motion_geometry.py','reconstruction_motion_patches.py'):
        shutil.copyfile(Path(__file__).with_name(name),src/name)
    meta=json.loads((prep/'preparation.json').read_text());raw=dict(np.load(prep/'local_geometry.npz'));F={str(n):raw['F'][i] for i,n in enumerate(raw['names'])};C={str(n):raw['C'][i] for i,n in enumerate(raw['world_names'])};result=[]
    for folder in sorted(measurements.glob('*-*')):
        if not (folder/'tracks.json').exists():continue
        t=json.loads((folder/'tracks.json').read_text());names=t['names'];body=t['coordinateGroup']=='body'
        if t['sourceHash']!=meta['sourceHash'] or set(names)&set(t['forbidden']):raise ValueError('geometry_source_or_role_mismatch')
        maps=C if body else F
        if any(n not in maps for n in names):raise ValueError('no_supported_camera')
        g=measured_geometry(t['tracks'],{n:maps[n] for n in names},raw['K'],t['timestamps'],body=body,scale=float(raw['scale']),max_nfev=60)
        g['sourceHash']=meta['sourceHash'];g['K']=raw['K'].tolist();g['timestamps']=t['timestamps'];g['inputHash']=digest(folder/'tracks.json');g['published']=False
        write_json(out/(folder.name+'-geometry.json'),g)
        if 'cameras' in g:
            build_track_patch(prep,g,out/(folder.name+'-patch'),'body' if body else 'hair')
        row=dict(group=t['coordinateGroup'],inputTracks=len(t['tracks']),uniqueTracks=len(g['records']),accepted=sum(r['accepted'] for r in g['records']),byRegion={r:sum(t['region']==r and t['accepted'] for t in g['records']) for r in {t['region'] for t in g['records']}},motionAccepted=g['motionAccepted'],withheldThirdP90=g.get('withheldThirdP90'),blocked=g.get('blocked'));result.append(row);print(json.dumps(row),flush=True)
    write_json(out/'result.json',dict(rows=result,seconds=time.perf_counter()-start,sourceHash=meta['sourceHash'],knownCamerasUnchanged=True,published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','measurements','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.prepared,a.measurements,a.out)
