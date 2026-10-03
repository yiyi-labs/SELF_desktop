"""Bounded multi-reference observed-room completion, in the same world gauge.

Only originally visible room pixels can propose missing surfaces, including
areas outside the main reference or behind its person silhouette. Occluded
pixels are unknown, never empty space.
No inferred plane, source RGB generation, camera change or global blur is used.
"""
import hashlib
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

from reconstruction_live_dense import (read_prepared,resolve_path,physical_masks,
    mask_at,native_uv,surface_samples,select_budget,training_name_scopes,static_track_names)
from reconstruction_live_dense_contract import digest,write_json,project,bilinear
from reconstruction_observation_domains import attach_observation_domains


def _domains(data,names):
    labels={n:dict(np.load(data['prepared']/'rectified_observations'/(n+'.npz'),allow_pickle=False)) for n in names}
    context=dict(labels=labels,K=data['K'],staticMap=str(resolve_path(data['metadata']['staticMap'],data['prepared'])))
    attach_observation_domains(context,data['prepared'])
    return context


def _reference_prediction(primary,root,parent):
    proof_path=parent['components']['room'].get('surfaceCorrectionReceipt')
    if proof_path:
        proof=json.loads(Path(proof_path).read_text())
        if proof['referenceName']==primary:
            a=dict(np.load(proof['surfacePath'],allow_pickle=False))
            return dict(depth=a['referenceDepthBefore'],K=a['K'],W2C=a['W2C'],nativeToProcessed=a['nativeToProcessed'])
    manifest=json.loads((Path(root)/'depth-manifest.json').read_text())
    accepted={tuple(k) for k in parent['acceptedWindows']}
    rows=[r for r in manifest['observations'] if r['group']=='world' and r['imageName']==primary and ('world',r['window']) in accepted]
    if not rows:raise ValueError('room_completion_primary_depth_missing')
    return dict(np.load(Path(root)/min(rows,key=lambda r:r['window'])['file'],allow_pickle=False))


def person_mask(labels):
    return labels['face_core']|labels['face_boundary']|labels['hair_visible']|labels['glasses_visible']|physical_masks(labels)['body']


def reference_occluded_region(xyz,labels,data,primary,root,parent,reference_prediction=None):
    """A selection hypothesis, not a claim of measured person/room visibility."""
    ref=reference_prediction or _reference_prediction(primary,root,parent)
    uv,z=project(xyz,ref['K'],ref['W2C']);depth=bilinear(ref['depth'],uv)
    person=mask_at(person_mask(labels),native_uv(uv,ref['nativeToProcessed']))
    return person&np.isfinite(depth)&(depth>0)&(z>1.03*depth)


def deduplicate_new_surface(fresh,existing):
    """Discard only collocated compatible new samples; never alter old points."""
    keep=np.ones(len(fresh['means']),bool)
    if not len(keep):return keep
    for old in existing:
        if not len(old['means']):continue
        distance,index=cKDTree(old['means']).query(fresh['means'])
        tangent=.65*(np.max(fresh['scales'][:,:2],axis=1)+np.max(old['scales'][index,:2],axis=1))
        aligned=np.abs((fresh['normal']*old['normal'][index]).sum(1))>.9
        gap=np.abs(((fresh['means']-old['means'][index])*fresh['normal']).sum(1))
        thickness=.5*(fresh['scales'][:,2]+old['scales'][index,2])
        keep&=~((distance<tangent)&aligned&(gap<thickness))
    return keep


def unrepresented_sample_mask(xyz,basis,scales,valid,existing):
    """Sampling demand covers any observed valid surface, never invalid depth."""
    result=np.zeros(len(xyz),bool)
    ids=np.flatnonzero(valid & np.isfinite(xyz).all(1) & np.isfinite(scales).all(1)
        & np.isfinite(basis).all((1,2)) & (scales>0).all(1))
    if len(ids):
        result[ids]=deduplicate_new_surface(dict(means=xyz[ids],scales=scales[ids],
            normal=basis[ids,:,2]),existing)
    return result


def select_completion_references(parent_bundle,*,max_references=2):
    """Greedy extra observed area, with real track eligibility; no audit RGB."""
    import pycolmap
    from reconstruction_live_shared_room_surface import point_fold,independent_track_observations
    parent=json.loads(Path(parent_bundle).read_text());root=Path(parent['depthManifestPath']).parent
    request=json.loads((root/'request.json').read_text());data=read_prepared(request['prepared'])
    scope=training_name_scopes(data,request.get('splitPath'),expected_split_hash=request.get('splitHash'))
    names=[n for n in scope['geometryTrain'] if n in data['world']]
    context=_domains(data,names);labels=context['labels'];masks={n:physical_masks(labels[n])['room'] for n in names}
    safe={n:cv2.erode(m.astype(np.uint8),np.ones((7,7),np.uint8)).astype(bool) for n,m in masks.items()}
    primary=parent['reference']
    old_room=dict(np.load(parent['components']['room']['path'],allow_pickle=False))
    cell_pitch=max(float(np.median(np.max(old_room['scales'][:,:2],axis=1))),1e-8)
    covered_references=set()
    proof_path=parent['components']['room'].get('surfaceCorrectionReceipt')
    if proof_path:
        proof=json.loads(Path(proof_path).read_text());covered_references.add(proof['referenceName'])
    manifest=json.loads((root/'depth-manifest.json').read_text());accepted={tuple(k) for k in parent['acceptedWindows']}
    rows=[r for r in manifest['observations'] if r['group']=='world' and ('world',r['window']) in accepted and r['imageName']!=primary
          and r['imageName'] not in covered_references and r['imageName'] in names]
    rec=pycolmap.Reconstruction(context['staticMap']);images={im.name:im for im in rec.images.values()};track_counts={};candidates=[]
    tracked=set(static_track_names(names,images,data['world']))
    for n in set(r['imageName'] for r in rows):
        counts={'fit':0,'validation':0}
        if n not in tracked:
            track_counts[n]=counts
            continue
        seen=set()
        for feature in images[n].points2D:
            if not feature.has_point3D():continue
            pid=int(feature.point3D_id)
            if pid in seen:continue
            seen.add(pid)
            p=rec.points3D[feature.point3D_id]
            if p.error>2 or p.track.length()<3:continue
            observations,_=independent_track_observations(rec,p,tracked,data['K'],safe)
            valid=[o['imageName'] for o in observations]
            if len(valid)>=3 and n in valid:counts['validation' if point_fold(int(feature.point3D_id))==0 else 'fit']+=1
        track_counts[n]=counts
    for row in rows:
        n=row['imageName'];a=dict(np.load(root/row['file'],allow_pickle=False))
        uv,xyz,basis,scales,valid=surface_samples(a['depth'],a['K'],a['W2C']);confidence=bilinear(a['confidence'],uv)
        valid&=mask_at(masks[n],native_uv(uv,a['nativeToProcessed']))&np.isfinite(confidence)&(confidence>0)
        valid=unrepresented_sample_mask(xyz,basis,scales,valid,[old_room])
        # A common world-grid measures proposed extra coverage across source
        # views. It is a demand proxy, not measured geometry or visibility.
        # Solving, held-out validation and point legality remain unchanged.
        cells=set(map(tuple,np.floor(xyz[valid]/cell_pitch).astype(np.int64)))
        counts=track_counts[n];eligible=counts['fit']>=20 and counts['validation']>=12 and len(cells)>=64
        candidates.append(dict(reference=n,window=row['window'],observedCandidates=int(valid.sum()),
            newAreaCells=len(cells),trackCounts=counts,eligible=eligible,
            mapTrackEvidence=n in tracked,_cells=cells))
    selected=[];covered=set();used=set()
    for _ in range(min(int(max_references),2)):
        choices=[c for c in candidates if c['eligible'] and c['reference'] not in used]
        if not choices:break
        best=max(choices,key=lambda c:(len(c['_cells']-covered),-c['window']))
        gain=len(best['_cells']-covered)
        if gain<64:break
        covered|=best['_cells'];used.add(best['reference']);selected.append({k:v for k,v in best.items() if k!='_cells'}|{'incrementalAreaCells':gain})
    return dict(primaryReference=primary,alreadyRepresentedSurfaceReferences=sorted(covered_references),selected=selected,candidates=[{k:v for k,v in c.items() if k!='_cells'} for c in candidates],
        sourceSha256=parent['sourceSha256'],selectionUsesOnlyOriginalTrain=True,
        coverageScope='all_observed_room_not_only_reference_person_silhouette',proposalCellPitch=cell_pitch,
        selectionBoundary='Proposed world coverage is a hypothesis; each selected shared surface still requires held-out static-track validation.')


def export_addition(fresh,solved,parent_path,out,budget,data,report,fit_ids,held_ids,existing_additions):
    from reconstruction_live_shared_room_surface import SharedRoomEvidenceUnavailable
    parent=json.loads(Path(parent_path).read_text());old=dict(np.load(parent['components']['room']['path'],allow_pickle=False))
    others=[dict(np.load(p,allow_pickle=False)) for p in existing_additions]
    unique=deduplicate_new_surface(fresh,[old,*others]);before=len(unique)
    fresh={k:v[unique] for k,v in fresh.items()}
    if not len(fresh['means']):raise SharedRoomEvidenceUnavailable('room_completion_no_unique_observed_surface')
    chosen=select_budget(fresh,budget);fresh={k:v[chosen] for k,v in fresh.items()}
    index=len(existing_additions)+1;fresh['source_receipt_index']=np.full(len(chosen),index,np.int16)
    asset=Path(out)/'addition.npz';np.savez_compressed(asset,**fresh,source_hash=np.asarray(parent['sourceSha256']),coordinate_frame=np.asarray('world'),referenceName=np.asarray(report['reference']))
    proof=dict(schemaVersion=1,kind='shared-static-track-surface-correction',qualified=True,
        sourceSha256=parent['sourceSha256'],preparedSha256=parent['preparedSha256'],localGeometrySha256=parent['localGeometrySha256'],
        nativeK=data['K'].tolist(),referenceName=report['reference'],referenceC=data['world'][report['reference']].tolist(),
        solverReportPath=str((Path(solved)/'report.json').resolve()),solverReportSha256=digest(Path(solved)/'report.json'),
        surfacePath=str((Path(solved)/'shared-surface.npz').resolve()),surfaceSha256=digest(Path(solved)/'shared-surface.npz'),
        trainTrackIds=fit_ids,validationTrackIds=held_ids,before=report['before'],after=report['after'],config=report['config'],
        originalDepthThreshold=.03,originalFreeMaximum=1,roomAssetHash=digest(asset),pointCount=len(chosen),
        originalCountUnchanged=len(old['means']),newCandidatesBeforeDedup=before,duplicateCandidates=int((~unique).sum()),
        budget=int(budget),actualAdded=len(chosen),sourceReceiptIndex=index,
        supportBoundary='Strict depth votes unchanged. Conditional surface has >=3 static-mask/real-colour observations; this is not measured visibility.',
        selectionBoundary='Only source-observed room behind the primary person-depth hypothesis; no unobserved pixels filled',
        inference=False,training=False)
    proof_path=Path(out)/'surface-correction-receipt.json';write_json(proof_path,proof)
    result=dict(index=index,path=str(proof_path.resolve()),sha256=digest(proof_path),assetPath=str(asset.resolve()),
        assetSha256=digest(asset),count=len(chosen),trainNames=sorted(set(parent['components']['room']['trainNames'])|{report['reference']}))
    write_json(Path(out)/'addition-result.json',result);return result


def complete_observed_room(parent_bundle,output,*,max_references=2,max_evaluations=40,extra_budget=8000):
    from reconstruction_live_shared_room_surface import run_shared_surface,export_shared_room_initialization,SharedRoomEvidenceUnavailable
    if not(0<extra_budget<=8000) or not(0<max_references<=2) or not(0<max_evaluations<=40):raise ValueError('room_completion_budget_contract')
    parent_path=Path(parent_bundle).resolve();parent=json.loads(parent_path.read_text());out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    if parent['components']['room'].get('additionalSurfaceReceipts'):raise ValueError('room_completion_already_applied')
    for component in parent['components'].values():
        if component.get('path') and digest(component['path'])!=component['sha256']:raise ValueError('room_completion_parent_asset_changed')
    if digest(parent['depthManifestPath'])!=parent['depthManifestHash']:raise ValueError('room_completion_depth_changed')
    row=parent['components']['room']
    if not row.get('typedSupport'):raise ValueError('room_completion_requires_qualified_primary_surface')
    if digest(row['surfaceCorrectionReceipt'])!=row['surfaceCorrectionReceiptSha256']:raise ValueError('room_completion_primary_receipt_changed')
    proof=json.loads(Path(row['surfaceCorrectionReceipt']).read_text())
    if not proof['qualified'] or proof['roomAssetHash']!=row['sha256']:raise ValueError('room_completion_primary_not_qualified')
    snapshot=out/'algorithm-source';snapshot.mkdir()
    for name in ('reconstruction_live_room_completion.py','reconstruction_live_shared_room_surface.py','reconstruction_live_dense.py','reconstruction_live_dense_contract.py'):
        shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    root=Path(parent['depthManifestPath']).parent;request=json.loads((root/'request.json').read_text())
    selection=select_completion_references(parent_path,max_references=max_references);write_json(out/'selection.json',selection)
    additions=[];outcomes=[]
    for number,candidate in enumerate(selection['selected']):
        folder=out/f'auxiliary-{number+1}';folder.mkdir();remaining=extra_budget-sum(a['count'] for a in additions)
        if remaining<=0:break
        # Each independent reference gets at most its balanced share; selecting
        # one never consumes the entire additional budget before the other.
        budget=max(1,remaining//(len(selection['selected'])-number))
        try:
            report=run_shared_surface(request['prepared'],root,folder/'solve',reference=candidate['reference'],
                window=candidate['window'],max_evaluations=max_evaluations)
            if not report['accepted']:
                outcomes.append({**candidate,'status':'validation_failed','reportPath':str(folder/'solve/report.json')});continue
            addition=export_shared_room_initialization(folder/'solve',parent_path,folder/'addition',budget=budget,
                completion_reference=selection['primaryReference'],existing_additions=[a['assetPath'] for a in additions])
            additions.append(addition);outcomes.append({**candidate,'status':'conditional_surface_added','count':addition['count']})
        except SharedRoomEvidenceUnavailable as error:
            outcomes.append({**candidate,'status':'evidence_unavailable','reason':str(error)})
    row=parent['components']['room'];base=dict(np.load(row['path'],allow_pickle=False));n=len(base['means'])
    final={**parent,'manifestPath':str(out/'result.json'),'parentManifestPath':str(parent_path),'parentManifestHash':digest(parent_path),'published':False}
    if additions:
        perpoint={k:v for k,v in base.items() if v.ndim and len(v)==n};perpoint['source_receipt_index']=np.zeros(n,np.int16)
        for addition in additions:
            extra=dict(np.load(addition['assetPath'],allow_pickle=False))
            if any(k not in extra for k in perpoint):raise ValueError('room_completion_point_field_missing')
            perpoint={k:np.concatenate((v,extra[k]),axis=0) for k,v in perpoint.items()}
        for k,v in base.items():
            if k in perpoint and not np.array_equal(perpoint[k][:n],v):raise AssertionError('room_completion_changed_original:'+k)
        if len(np.unique(perpoint['uid']))!=len(perpoint['uid']):raise ValueError('room_completion_duplicate_uid')
        asset=out/'room-surface.npz';np.savez_compressed(asset,**perpoint,source_hash=np.asarray(parent['sourceSha256']),coordinate_frame=np.asarray('world'),referenceName=np.asarray(parent['reference']))
        newrow={**row,'path':str(asset),'sha256':digest(asset),'count':len(perpoint['means']),
            'surfaceBaseComponent':{'path':row['path'],'sha256':row['sha256'],'count':n},'additionalSurfaceReceipts':additions,
            'trainNames':sorted(set(row['trainNames']).union(*(a['trainNames'] for a in additions))),
            'originalPrefixBitwiseUnchanged':True}
        final['components']={**parent['components'],'room':newrow}
    final['roomCompletion']=dict(status='conditional_observed_surfaces_added' if additions else 'original_bundle_retained',
        reason=None if additions else ('no_auxiliary_reference_with_new_observed_area_and_track_support' if not selection['selected'] else 'no_auxiliary_surface_passed_validation_and_support'),
        outcomes=outcomes,selectionPath=str(out/'selection.json'),selectionSha256=digest(out/'selection.json'),
        originalCount=n,addedCount=sum(a['count'] for a in additions),originalPrefixBitwiseUnchanged=True,
        visualQualityPassed=False,geometryIsConditional=True,unobservedBackgroundFilled=False)
    write_json(out/'result.json',final);return final
