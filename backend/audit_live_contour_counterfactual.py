"""CPU-only same-grid derivative replay; no prepared/asset mutation."""
from pathlib import Path
import argparse,json
import numpy as np
from audit_live_boundary_coverage import boundary_regions,original_semantics,sha


def audit(run,output):
    from reconstruction_live_dense import read_prepared,physical_masks,surface_samples,mask_at,native_uv,bilinear,support_samples
    from reconstruction_live_contour_sampling import surface_samples as one_sided
    run=Path(run).resolve();out=Path(output)
    if out.exists():raise FileExistsError(out)
    config=json.loads((run/'config.json').read_text());p=Path(config['prepared']).resolve();d=read_prepared(p)
    bundle=json.loads(Path(config['denseSurfaces']['manifestPath']).read_text());ref=bundle['reference']
    mp=Path(bundle['depthManifestPath']);dm=json.loads(mp.read_text());rows=[];label_cache={}
    def domains(name):
        if name not in label_cache:
            old=dict(np.load(p/'rectified_observations'/(name+'.npz'),allow_pickle=False))
            label_cache[name]=original_semantics(p,d['metadata'],name,d['K'],old)
        return label_cache[name]
    c,cf,o,l=domains(ref);regions,radius=boundary_regions(c,l['face_core']|l['face_boundary'],o)
    all_ids=[]
    for component,group in [('room','world'),('body','body-world')]:
        accepted={w for g,w in bundle['acceptedWindows'] if g==group}
        for row in dm['observations']:
            if row['group']!=group or row['imageName']!=ref or row['window'] not in accepted:continue
            targets=[];masks={}
            for r in dm['observations']:
                if r['group']==group and r['window']==row['window']:
                    path=mp.parent/r['file']
                    if sha(path)!=r['depthHash']:raise ValueError('contour_input_changed')
                    targets.append((r,dict(np.load(path,allow_pickle=False))))
                    masks[r['imageName']]=physical_masks(domains(r['imageName'])[3])[component]
            a=next(a for r,a in targets if r['imageName']==ref);h,w=a['depth'].shape
            yy,xx=np.mgrid[:h,:w];ownership=mask_at(masks[ref],native_uv(np.c_[xx.ravel(),yy.ravel()],a['nativeToProcessed'])).reshape(h,w)
            old=surface_samples(a['depth'],a['K'],a['W2C'])
            new=one_sided(a['depth'],a['K'],a['W2C'],ownership=ownership)
            np.testing.assert_array_equal(old[0],new[0]);np.testing.assert_allclose(old[1],new[1],atol=0,rtol=0)
            native=native_uv(old[0],a['nativeToProcessed']);confidence=bilinear(a['confidence'],old[0])
            domain=mask_at(masks[ref],native)&np.isfinite(confidence)&(confidence>0)
            if component!='room':domain&=confidence>=np.quantile(a['confidence'],.2)
            old_proposal=old[4]&domain;new_proposal=new[4]&domain;ids=np.flatnonzero(old_proposal|new_proposal)
            support=np.zeros(len(native),np.int16);free=support.copy()
            if len(ids):support[ids],free[ids],_=support_samples(old[1][ids],targets,masks,confidence_gate=component!='room')
            old_accepted=old_proposal&(support>=3)&(free<=1);new_accepted=new_proposal&(support>=3)&(free<=1)
            gained=new_accepted&~old_accepted;lost=old_accepted&~new_accepted
            areas={}
            for label,mask in {'whole_grid':np.ones_like(l['face_core']),**regions}.items():
                area=mask_at(mask,native)
                if not area.any():continue
                areas[label]={k:int((value&area).sum()) for k,value in dict(
                    oldProposed=old_proposal,newProposed=new_proposal,
                    derivativeNewValid=~old[4]&new[4]&domain,
                    derivativeNewInvalid=old[4]&~new[4]&domain,
                    oldAccepted=old_accepted,newAccepted=new_accepted,addedAccepted=gained,lostAccepted=lost).items()}
            rows.append(dict(component=component,window=row['window'],sourceImage=ref,grid=[w,h],
                distinctSupportImages=len(set(r['imageName'] for r,a in targets)),areas=areas))
            all_ids.append((component,dict(native_uv=native,added=gained,lost=lost,support=support,free=free)))
    report=dict(sourceHash=d['metadata']['sourceHash'],run=str(run),reference=ref,bandRadiusNativePixels=radius,
        hypothesis='same semantic side derivative only; centre depth and all original point filters unchanged',
        helperSha256=sha(Path(__file__).with_name('reconstruction_live_contour_sampling.py')),
        auditSha256=sha(__file__),results=rows,zeroTraining=True,assetChanged=False,
        limitation='Accepted source-grid locations are not new independent physical surfaces; no budget or rendered coverage is inferred.')
    out.mkdir(parents=True);(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    for component,values in all_ids:np.savez_compressed(out/(component+'-source-grid.npz'),**values)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();print(json.dumps(audit(a.run,a.output),indent=2))
