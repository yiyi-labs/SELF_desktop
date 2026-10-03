"""Restore non-Parameter training/render contracts alongside a trained model.

Python flags and semantic masks are not in ``scene.state_dict()``. A model
warm-start is therefore incomplete until its original observation contract is
verified. This helper never regenerates the appearance prior or updates tensors.
"""
from pathlib import Path
import hashlib
import json
import shutil

import numpy as np


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def restore_person_supervision(scene, data, parent, config, checkpoint):
    """Call after restore_recorded + model load, before any render or export.

    Older checkpoints without this metadata are accepted only for a recorded
    legacy run where both opaque flags are false. A requested flag change must
    be a separate explicit experiment, not silently inherited warm-start state.
    """
    from live_opaque_person import prepare_opaque_interiors, OpaquePersonConfig
    parent=Path(parent)
    head=config.get('opaquePerson',False)
    body=config.get('opaqueBody',False)
    if not isinstance(head,bool) or not isinstance(body,bool) or (body and not head):
        raise ValueError('person_restore_invalid_flags')
    if checkpoint.get('sourceSha256')!=data.get('sourceHash'):
        raise ValueError('person_restore_source_mismatch')
    if config.get('sourceSha256',data['sourceHash'])!=data['sourceHash']:
        raise ValueError('person_restore_config_source_mismatch')
    appearance=data['appearanceHash']
    if config.get('appearanceHash',appearance)!=appearance:
        raise ValueError('person_restore_appearance_mismatch')
    recorded=checkpoint.get('personSupervision')
    if recorded is None:
        if head or body:
            raise ValueError('person_restore_missing_checkpoint_contract')
    elif (recorded.get('opaqueHead') is not head or recorded.get('opaqueBody') is not body or
          recorded.get('appearanceSha256')!=appearance):
        raise ValueError('person_restore_checkpoint_contract_mismatch')
    domain=config.get('observedFaceDomain')
    if domain is not None:
        face_file=parent/'observed-face-domain.json'
        prior=parent/'observed-face-initial-appearance.npz'
        if not face_file.is_file() or json.loads(face_file.read_text())!=domain:
            raise ValueError('person_restore_face_receipt_changed')
        if (not prior.is_file() or _digest(prior)!=domain.get('appearanceSha256') or
                appearance!=domain.get('appearanceSha256') or data.get('face_domain_receipt')!=domain):
            raise ValueError('person_restore_prior_not_restored')
    elif head:
        raise ValueError('person_restore_opaque_requires_observed_face')
    footprint=config.get('surfaceFootprint')
    if footprint is not None:
        file=parent/'surface-footprint.json'
        if (not domain or not file.is_file() or json.loads(file.read_text())!=footprint or
                _digest(file)!=domain.get('surfaceFootprintSha256')):
            raise ValueError('person_restore_footprint_identity_changed')
    additions={}
    mask_hashes={}
    receipt_hash=None
    if head:
        file=parent/'opaque-interiors.json'
        if not file.is_file() or _digest(file)!=config.get('opaqueInteriorsReceiptSha256'):
            raise ValueError('person_restore_opaque_receipt_changed')
        receipt_hash=_digest(file)
        views=json.loads(file.read_text())
        if not isinstance(views,dict) or set(views)!=set(data['labels']):
            raise ValueError('person_restore_observation_names_changed')
        if recorded.get('opaqueInteriorsReceiptSha256',receipt_hash)!=receipt_hash:
            raise ValueError('person_restore_checkpoint_masks_mismatch')
        for name,labels in data['labels'].items():
            masks,receipt=prepare_opaque_interiors(labels,OpaquePersonConfig(**views[name]['config']))
            if receipt!=views[name]:
                raise ValueError('person_restore_masks_changed:'+name)
            additions[name]=masks
            mask_hashes[name]={key:hashlib.sha256(np.packbits(mask).tobytes()).hexdigest()
                               for key,mask in masks.items()}
    # Mutation only after every file/view has passed. This also prevents a
    # reused in-memory data object retaining masks from a prior opt-in run.
    for name,labels in data['labels'].items():
        for key in ('opaque_skin','opaque_cloth','opaque_body_skin'):
            labels.pop(key,None)
        labels.update(additions.get(name,{}))
    scene.opaque_person=head
    scene.opaque_body=body
    return dict(opaqueHead=head,opaqueBody=body,appearanceSha256=appearance,
                opaqueInteriorsReceiptSha256=receipt_hash,maskHashes=mask_hashes,
                legacyCheckpointContract=recorded is None,
                maskEvidence='same_prepared_observations_and_recorded_region_receipts; not independent_geometry')


def copy_person_supervision_files(parent, output, config):
    """Retain exact original receipt bytes for another independent run."""
    parent=Path(parent)
    output=Path(output)
    files=[]
    if config.get('observedFaceDomain') is not None:
        files.extend(('observed-face-domain.json','observed-face-initial-appearance.npz'))
    if config.get('opaquePerson',False):
        files.append('opaque-interiors.json')
    if config.get('surfaceFootprint') is not None:
        files.extend(('surface-footprint.json','surface-footprint-diagnostics.npz'))
    if config.get('roomWindowRecovery',False):
        files.append('room-window-recovery.json')
    output.mkdir(parents=True,exist_ok=True)
    for name in files:
        if not (parent/name).is_file():
            raise ValueError('person_restore_evidence_missing:'+name)
        target=output/name
        if target.exists():
            if _digest(target)!=_digest(parent/name):
                raise ValueError('person_restore_destination_conflict:'+name)
        else:
            shutil.copyfile(parent/name,target)
    return {name:_digest(output/name) for name in files}
