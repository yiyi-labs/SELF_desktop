"""Bounded recovery of anchored room windows rejected before surface correction.

The original window rejection is never rewritten. Fixed camera geometry and
independent held-out tracks can authorize a correction attempt, not acceptance.
Accepted surfaces additionally need conservative mutual room-surface checks.
No point is moved, deleted, enlarged or made opaque in the parent bundle.
"""
import json
import shutil
from pathlib import Path

import cv2
import numpy as np

from live_dense_contract import digest, write_json, bilinear, project, unproject


def make_window_proposal(parent_path, reference, window, output):
    parent_path=Path(parent_path).resolve()
    parent=json.loads(parent_path.read_text())
    root=Path(parent['depthManifestPath']).parent
    manifest=json.loads((root/'depth-manifest.json').read_text())
    original=json.loads((root/'result.json').read_text())
    rows=[r for r in manifest['observations'] if r['group']=='world' and r['window']==window]
    if ('world',window) in {tuple(x) for x in original['acceptedWindows']}:
        raise ValueError('recovery_window_was_not_rejected')
    if not rows or reference not in {r['imageName'] for r in rows} or not all(r.get('scaleGatePassed') is True for r in rows):
        raise ValueError('recovery_window_missing_or_scale_invalid')
    conflicts=[r for r in original['windowComparisons'] if r['group']=='world' and window in r['windows'] and not r['accepted']]
    if not conflicts:
        raise ValueError('recovery_original_rejection_evidence_missing')
    receipt=dict(schemaVersion=1,kind='rejected-fixed-camera-window-proposal',
        parentManifestPath=str(parent_path),parentManifestSha256=digest(parent_path),
        sourceSha256=parent['sourceSha256'],preparedSha256=parent['preparedSha256'],localGeometrySha256=parent['localGeometrySha256'],
        depthManifestPath=str(root/'depth-manifest.json'),depthManifestSha256=digest(root/'depth-manifest.json'),
        originalDecisionPath=str(root/'result.json'),originalDecisionSha256=digest(root/'result.json'),
        reference=reference,window=window,rows=rows,originalConflicts=conflicts,
        acceptedWindowsUnchanged=original['acceptedWindows'],permitsSolveOnly=True)
    write_json(output,receipt)
    return receipt


def verify_window_proposal(path,data,dense,reference,window):
    """An explicit rejected-window attempt cannot silently relax the old gate."""
    from live_dense import training_name_scopes
    path=Path(path).resolve()
    p=json.loads(path.read_text())
    dense=Path(dense).resolve()
    if p.get('kind')!='rejected-fixed-camera-window-proposal' or p.get('permitsSolveOnly') is not True:
        raise ValueError('recovery_proposal_kind')
    if p['reference']!=reference or p['window']!=window:
        raise ValueError('recovery_proposal_selection')
    for key,actual in (('depthManifest',dense/'depth-manifest.json'),('originalDecision',dense/'result.json')):
        if Path(p[key+'Path']).resolve()!=actual or digest(actual)!=p[key+'Sha256']:
            raise ValueError('recovery_proposal_changed:'+key)
    parent=Path(p['parentManifestPath'])
    if digest(parent)!=p['parentManifestSha256']:
        raise ValueError('recovery_proposal_parent_changed')
    original=json.loads((dense/'result.json').read_text())
    manifest=json.loads((dense/'depth-manifest.json').read_text())
    if original['acceptedWindows']!=p['acceptedWindowsUnchanged'] or ['world',window] in original['acceptedWindows']:
        raise ValueError('recovery_original_decision_changed')
    if manifest['sourceHash']!=p['sourceSha256']:
        raise ValueError('recovery_source_changed')
    for filename,key in (('preparation.json','preparedSha256'),('local_geometry.npz','localGeometrySha256')):
        if digest(data['prepared']/filename)!=p[key]:
            raise ValueError('recovery_prepared_changed:'+filename)
    request=json.loads((dense/'request.json').read_text())
    scope=training_name_scopes(data,request.get('splitPath'),expected_split_hash=request.get('splitHash'))
    rows=[r for r in manifest['observations'] if r['group']=='world' and r['window']==window]
    if rows!=p['rows'] or not rows:
        raise ValueError('recovery_proposal_rows_changed')
    if reference not in {r['imageName'] for r in rows}:
        raise ValueError('recovery_reference_missing')
    for row in rows:
        n=row['imageName']
        f=dense/row['file']
        if not row.get('scaleGatePassed') or n not in scope['geometryTrain'] or n not in data['world']:
            raise ValueError('recovery_observation_not_fixed_train')
        if row.get('role')!='train' or row.get('sourceHash')!=p['sourceSha256']:
            raise ValueError('recovery_row_identity')
        if digest(data['prepared']/'rectified_observations'/n)!=row['imageHash']:
            raise ValueError('recovery_source_image_changed')
        if digest(f)!=row['depthHash']:
            raise ValueError('recovery_raw_depth_changed')
        a=dict(np.load(f,allow_pickle=False))
        if str(a['sourceHash'])!=p['sourceSha256'] or str(a['imageName'])!=n:
            raise ValueError('recovery_depth_identity')
        np.testing.assert_allclose(a['W2C'],data['world'][n],atol=1e-7,rtol=0)
        np.testing.assert_allclose(a['K'],a['nativeToProcessed']@data['K'],atol=1e-6,rtol=0)
    return dict(path=str(path),sha256=digest(path),window=window,reference=reference,
                originalRejected=True,permitsSolveOnly=True,cameraChanged=False,sourceSha256=p['sourceSha256'])


def depth_agreement(relative,*,minimum=128):
    """Same original window tolerances; insufficient overlap is unverified."""
    a=np.asarray(relative,float)
    a=a[np.isfinite(a)]
    med=float(np.median(a)) if len(a) else None
    p90=float(np.quantile(a,.9)) if len(a) else None
    return dict(count=len(a),medianRelative=med,p90Relative=p90,
        qualified=bool(len(a)>=minimum and med<=.04 and p90<=.10),minimum=minimum)


def surface_pair_overlap(a,b,mask_a,mask_b):
    """All mutual source-room rays, before any residual-based filtering.

    Room masks do not establish visibility. Occluded surfaces may therefore
    conservatively fail this gate; none is relabelled measured or empty.
    """
    from live_dense import mask_at,native_uv
    output=[]
    for source,target,sm,tm in ((a,b,mask_a,mask_b),(b,a,mask_b,mask_a)):
        depth=source['referenceDepthAfter']
        h,w=depth.shape
        y,x=np.mgrid[2:h-2:4,2:w-2:4]
        uv=np.c_[x.ravel(),y.ravel()].astype(float)
        z=bilinear(depth,uv)
        keep=np.isfinite(z)&(z>0)&mask_at(sm,native_uv(uv,source['nativeToProcessed']))
        uv=uv[keep]
        z=z[keep]
        world=unproject(uv,z,source['K'],source['W2C'])
        q,zz=project(world,target['K'],target['W2C'])
        other=bilinear(target['referenceDepthAfter'],q)
        valid=np.isfinite(other)&(other>0)&(zz>0)&mask_at(tm,native_uv(q,target['nativeToProcessed']))
        error=np.abs(zz[valid]/other[valid]-1)
        result=depth_agreement(error)
        result.update(sourceRoomSamples=len(uv),mutualRoomSamples=int(valid.sum()),
            nearerThanOther3pct=int((zz[valid]<other[valid]*.97).sum()),
            fartherThanOther3pct=int((zz[valid]>other[valid]*1.03).sum()))
        output.append(result)
    return dict(directions=output,qualified=all(r['qualified'] for r in output),
                visibilityBoundary='mutual semantic room is a conservative surface hypothesis, not visibility truth')


def check_surface_overlap(solved,parent_path,output,extra_proofs=()):
    from live_dense import read_prepared,physical_masks
    from live_room_completion import _domains
    solved=Path(solved)
    parent=json.loads(Path(parent_path).read_text())
    root=Path(parent['depthManifestPath']).parent
    request=json.loads((root/'request.json').read_text())
    data=read_prepared(request['prepared'])
    report=json.loads((solved/'report.json').read_text())
    a=dict(np.load(solved/'shared-surface.npz',allow_pickle=False))
    row=parent['components']['room']
    paths=[row['surfaceCorrectionReceipt'],*[i['path'] for i in row.get('additionalSurfaceReceipts',[])],*extra_proofs]
    proofs=[json.loads(Path(p).read_text()) for p in paths]
    names=sorted({report['reference'],*[p['referenceName'] for p in proofs]})
    context=_domains(data,names)
    masks={n:physical_masks(context['labels'][n])['room'] for n in names}
    pairs=[]
    aids={t['pointId'] for t in report['tracks']}
    for path,p in zip(paths,proofs):
        if digest(p['surfacePath'])!=p['surfaceSha256']:
            raise ValueError('recovery_existing_surface_changed')
        if digest(p['solverReportPath'])!=p['solverReportSha256']:
            raise ValueError('recovery_existing_report_changed')
        old=json.loads(Path(p['solverReportPath']).read_text())
        b=dict(np.load(p['surfacePath'],allow_pickle=False))
        shared=aids&{t['pointId'] for t in old['tracks']}
        pair=surface_pair_overlap(a,b,masks[report['reference']],masks[p['referenceName']])
        # A semantic overlap disconnected from real common static tracks is
        # not promoted into an independently validated surface connection.
        linked=len(shared)>=6 and all(d['count']>=128 for d in pair['directions'])
        pairs.append(dict(reference=p['referenceName'],receiptPath=str(path),receiptSha256=digest(path),
            sharedTrackIds=sorted(shared),linked=linked,**pair))
    linked=[p for p in pairs if p['linked']]
    accepted=bool(linked and all(p['qualified'] for p in linked))
    result=dict(kind='recovered-room-mutual-surface-overlap',qualified=accepted,
        sourceSha256=parent['sourceSha256'],reference=report['reference'],window=report['window'],
        surfacePath=str(solved/'shared-surface.npz'),surfaceSha256=digest(solved/'shared-surface.npz'),
        minimumCommonTracks=6,minimumMutualSamples=128,medianMaximum=.04,p90Maximum=.10,
        pairs=pairs,linkedPairs=len(linked),
        reason=None if accepted else ('no_independent_common_surface_connection' if not linked else 'mutual_corrected_surface_disagreement'),
        camerasChanged=False,unknownIsVisible=False,residualFiltering=False)
    write_json(output,result)
    return result


def verify_recovery_proof(proof,meta):
    recovery=proof.get('windowRecovery')
    if not recovery:
        raise ValueError('room_window_recovery_proof_missing')
    for key in ('proposal','overlap'):
        if digest(recovery[key+'Path'])!=recovery[key+'Sha256']:
            raise ValueError('room_window_recovery_dependency:'+key)
    proposal=json.loads(Path(recovery['proposalPath']).read_text())
    overlap=json.loads(Path(recovery['overlapPath']).read_text())
    if proposal['kind']!='rejected-fixed-camera-window-proposal' or proposal['permitsSolveOnly'] is not True:
        raise ValueError('room_window_recovery_proposal_kind')
    for key in ('sourceSha256','preparedSha256','localGeometrySha256'):
        if proposal[key]!=meta[key]:
            raise ValueError('room_window_recovery_identity:'+key)
    if overlap['sourceSha256']!=meta['sourceSha256']:
        raise ValueError('room_window_recovery_overlap_source')
    for key in ('depthManifest','originalDecision','parentManifest'):
        if digest(proposal[key+'Path'])!=proposal[key+'Sha256']:
            raise ValueError('room_window_recovery_original_changed:'+key)
    original=json.loads(Path(proposal['originalDecisionPath']).read_text())
    if original['acceptedWindows']!=proposal['acceptedWindowsUnchanged'] or ['world',proposal['window']] in original['acceptedWindows']:
        raise ValueError('room_window_recovery_original_decision')
    report=json.loads(Path(proof['solverReportPath']).read_text())
    if report.get('windowRecoveryProposal',{}).get('sha256')!=recovery['proposalSha256']:
        raise ValueError('room_window_recovery_solver_proposal')
    if proposal['reference']!=proof['referenceName'] or overlap['reference']!=proof['referenceName'] or proposal['window']!=overlap['window']:
        raise ValueError('room_window_recovery_reference')
    if overlap['surfaceSha256']!=proof['surfaceSha256'] or not overlap['qualified']:
        raise ValueError('room_window_recovery_overlap_not_qualified')
    if overlap['kind']=='recovered-room-unrepresented-observation':
        if (overlap['minimumDistinctDepthSupport'],overlap['maximumFree'],overlap['oldMaximumSingleAlpha'],overlap['oldMaximumTotalAlpha'])!=(3,1,1/255,.01):
            raise ValueError('room_window_recovery_local_thresholds')
        allow_conditional=overlap.get('allowTypedConditional',False)
        if (not overlap.get('allKeptOriginalSupport',overlap['allKeptStrictDepth']) or
            (not allow_conditional and not overlap['allKeptStrictDepth']) or
            not overlap['allKeptOutsideOldFootprints'] or overlap['kept']<=0):
            raise ValueError('room_window_recovery_local_evidence')
        if digest(overlap['pointEvidencePath'])!=overlap['pointEvidenceSha256']:
            raise ValueError('room_window_recovery_local_evidence_changed')
        if digest(overlap['parentRoomPath'])!=overlap['parentRoomSha256']:
            raise ValueError('room_window_recovery_parent_room_changed')
        evidence=dict(np.load(overlap['pointEvidencePath'],allow_pickle=False))
        kept=evidence['kept']
        original_support=evidence['depth_support']>=3
        if allow_conditional:
            for key in ('static_image_support','colour_support','evidence_type'):
                if key not in evidence:
                    raise ValueError('room_window_recovery_conditional_evidence_missing')
            conditional=(evidence['static_image_support']>=3)&(evidence['colour_support']>=3)&(evidence['evidence_type']=='conditional_shared_surface')
            original_support|=conditional
        if (int(kept.sum())!=overlap['kept'] or not np.all(original_support[kept])
            or not np.all(evidence['free'][kept]<=1) or not np.all(evidence['old_peak_alpha'][kept]<1/255)
            or not np.all(evidence['old_total_alpha'][kept]<.01)):
            raise ValueError('room_window_recovery_local_point_contract')
        # The actual asset is verified by the binding caller; this evidence
        # maps the eligible source UID set without requiring a fixed layout.
        if len(np.unique(evidence['uid']))!=len(evidence['uid']):
            raise ValueError('room_window_recovery_duplicate_evidence_uid')
        return recovery
    if (overlap['minimumCommonTracks'],overlap['minimumMutualSamples'],overlap['medianMaximum'],overlap['p90Maximum'])!=(6,128,.04,.10):
        raise ValueError('room_window_recovery_overlap_thresholds')
    linked=[p for p in overlap['pairs'] if p['linked']]
    if not linked:
        raise ValueError('room_window_recovery_no_connected_surface')
    for pair in linked:
        if len(set(pair['sharedTrackIds']))<6 or not pair['qualified']:
            raise ValueError('room_window_recovery_pair_failed')
        for d in pair['directions']:
            if d['count']<128 or d['medianRelative']>.04 or d['p90Relative']>.10:
                raise ValueError('room_window_recovery_pair_threshold')
        if digest(pair['receiptPath'])!=pair['receiptSha256']:
            raise ValueError('room_window_recovery_prior_changed')
    return recovery


def projected_room_footprints(values,K,C,size):
    """Native-canvas covariance footprint proxy, with no tiny viewport cull.

    The union alpha does not depend on sort order. This does not reproduce
    renderer tile limits or its RGB; it conservatively retains all 3-sigma
    kernels including centres outside the canvas and a one-pixel guard.
    """
    from scipy.spatial.transform import Rotation
    width,height=map(int,size)
    peak=np.zeros((height,width),np.float32)
    log_t=np.zeros_like(peak)
    xyz=values['means']@C[:3,:3].T+C[:3,3]
    uv,z=project(values['means'],K,C)
    rotations=Rotation.from_quat(values['quats'][:,[1,2,3,0]]).as_matrix()
    covariance=(rotations*values['scales'][:,None,:]**2)@rotations.transpose(0,2,1)
    covariance=C[:3,:3][None]@covariance@C[:3,:3].T[None]
    count=0
    for i in np.flatnonzero((z>0)&np.isfinite(uv).all(1)):
        x,y,depth=xyz[i]
        j=np.array([[K[0,0]/depth,0,-K[0,0]*x/depth**2],[0,K[1,1]/depth,-K[1,1]*y/depth**2]])
        cov=j@covariance[i]@j.T+np.eye(2)*.3
        radius=3*np.sqrt(np.diag(cov))+1
        lo=np.maximum(0,np.floor(uv[i]-radius).astype(int))
        hi=np.minimum([width-1,height-1],np.ceil(uv[i]+radius).astype(int))
        if np.any(lo>hi):
            continue
        yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        d=np.stack((xx-uv[i,0],yy-uv[i,1]),-1)
        inv=np.linalg.inv(cov)
        power=np.einsum('...i,ij,...j->...',d,inv,d)
        alpha=np.where(power<=9,np.minimum(.99,values['opacity'][i]*np.exp(-.5*power)),0).astype(np.float32)
        alpha[alpha<1/255]=0
        dest=(slice(lo[1],hi[1]+1),slice(lo[0],hi[0]+1))
        peak[dest]=np.maximum(peak[dest],alpha)
        log_t[dest]+=np.log1p(-alpha)
        count+=1
    return dict(peak=cv2.dilate(peak,np.ones((3,3),np.uint8)),
        alpha=cv2.dilate(-np.expm1(log_t),np.ones((3,3),np.uint8)),projectedKernels=count)


def original_candidate_support(fresh,allow_typed_conditional=False):
    strict=(fresh['support']>=3)&(fresh['depth_free']<=1)
    conditional=(fresh['support']<3)&(fresh['static_image_support']>=3)&(fresh['colour_support']>=3)&(fresh['depth_free']<=1)
    conditional&=fresh['evidence_type']=='conditional_shared_surface'
    return strict,strict|(conditional if allow_typed_conditional else False)


def filter_unrepresented_observations(fresh,solved,parent_path,output,*,allow_typed_conditional=False):
    """Add supported points outside the parent's effective native footprint.

    Conflicting/covered rays are withheld. A room semantic label alone cannot
    establish that another surface is visible or authorize a double layer.
    The optional conditional class preserves the pre-existing >=3 static RGB
    corroborations, original free-space rule and honest non-measurement label.
    """
    from live_dense import read_prepared
    from scipy.spatial import cKDTree
    solved=Path(solved)
    out=Path(output)
    out.mkdir(parents=True,exist_ok=False)
    parent=json.loads(Path(parent_path).read_text())
    root=Path(parent['depthManifestPath']).parent
    request=json.loads((root/'request.json').read_text())
    data=read_prepared(request['prepared'])
    report=json.loads((solved/'report.json').read_text())
    reference=report['reference']
    shape=cv2.imread(str(data['prepared']/'rectified_observations'/reference)).shape
    old=dict(np.load(parent['components']['room']['path'],allow_pickle=False))
    maps=projected_room_footprints(old,data['K'],data['world'][reference],(shape[1],shape[0]))
    peak=bilinear(maps['peak'],fresh['source_uv'])
    alpha=bilinear(maps['alpha'],fresh['source_uv'])
    outside=np.isfinite(peak)&np.isfinite(alpha)&(peak<1/255)&(alpha<.01)
    strict,supported=original_candidate_support(fresh,allow_typed_conditional)
    keep=outside&supported
    dist,index=cKDTree(old['means']).query(fresh['means'])
    evidence=out/'point-evidence.npz'
    np.savez_compressed(evidence,uid=fresh['uid'],source_uv=fresh['source_uv'],means=fresh['means'],
        depth_support=fresh['support'],free=fresh['depth_free'],old_peak_alpha=peak,old_total_alpha=alpha,
        static_image_support=fresh['static_image_support'],colour_support=fresh['colour_support'],evidence_type=fresh['evidence_type'],
        outside_old_effective_footprint=outside,strict_depth=strict,kept=keep,
        nearest_old_uid=old['uid'][index],nearest_old_distance=dist,
        nearest_old_normalized_tangent_distance=dist/np.max(old['scales'][index,:2],axis=1))
    result=dict(kind='recovered-room-unrepresented-observation',qualified=bool(keep.any()),
        sourceSha256=parent['sourceSha256'],reference=reference,window=report['window'],
        surfacePath=str(solved/'shared-surface.npz'),surfaceSha256=digest(solved/'shared-surface.npz'),
        parentRoomPath=parent['components']['room']['path'],parentRoomSha256=parent['components']['room']['sha256'],
        total=len(keep),strictDepth=int(strict.sum()),outsideOldFootprints=int(outside.sum()),kept=int(keep.sum()),
        withheldCovered=int((~outside).sum()),outsideInsufficientStrictDepth=int((outside&~strict).sum()),
        withheldInsufficientOriginalSupport=int((outside&~supported).sum()),
        minimumDistinctDepthSupport=3,maximumFree=1,oldMaximumSingleAlpha=1/255,oldMaximumTotalAlpha=.01,
        allKeptStrictDepth=bool(strict[keep].all()),allKeptOutsideOldFootprints=bool(outside[keep].all()),
        allowTypedConditional=bool(allow_typed_conditional),allKeptOriginalSupport=bool(supported[keep].all()),
        keptStrict=int((keep&strict).sum()),keptConditional=int((keep&~strict).sum()),
        pointEvidencePath=str(evidence),pointEvidenceSha256=digest(evidence),
        nativeCanvas=[shape[1],shape[0]],projectedKernels=maps['projectedKernels'],
        unknownIsVisible=False,existingPointParametersChanged=False,
        limitations='Analytic native footprint proxy, not rendered RGB or measured visibility; predicted depth remains conditional.')
    write_json(out/'report.json',result)
    return {k:v[keep] for k,v in fresh.items()}


def replay_local_recovery(parent_bundle,failed_recovery,output,*,budget=30000,allow_typed_conditional=False):
    """Reuse only accepted solves; no second solve or new reference search."""
    from live_shared_room_surface import export_shared_room_initialization,SharedRoomEvidenceUnavailable
    parent_path=Path(parent_bundle).resolve()
    parent=json.loads(parent_path.read_text())
    failed=Path(failed_recovery).resolve()
    previous=json.loads((failed/'result.json').read_text())
    if previous['parentManifestPath']!=str(parent_path) or previous['parentManifestHash']!=digest(parent_path):
        raise ValueError('recovery_replay_parent')
    eligible=[row for row in previous['roomWindowRecovery']['outcomes'] if row['status']=='mutual_surface_validation_failed']
    if len(eligible)!=1 or not(0<budget<=30000):
        raise ValueError('recovery_replay_requires_one_qualified_solve')
    chosen=eligible[0]
    oldfolder=Path(chosen['overlapPath']).parent
    report=json.loads((oldfolder/'solve/report.json').read_text())
    if not report['accepted']:
        raise ValueError('recovery_replay_solve_unqualified')
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'algorithm-source'
    snapshot.mkdir()
    for name in (Path(__file__).name,'live_room_completion.py','live_shared_room_surface.py','live_surface_binding.py','live_dense.py'):
        shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    # Immutable original solver and rejection records remain referenced; this
    # candidate owns only its local filter, addition, and composite manifest.
    added=None
    try:
        added=export_shared_room_initialization(oldfolder/'solve',parent_path,out/'addition',budget=budget,
            completion_reference=parent['reference'],candidate_filter=lambda fresh:filter_unrepresented_observations(fresh,oldfolder/'solve',parent_path,out/'local-filter',allow_typed_conditional=allow_typed_conditional))
    except SharedRoomEvidenceUnavailable as error:
        reason=str(error)
    final={**parent,'manifestPath':str(out/'result.json'),'parentManifestPath':str(parent_path),'parentManifestHash':digest(parent_path),'published':False}
    if added:
        proof=json.loads(Path(added['path']).read_text())
        proposal=oldfolder/'window-proposal.json'
        overlap=out/'local-filter/report.json'
        proof['windowRecovery']=dict(proposalPath=str(proposal),proposalSha256=digest(proposal),overlapPath=str(overlap),overlapSha256=digest(overlap))
        write_json(added['path'],proof)
        added.update(sha256=digest(added['path']),recoveredWindow=chosen['window'])
        write_json(out/'addition/addition-result.json',added)
        row=parent['components']['room']
        old=dict(np.load(row['path'],allow_pickle=False))
        extra=dict(np.load(added['assetPath'],allow_pickle=False))
        n=len(old['means'])
        fields={k:np.concatenate((v,extra[k])) for k,v in old.items() if v.ndim and len(v)==n}
        if 'source_receipt_index' not in fields:
            fields['source_receipt_index']=np.r_[np.zeros(n,np.int16),extra['source_receipt_index']]
        for k,v in old.items():
            if k in fields and not np.array_equal(v,fields[k][:n]):
                raise AssertionError('recovery_replay_parent_changed:'+k)
        asset=out/'room-surface.npz'
        np.savez_compressed(asset,**fields,source_hash=np.asarray(parent['sourceSha256']),coordinate_frame=np.asarray('world'),referenceName=np.asarray(parent['reference']))
        final['components']={**parent['components'],'room':{**row,'path':str(asset),'sha256':digest(asset),'count':len(fields['means']),
            'additionalSurfaceReceipts':row.get('additionalSurfaceReceipts',[])+[added],
            'surfaceBaseComponent':row.get('surfaceBaseComponent',dict(path=row['path'],sha256=row['sha256'],count=n)),
            'trainNames':sorted(set(row['trainNames'])|set(added['trainNames'])),'originalPrefixBitwiseUnchanged':True}}
    final['roomWindowRecovery']=dict(status='conditional_local_surface_added' if added else 'original_bundle_retained',
        reason=None if added else reason,solverInvoked=False,selectionInvoked=False,sourceRecoveryPath=str(failed/'result.json'),
        sourceRecoverySha256=digest(failed/'result.json'),addedCount=added['count'] if added else 0,
        originalPrefixBitwiseUnchanged=True,localFilterPath=str(out/'local-filter/report.json'),visualQualityPassed=False)
    write_json(out/'result.json',final)
    return final


def recover_static_window_surfaces(parent_bundle,output,*,max_surfaces=2,max_evaluations=40,extra_budget=30000,local_unrepresented_fallback=True,allow_typed_conditional=False):
    from live_dense import read_prepared
    from live_room_completion import select_completion_references
    from live_shared_room_surface import run_shared_surface,export_shared_room_initialization,SharedRoomEvidenceUnavailable
    if any(type(v) is not int for v in (max_surfaces,max_evaluations,extra_budget)) or not(0<max_surfaces<=2 and 0<max_evaluations<=40 and 0<extra_budget<=30000):
        raise ValueError('room_window_recovery_budget')
    parent_path=Path(parent_bundle).resolve()
    parent=json.loads(parent_path.read_text())
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    if parent.get('roomWindowRecovery'):
        raise ValueError('room_window_recovery_already_attempted')
    for row in parent['components'].values():
        if digest(row['path'])!=row['sha256']:
            raise ValueError('room_window_recovery_parent_asset_changed')
    if digest(parent['depthManifestPath'])!=parent['depthManifestHash']:
        raise ValueError('room_window_recovery_depth_changed')
    snapshot=out/'algorithm-source'
    snapshot.mkdir()
    for name in (Path(__file__).name,'live_room_completion.py','live_shared_room_surface.py','live_surface_binding.py','live_dense.py'):
        shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    row=parent['components']['room']
    proof_path=row.get('surfaceCorrectionReceipt')
    qualified_base=False
    if proof_path:
        if digest(proof_path)!=row['surfaceCorrectionReceiptSha256']:
            raise ValueError('room_window_recovery_base_receipt_changed')
        proof=json.loads(Path(proof_path).read_text())
        qualified_base=proof.get('qualified') is True
    if not qualified_base:
        # A legitimate shared-surface fallback has no validated surface with
        # which to check a proposed addition. Keep the actual input instead of
        # assuming a proof exists or treating an unanchored depth map as one.
        final={**parent,'manifestPath':str(out/'result.json'),
            'parentManifestPath':str(parent_path),'parentManifestHash':digest(parent_path),'published':False}
        final['roomWindowRecovery']=dict(status='original_bundle_retained',reason='no_qualified_base_surface',
            originalCount=int(row['count']),addedCount=0,originalPrefixBitwiseUnchanged=True,
            outcomes=[],maxSurfaces=max_surfaces,extraBudget=extra_budget,
            acceptedWindowsUnchanged=parent['acceptedWindows'],visualQualityPassed=False,
            selectionInvoked=False,solverInvoked=False,inference=False,training=False)
        write_json(out/'result.json',final)
        return final
    root=Path(parent['depthManifestPath']).parent
    request=json.loads((root/'request.json').read_text())
    data=read_prepared(request['prepared'])
    selection=select_completion_references(parent_path,max_references=max_surfaces,rejected_windows_only=True)
    write_json(out/'selection.json',selection)
    additions=[]
    outcomes=[]
    for number,candidate in enumerate(selection['selected']):
        folder=out/f'recovery-{number+1}'
        folder.mkdir()
        proposal=folder/'window-proposal.json'
        make_window_proposal(parent_path,candidate['reference'],candidate['window'],proposal)
        budget=(extra_budget-sum(a['count'] for a in additions))//(len(selection['selected'])-number)
        try:
            report=run_shared_surface(request['prepared'],root,folder/'solve',window=candidate['window'],reference=candidate['reference'],
                max_evaluations=max_evaluations,proposed_window_receipt=proposal)
            if not report['accepted']:
                outcomes.append({**candidate,'status':'independent_validation_failed','reportPath':str(folder/'solve/report.json')})
                continue
            overlap=check_surface_overlap(folder/'solve',parent_path,folder/'overlap.json',[a['path'] for a in additions])
            if not overlap['qualified'] and not local_unrepresented_fallback:
                outcomes.append({**candidate,'status':'mutual_surface_validation_failed','overlapPath':str(folder/'overlap.json')})
                continue
            candidate_filter=None
            overlap_path=folder/'overlap.json'
            if not overlap['qualified']:
                # Preserve the failed broad comparison. Recover only strict
                # multiview samples with no effective parent room footprint;
                # covered or conflicting local rays remain withheld.
                candidate_filter=lambda fresh:filter_unrepresented_observations(fresh,folder/'solve',parent_path,folder/'local-filter',allow_typed_conditional=allow_typed_conditional)
                overlap_path=folder/'local-filter/report.json'
            added=export_shared_room_initialization(folder/'solve',parent_path,folder/'addition',budget=budget,
                completion_reference=parent['reference'],existing_additions=[a['assetPath'] for a in additions],candidate_filter=candidate_filter)
            proof=json.loads(Path(added['path']).read_text())
            proof['windowRecovery']=dict(proposalPath=str(proposal),proposalSha256=digest(proposal),
                overlapPath=str(overlap_path),overlapSha256=digest(overlap_path))
            write_json(added['path'],proof)
            added['sha256']=digest(added['path'])
            added['recoveredWindow']=candidate['window']
            write_json(folder/'addition/addition-result.json',added)
            additions.append(added)
            outcomes.append({**candidate,'status':'conditional_surface_added','count':added['count']})
        except SharedRoomEvidenceUnavailable as error:
            outcomes.append({**candidate,'status':'evidence_unavailable','reason':str(error)})
    row=parent['components']['room']
    base=dict(np.load(row['path'],allow_pickle=False))
    n=len(base['means'])
    final={**parent,'manifestPath':str(out/'result.json'),'parentManifestPath':str(parent_path),'parentManifestHash':digest(parent_path),'published':False}
    if additions:
        perpoint={k:v for k,v in base.items() if v.ndim and len(v)==n}
        if 'source_receipt_index' not in perpoint:
            perpoint['source_receipt_index']=np.zeros(n,np.int16)
        for added in additions:
            values=dict(np.load(added['assetPath'],allow_pickle=False))
            if any(k not in values for k in perpoint):
                raise ValueError('room_window_recovery_field_missing')
            perpoint={k:np.concatenate((v,values[k])) for k,v in perpoint.items()}
        for k,v in base.items():
            if v.ndim and len(v)==n and not np.array_equal(perpoint[k][:n],v):
                raise AssertionError('room_window_recovery_changed_parent:'+k)
        if len(np.unique(perpoint['uid']))!=len(perpoint['uid']):
            raise ValueError('room_window_recovery_duplicate_uid')
        asset=out/'room-surface.npz'
        np.savez_compressed(asset,**perpoint,source_hash=np.asarray(parent['sourceSha256']),coordinate_frame=np.asarray('world'),referenceName=np.asarray(parent['reference']))
        newrow={**row,'path':str(asset),'sha256':digest(asset),'count':len(perpoint['means']),
            'surfaceBaseComponent':row.get('surfaceBaseComponent',dict(path=row['path'],sha256=row['sha256'],count=n)),
            'additionalSurfaceReceipts':row.get('additionalSurfaceReceipts',[])+additions,
            'trainNames':sorted(set(row['trainNames']).union(*(a['trainNames'] for a in additions))),
            'originalPrefixBitwiseUnchanged':True}
        final['components']={**parent['components'],'room':newrow}
    final['roomWindowRecovery']=dict(status='conditional_surfaces_added' if additions else 'original_bundle_retained',outcomes=outcomes,
        originalCount=n,addedCount=sum(a['count'] for a in additions),originalPrefixBitwiseUnchanged=True,
        maxSurfaces=max_surfaces,extraBudget=extra_budget,selectionPath=str(out/'selection.json'),selectionSha256=digest(out/'selection.json'),
        acceptedWindowsUnchanged=parent['acceptedWindows'],visualQualityPassed=False,inference=False,training=False,
        uncertainty='Depth remains a conditional surface hypothesis; no unseen background is generated.')
    write_json(out/'result.json',final)
    from live_room_retry import complete_room_recovery
    return complete_room_recovery(final,out,max_evaluations=max_evaluations,max_surfaces=max_surfaces,
        extra_budget=extra_budget,allow_typed_conditional=allow_typed_conditional)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parent_bundle',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    result=recover_static_window_surfaces(args.parent_bundle,args.output)
    print(json.dumps({'manifestPath':result['manifestPath'],'roomWindowRecovery':result['roomWindowRecovery']},indent=2))
