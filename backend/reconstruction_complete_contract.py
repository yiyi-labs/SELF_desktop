"""Small extension of research manifests: patch identity and target conservation.
No image mask, renderer, publisher or production entrypoint is changed.
"""
from __future__ import annotations
import numpy as np

ROLES={'local_probe','component_candidate','assembled_research','release_candidate'}


def local_to_world(C,Q,*,world_units_per_local_unit=1.):
    """C: W2C in world units; Q: local2camera, translation in local units."""
    C=np.asarray(C,dtype=float);Q=np.asarray(Q,dtype=float).copy();s=float(world_units_per_local_unit)
    if not np.isfinite(s) or s<=0:raise ValueError('invalid_shared_scale')
    for T in (C,Q):
        if T.shape!=(4,4) or not np.isfinite(T).all() or not np.allclose(T[3],[0,0,0,1]):raise ValueError('invalid_rigid_transform')
        if not np.allclose(T[:3,:3].T@T[:3,:3],np.eye(3),atol=1e-5) or np.linalg.det(T[:3,:3])<.999:raise ValueError('per_frame_scale_or_nonrigid_pose')
    Q[:3,3]*=s;B=np.linalg.solve(C,Q)
    if not np.allclose(C@B,Q,atol=1e-7):raise ValueError('coordinate_handoff_failed')
    return B


def plan_patch(base,patch,*,reference,retire_uids):
    """No automatic whole-group replacement, no fabricated cross-time mapping.
    Returns explicit ordered sets; the caller applies a transaction only after
    its geometry/coverage evidence permits that proposed retirement.
    """
    for value in (base,patch):
        if value['role'] not in ROLES:raise ValueError('invalid_result_role')
        for k in ('sourceHash','canonicalFrame','unitScale','checkpointHash','pointUIDs'):
            if k not in value:raise ValueError('missing_component_contract:'+k)
    if base['sourceHash']!=patch['sourceHash']:raise ValueError('different_capture')
    old=np.asarray(base['pointUIDs'],np.int64);new=np.asarray(patch['pointUIDs'],np.int64);retire=np.asarray(retire_uids,np.int64)
    if any(len(v)!=len(np.unique(v)) for v in (old,new,retire)):raise ValueError('duplicate_UID')
    if np.intersect1d(old,new).size:raise ValueError('new_topology_requires_new_UIDs')
    if not np.isin(retire,old).all():raise ValueError('unknown_retirement_UID')
    if patch.get('scope')=='patch' and len(retire)==len(old):raise ValueError('patch_cannot_replace_whole_component')
    if patch['canonicalFrame']!=base['canonicalFrame'] or not np.isclose(patch['unitScale'],base['unitScale']):raise ValueError('canonical_alignment_required')
    transforms=patch.get('worldFromCanonical',{})
    if reference not in transforms or not patch.get('transformEvidence',{}).get(reference,False):raise ValueError('untrusted_reference_transform')
    local_to_world(np.eye(4),transforms[reference])
    if len(retire) and not (patch.get('replacementEvidence',{}).get('coveragePassed') and patch['replacementEvidence'].get('geometryPassed')):raise ValueError('retirement_before_replacement_validated')
    keep=old[~np.isin(old,retire)]
    return {'role':'assembled_research','reference':reference,'sourceHash':base['sourceHash'],'retainedUIDs':keep.tolist(),'retiredUIDs':retire.tolist(),'addedUIDs':new.tolist(),'releaseQualityPassed':False,'requiresCommonForward':True}


def observed_completeness(observed,unknown,alpha,explained=None):
    """Unknown is retained in the report; unexplained visible pixels stay in denominator."""
    observed=np.asarray(observed,bool);unknown=np.asarray(unknown,bool);a=np.asarray(alpha);e=a>=.8 if explained is None else np.asarray(explained,bool)
    if any(x.shape!=observed.shape for x in (unknown,a,e)):raise ValueError('full_canvas_required')
    visible=observed&~unknown;return {'observed':int(observed.sum()),'unknownOverlap':int((observed&unknown).sum()),'visibleTarget':int(visible.sum()),'unexplainedVisible':int((visible&~e).sum()),'alphaBelow08':int((visible&(a<.8)).sum()),'note':'alpha diagnostic is not measured geometric completeness'}


def export_native_mvs_window(out,images,masks,names,cameras,K,points,*,input_pixel_center):
    """Explicit OpenCV-integer -> COLMAP-half convention, exactly once.
    Installed OpenMVS 2.4.0 subtracts 0.5 on import. Original arrays and prior
    exports remain unchanged. This is a research adapter, not a production hook.
    """
    if input_pixel_center!='opencv_integer':raise ValueError('explicit_native_pixel_contract_required')
    from reconstruction_surface_evidence import export_colmap
    k=np.asarray(K,dtype=float).copy();k[:2,2]+=.5
    changed=[{**p,'observations':[{**o,'uv':(np.asarray(o['uv'])+.5).tolist()} for o in p['observations']]} for p in points]
    result=export_colmap(out,images,masks,names,cameras,k,changed)
    return {**result,'nativeK':np.asarray(K).tolist(),'pixelCenter':'COLMAP_half_export_OpenMVS_integer_import','inputPixelCenter':input_pixel_center}
