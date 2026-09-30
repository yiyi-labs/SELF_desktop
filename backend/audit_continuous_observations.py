"""Frozen continuous proposals -> corrected native measurements and withheld 3D checks.
No new neural inference, pose copying, background reconstruction or publication.
"""
import argparse,json,shutil
from pathlib import Path
import numpy as np,cv2
from reconstruction_temporal_observations import bounded_native_affine,affine_center_delta
from run_complete_observations import distributed_queries
from reconstruction_surface_evidence import triangulate_track,project
from reconstruction_components_v3 import save_json,sha

def run(prepared,proposals,out):
    prep=Path(prepared);root=Path(proposals);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(__file__,out/Path(__file__).name)
    shutil.copyfile(Path(__file__).with_name('reconstruction_temporal_observations.py'),out/'reconstruction_temporal_observations.py')
    cfg=json.loads((root/'config.json').read_text());geom=dict(np.load(prep/'local_geometry.npz'))
    meta=json.loads((prep/'preparation.json').read_text())
    if cfg['sourceHash']!=meta['sourceHash']:raise ValueError("source_changed")
    F={str(n):f for n,f in zip(geom['names'],geom['F'])};rows=[];allhead=[];counts={}
    for wi,names in enumerate(cfg['windows']):
        images={n:cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB) for n in names}
        labels={n:dict(np.load(prep/'rectified_observations'/(n+'.npz'))) for n in names}
        gray={n:cv2.cvtColor(im,cv2.COLOR_RGB2GRAY) for n,im in images.items()};h,w=gray[names[0]].shape
        accepted=[]
        for group in ['head','body']:
            file=root/f'window-{wi}'/(group+'-proposals.npz');z=dict(np.load(file))
            query=[];roles=[];seeds=[]
            for ai in [0,len(names)//2]:
                q,rr=distributed_queries(images[names[ai]],labels[names[ai]])
                for j,r in enumerate(rr):
                    if (r in ['face','hair','glasses'])==(group=='head'):
                        query.append(q[j]);roles.append(r);seeds.append(ai)
            if not np.array_equal(np.array(query),z['query']):raise ValueError("frozen_query_identity_changed")
            # Associate proposal time -> measured anchor by the saved query times and native sequence.
            # Source indices are actual timestamps, not COLMAP/image IDs.
            source_indices=z['sourceIndices']
            manifest=json.loads((prep.parent.parent/meta['source']/'frame_manifest.audit.json').read_text())
            byname={r['name']:r['sourceIndexZeroBased'] for r in manifest['frames']}
            for j,role in enumerate(roles):
                seed=seeds[j];n0=names[seed];p0=z['query'][j]
                src=cv2.getRectSubPix(gray[n0],(25,25),tuple(p0.astype(np.float32))).astype(np.float32)/255
                observations=[];differences=[]
                for n in names[seed:]:
                    ti=int(np.where(source_indices==byname[n])[0][0]);p=z['native'][ti,j];x,y=np.rint(p).astype(int)
                    try:
                        if not(z['visible'][ti,j] and z['reverseVisible'][ti,j]) or z['fb'][ti,j]>2:raise ValueError("visibility_or_reverse")
                        if not (15<x<w-16 and 15<y<h-16):raise ValueError("native_boundary")
                        key='face_core' if role=='face' else 'hair_visible' if role=='hair' else 'glasses_visible' if role=='glasses' else 'neck_cloth_visible'
                        if not labels[n][key][y,x] or labels[n]['unknown_or_occluded'][y,x]:raise ValueError("measured_component_or_occlusion")
                        dst=cv2.getRectSubPix(gray[n],(25,25),tuple(p.astype(np.float32))).astype(np.float32)/255
                        warp,corr,cycle=bounded_native_affine(src,dst);delta=affine_center_delta(warp,src.shape);uv=p+delta
                        xx,yy=np.rint(uv).astype(int)
                        if not(0<=xx<w and 0<=yy<h) or not labels[n][key][yy,xx] or labels[n]['unknown_or_occluded'][yy,xx]:raise ValueError("refined_component_boundary")
                        observations.append(dict(name=n,uv=uv.tolist(),sigma=float(np.clip(.5+z['fb'][ti,j]*.4+(1-corr)*2,.5,2.)),
                            fb=float(z['fb'][ti,j]),correlation=corr,visibleMeasured=True))
                        differences.append(float(np.linalg.norm(delta-warp[:,2])))
                    except (ValueError,cv2.error):continue
                if len(observations)>=3 and observations[0]['name']==n0:
                    t=dict(id=f'{n0}:{group}:{j}',region=role,observations=observations)
                    accepted.append(t);counts[role]=counts.get(role,0)+1
                    row=dict(id=t['id'],region=role,observations=len(observations),maxCenterVsTranslationDifference=float(max(differences)))
                    if role in ['hair','glasses','face']:
                        try:
                            x,info=triangulate_track({**t,'observations':observations[:-1]},F,geom['K'])
                            last=observations[-1];uv,zdepth=project(x[None],F[last['name']],geom['K'])
                            third=float(np.linalg.norm(uv[0]-last['uv']))
                            row.update(fit=info,thirdError=third,positiveThird=bool(zdepth[0]>0),xyz=x.tolist())
                            row['headLocal3DCheckPassed']=bool(info['positive'] and zdepth[0]>0 and info['maxAngleDegrees']>=2 and info['p90Error']<=2 and third<=2)
                            allhead.append(row)
                        except (ValueError,np.linalg.LinAlgError):row['headLocal3DCheckPassed']=False
                    else:
                        row['headLocal3DCheckPassed']=False
                        row['reason']='upper-body camera B not measured; head F is not a cloth camera'
                    rows.append(row)
            # Native seeds diagnostic: physical tracks and projected measurements, no geometry claim.
            im=images[names[0]].copy()
            for t in accepted:
                if t['observations'][0]['name']==names[0] and (t['region'] in ['face','hair','glasses'])==(group=='head'):
                    cv2.circle(im,tuple(np.rint(t['observations'][0]['uv']).astype(int)),4,(170,240,100),-1)
            cv2.imwrite(str(out/f'window-{wi}-{group}.png'),cv2.cvtColor(im,cv2.COLOR_RGB2BGR))
        save_json(out/f'window-{wi}-tracks.json',dict(sourceHash=cfg['sourceHash'],names=names,tracks=accepted))
    passed=[r for r in allhead if r['headLocal3DCheckPassed']]
    save_json(out/'measurements.json',rows)
    save_json(out/'result.json',dict(counts=counts,headLocalChecks={k:dict(proposals=sum(r['region']==k for r in allhead),passed=sum(r['region']==k for r in passed)) for k in ['face','hair','glasses']},
        sourceHash=cfg['sourceHash'],proposalFiles={str(p.relative_to(root)):sha(p) for p in root.glob('window-*/*proposals.npz')},
        proposalInferenceRepeated=False,bodyCameraInvented=False,published=False,
        noIndependentGeometryTruth=True,countsAreProposalsNotUniqueSurfaceArea=True))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ['prepared','proposals','out']:p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.prepared,a.proposals,a.out)
