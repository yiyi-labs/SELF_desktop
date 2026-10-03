"""One capture reference shared by local portrait, body and dense handoff.

Only real local-training observations with real registered world cameras may
support the short body window. This is numerical eligibility, not proof that
the torso is perfectly rigid or that predicted depth is measured truth.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np


class CaptureReferenceUnavailable(ValueError):
    def __init__(self,reason,receipt):
        super().__init__(reason)
        self.receipt=receipt


def capture_timestamps(data):
    source=Path(data['source'])
    if not source.is_absolute():source=Path(__file__).resolve().parent/source
    paths=(source/'frame_selection.json',source/'frame_manifest.audit.json')
    path=next((p for p in paths if p.is_file()),None)
    if path is None:raise ValueError('capture_reference_timestamp_manifest_missing')
    raw=path.read_bytes();record=json.loads(raw)
    if not data.get('sourceHash') or record.get('captureSha256')!=data['sourceHash']:
        raise ValueError('capture_reference_timestamp_source_mismatch')
    rows=record.get('selectedFrames',record.get('frames',[]));result={}
    for row in rows:
        name=row.get('name')
        if not name or name in result:raise ValueError('capture_reference_duplicate_timestamp_identity')
        value=row.get('timestampSeconds')
        if value is None or not np.isfinite(value) or float(value)<0:
            continue
        result[name]=float(value)
    return result,{'kind':'source_capture_manifest','fileName':path.name,
                   'sha256':hashlib.sha256(raw).hexdigest(),'captureSha256':data['sourceHash']}


def _rigid(value):
    a=np.asarray(value,dtype=float)
    return (a.shape==(4,4) and np.isfinite(a).all() and np.allclose(a[3],[0,0,0,1],atol=1e-6)
        and np.allclose(a[:3,:3].T@a[:3,:3],np.eye(3),atol=2e-4)
        and np.linalg.det(a[:3,:3])>.999)


def choose_capture_reference(data,*,timestamps=None,timestamp_provenance=None,preferred=None,
                             radius_seconds=1.75,max_window=8,min_views=3,min_baseline_ratio=.005):
    """Return (reference imageName, evidence receipt), without mutating data.

    Retain the old maximum apparent-width reference whenever it is eligible.
    Otherwise select the most frontal candidate that really has a usable
    near-time training window. Explicit ``preferred`` keeps an existing valid
    reference, useful when continuing a frozen prepared capture.

    ``timestamps`` can be a caller-verified imageName -> seconds mapping;
    otherwise the capture-hash-checked existing manifest is read. No frame
    ordinal, camera ID, missing pose or timestamp is synthesized.
    """
    if min_views<3 or max_window<min_views or radius_seconds<=0 or min_baseline_ratio<=0:
        raise ValueError('capture_reference_invalid_window_contract')
    scale=float(data.get('scale',np.nan))
    if not np.isfinite(scale) or scale<=0:raise ValueError('capture_reference_scene_scale_missing')
    if timestamps is None:
        timestamps,provenance=capture_timestamps(data)
    else:
        provenance=timestamp_provenance or {'kind':'caller_supplied_imageName_timestamp_map'}
    forbidden=set(data.get('development',[]))|set(data.get('audit',[]))
    worlds=data['worlds'];local=data['local'];rejected={};eligible=[];score={}
    for n in dict.fromkeys(data['train']):
        if n in forbidden or n not in local or local[n].get('role')!='train':
            rejected[n]='not_local_and_world_training';continue
        if n not in worlds or not _rigid(worlds[n]) or not _rigid(local[n]['F']):
            rejected[n]='missing_or_invalid_actual_pose';continue
        t=timestamps.get(n)
        if t is None or not np.isfinite(t) or float(t)<0:
            rejected[n]='missing_actual_timestamp';continue
        marks=np.asarray(local[n]['marks'])
        if marks.ndim!=2 or len(marks)<=454 or not np.isfinite(marks).all():
            rejected[n]='invalid_measured_landmarks';continue
        distance=float(np.linalg.norm(np.asarray(local[n]['F'])[:3,3]))*scale
        if not np.isfinite(distance) or distance<=1e-8:
            rejected[n]='invalid_local_head_distance';continue
        score[n]=float(np.linalg.norm(marks[234]-marks[454])/max(np.linalg.norm(marks[10]-marks[152]),1.))
        eligible.append(n)
    receipt={'method':'shared_reference_real_train_time_and_baseline','timestampProvenance':provenance,
        'sourceHash':data.get('sourceHash'),'radiusSeconds':float(radius_seconds),'maxWindow':int(max_window),
        'minViews':int(min_views),'minBaselineToHeadDistance':float(min_baseline_ratio),
        'excludedObservations':rejected,'independentGeometryQualityApproved':False,'cameraInterpolation':False}
    if not eligible:
        raise CaptureReferenceUnavailable('capture_reference_no_world_local_training_observations',receipt)
    old=max(eligible,key=score.get);valid={};reasons={}
    for n in eligible:
        near=sorted((m for m in eligible if abs(float(timestamps[m])-float(timestamps[n]))<=radius_seconds),
                    key=lambda m:(abs(float(timestamps[m])-float(timestamps[n])),float(timestamps[m]),m))[:max_window]
        if len(near)<min_views or len({float(timestamps[m]) for m in near})<min_views:
            reasons[n]='insufficient_distinct_near_time_training';continue
        centres=np.stack([-np.asarray(worlds[m])[:3,:3].T@np.asarray(worlds[m])[:3,3] for m in near])
        baseline=float(np.linalg.norm(centres[:,None]-centres[None,:],axis=-1).max())
        distance=float(np.median([np.linalg.norm(np.asarray(local[m]['F'])[:3,3])*scale for m in near]))
        ratio=baseline/max(distance,1e-12)
        if baseline<=1e-7 or ratio<min_baseline_ratio:
            reasons[n]='insufficient_actual_camera_baseline';continue
        ordered=sorted(near,key=lambda m:(float(timestamps[m]),m))
        valid[n]={'imageNames':ordered,'timestampsSeconds':[float(timestamps[m]) for m in ordered],
                  'cameraBaselineWorld':baseline,'medianHeadDistanceWorld':distance,
                  'baselineToHeadDistance':ratio,'frontalWidthScore':score[n]}
    receipt.update(oldMaxWidthReference=old,requestedPreferredReference=preferred,rejectedWindows=reasons)
    if not valid:
        raise CaptureReferenceUnavailable('capture_reference_no_supported_body_window',receipt)
    chosen=preferred if preferred in valid else old if old in valid else max(valid,key=score.get)
    receipt.update(reference=chosen,keptOldMaxWidthReference=chosen==old,
                   keptRequestedPreferredReference=preferred is not None and chosen==preferred,
                   bodyWindow=valid[chosen],status='numerically_eligible_short_window_not_verified_rigid_motion')
    return chosen,receipt
