"""Retain surface initialization without rewriting its checkpoint identity.

The original manifest is immutable provenance. A separate relocation index
resolves verified local copies after temporary job inputs have been cleaned.
No RGB, video or decoded image is retained by this helper.
"""
from pathlib import Path,PureWindowsPath
import hashlib,json,shutil,os,posixpath,ntpath
import numpy as np


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):
            h.update(block)
    return h.hexdigest()


def _historic_identity(value,parent=None):
    """Lexical old identity, including when verifying on another platform."""
    value=str(value)
    windows=bool(PureWindowsPath(value).drive) or (parent is not None and bool(PureWindowsPath(str(parent)).drive))
    module=ntpath if windows else posixpath
    if not module.isabs(value):
        if parent is None:
            raise ValueError('surface_recovery_absolute_identity_required')
        value=module.join(module.dirname(str(parent)),value)
    return module.normpath(value)


def _window_proof_closure(proof,proof_identity,keep,*,prefix,source_hash,active=None):
    """Walk only the declared verification graph, never arbitrary JSON paths.

    Manifest/depth summaries are retained byte-exact as provenance leaves.
    Their RGB/video/inference-cache paths are intentionally not traversed:
    image-supervised resume still requires original capture/preparation.
    ``keep`` resolves either original files or the relocation index, so the
    identical graph is verified after all old directories disappear.
    """
    recovery=proof.get('windowRecovery')
    if not recovery:
        return
    active=set() if active is None else active
    if proof_identity in active:
        raise ValueError('surface_recovery_proof_cycle')
    active.add(proof_identity)
    def dependency(label,declared,wanted,parent,extension):
        identity=_historic_identity(declared,parent)
        if Path(identity).suffix.lower()!=extension:
            raise ValueError('surface_recovery_window_dependency_type:'+label)
        return keep(prefix+'windowRecovery.'+label,declared,wanted,parent)
    try:
        proposal_file,proposal_identity=dependency('proposal',recovery['proposalPath'],recovery['proposalSha256'],proof_identity,'.json')
        proposal=json.loads(proposal_file.read_text())
        if (proposal.get('kind')!='rejected-fixed-camera-window-proposal' or proposal.get('sourceSha256')!=source_hash
            or proposal.get('permitsSolveOnly') is not True):
            raise ValueError('surface_recovery_window_proposal_identity')
        for key in ('depthManifest','originalDecision','parentManifest'):
            file,_=dependency('proposal.'+key,proposal[key+'Path'],proposal[key+'Sha256'],proposal_identity,'.json')
            metadata=json.loads(file.read_text())
            if metadata.get('sourceSha256',metadata.get('sourceHash'))!=source_hash:
                raise ValueError('surface_recovery_window_metadata_source:'+key)
        overlap_file,overlap_identity=dependency('overlap',recovery['overlapPath'],recovery['overlapSha256'],proof_identity,'.json')
        overlap=json.loads(overlap_file.read_text())
        if overlap.get('sourceSha256')!=source_hash or overlap.get('qualified') is not True:
            raise ValueError('surface_recovery_window_overlap_identity')
        dependency('overlap.surface',overlap['surfacePath'],overlap['surfaceSha256'],overlap_identity,'.npz')
        if overlap['kind']=='recovered-room-unrepresented-observation':
            dependency('overlap.pointEvidence',overlap['pointEvidencePath'],overlap['pointEvidenceSha256'],overlap_identity,'.npz')
            file,_=dependency('overlap.parentRoom',overlap['parentRoomPath'],overlap['parentRoomSha256'],overlap_identity,'.npz')
            with np.load(file,allow_pickle=False) as values:
                if str(values['source_hash'])!=source_hash or str(values['coordinate_frame'])!='world':
                    raise ValueError('surface_recovery_window_parent_room_identity')
        elif overlap['kind']=='recovered-room-mutual-surface-overlap':
            for i,pair in enumerate(overlap['pairs']):
                label='overlap.link'+str(i)+'.'
                linked_file,linked_identity=dependency(label+'receipt',pair['receiptPath'],pair['receiptSha256'],overlap_identity,'.json')
                linked=json.loads(linked_file.read_text())
                if (linked.get('kind')!='shared-static-track-surface-correction' or linked.get('qualified') is not True
                    or linked.get('sourceSha256')!=source_hash):
                    raise ValueError('surface_recovery_linked_proof_identity')
                for key,extension in (('solverReport','.json'),('surface','.npz')):
                    dependency(label+key,linked[key+'Path'],linked[key+'Sha256'],linked_identity,extension)
                _window_proof_closure(linked,linked_identity,keep,prefix=prefix+'windowRecovery.'+label,
                                      source_hash=source_hash,active=active)
        else:
            raise ValueError('surface_recovery_window_overlap_kind')
    finally:
        active.remove(proof_identity)


def _second_reference_provenance(metadata,manifest_identity,keep):
    """Keep the bounded retry decision, not just the successful surface proof."""
    attempt=metadata.get('roomWindowSecondReference')
    if not attempt:
        return
    def dependency(label,declared,wanted,parent):
        if Path(_historic_identity(declared,parent)).suffix.lower()!='.json':
            raise ValueError('surface_recovery_retry_dependency_type')
        return keep('roomSecondReference.'+label,declared,wanted,parent)
    file,identity=dependency('decision',attempt['decisionPath'],attempt['decisionSha256'],manifest_identity)
    decision=json.loads(file.read_text())
    if (decision.get('kind')!='one-second-reference-research' or decision.get('maxAttemptsPerWindow')!=2
        or not 0<decision['maxEvaluations']<=40):
        raise ValueError('surface_recovery_retry_decision_contract')
    for key in ('priorAttempt','selection'):
        file,_=dependency(key,decision[key+'Path'],decision[key+'Sha256'],identity)
        source=json.loads(file.read_text())
        if source.get('sourceSha256')!=metadata['sourceSha256']:
            raise ValueError('surface_recovery_retry_source')


def _proof_dependencies(manifest,metadata):
    result={}
    for name,row in metadata['components'].items():
        if not row.get('typedSupport') or int(row.get('count',0))<=0:
            continue
        if name!='room':
            raise ValueError('surface_recovery_typed_component')
        proofs=[('',row['surfaceCorrectionReceipt'],row['surfaceCorrectionReceiptSha256'],
                 row.get('surfaceBaseComponent',row)['sha256'])]
        assets=[]
        if row.get('surfaceBaseComponent'):
            assets.append(('surfaceBaseComponent',row['surfaceBaseComponent']))
        for item in row.get('additionalSurfaceReceipts',[]):
            prefix='additional'+str(item['index'])+'.'
            proofs.append((prefix,item['path'],item['sha256'],item['assetSha256']))
            assets.append((prefix+'asset',{'path':item['assetPath'],'sha256':item['assetSha256'],'count':item['count']}))
        for label,asset in assets:
            path=_source_component(manifest,'room',asset,metadata['sourceSha256'])
            result[name+'.'+label]=(path,asset['sha256'],str(asset['path']))
        for prefix,declared,expected,asset_hash in proofs:
            path=Path(declared)
            if not path.is_absolute():
                path=manifest.parent/path
            if digest(path)!=expected:
                raise ValueError('surface_recovery_proof_hash')
            proof=json.loads(path.read_text())
            if proof.get('kind')!='shared-static-track-surface-correction' or proof.get('qualified') is not True:
                raise ValueError('surface_recovery_proof_unqualified')
            if proof.get('sourceSha256')!=metadata['sourceSha256'] or proof.get('roomAssetHash')!=asset_hash:
                raise ValueError('surface_recovery_proof_identity')
            result[name+'.'+prefix+'surfaceCorrectionReceipt']=(path,expected,str(declared))
            for key in ('solverReport','surface'):
                dependency=Path(proof[key+'Path'])
                if not dependency.is_absolute():
                    dependency=path.parent/dependency
                wanted=proof[key+'Sha256']
                if digest(dependency)!=wanted:
                    raise ValueError('surface_recovery_dependency_hash:'+key)
                result[name+'.'+prefix+key]=(dependency,wanted,str(proof[key+'Path']))
            def keep(label,declared,wanted,parent):
                identity=_historic_identity(declared,parent)
                dependency=Path(identity)
                if digest(dependency)!=wanted:
                    raise ValueError('surface_recovery_dependency_hash:'+label)
                result[name+'.'+label]=(dependency,wanted,str(declared))
                return dependency,identity
            _window_proof_closure(proof,_historic_identity(os.path.abspath(path)),keep,
                prefix=prefix,source_hash=metadata['sourceSha256'])
            if proof.get('selfReferenceCorrection'):
                from live_room_self_reference import retain_self_reference_dependencies
                retain_self_reference_dependencies(proof,_historic_identity(os.path.abspath(path)),keep,
                    prefix=prefix,source_hash=metadata['sourceSha256'])
    def keep_attempt(label,declared,wanted,parent):
        identity=_historic_identity(declared,parent)
        dependency=Path(identity)
        if digest(dependency)!=wanted:
            raise ValueError('surface_recovery_dependency_hash:'+label)
        result[label]=(dependency,wanted,str(declared))
        return dependency,identity
    _second_reference_provenance(metadata,_historic_identity(os.path.abspath(manifest)),keep_attempt)
    return result


def _source_component(manifest,name,row,source_hash):
    if name not in ('room','body','hair'):
        raise ValueError('surface_recovery_unknown_component')
    path=Path(row['path'])
    if not path.is_absolute():
        path=manifest.parent/path
    if path.suffix.lower()!='.npz' or not path.is_file():
        raise ValueError('surface_recovery_component_missing:'+name)
    if digest(path)!=row.get('sha256'):
        raise ValueError('surface_recovery_component_hash:'+name)
    with np.load(path,allow_pickle=False) as data:
        if str(data['source_hash'])!=source_hash:
            raise ValueError('surface_recovery_component_source:'+name)
        if len(data['means'])!=int(row['count']):
            raise ValueError('surface_recovery_component_count:'+name)
        expected='head-local' if name=='hair' else 'world'
        if str(data['coordinate_frame'])!=expected:
            raise ValueError('surface_recovery_component_coordinates:'+name)
    return path


def _hair_dependencies(manifest,metadata):
    row=metadata['components'].get('hair',{})
    motion=row.get('hairMotion')
    if not motion or not row.get('count'):
        return {}
    result={}
    def keep(label,declared,wanted,parent):
        path=Path(declared)
        if not path.is_absolute():
            path=parent.parent/path
        if digest(path)!=wanted:
            raise ValueError('surface_recovery_hair_dependency_hash:'+label)
        result['hair.'+label]=(path,wanted,str(declared))
        return path
    receipt=keep('motion',motion['path'],motion['sha256'],manifest)
    saved=json.loads(receipt.read_text())
    for key in ('status','sourceHash','checkpointSha256','modelSha256','referenceName','transformSha256'):
        if saved.get(key)!=motion.get(key):
            raise ValueError('surface_recovery_hair_motion_identity:'+key)
    if saved.get('sourceHash') not in (None,metadata['sourceSha256']):
        raise ValueError('surface_recovery_hair_source')
    keep('motionArrays',saved['arrayPath'],saved['arraySha256'],receipt)
    if saved['status']!='explicit_legacy_root_local':
        keep('fitState',saved['fitStatePath'],saved['checkpointSha256'],receipt)
    if row.get('hairDepthManifestPath'):
        depth=keep('depthManifest',row['hairDepthManifestPath'],row['hairDepthManifestHash'],manifest)
        dm=json.loads(depth.read_text())
        if dm.get('sourceHash')!=metadata['sourceSha256'] or dm.get('hairMotion')!=motion:
            raise ValueError('surface_recovery_hair_depth_identity')
    return result


def retain_surface_initialization(manifest,destination,*,expected_manifest_hash,expected_source_hash):
    manifest=Path(manifest)
    destination=Path(destination)
    raw=manifest.read_bytes()
    actual=hashlib.sha256(raw).hexdigest()
    if actual!=expected_manifest_hash:
        raise ValueError('surface_recovery_checkpoint_manifest_mismatch')
    metadata=json.loads(raw)
    if metadata.get('sourceSha256')!=expected_source_hash:
        raise ValueError('surface_recovery_source_mismatch')
    files={}
    for name,row in metadata['components'].items():
        if int(row.get('count',0))<=0:
            continue
        files[name]=_source_component(manifest,name,row,expected_source_hash)
    if not {'room','body'}<=set(files):
        raise ValueError('surface_recovery_complete_environment_missing')
    dependencies={**_proof_dependencies(manifest,metadata),**_hair_dependencies(manifest,metadata)}
    destination.mkdir(parents=True,exist_ok=False)
    original=destination/'result.json'
    original.write_bytes(raw)
    if digest(original)!=actual:
        raise ValueError('surface_recovery_original_copy_failed')
    components=destination/'components'
    components.mkdir()
    rows={}
    relocations={}
    original_identity=_historic_identity(os.path.abspath(manifest))
    relocations[original_identity]={'file':'result.json','sha256':actual}
    for name,source in files.items():
        target=components/(name+'.npz')
        shutil.copyfile(source,target)
        wanted=metadata['components'][name]['sha256']
        if digest(target)!=wanted:
            raise ValueError('surface_recovery_copy_hash:'+name)
        rows[name]={'file':target.relative_to(destination).as_posix(),'sha256':wanted,
                    'originalDeclaredSha256':wanted,'count':int(metadata['components'][name]['count']),
                    'originalIdentity':_historic_identity(metadata['components'][name]['path'],original_identity)}
        relocations[rows[name]['originalIdentity']]={'file':rows[name]['file'],'sha256':wanted}
    evidence={}
    if dependencies:
        (destination/'evidence').mkdir()
    for label,(source,wanted,declared) in dependencies.items():
        suffix=source.suffix
        target=destination/'evidence'/(label+suffix)
        shutil.copyfile(source,target)
        if digest(target)!=wanted:
            raise ValueError('surface_recovery_evidence_copy:'+label)
        identity=_historic_identity(os.path.abspath(source))
        evidence[label]={'file':target.relative_to(destination).as_posix(),'sha256':wanted,
                         'originalIdentity':identity,'originalDeclaredPath':declared,'bytesPreserved':True}
        if identity in relocations and relocations[identity]['sha256']!=wanted:
            raise ValueError('surface_recovery_identity_collision')
        relocations[identity]={'file':evidence[label]['file'],'sha256':wanted}
    provenance={}
    for name in ('request.json','depth-manifest.json','source-snapshot.json'):
        source=manifest.parent/name
        if source.is_file():
            target=destination/name
            shutil.copyfile(source,target)
            if digest(target)!=digest(source):
                raise ValueError('surface_recovery_provenance_copy')
            provenance[name]={'sha256':digest(target),'role':'provenance_only_paths_may_be_historical'}
    receipt={'schema':'self-surface-recovery-1','sourceSha256':expected_source_hash,
        'checkpointManifestSha256':expected_manifest_hash,
        'originalManifest':{'file':'result.json','sha256':actual,'bytesPreserved':True,'originalIdentity':original_identity},
        'components':rows,'evidenceFiles':evidence,'relocations':relocations,'provenanceFiles':provenance,
        'recovery':{'surfaceInitializationVerified':True,'parameterOptimizerRngCheckpointsStoredSeparately':True,
                    'originalVideoRetained':False,'decodedImagesRetained':False,
                    'imageSupervisedResumeRequiresOriginalCaptureAndObservationPreparation':True,
                    'exactTrainingResumeEstablished':False},
        'pathContract':'Resolve components through this index; never substitute its hash for the original checkpoint manifest hash.'}
    recovery=destination/'recovery-manifest.json'
    recovery.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    verify_recovery_manifest(recovery,expected_manifest_hash=expected_manifest_hash)
    return receipt


def verify_recovery_manifest(path,*,expected_manifest_hash):
    """Return verified original metadata and relocated component Paths.

    This does not edit the metadata, replace the original identity or claim
    that missing capture-dependent losses can be resumed without inputs.
    """
    path=Path(path)
    root=path.parent.resolve()
    index=json.loads(path.read_text())
    if index.get('schema')!='self-surface-recovery-1' or index['checkpointManifestSha256']!=expected_manifest_hash:
        raise ValueError('surface_recovery_index_contract')
    def within(relative):
        candidate=(root/relative).resolve()
        if Path(relative).is_absolute() or not candidate.is_relative_to(root):
            raise ValueError('surface_recovery_relative_path_escape')
        return candidate
    original=within(index['originalManifest']['file'])
    if digest(original)!=expected_manifest_hash or index['originalManifest']['sha256']!=expected_manifest_hash:
        raise ValueError('surface_recovery_original_identity_changed')
    metadata=json.loads(original.read_text())
    if metadata['sourceSha256']!=index['sourceSha256']:
        raise ValueError('surface_recovery_index_source_changed')
    expected={n for n,r in metadata['components'].items() if int(r.get('count',0))>0}
    if set(index['components'])!=expected:
        raise ValueError('surface_recovery_component_set_changed')
    resolved={}
    old_manifest=index['originalManifest'].get('originalIdentity')
    expected_relocations={old_manifest:{'file':index['originalManifest']['file'],'sha256':expected_manifest_hash}} if old_manifest else {}
    for name,row in index['components'].items():
        file=within(row['file'])
        wanted=metadata['components'][name]['sha256']
        if row['sha256']!=wanted or row['originalDeclaredSha256']!=wanted or digest(file)!=wanted:
            raise ValueError('surface_recovery_retained_component_changed:'+name)
        if int(row['count'])!=int(metadata['components'][name]['count']):
            raise ValueError('surface_recovery_retained_count_changed')
        resolved[name]=file
        if old_manifest:
            identity=_historic_identity(metadata['components'][name]['path'],old_manifest)
            if row.get('originalIdentity')!=identity:
                raise ValueError('surface_recovery_component_identity_changed')
            expected_relocations[identity]={'file':row['file'],'sha256':wanted}
    evidence=index.get('evidenceFiles',{})
    expected_evidence=set()
    for name,row in metadata['components'].items():
        if not row.get('typedSupport') or int(row.get('count',0))<=0:
            continue
        if name!='room' or not old_manifest:
            raise ValueError('surface_recovery_typed_identity_missing')
        def check(label,declared,wanted,parent):
            key=name+'.'+label
            expected_evidence.add(key)
            saved=evidence.get(key)
            if not saved:
                raise ValueError('surface_recovery_evidence_missing:'+key)
            identity=_historic_identity(declared,parent)
            if saved.get('originalIdentity')!=identity or saved.get('originalDeclaredPath')!=str(declared):
                raise ValueError('surface_recovery_evidence_identity_changed:'+key)
            file=within(saved['file'])
            if saved['sha256']!=wanted or digest(file)!=wanted:
                raise ValueError('surface_recovery_evidence_changed:'+key)
            expected_relocations[identity]={'file':saved['file'],'sha256':wanted}
            return file,identity
        proofs=[('',row['surfaceCorrectionReceipt'],row['surfaceCorrectionReceiptSha256'],
                 row.get('surfaceBaseComponent',row)['sha256'])]
        if row.get('surfaceBaseComponent'):
            base=row['surfaceBaseComponent']
            check('surfaceBaseComponent',base['path'],base['sha256'],old_manifest)
        for item in row.get('additionalSurfaceReceipts',[]):
            prefix='additional'+str(item['index'])+'.'
            check(prefix+'asset',item['assetPath'],item['assetSha256'],old_manifest)
            proofs.append((prefix,item['path'],item['sha256'],item['assetSha256']))
        for prefix,declared,wanted,asset_hash in proofs:
            proof_file,proof_identity=check(prefix+'surfaceCorrectionReceipt',declared,wanted,old_manifest)
            proof=json.loads(proof_file.read_text())
            if proof.get('sourceSha256')!=metadata['sourceSha256'] or proof.get('roomAssetHash')!=asset_hash:
                raise ValueError('surface_recovery_proof_identity')
            for key in ('solverReport','surface'):
                check(prefix+key,proof[key+'Path'],proof[key+'Sha256'],proof_identity)
            _window_proof_closure(proof,proof_identity,check,prefix=prefix,source_hash=metadata['sourceSha256'])
            if proof.get('selfReferenceCorrection'):
                from live_room_self_reference import retain_self_reference_dependencies
                retain_self_reference_dependencies(proof,proof_identity,check,prefix=prefix,source_hash=metadata['sourceSha256'])
    def check_attempt(label,declared,wanted,parent):
        expected_evidence.add(label)
        saved=evidence.get(label)
        if not saved:
            raise ValueError('surface_recovery_retry_evidence_missing:'+label)
        identity=_historic_identity(declared,parent)
        if saved.get('originalIdentity')!=identity or saved.get('originalDeclaredPath')!=str(declared):
            raise ValueError('surface_recovery_retry_identity_changed:'+label)
        file=within(saved['file'])
        if saved['sha256']!=wanted or digest(file)!=wanted:
            raise ValueError('surface_recovery_retry_evidence_changed:'+label)
        expected_relocations[identity]={'file':saved['file'],'sha256':wanted}
        return file,identity
    _second_reference_provenance(metadata,old_manifest,check_attempt)
    hair=metadata['components'].get('hair',{})
    motion=hair.get('hairMotion')
    if motion and hair.get('count'):
        def check_hair(label,declared,wanted,parent):
            key='hair.'+label
            expected_evidence.add(key)
            saved=evidence.get(key)
            if not saved:
                raise ValueError('surface_recovery_hair_evidence_missing:'+key)
            identity=_historic_identity(declared,parent)
            if saved.get('originalIdentity')!=identity or saved.get('originalDeclaredPath')!=str(declared):
                raise ValueError('surface_recovery_hair_identity_changed:'+key)
            file=within(saved['file'])
            if saved['sha256']!=wanted or digest(file)!=wanted:
                raise ValueError('surface_recovery_hair_evidence_changed:'+key)
            expected_relocations[identity]={'file':saved['file'],'sha256':wanted}
            return file,identity
        receipt,receipt_identity=check_hair('motion',motion['path'],motion['sha256'],old_manifest)
        proof=json.loads(receipt.read_text())
        for key in ('status','sourceHash','checkpointSha256','modelSha256','referenceName','transformSha256'):
            if proof.get(key)!=motion.get(key):
                raise ValueError('surface_recovery_hair_motion_identity:'+key)
        if proof.get('sourceHash') not in (None,metadata['sourceSha256']):
            raise ValueError('surface_recovery_hair_source')
        check_hair('motionArrays',proof['arrayPath'],proof['arraySha256'],receipt_identity)
        if proof['status']!='explicit_legacy_root_local':
            check_hair('fitState',proof['fitStatePath'],proof['checkpointSha256'],receipt_identity)
        if hair.get('hairDepthManifestPath'):
            depth,_=check_hair('depthManifest',hair['hairDepthManifestPath'],hair['hairDepthManifestHash'],old_manifest)
            dm=json.loads(depth.read_text())
            if dm.get('sourceHash')!=metadata['sourceSha256'] or dm.get('hairMotion')!=motion:
                raise ValueError('surface_recovery_hair_depth_identity')
    if set(evidence)!=expected_evidence:
        raise ValueError('surface_recovery_evidence_set_changed')
    if old_manifest and index.get('relocations')!=expected_relocations:
        raise ValueError('surface_recovery_relocation_set_changed')
    return metadata,resolved


def resolve_recovery_identity(path,original_identity,*,expected_manifest_hash,expected_hash):
    """Resolve an old absolute dependency identity only after full validation."""
    verify_recovery_manifest(path,expected_manifest_hash=expected_manifest_hash)
    path=Path(path)
    index=json.loads(path.read_text())
    identity=_historic_identity(original_identity)
    entry=index.get('relocations',{}).get(identity)
    if not entry or entry['sha256']!=expected_hash:
        raise ValueError('surface_recovery_dependency_identity_not_retained')
    return (path.parent/entry['file']).resolve()


def retain_runtime_surface_initialization(output,state_dir,report):
    """Locate the exact manifest referenced by the final saved checkpoint."""
    from checkpoint import load_checkpoint
    output=Path(output)
    state_dir=Path(state_dir)
    checkpoint=load_checkpoint(output/'trained-state.pt',device='cpu')
    wanted=checkpoint.get('surfaceContract',{}).get('manifestSha256')
    if not wanted:
        raise ValueError('surface_recovery_checkpoint_contract_missing')
    metadata=report.get('denseSurfaces') or {}
    candidates=[output/'dense-surfaces/result.json']
    if metadata.get('manifestPath'):
        candidates.append(Path(metadata['manifestPath']))
    matches=[p for p in candidates if p.is_file() and digest(p)==wanted]
    if not matches:
        raise ValueError('surface_recovery_exact_manifest_missing')
    result=retain_surface_initialization(matches[0],state_dir/'surface-initialization',
        expected_manifest_hash=wanted,expected_source_hash=report['sourceSha256'])
    return {'recoveryManifest':'surface-initialization/recovery-manifest.json',
            'recoveryManifestSha256':digest(state_dir/'surface-initialization/recovery-manifest.json'),
            'originalManifestSha256':wanted,'components':result['components'],
            'evidenceFiles':result['evidenceFiles'],'recovery':result['recovery']}
