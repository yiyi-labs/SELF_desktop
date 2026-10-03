"""Bounded research replay of a corrected surface's obsolete self-depth vote.

This is deliberately not called by the automatic live route. Other observations
and the original raw vote ledger are retained, not relabelled as measured depth.
"""
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

from live_dense_contract import digest,write_json

KIND='conditional_corrected_reference'
AUTHORIZED_POLICY='corrected_reference_negative_evidence'


def apply_self_reference_correction(parent_bundle,output,*,authorized_policy=None,budget=6000):
    """Optional live adapter; callers must explicitly authorize this policy.

    Undeclared/unqualified surface evidence preserves the existing component.
    A declared proof or qualified dependency that is missing/changed is an
    input-contract failure. A saved attempt is idempotent, including a failure.
    """
    pp=Path(parent_bundle).resolve()
    parent=json.loads(pp.read_text())
    if authorized_policy is None:
        return {**parent,'manifestPath':str(pp)}
    if authorized_policy!=AUTHORIZED_POLICY:
        raise ValueError('self_depth_policy_not_authorized')
    if type(budget) is not int or not 0<budget<=6000:
        raise ValueError('self_depth_budget')
    if parent.get('roomSelfReferenceCorrection'):
        return {**parent,'manifestPath':str(pp)}
    # The live bundle contract uses absolute dependencies. Fail rather than
    # reinterpreting a historic relative path in a new job directory.
    def inspect(value,expected,label):
        p=Path(value)
        if not p.is_absolute():
            raise ValueError('self_depth_absolute_dependency_required:'+label)
        if not p.is_file():
            return False
        if digest(p)!=expected:
            raise ValueError('self_depth_present_dependency_changed:'+label)
        return True
    for name,row in parent['components'].items():
        if row.get('count',0) and not inspect(row['path'],row['sha256'],name):
            raise ValueError('self_depth_existing_component_missing:'+name)
    row=parent['components'].get('room',{})
    reason=None
    if not row.get('typedSupport') or not row.get('surfaceCorrectionReceipt'):
        reason='no_qualified_base_surface'
    else:
        items=[(row['surfaceCorrectionReceipt'],row['surfaceCorrectionReceiptSha256'])]
        items += [(r['path'],r['sha256']) for r in row.get('additionalSurfaceReceipts',[])]
        if len(items)>5:
            raise ValueError('self_depth_surface_limit')
        # A declared proof is part of the immutable asset, not optional data.
        for path,expected in items:
            if not inspect(path,expected,'surface_proof'):
                raise ValueError('self_depth_declared_proof_missing')
            proof=json.loads(Path(path).read_text())
            if proof.get('kind')!='shared-static-track-surface-correction' or proof.get('qualified') is not True:
                reason=reason or 'no_qualified_surface'
                continue
            for key in ('sourceSha256','preparedSha256','localGeometrySha256'):
                if proof.get(key)!=parent.get(key):
                    raise ValueError('self_depth_present_proof_identity:'+key)
            for key in ('solverReport','surface'):
                if not inspect(proof[key+'Path'],proof[key+'Sha256'],key):
                    raise ValueError('self_depth_qualified_dependency_missing:'+key)
        if not parent.get('depthManifestPath'):
            if reason is None:
                raise ValueError('self_depth_qualified_depth_manifest_missing')
        elif not inspect(parent['depthManifestPath'],parent['depthManifestHash'],'depth_manifest'):
            raise ValueError('self_depth_qualified_depth_manifest_missing')
    if reason is None:
        result=build_self_reference_candidate(pp,output,budget=budget)
        result['roomSelfReferenceCorrection'].update(authorizedPolicy=authorized_policy,
            invokedByLivePolicy=True,automaticDefault=True)
        write_json(result['manifestPath'],result)
        return result
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    final={**parent,'manifestPath':str(out/'result.json'),'parentManifestPath':str(pp),'parentManifestHash':digest(pp),
        'roomSelfReferenceCorrection':dict(status='original_bundle_retained',reason=reason,addedCount=0,
            authorizedPolicy=authorized_policy,cameraChanged=False,training=False,geometricVisibilityConfirmed=False,
            independentSupportVotesAdded=0,invokedByLivePolicy=True,automaticDefault=True)}
    write_json(out/'result.json',final)
    return final


def eligible_self_correction(support,free,self_free,image_support,colour_support):
    """Remove no independent vote; require the old rejection to be self-decisive."""
    other=free-self_free
    return ((free>1)&(self_free==1)&(other>=0)&(other<=1)
        &(image_support>=3)&(colour_support>=3))


def verify_self_reference(proof,meta,asset):
    receipt=proof.get('selfReferenceCorrection')
    if not receipt or receipt.get('kind')!='corrected-source-depth-vote-replay':
        raise ValueError('self_depth_receipt_kind')
    if receipt.get('originalDepthThreshold')!=.03 or receipt.get('otherFreeMaximum')!=1:
        raise ValueError('self_depth_threshold_changed')
    if receipt.get('supportVotesAdded')!=0 or receipt.get('rawFreePreserved') is not True:
        raise ValueError('self_depth_votes_relabelled')
    files={}
    for key in ('originalProof','parentManifest','parentRoom','depthManifest','pointEvidence'):
        path=Path(receipt[key+'Path'])
        if digest(path)!=receipt[key+'Sha256']:
            raise ValueError('self_depth_dependency_hash:'+key)
        files[key]=path
    original=json.loads(files['originalProof'].read_text())
    if original.get('selfReferenceCorrection') or not original.get('qualified'):
        raise ValueError('self_depth_recursive_or_unqualified')
    for key in ('sourceSha256','preparedSha256','localGeometrySha256','surfaceSha256','solverReportSha256','referenceName','referenceC','nativeK'):
        if original[key]!=proof[key]:
            raise ValueError('self_depth_original_surface_changed:'+key)
    parent=json.loads(files['parentManifest'].read_text())
    if parent['sourceSha256']!=meta['sourceSha256'] or parent['components']['room']['sha256']!=digest(files['parentRoom']):
        raise ValueError('self_depth_parent_identity')
    originals=[parent['components']['room']['surfaceCorrectionReceiptSha256']]+[r['sha256'] for r in parent['components']['room'].get('additionalSurfaceReceipts',[])]
    if digest(files['originalProof']) not in originals:
        raise ValueError('self_depth_source_not_in_parent')
    dm=json.loads(files['depthManifest'].read_text())
    if dm['sourceHash']!=meta['sourceSha256'] or digest(files['depthManifest'])!=parent['depthManifestHash']:
        raise ValueError('self_depth_manifest_identity')
    e=dict(np.load(files['pointEvidence'],allow_pickle=False))
    names=e['depth_names'].tolist()
    colours=e['colour_names'].tolist()
    if len(names)!=len(set(names)) or len(colours)!=len(set(colours)):
        raise ValueError('self_depth_duplicate_observation')
    if names.count(proof['referenceName'])!=1 or colours.count(proof['referenceName'])!=1:
        raise ValueError('self_depth_reference_observation')
    allowed={r['imageName'] for r in dm['observations'] if r['group']=='world' and r['window']==int(e['window'])}
    if set(names)!=allowed or not set(colours)<=set(parent['components']['room']['trainNames']):
        raise ValueError('self_depth_training_observation')
    if any(not np.isin(e[k],[0,1]).all() for k in ('support_by_view','free_by_view','static_by_view','colour_by_view')):
        raise ValueError('self_depth_nonbinary_evidence')
    if np.any(e['support_by_view']&e['free_by_view']):
        raise ValueError('self_depth_inconsistent_evidence')
    support=e['support_by_view'].sum(1)
    free=e['free_by_view'].sum(1)
    sf=e['free_by_view'][:,names.index(proof['referenceName'])]
    ims=e['static_by_view'].sum(1)
    cs=e['colour_by_view'].sum(1)
    passed=eligible_self_correction(support,free,sf,ims,cs)
    passed&=(e['old_peak_alpha']<1/255)&(e['old_total_alpha']<.01)
    if not passed.all():
        raise ValueError('self_depth_point_not_eligible')
    if len(np.unique(e['uid']))!=len(e['uid']):
        raise ValueError('self_depth_duplicate_evidence_uid')
    lookup={int(v):i for i,v in enumerate(e['uid'])}
    if not set(map(int,asset['uid']))<=set(lookup):
        raise ValueError('self_depth_asset_not_in_evidence')
    sel=np.array([lookup[int(v)] for v in asset['uid']])
    expected=dict(support=support,depth_free=free,self_reference_free=sf,other_depth_free=free-sf,
        static_image_support=ims,colour_support=cs,means=e['means'],source_original_index=e['source_original_index'])
    for key,value in expected.items():
        if not np.array_equal(asset[key],value[sel]):
            raise ValueError('self_depth_asset_evidence_changed:'+key)
    if not np.all(asset['evidence_type']==KIND):
        raise ValueError('self_depth_not_conditional')
    if not np.all(asset['source_image']==proof['referenceName']):
        raise ValueError('self_depth_source_changed')
    return receipt


def retain_self_reference_dependencies(proof,proof_identity,keep,*,prefix,source_hash):
    """Explicit proof leaves only; never recursively copy capture images/video."""
    r=proof.get('selfReferenceCorrection')
    if not r:
        return
    if r.get('kind')!='corrected-source-depth-vote-replay':
        raise ValueError('self_depth_recovery_kind')
    original=None
    identity=None
    for key in ('originalProof','parentManifest','parentRoom','depthManifest','pointEvidence'):
        path,ident=keep(prefix+'selfReference.'+key,r[key+'Path'],r[key+'Sha256'],proof_identity)
        if key=='originalProof':
            original=json.loads(path.read_text())
            identity=ident
        if key in ('parentManifest','depthManifest'):
            meta=json.loads(path.read_text())
            if meta.get('sourceSha256',meta.get('sourceHash'))!=source_hash:
                raise ValueError('self_depth_recovery_source')
    if original.get('selfReferenceCorrection') or original.get('sourceSha256')!=source_hash or not original.get('qualified'):
        raise ValueError('self_depth_recovery_original')
    from surface_recovery import _window_proof_closure
    _window_proof_closure(original,identity,keep,prefix=prefix+'selfReference.original.',source_hash=source_hash)


def build_self_reference_candidate(parent_bundle,output,*,budget=6000):
    """One finite replay, same already-qualified surfaces, no solve/inference."""
    import cv2
    from scipy.spatial import cKDTree
    from scipy.spatial.transform import Rotation
    from live_dense import read_prepared,physical_masks,mask_at,native_uv,surface_samples,support_samples,training_name_scopes,select_budget,C0
    from live_dense_contract import bilinear,project
    from live_room_completion import _domains,deduplicate_new_surface
    from live_room_window_recovery import projected_room_footprints
    from live_surface_binding import verify_room_correction
    if type(budget) is not int or not 0<budget<=6000:
        raise ValueError('self_depth_budget')
    pp=Path(parent_bundle).resolve()
    parent=json.loads(pp.read_text())
    row=parent['components']['room']
    if parent.get('roomSelfReferenceCorrection'):
        raise ValueError('self_depth_already_attempted')
    for c in parent['components'].values():
        if digest(c['path'])!=c['sha256']:
            raise ValueError('self_depth_parent_asset_changed')
    root=Path(parent['depthManifestPath']).parent
    if digest(parent['depthManifestPath'])!=parent['depthManifestHash']:
        raise ValueError('self_depth_depth_changed')
    request=json.loads((root/'request.json').read_text())
    data=read_prepared(request['prepared'])
    for key,name in (('preparedSha256','preparation.json'),('localGeometrySha256','local_geometry.npz')):
        if digest(data['prepared']/name)!=parent[key]:
            raise ValueError('self_depth_prepared_changed')
    scope=training_name_scopes(data,request.get('splitPath'),expected_split_hash=request.get('splitHash'))
    trains=[n for n in scope['geometryTrain'] if n in data['world']]
    if not set(trains)<=set(row['trainNames']):
        raise ValueError('self_depth_parent_train_scope')
    masks={n:physical_masks(_domains(data,[n])['labels'][n])['room'] for n in trains}
    dm=json.loads((root/'depth-manifest.json').read_text())
    paths=[(row['surfaceCorrectionReceipt'],row['surfaceCorrectionReceiptSha256'],row.get('surfaceBaseComponent',row)['sha256'])]
    paths += [(r['path'],r['sha256'],r['assetSha256']) for r in row.get('additionalSurfaceReceipts',[])]
    if len(paths)>5:
        raise ValueError('self_depth_surface_limit')
    out=Path(output).resolve()
    out.mkdir(parents=True,exist_ok=False)
    snap=out/'algorithm-source'
    snap.mkdir()
    for name in (Path(__file__).name,'live_surface_binding.py','surface_recovery.py','live_dense.py'):
        shutil.copyfile(Path(__file__).with_name(name),snap/name)
    old=dict(np.load(row['path'],allow_pickle=False))
    n=len(old['means'])
    extras=[]
    items=[]
    summaries=[]
    checkdata=dict(K=data['K'],worlds=data['world'])
    for ordinal,(path,ph,ah) in enumerate(paths):
        if sum(len(x['means']) for x in extras)>=budget:
            break
        proof=verify_room_correction(dict(surfaceCorrectionReceipt=path,surfaceCorrectionReceiptSha256=ph,sha256=ah),parent,checkdata,pp)
        solved=json.loads(Path(proof['solverReportPath']).read_text())
        surface=dict(np.load(proof['surfacePath'],allow_pickle=False))
        reference=proof['referenceName']
        window=solved['window']
        if reference not in trains:
            raise ValueError('self_depth_reference_not_training')
        np.testing.assert_allclose(surface['W2C'],data['world'][reference],rtol=0,atol=1e-7)
        np.testing.assert_allclose(surface['K'],surface['nativeToProcessed']@data['K'],rtol=0,atol=1e-6)
        uv,xyz,basis,scales,geom=surface_samples(surface['referenceDepthAfter'],surface['K'],surface['W2C'])
        native=native_uv(uv,surface['nativeToProcessed'])
        valid=geom&mask_at(masks[reference],native)
        rgb=cv2.cvtColor(cv2.imread(str(data['prepared']/'rectified_observations'/reference)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        colour=bilinear(rgb,native)
        valid&=np.isfinite(colour).all(1)
        indices=np.flatnonzero(valid)
        xyz=xyz[indices]
        native=native[indices]
        colour=colour[indices]
        targets=[(r,dict(np.load(root/r['file'],allow_pickle=False))) for r in dm['observations'] if r['group']=='world' and r['window']==window]
        names=[r['imageName'] for r,a in targets]
        if len(set(names))!=len(names) or names.count(reference)!=1:
            raise ValueError('self_depth_target_identity')
        ledger=[support_samples(xyz,[t],masks,confidence_gate=False) for t in targets]
        sup=np.stack([a[0] for a in ledger],1)
        free=np.stack([a[1] for a in ledger],1)
        occ=np.stack([a[2] for a in ledger],1)
        st=[]
        co=[]
        for name in trains:
            q,z=project(xyz,data['K'],data['world'][name])
            static=(z>0)&mask_at(masks[name],q)
            im=cv2.cvtColor(cv2.imread(str(data['prepared']/'rectified_observations'/name)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
            c=bilinear(cv2.GaussianBlur(im,(3,3),0),q)
            st.append(static)
            co.append(static&np.isfinite(c).all(1)&(np.mean(np.abs(c-colour),1)<=.12))
        st=np.stack(st,1)
        co=np.stack(co,1)
        votes=sup.sum(1).astype(np.int16)
        rawfree=free.sum(1).astype(np.int16)
        sf=free[:,names.index(reference)]
        keep=eligible_self_correction(votes,rawfree,sf,st.sum(1),co.sum(1))
        fp=projected_room_footprints(old,data['K'],data['world'][reference],[rgb.shape[1],rgb.shape[0]])
        peak=bilinear(fp['peak'],native)
        alpha=bilinear(fp['alpha'],native)
        outside=(peak<1/255)&(alpha<.01)
        selected=np.flatnonzero(keep&outside)
        summary=dict(reference=reference,window=window,originalRoomCandidates=len(indices),selfDecisive=int(keep.sum()),outsideOldFootprint=int((keep&outside).sum()))
        summaries.append(summary)
        if not len(selected):
            continue
        sh=np.zeros((len(selected),4,3),np.float32)
        sh[:,0]=(colour[selected]-.5)/C0
        trainuv=np.array([t['referenceProcessedUV'] for t in solved['tracks'] if t['role']=='fit'])
        distance=cKDTree(trainuv).query(uv[indices[selected]])[0]
        conf=np.clip(.15+.65*np.exp(-distance/24),.15,.8)
        ids=indices[selected]
        uid=np.array([int.from_bytes(hashlib.sha256(f'SHARED:{parent["sourceSha256"]}:{proof["surfaceSha256"]}:{int(i)}'.encode()).digest()[:8],'little')&((1<<63)-1) for i in ids],np.int64)
        fresh=dict(means=xyz[selected],scales=scales[ids],quats=Rotation.from_matrix(basis[ids]).as_quat()[:,[3,0,1,2]],
            opacity=np.full(len(ids),.6),sh=sh,normal=basis[ids,:,2],parts=np.zeros(len(ids),np.int16),uid=uid,layer=np.full(len(ids),'room'),
            source_image=np.full(len(ids),reference),source_uv=native[selected],source_window=np.full(len(ids),window,np.int16),
            support=votes[selected],confidence=conf,raw_confidence=np.ones(len(ids)),weighted_support=votes[selected]*conf,
            static_image_support=st[selected].sum(1).astype(np.int16),colour_support=co[selected].sum(1).astype(np.int16),
            depth_free=rawfree[selected],depth_occluded=occ[selected].sum(1).astype(np.int16),self_reference_free=sf[selected],other_depth_free=rawfree[selected]-sf[selected],
            evidence_type=np.full(len(ids),KIND),anchor_distance_processed_px=distance,correction_type=np.full(len(ids),'shared_world_inverse_depth'),source_original_index=ids.astype(np.int64))
        unique=deduplicate_new_surface(fresh,[old,*extras])
        sub=np.flatnonzero(unique)
        fresh={k:v[sub] for k,v in fresh.items()}
        selected=selected[sub]
        if not len(selected):
            continue
        chosen=select_budget(fresh,budget-sum(len(x['means']) for x in extras))
        fresh={k:v[chosen] for k,v in fresh.items()}
        selected=selected[chosen]
        index=len(row.get('additionalSurfaceReceipts',[]))+len(items)+1
        fresh['source_receipt_index']=np.full(len(selected),index,np.int16)
        folder=out/('surface-'+str(ordinal))
        folder.mkdir()
        asset=folder/'addition.npz'
        np.savez_compressed(asset,**fresh,source_hash=np.asarray(parent['sourceSha256']),coordinate_frame=np.asarray('world'),referenceName=np.asarray(reference))
        ep=folder/'point-evidence.npz'
        np.savez_compressed(ep,uid=fresh['uid'],means=fresh['means'],source_original_index=fresh['source_original_index'],
            depth_names=np.asarray(names),colour_names=np.asarray(trains),window=np.asarray(window),support_by_view=sup[selected],free_by_view=free[selected],
            static_by_view=st[selected],colour_by_view=co[selected],old_peak_alpha=peak[selected],old_total_alpha=alpha[selected])
        exception=dict(kind='corrected-source-depth-vote-replay',originalDepthThreshold=.03,otherFreeMaximum=1,supportVotesAdded=0,rawFreePreserved=True,
            originalProofPath=str(Path(path).resolve()),originalProofSha256=ph,parentManifestPath=str(pp),parentManifestSha256=digest(pp),
            parentRoomPath=row['path'],parentRoomSha256=row['sha256'],depthManifestPath=parent['depthManifestPath'],depthManifestSha256=parent['depthManifestHash'],
            pointEvidencePath=str(ep),pointEvidenceSha256=digest(ep),sourceReferenceIsIndependentSupport=False)
        newproof={k:v for k,v in proof.items() if k!='windowRecovery'}
        newproof.update(roomAssetHash=digest(asset),pointCount=len(selected),actualAdded=len(selected),selfReferenceCorrection=exception,
            supportBoundary='Raw votes preserved; only obsolete own-reference negative evidence separated. All points conditional, not measured geometry.')
        pf=folder/'surface-correction-receipt.json'
        write_json(pf,newproof)
        verify_self_reference(newproof,parent,fresh)
        item=dict(index=index,path=str(pf),sha256=digest(pf),assetPath=str(asset),assetSha256=digest(asset),count=len(selected),trainNames=trains,selfReferenceCorrection=True)
        items.append(item)
        extras.append(fresh)
        summary['added']=len(selected)
        write_json(out/'progress.json',summaries)
        print(json.dumps(summary),flush=True)
    final={**parent,'manifestPath':str(out/'result.json'),'parentManifestPath':str(pp),'parentManifestHash':digest(pp),'published':False}
    if extras:
        fields={k:np.concatenate([v,*[a[k] for a in extras]]) for k,v in old.items() if v.ndim and len(v)==n}
        for k in ('self_reference_free','other_depth_free'):
            fields[k]=np.concatenate([np.full(n,-1,np.int16),*[a[k] for a in extras]])
        for k,v in old.items():
            if k in fields and not np.array_equal(v,fields[k][:n]):
                raise AssertionError('self_depth_old_parameter_changed:'+k)
        if len(np.unique(fields['uid']))!=len(fields['uid']):
            raise ValueError('self_depth_duplicate_combined_uid')
        asset=out/'room-surface.npz'
        np.savez_compressed(asset,**fields,source_hash=np.asarray(parent['sourceSha256']),coordinate_frame=np.asarray('world'),referenceName=np.asarray(parent['reference']))
        final['components']={**parent['components'],'room':{**row,'path':str(asset),'sha256':digest(asset),'count':len(fields['means']),
            'additionalSurfaceReceipts':row.get('additionalSurfaceReceipts',[])+items,'originalPrefixBitwiseUnchanged':True}}
    final['roomSelfReferenceCorrection']=dict(status='conditional_candidates_added' if extras else 'original_bundle_retained',
        addedCount=sum(len(a['means']) for a in extras),surfaces=summaries,budget=budget,cameraChanged=False,training=False,automaticDefault=False,
        geometricVisibilityConfirmed=False,independentSupportVotesAdded=0)
    write_json(out/'result.json',final)
    return final
