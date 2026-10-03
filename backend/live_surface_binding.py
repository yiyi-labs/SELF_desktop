"""Measured-image surface handoff for the existing live portrait trainer.

Depth predictions are proposals, not measured ground truth. This adapter only
accepts the explicitly validated training-source bundle. It preserves its
anisotropic covariance instead of replacing it with sparse KNN blob sizes.
"""
from pathlib import Path
import hashlib
import json
import numpy as np
import torch


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_component(path, source_hash, expected_frame, *, conditional_room=False, self_reference_room=False):
    with np.load(path, allow_pickle=False) as archive:
        values = {k: archive[k].copy() for k in archive.files}
    if str(values['source_hash']) != source_hash:
        raise ValueError('dense_component_source_mismatch')
    if str(values['coordinate_frame']) != expected_frame:
        raise ValueError('dense_component_coordinate_mismatch')
    n = len(values['means'])
    for name, shape in (('means',(n,3)), ('scales',(n,3)), ('quats',(n,4)),
                        ('opacity',(n,)), ('sh',(n,4,3))):
        value = values[name]
        if value.shape != shape or not np.isfinite(value).all():
            raise ValueError('dense_component_invalid:'+name)
    if not n or np.any(values['scales'] <= 0):
        raise ValueError('dense_component_empty_or_nonpositive_scale')
    if np.any((values['opacity'] <= 0) | (values['opacity'] >= 1)):
        raise ValueError('dense_component_invalid_opacity')
    if conditional_room:
        required=('evidence_type','static_image_support','colour_support','depth_free')
        if any(k not in values or values[k].shape!=(n,) for k in required):raise ValueError('conditional_room_evidence_missing')
        kind=values['evidence_type']
        conditional=kind=='conditional_shared_surface'
        corrected=kind=='conditional_corrected_reference'
        known=np.isin(kind,['conditional_shared_surface','depth_consistent_shared_surface','original_depth_consistent'])
        valid=np.where(conditional,(values['static_image_support']>=3)&(values['colour_support']>=3)&(values['depth_free']<=1),values['support']>=3)
        if corrected.any():
            if not self_reference_room:raise ValueError('self_depth_explicit_receipt_required')
            if any(k not in values or values[k].shape!=(n,) for k in ('self_reference_free','other_depth_free')):
                raise ValueError('self_depth_votes_missing')
            from live_room_self_reference import eligible_self_correction
            ok=eligible_self_correction(values['support'],values['depth_free'],values['self_reference_free'],values['static_image_support'],values['colour_support'])
            ok &= values['other_depth_free']==values['depth_free']-values['self_reference_free']
            valid[corrected]=ok[corrected];known|=corrected
        if not known.all() or not valid.all():raise ValueError('conditional_room_evidence_invalid')
    elif np.any(values['support'] < 3):
        raise ValueError('dense_component_insufficient_distinct_observations')
    if len(np.unique(values['uid'])) != n:
        raise ValueError('dense_component_duplicate_uid')
    return values


def verify_room_correction(row,meta,data,manifest_path,*,expected_asset_hash=None):
    """Verify the geometric solve, without relabelling its depth as measured."""
    receipt_path=Path(row['surfaceCorrectionReceipt'])
    if not receipt_path.is_absolute():receipt_path=manifest_path.parent/receipt_path
    if file_hash(receipt_path)!=row['surfaceCorrectionReceiptSha256']:raise ValueError('room_correction_receipt_hash')
    proof=json.loads(receipt_path.read_text())
    if proof.get('kind')!='shared-static-track-surface-correction' or proof.get('qualified') is not True:
        raise ValueError('room_correction_unqualified')
    for key in ('sourceSha256','preparedSha256','localGeometrySha256'):
        if proof[key]!=meta[key]:raise ValueError('room_correction_identity:'+key)
    if proof['roomAssetHash']!=(expected_asset_hash or row['sha256']):raise ValueError('room_correction_asset_hash')
    np.testing.assert_allclose(proof['nativeK'],data['K'],rtol=0,atol=1e-6)
    np.testing.assert_allclose(proof['referenceC'],data['worlds'][proof['referenceName']],rtol=0,atol=1e-6)
    for key in ('solverReport','surface'):
        path=Path(proof[key+'Path'])
        if not path.is_absolute():path=receipt_path.parent/path
        if file_hash(path)!=proof[key+'Sha256']:raise ValueError('room_correction_dependency_hash:'+key)
    fit=set(proof['trainTrackIds']);held=set(proof['validationTrackIds'])
    config=proof['config'];v=proof['after']['validation'];before=proof['before']['validation']
    if len(fit)<20 or len(held)<12 or fit&held or not config['oneSharedSurface'] or config['KChanged'] or config['CChanged']:
        raise ValueError('room_correction_geometry_contract')
    if not(v['relativeDepth']['median']<=.03 and v['relativeDepth']['p90']<=.08 and v['reprojectionPx']['p90']<=before['reprojectionPx']['p90']):
        raise ValueError('room_correction_validation_failed')
    if proof['originalDepthThreshold']!=.03 or proof['originalFreeMaximum']!=1:raise ValueError('room_correction_depth_contract_changed')
    return proof


def verify_room_completion(row,meta,data,manifest_path,values):
    """Each auxiliary surface carries its own geometry and exact point source.

    A successful proof for the primary wall cannot silently authorize other
    depth proposals. The original component is retained exactly, including its
    conditional-support fields; extra points must equal their source asset.
    """
    base=row.get('surfaceBaseComponent');extra=row.get('additionalSurfaceReceipts',[])
    if not base:
        if extra:raise ValueError('room_completion_base_missing')
        verify_room_correction(row,meta,data,manifest_path)
        return
    def resolve(value):
        path=Path(value)
        return path if path.is_absolute() else manifest_path.parent/path
    ids=values.get('source_receipt_index')
    if ids is None or ids.shape!=(len(values['means']),) or not np.issubdtype(ids.dtype,np.integer):
        raise ValueError('room_completion_point_proof_index')
    self_items=[item for item in extra if item.get('selfReferenceCorrection')]
    recovery_items=[item for item in extra if 'recoveredWindow' in item and item not in self_items]
    ordinary_items=[item for item in extra if 'recoveredWindow' not in item and item not in self_items]
    if (len(ordinary_items)>2 or len(recovery_items)>2 or len(self_items)>5 or ordinary_items+recovery_items+self_items!=extra
        or [item['index'] for item in extra]!=list(range(1,len(extra)+1))):
        raise ValueError('room_completion_proof_sequence')
    if not np.isin(ids,np.arange(len(extra)+1)).all():raise ValueError('room_completion_unknown_point_proof')
    entries=[(0,base['path'],base['sha256'],base['count'])]
    verify_room_correction(row,meta,data,manifest_path,expected_asset_hash=base['sha256'])
    for item in extra:
        proof_row={'surfaceCorrectionReceipt':item['path'],
                   'surfaceCorrectionReceiptSha256':item['sha256'],'sha256':item['assetSha256']}
        proof=verify_room_correction(proof_row,meta,data,manifest_path)
        if isinstance(proof,dict) and bool(proof.get('selfReferenceCorrection'))!=bool(item.get('selfReferenceCorrection')):
            raise ValueError('self_depth_receipt_type_missing')
        if item.get('selfReferenceCorrection'):
            from live_room_self_reference import verify_self_reference
            with np.load(resolve(item['assetPath']),allow_pickle=False) as asset:verify_self_reference(proof,meta,asset)
        if isinstance(proof,dict) and bool(proof.get('windowRecovery'))!=('recoveredWindow' in item):
            raise ValueError('room_window_recovery_type_missing')
        if 'recoveredWindow' in item:
            from live_room_window_recovery import verify_recovery_proof
            recovery=verify_recovery_proof(proof,meta)
            proposal=json.loads(Path(recovery['proposalPath']).read_text())
            if proposal['window']!=item['recoveredWindow']:raise ValueError('room_window_recovery_window_identity')
            local=json.loads(Path(recovery['overlapPath']).read_text())
            if local['kind']=='recovered-room-unrepresented-observation':
                with np.load(local['pointEvidencePath'],allow_pickle=False) as evidence:
                    allowed=set(map(int,evidence['uid'][evidence['kept']]))
                with np.load(resolve(item['assetPath']),allow_pickle=False) as asset:
                    if not set(map(int,asset['uid']))<=allowed:raise ValueError('room_window_recovery_asset_not_eligible')
        entries.append((item['index'],item['assetPath'],item['assetSha256'],item['count']))
    for index,filename,expected,count in entries:
        path=resolve(filename)
        if file_hash(path)!=expected:raise ValueError('room_completion_source_asset_hash')
        original=load_component(path,data['sourceHash'],'world',conditional_room=True,self_reference_room=index in {i['index'] for i in self_items})
        selected=np.flatnonzero(ids==index)
        if len(selected)!=count or len(original['means'])!=count:
            raise ValueError('room_completion_source_count')
        for key,value in original.items():
            if key=='source_receipt_index':continue
            if value.ndim and len(value)==count:
                if key not in values or not np.array_equal(values[key][selected],value):
                    raise ValueError('room_completion_source_parameters_changed:'+key)
    if len(np.unique(values['uid']))!=len(values['uid']):raise ValueError('room_completion_duplicate_uid')
    if self_items:
        if sum(item['count'] for item in self_items)>6000:raise ValueError('self_depth_total_budget')
        references=[json.loads(resolve(item['path']).read_text())['referenceName'] for item in self_items]
        if len(set(references))!=len(references):raise ValueError('self_depth_duplicate_source_surface')


def replace_hair_prior(prior, hair):
    """Retain the exact face prefix; replace only explicitly supported hair."""
    result = {k:np.array(v,copy=True) for k,v in prior.items()}
    s = len(prior['surface_ids']); old_n = len(prior['role']); n = len(hair['means'])
    if not np.array_equal(np.flatnonzero(prior['role'] != 2), np.arange(s)):
        raise ValueError('surface_prefix_contract_invalid')
    additions = {
        'role':np.full(n,2,dtype=prior['role'].dtype),
        'local_offsets':np.zeros((n,3),np.float32),
        'log_scales':np.log(hair['scales']), 'local_quats':hair['quats'],
        'opacity_logits':np.log(hair['opacity']/(1-hair['opacity'])),
        'sh_coeff':hair['sh'], 'source_index':hair['uid'].astype(np.int64),
        'origin_index':np.arange(s,s+n,dtype=np.int64),
        'source_confidence':hair['confidence'].astype(np.float32)}
    if 'base_rgb_logits' in prior:
        rgb=np.clip(hair['sh'][:,0]*.28209479177387814+.5,1e-5,1-1e-5)
        additions['base_rgb_logits']=np.log(rgb/(1-rgb))
    if 'sh1' in prior:additions['sh1']=hair['sh'][:,1:].copy()
    for key, value in additions.items():
        if len(prior[key]) != old_n:
            raise ValueError('portrait_point_field_length:'+key)
        result[key] = np.concatenate((prior[key][:s],value),axis=0)
    result['hair_local_points'] = hair['means'].astype(np.float32)
    for key in ('surface_ids','surface_bary'):
        if not np.array_equal(result[key],prior[key]):raise AssertionError('face_binding_changed')
    return result


def environment_from_components(components, device):
    """Room and body share one rasterization; their evidence stays distinct."""
    if not components:raise ValueError('no_dense_environment_components')
    chunks=[];sources={'kind':[], 'id':[]};layers=[]
    for name, value in components.items():
        if name not in ('room','body'):raise ValueError('unknown_environment_part')
        n=len(value['means']);part=0 if name=='room' else 4
        chunks.append({
            'means':value['means'], 'scales':np.log(value['scales']),
            'quats':value['quats'],
            'opacities':np.log(value['opacity']/(1-value['opacity'])),
            'sh':value['sh'], 'part':np.full((n,1),part,np.int64)})
        sources['kind'].append(np.full(n,20 if name=='room' else 21,np.int16))
        sources['id'].append(value['uid'].astype(np.int64))
        layers.append(value.get('layer',np.full(n,'room' if part==0 else 'cloth')))
    result={key:torch.as_tensor(np.concatenate([v[key] for v in chunks]),device=device,
               dtype=torch.long if key=='part' else torch.float32) for key in chunks[0]}
    return result,{key:np.concatenate(value) for key,value in sources.items()},np.concatenate(layers)


def load_surface_bundle(path, data):
    path=Path(path);meta=json.loads(path.read_text())
    if meta['sourceSha256']!=data['sourceHash']:raise ValueError('dense_bundle_source_mismatch')
    if meta.get('schemaVersion')!=1:raise ValueError('dense_bundle_schema')
    if not np.isclose(meta['headToWorldScale'],data['scale'],rtol=1e-7,atol=0):
        raise ValueError('dense_bundle_scene_scale_mismatch')
    np.testing.assert_allclose(meta['K'],data['K'],rtol=0,atol=1e-6)
    for key,filename in (('preparedSha256','preparation.json'),('localGeometrySha256','local_geometry.npz')):
        if meta[key]!=file_hash(Path(data['prepared'])/filename):raise ValueError('dense_bundle_geometry_changed:'+filename)
    components={}
    for name,row in meta['components'].items():
        if name not in ('room','body','hair') or row.get('count',0)==0:continue
        file=Path(row['path'])
        if not file.is_absolute():file=path.parent/file
        if file_hash(file)!=row['sha256']:raise ValueError('dense_component_hash_changed:'+name)
        conditional=bool(row.get('typedSupport'))
        if conditional:
            if name!='room':raise ValueError('conditional_evidence_only_room')
        self_reference=conditional and any(r.get('selfReferenceCorrection') for r in row.get('additionalSurfaceReceipts',[]))
        components[name]=load_component(file,data['sourceHash'],'head-local' if name=='hair' else 'world',conditional_room=conditional,self_reference_room=self_reference)
        if name=='hair' and data.get('hair_motion') is not None:
            from live_hair_motion import verify_motion_receipt
            verify_motion_receipt(row.get('hairMotion'),data['hair_motion'])
            if row['referenceName']!=data['reference']:raise ValueError('hair_reference_state_mismatch')
            if row.get('hairDepthManifestPath'):
                depth_path=Path(row['hairDepthManifestPath'])
                if file_hash(depth_path)!=row['hairDepthManifestHash']:raise ValueError('hair_depth_manifest_changed')
                depth=json.loads(depth_path.read_text())
                verify_motion_receipt(depth.get('hairMotion'),data['hair_motion'])
        if conditional:verify_room_completion(row,meta,data,path,components[name])
        allowed=set(data['train'] if name!='hair' else [n for n,r in data['local'].items() if r['role']=='train'])
        if not set(row['trainNames'])<=allowed:raise ValueError('dense_component_uses_evaluation_view')
    if 'body' in components and meta['components']['body']['referenceName']!=data['reference']:
        raise ValueError('body_reference_state_mismatch')
    return meta,components
