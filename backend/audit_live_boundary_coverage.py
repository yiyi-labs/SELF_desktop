"""CPU attribution of observed person/room boundary loss, without new geometry.

Uses saved native full-frame renders for alpha/contribution measurements and
replays the existing per-window sampling predicates on cached depth only.
"""
from pathlib import Path
import argparse
import hashlib
import json
import cv2
import numpy as np


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def boundary_regions(classes, face_anchor, outside):
    """Image-relative diagnostic bands, not reconstruction/selection masks."""
    ys,xs=np.where(face_anchor)
    radius=max(4,round((np.ptp(xs)+1)*.025)) if len(xs) else max(4,round(min(classes.shape)*.01))
    person=(classes!=0)&~outside
    # Invalid rectification pixels are neither person nor room. Measuring to
    # their zero values would mistake the canvas edge for the person's contour.
    room=(~person)&~outside
    inside=cv2.distanceTransform((~room).astype(np.uint8),cv2.DIST_L2,5)
    exterior=cv2.distanceTransform((~person).astype(np.uint8),cv2.DIST_L2,5)
    regions={}
    for label,base,dist in [('person',person,inside),('room',~person&~outside,exterior)]:
        regions[label+'_edge']=base&(dist<=radius)
        regions[label+'_near']=base&(dist>radius)&(dist<=3*radius)
        regions[label+'_interior']=base&(dist>3*radius)
    for label,codes in [('body',[2,4]),('skin',[3]),('hair',[1])]:
        for band in ('edge','near'):
            regions[label+'_'+band]=regions['person_'+band]&np.isin(classes,codes)
    return regions,radius


def rejection_stages(raw_valid, derivative, semantic, confidence, support, free):
    masks={};remaining=np.ones(len(raw_valid),bool)
    for name,criterion in [('invalid_depth',raw_valid),('local_derivative',derivative),
                          ('semantic_domain',semantic),('confidence_quintile',confidence),
                          ('three_view_support',support>=3),('free_space_conflict',free<=1)]:
        masks[name]=remaining&~criterion;remaining&=criterion
    masks['accepted']=remaining
    if not np.all(np.sum(np.stack(list(masks.values())),axis=0)==1):raise AssertionError('boundary_rejection_partition')
    return masks


def original_semantics(prepared,metadata,name,K,existing):
    from reconstruction_observation_domains import observation_domains
    root=Path(metadata['masks'])
    if not root.is_absolute():root=(prepared.parent.parent/root).resolve()
    raw=cv2.imread(str(root/'labels'/(name+'.png')),0)
    with np.load(root/'confidence'/(name+'.npz')) as a:cf=a['confidence'].astype(np.float32)
    if raw is None or cf.shape!=raw.shape:raise ValueError('boundary_semantics_missing')
    distortion=metadata.get('sourceDistortion')
    if distortion is None:raise ValueError('boundary_native_distortion_required')
    h,w=raw.shape;mx,my=cv2.initUndistortRectifyMap(K,np.asarray(distortion),np.eye(3),K,(w,h),cv2.CV_32FC1)
    outside=(mx<0)|(my<0)|(mx>=w)|(my>=h)
    classes=cv2.remap(raw,mx,my,cv2.INTER_NEAREST);certainty=cv2.remap(cf,mx,my,cv2.INTER_LINEAR)
    return classes,certainty,outside,observation_domains(classes,certainty,outside,existing)


def audit(run,output):
    from reconstruction_live_dense import (read_prepared,physical_masks,surface_samples,
        support_samples,native_uv,mask_at,bilinear,project)
    from reconstruction_live_face_domain import observed_face_domain
    run=Path(run).resolve();out=Path(output)
    if out.exists():raise FileExistsError(out)
    config=json.loads((run/'config.json').read_text());prepared=Path(config['prepared']).resolve();data=read_prepared(prepared)
    meta=data['metadata'];manifest_path=Path(config['denseSurfaces']['manifestPath'])
    bundle=json.loads(manifest_path.read_text());reference=bundle['reference']
    if bundle['sourceHash']!=meta['sourceHash']:raise ValueError('boundary_source_changed')
    reference_labels={};source_stats=[];all_regions={};native_sources={};frozen={}
    def labels(name):
        if name not in reference_labels:
            file=prepared/'rectified_observations'/(name+'.npz')
            old=dict(np.load(file,allow_pickle=False));frozen[str(file)]=sha(file)
            reference_labels[name]=original_semantics(prepared,meta,name,data['K'],old)
        return reference_labels[name]
    available=sorted(p.name[:-4] for p in (run/'full-final').glob('*.npz'))
    for name in available:
        classes,certainty,outside,lab=labels(name)
        regions,radius=boundary_regions(classes,lab['face_core']|lab['face_boundary'],outside)
        training_face=observed_face_domain(classes,certainty,outside,lab)
        masks=physical_masks(lab);domain=masks['room']|masks['body']|masks['hair']|training_face|lab['glasses_visible']
        source=cv2.cvtColor(cv2.imread(str(prepared/'rectified_observations'/name)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        native_sources[name]=source;all_regions[name]=regions
        rendered={}
        for stage in ('full-initial','full-final'):
            path=run/stage/(name+'.npz');frozen[str(path)]=sha(path);rendered[stage]=dict(np.load(path,allow_pickle=False))
            np.testing.assert_allclose(rendered[stage]['K'],data['K'],rtol=0,atol=1e-8)
        stats={}
        for label,region in regions.items():
            if not region.any():continue
            values=dict(pixels=int(region.sum()),unsupervisedPixels=int((region&~domain).sum()),
                unknownLegacyPixels=int((region&lab['unknown_or_occluded']).sum()),confidenceMedian=float(np.median(certainty[region])),
                observedRoomPixels=int((region&masks['room']).sum()),observedBodyPixels=int((region&masks['body']).sum()),
                observedHairPixels=int((region&masks['hair']).sum()),observedFacePixels=int((region&training_face).sum()))
            for stage,a in rendered.items():
                values[stage]=dict(alphaMean=float(a['alpha'][region].mean()),alphaBelow01=float((a['alpha'][region]<.1).mean()),
                    alphaBelow08=float((a['alpha'][region]<.8).mean()),qMean=a['q'][region].mean(0).tolist(),
                    fixedRgbL1=float(np.abs(a['rgb'][region]-source[region]).mean()))
            stats[label]=values
        source_stats.append(dict(imageName=name,role=data['roles'][name] if 'roles' in data else next((r['role'] for r in meta.get('observations',[]) if r.get('imageName')==name),'see_prepared'),
            bandRadiusNativePixels=radius,regions=stats))
    # Exact current predicates on original reference depth grids, each group
    # uses its original accepted window and original unique source observations.
    stage_rows=[];maps={}
    manifests={}
    for component in ('room','body','hair'):
        row=bundle['components'][component]
        mp=Path(row['hairDepthManifestPath']) if component=='hair' else Path(bundle['depthManifestPath'])
        manifests[component]=mp
        dm=json.loads(mp.read_text());frozen[str(mp)]=sha(mp)
        group={'room':'world','body':'body-world','hair':'head-local'}[component]
        if component=='hair':accepted=json.loads((mp.parent/'result.json').read_text())['acceptedWindows']
        else:accepted=bundle['acceptedWindows']
        keys={w for g,w in accepted if g==group}
        candidates=[r for r in dm['observations'] if r['group']==group and r['imageName']==reference and r['window'] in keys]
        for row in candidates:
            targets=[];vm={}
            for r in dm['observations']:
                if r['group']!=group or r['window']!=row['window']:continue
                path=mp.parent/r['file'];a=dict(np.load(path,allow_pickle=False))
                if sha(path)!=r['depthHash']:raise ValueError('boundary_cached_depth_changed')
                frozen[str(path)]=r['depthHash'];targets.append((r,a));vm[r['imageName']]=physical_masks(labels(r['imageName'])[3])[component]
            a=next(a for r,a in targets if r['imageName']==reference)
            uv,xyz,basis,scales,derivative=surface_samples(a['depth'],a['K'],a['W2C'])
            native=native_uv(uv,a['nativeToProcessed']);h,w=a['depth'].shape
            z=a['depth'][uv[:,1].astype(int),uv[:,0].astype(int)]
            valid=np.isfinite(z)&(z>0)&np.isfinite(xyz).all(1)
            semantic=mask_at(vm[reference],native);cf=bilinear(a['confidence'],uv)
            finite_cf=np.isfinite(cf)&(cf>0)
            conf=(cf>=np.quantile(a['confidence'],.2)) if component!='room' else np.ones(len(uv),bool)
            # No posterior resampling or new budget: assess every existing grid
            # location, then partition reasons in original implementation order.
            support=np.zeros(len(uv),np.int16);free=support.copy()
            ids=np.flatnonzero(valid&derivative&semantic&finite_cf&conf)
            if len(ids):support[ids],free[ids],_=support_samples(xyz[ids],targets,vm,confidence_gate=component!='room')
            stages=rejection_stages(valid,derivative,semantic&finite_cf,conf,support,free)
            regions=all_regions[reference];summary={}
            for label,region in regions.items():
                region_grid=mask_at(region,native)
                if not region_grid.any():continue
                summary[label]=dict(gridSamples=int(region_grid.sum()),reasons={k:int((v&region_grid).sum()) for k,v in stages.items()})
            selected=dict(np.load(bundle['components'][component]['path'],allow_pickle=False))
            same=(selected['source_image']==reference) if 'source_image' in selected else np.zeros(len(selected['means']),bool)
            if 'source_window' in selected:same&=selected['source_window']==row['window']
            same_uv=selected.get('source_uv',np.empty((0,2)))[same] if 'source_uv' in selected else np.empty((0,2))
            for label,region in regions.items():
                if label in summary:summary[label]['finalInitPointsFromExactSourceGrid']=int(mask_at(region,same_uv).sum()) if len(same_uv) else 0
            stage_rows.append(dict(component=component,sourceImage=reference,window=row['window'],depthGrid=[w,h],
                numberOfDistinctSupportImages=len(set(r['imageName'] for r,a in targets)),regions=summary,
                note='Room final initialization may additionally use corrected auxiliary surfaces; these original-grid counts do not describe all room points.'))
            code=np.zeros(len(uv),np.uint8)
            for i,key in enumerate(stages):code[stages[key]]=i+1
            maps[component]=(native,code,list(stages))
    if any(sha(Path(path))!=wanted for path,wanted in frozen.items()):raise ValueError('boundary_inputs_changed_during_audit')
    report=dict(schema=1,run=str(run),sourceHash=meta['sourceHash'],reference=reference,
        configSha256=sha(run/'config.json'),bundleSha256=sha(manifest_path),sourceObservations=source_stats,
        referenceSampling=stage_rows,inputsSha256=frozen,zeroTraining=True,modelUnchanged=True,
        limitations=['Band is a diagnostic silhouette neighbourhood, never a reconstruction mask.',
            'Argmax semantic pixels at low confidence are observed colour but uncertain ownership.',
            'Saved full-frame alpha/q are actual prior GPU renders; sampling projections are CPU diagnostics.',
            'A missing accepted sample does not prove absent physical geometry; room and body depth remain conditional.',
            'No camera, opacity, scale, mask threshold, budget or asset was modified.'])
    out.mkdir(parents=True)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    source=(native_sources[reference]*255).round().astype(np.uint8);lab=labels(reference)[3]
    classes,certainty,outside,_=labels(reference);regions=all_regions[reference]
    domain=physical_masks(lab);face=observed_face_domain(classes,certainty,outside,lab)
    valid=domain['room']|domain['body']|domain['hair']|face|lab['glasses_visible']
    boundary=regions['person_edge']|regions['person_near']|regions['room_edge']|regions['room_near']
    overlay=source.copy();overlay[boundary&~valid]=(255,60,30);overlay[regions['room_edge']&valid]=(60,210,240)
    cv2.imwrite(str(out/'reference-supervision-boundary.png'),cv2.cvtColor(cv2.addWeighted(source,.5,overlay,.5,0),cv2.COLOR_RGB2BGR))
    palette=np.array([[0,0,0],[0,0,255],[0,140,255],[0,255,255],[255,0,255],[255,120,0],[50,50,255],[50,220,50]],np.uint8)
    for component,(native,code,names) in maps.items():
        image=cv2.cvtColor(source,cv2.COLOR_RGB2BGR)
        for point,value in zip(native,code):
            x,y=np.rint(point).astype(int)
            if 0<=x<image.shape[1] and 0<=y<image.shape[0] and boundary[y,x]:cv2.circle(image,(x,y),2,tuple(map(int,palette[value])),-1)
        cv2.imwrite(str(out/(component+'-sampling-boundary.png')),image)
        np.savez_compressed(out/(component+'-sample-decisions.npz'),native_uv=native,reason=code,reason_names=np.asarray(names))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=audit(a.run,a.output);print(json.dumps({'reference':r['reference'],'sourceObservations':len(r['sourceObservations']),'referenceSampling':r['referenceSampling']},indent=2))
