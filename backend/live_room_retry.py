"""One bounded second reference for a previously failed room window.

This bounded stage reuses locked depth and measurements. It cannot
repeat itself, change the first failure, or bypass any surface/point check.
"""
import json
import shutil
from pathlib import Path

import numpy as np

from live_dense_contract import digest,write_json


def select_second_reference(selection,outcomes):
    """Prefer independent measurement support, not development RGB or a name."""
    attempted={}
    for row in outcomes:
        attempted.setdefault(row['window'],set()).add(row['reference'])
    failed={row['window'] for row in outcomes if row['status']=='independent_validation_failed'}
    choices=[c for c in selection['candidates'] if c['window'] in failed
        and len(attempted[c['window']])==1 and c['reference'] not in attempted[c['window']]
        and c['eligible'] and c.get('mapTrackEvidence') and c['trackCounts']['fit']>=20
        and c['trackCounts']['validation']>=12]
    if not choices:return None
    return max(choices,key=lambda c:(c['trackCounts']['validation'],c['trackCounts']['fit'],c['newAreaCells']))


def retry_room_reference(parent_bundle,first_attempt,output,*,max_evaluations=40,max_surfaces=2,extra_budget=30000,allow_typed_conditional=True):
    from live_room_window_recovery import make_window_proposal,check_surface_overlap,filter_unrepresented_observations
    from live_shared_room_surface import run_shared_surface,export_shared_room_initialization,SharedRoomEvidenceUnavailable
    if (any(type(v) is not int for v in (max_evaluations,max_surfaces,extra_budget))
        or not(0<max_evaluations<=40 and 0<max_surfaces<=2 and 0<extra_budget<=30000)):
        raise ValueError('room_retry_budget')
    parent_path=Path(parent_bundle).resolve();parent=json.loads(parent_path.read_text())
    first=Path(first_attempt).resolve();previous=json.loads((first/'result.json').read_text())
    if parent.get('roomWindowSecondReference'):raise ValueError('room_retry_already_attempted')
    for key in ('sourceSha256','preparedSha256','localGeometrySha256','depthManifestHash'):
        if parent[key]!=previous[key]:raise ValueError('room_retry_source_changed:'+key)
    if parent['acceptedWindows']!=previous['acceptedWindows']:raise ValueError('room_retry_decision_changed')
    if digest(previous['parentManifestPath'])!=previous['parentManifestHash']:raise ValueError('room_retry_original_parent_changed')
    selection_path=first/'selection.json';selection=json.loads(selection_path.read_text())
    prior=previous['roomWindowRecovery']
    if digest(selection_path)!=prior['selectionSha256']:raise ValueError('room_retry_selection_changed')
    candidate=select_second_reference(selection,prior['outcomes'])
    row=parent['components']['room']
    proofs=[json.loads(Path(p['path']).read_text()) for p in row.get('additionalSurfaceReceipts',[])]
    existing_recoveries=[p for p in proofs if p.get('windowRecovery')]
    budget=extra_budget-sum(p['actualAdded'] for p in existing_recoveries)
    if len(existing_recoveries)>=max_surfaces or budget<=0:raise ValueError('room_retry_total_recovery_budget')
    if not row.get('surfaceCorrectionReceipt'):raise ValueError('room_retry_qualified_base_required')
    for component in parent['components'].values():
        if digest(component['path'])!=component['sha256']:raise ValueError('room_retry_asset_changed')
    out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'algorithm-source';snapshot.mkdir()
    for name in (Path(__file__).name,'live_room_window_recovery.py','live_shared_room_surface.py','live_room_completion.py','live_surface_binding.py'):
        shutil.copyfile(Path(__file__).with_name(name),snapshot/name)
    decision=dict(kind='one-second-reference-research',maxAttemptsPerWindow=2,maxEvaluations=max_evaluations,
        candidate=candidate,priorAttemptPath=str(first/'result.json'),priorAttemptSha256=digest(first/'result.json'),
        selectionPath=str(selection_path),selectionSha256=digest(selection_path),
        rank='independent_validation_track_count_then_fit_then_observed_area',solverInvoked=False,
        originalFailuresRetained=True,extraBudget=budget)
    write_json(out/'decision.json',decision)
    final={**parent,'manifestPath':str(out/'result.json'),'parentManifestPath':str(parent_path),'parentManifestHash':digest(parent_path),'published':False}
    added=None;reason='no_eligible_second_reference'
    if candidate is not None:
        root=Path(parent['depthManifestPath']).parent;request=json.loads((root/'request.json').read_text())
        proposal=out/'window-proposal.json';make_window_proposal(parent_path,candidate['reference'],candidate['window'],proposal)
        decision['solverInvoked']=True;write_json(out/'decision.json',decision)
        try:
            report=run_shared_surface(request['prepared'],root,out/'solve',window=candidate['window'],reference=candidate['reference'],
                max_evaluations=max_evaluations,proposed_window_receipt=proposal)
            reason='independent_validation_failed'
            if report['accepted']:
                overlap=check_surface_overlap(out/'solve',parent_path,out/'overlap.json')
                filter_fn=None;overlap_path=out/'overlap.json'
                if not overlap['qualified']:
                    filter_fn=lambda fresh:filter_unrepresented_observations(fresh,out/'solve',parent_path,out/'local-filter',allow_typed_conditional=allow_typed_conditional)
                    overlap_path=out/'local-filter/report.json'
                added=export_shared_room_initialization(out/'solve',parent_path,out/'addition',budget=budget,
                    completion_reference=parent['reference'],candidate_filter=filter_fn)
                proof=json.loads(Path(added['path']).read_text());proof['windowRecovery']=dict(proposalPath=str(proposal),proposalSha256=digest(proposal),
                    overlapPath=str(overlap_path),overlapSha256=digest(overlap_path))
                write_json(added['path'],proof);added.update(sha256=digest(added['path']),recoveredWindow=candidate['window'])
                write_json(out/'addition/addition-result.json',added);reason=None
        except SharedRoomEvidenceUnavailable as error:reason=str(error)
    if added:
        old=dict(np.load(row['path'],allow_pickle=False));extra=dict(np.load(added['assetPath'],allow_pickle=False));n=len(old['means'])
        perpoint={k:np.concatenate((v,extra[k])) for k,v in old.items() if v.ndim and len(v)==n}
        if any(not np.array_equal(v,perpoint[k][:n]) for k,v in old.items() if k in perpoint):raise AssertionError('room_retry_parent_changed')
        if len(np.unique(perpoint['uid']))!=len(perpoint['uid']):raise ValueError('room_retry_duplicate_uid')
        asset=out/'room-surface.npz';np.savez_compressed(asset,**perpoint,source_hash=np.asarray(parent['sourceSha256']),coordinate_frame=np.asarray('world'),referenceName=np.asarray(parent['reference']))
        newrow={**row,'path':str(asset),'sha256':digest(asset),'count':len(perpoint['means']),
            'surfaceBaseComponent':row.get('surfaceBaseComponent',dict(path=row['path'],sha256=row['sha256'],count=n)),
            'additionalSurfaceReceipts':row.get('additionalSurfaceReceipts',[])+[added],
            'trainNames':sorted(set(row['trainNames'])|set(added['trainNames'])),'originalPrefixBitwiseUnchanged':True}
        final['components']={**parent['components'],'room':newrow}
    final['roomWindowSecondReference']=dict(status='conditional_surface_added' if added else 'original_bundle_retained',reason=reason,
        decisionPath=str(out/'decision.json'),decisionSha256=digest(out/'decision.json'),addedCount=added['count'] if added else 0,
        originalPrefixBitwiseUnchanged=True,cameraChanged=False,thresholdsChanged=False,training=False,visualQualityPassed=False)
    first_summary=parent['roomWindowRecovery'];total_added=int(first_summary.get('addedCount',0))+(added['count'] if added else 0)
    final['roomWindowRecovery']={**first_summary,
        'status':'conditional_surfaces_added' if total_added else 'original_bundle_retained','addedCount':total_added,
        'firstAttemptManifestPath':str(first/'result.json'),'firstAttemptManifestSha256':digest(first/'result.json'),
        'secondReference':final['roomWindowSecondReference'],'visualQualityPassed':False}
    write_json(out/'result.json',final);return final


def complete_room_recovery(first_result,first_attempt,*,max_evaluations=40,max_surfaces=2,extra_budget=30000,allow_typed_conditional=True):
    """Finish the one automatic stage without replacing its first-attempt files."""
    if first_result.get('roomWindowSecondReference'):return first_result
    first=Path(first_attempt).resolve();manifest=Path(first_result['manifestPath']).resolve()
    if manifest!=first/'result.json' or json.loads(manifest.read_text())!=first_result:
        raise ValueError('room_retry_first_result_mismatch')
    summary=first_result['roomWindowRecovery']
    if not summary.get('selectionPath'):return first_result
    selection=Path(summary['selectionPath'])
    if digest(selection)!=summary['selectionSha256']:raise ValueError('room_retry_selection_changed')
    if select_second_reference(json.loads(selection.read_text()),summary['outcomes']) is None:return first_result
    extras=first_result['components']['room'].get('additionalSurfaceReceipts',[])
    proofs=[json.loads(Path(p['path']).read_text()) for p in extras]
    recoveries=[p for p in proofs if p.get('windowRecovery')]
    if len(recoveries)>=max_surfaces or sum(p['actualAdded'] for p in recoveries)>=extra_budget:return first_result
    return retry_room_reference(manifest,first,first/'second-reference',max_evaluations=max_evaluations,
                                max_surfaces=max_surfaces,extra_budget=extra_budget,allow_typed_conditional=allow_typed_conditional)
