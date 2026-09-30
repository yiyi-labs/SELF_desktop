"""Reuse frozen TAPIR predictions; do not rerun the model or fit heldout RGB."""
import argparse,json,shutil
from pathlib import Path
import numpy as np,cv2
from reconstruction_dense_contract import write_json,digest
from reconstruction_native_measurements import native_measurement

def run(prepared,proposals,out):
    prep=Path(prepared);prop=Path(proposals);out=Path(out);out.mkdir(parents=True,exist_ok=False);meta=json.loads((prep/'preparation.json').read_text());config=json.loads((prop/'result.json').read_text());report=[]
    if config['sourceHash']!=meta['sourceHash']:raise ValueError('proposal_video_identity_mismatch')
    src=out/'algorithm-source';src.mkdir()
    for n in ('audit_tapir_native_measurements.py','reconstruction_native_measurements.py','reconstruction_temporal_observations.py'):shutil.copyfile(Path(__file__).with_name(n),src/n)
    for row in config['windows']:
        part=row['group'];folder=(prop/row['folder']) if 'folder' in row else next(p for p in prop.glob(part+'-*') if (p/'tracks.json').exists() and json.loads((p/'tracks.json').read_text())['names']==row['names']);spec=json.loads((folder/'tracks.json').read_text());names=spec['names'];a=dict(np.load(folder/'proposals.npz'));ims={n:cv2.imread(str(prep/'rectified_observations'/n),cv2.IMREAD_GRAYSCALE) for n in names};labs={n:dict(np.load(prep/'rectified_observations'/(n+'.npz'))) for n in names};sourceIndices=row['sourceIndices'];raw=np.load(prep/'local_geometry.npz');index={str(n):i for i,n in enumerate(raw['names'])};sourceRoot=(prep.parent.parent/meta['source']).resolve();fm=json.loads((sourceRoot/'frame_manifest.audit.json').read_text());identity={r['name']:r for r in fm['frames']};positions={n:sourceIndices.index(identity[n]['sourceIndexZeroBased']) for n in names};tracks=[];reject={};counts={}
        if spec['sourceHash']!=meta['sourceHash'] or fm['captureSha256']!=meta['sourceHash']:raise ValueError('measurement_video_identity_mismatch')
        if set(names)&set(spec['forbidden']):raise ValueError('heldout_measurement_anchor')
        for j,region in enumerate(a['roles']):
            seed=int(a['seeds'][j]);n0=names[seed];q=a['queries'][j];obs=[]
            for n in names:
                ti=positions[n];p=a['native'][ti,j]
                try:
                    if n==n0:uv=q;measurement=dict(fb=0.,correlation=1.,peakMargin=1.,affineCycle=0.)
                    else:
                        if not(a['visible'][ti,j] and a['reverseVisible'][ti,j]):raise ValueError('network_occluded_proposal')
                        uv,measurement=native_measurement(ims[n0],ims[n],q,p)
                    x,y=np.rint(uv).astype(int);h,w=ims[n].shape;key='face_core' if region=='face' else 'hair_visible' if region=='hair' else 'glasses_visible' if region=='glasses' else 'neck_cloth_visible'
                    if not(0<=x<w and 0<=y<h) or not labs[n][key][y,x] or labs[n]['unknown_or_occluded'][y,x]:raise ValueError('native_semantic_or_unknown')
                    obs.append(dict(name=n,uv=uv.tolist(),sigma=float(np.clip(.5+measurement['fb']+2*(1-measurement['correlation']),.5,2)),networkFB=float(a['fb'][ti,j]),**measurement))
                except (ValueError,cv2.error) as e:reason=str(e).split('\n')[0][:80];reject[reason]=reject.get(reason,0)+1
            if len(obs)>=4:
                tracks.append(dict(id=f'{part}:{n0}:{j}',region=str(region),sourceName=n0,observations=obs));counts[str(region)]=counts.get(str(region),0)+1
        dest=out/folder.name;dest.mkdir();write_json(dest/'tracks.json',{**spec,'tracks':tracks,'proposalsHash':digest(folder/'proposals.npz'),'nativePrecision':'NCC>=.78; unique peak>.025; bounded symmetric affine; native reverse<=1px; real masks/unknown; network FB logged, not geometric evidence'})
        rr=dict(group=part,names=names,tracks=len(tracks),byRegion=counts,rejections=reject);report.append(rr);print(json.dumps(rr),flush=True)
    write_json(out/'result.json',dict(sourceHash=meta['sourceHash'],windows=report,published=False,modelRerun=False,thresholdScope='coarse learned track proposal vs independently verified native measurement'))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','proposals','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.prepared,a.proposals,a.out)
