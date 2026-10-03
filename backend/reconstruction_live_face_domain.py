"""Observed facial skin extends beyond a landmark oval; the oval is not a cutout.

Keep historical evaluation masks unchanged. A connected semantic observation
selects supervision/colour only, never creates depth or fills unknown pixels.
"""
from pathlib import Path
import hashlib
import json
import cv2
import numpy as np


def observed_face_domain(classes, certainty, outside, existing):
    valid=(~outside)&(certainty>=.70)
    anchor=existing['face_core']|existing['face_boundary']
    # Class 3 is facial skin; class 2 (body/neck skin) is deliberately separate.
    skin=valid&(classes==3)&~existing['hair_visible']
    count,connected=cv2.connectedComponents(skin.astype(np.uint8),connectivity=8)
    ids=np.unique(connected[skin&anchor]);ids=ids[ids!=0]
    attached=np.isin(connected,ids)&skin
    details=valid&(classes==5)&anchor&~existing['hair_visible']
    return attached|details


def activate(data,out,*,regenerate_prior=True,write_receipt=True):
    from reconstruction_components_v2 import source_camera
    from reconstruction_live_prepare import initial_appearance
    from reconstruction_portrait_pipeline import digest,write_json
    prepared=Path(data['prepared']);meta=json.loads((prepared/'preparation.json').read_text())
    root=Path(meta['masks']);dist=meta.get('sourceDistortion')
    if dist is None:
        import pycolmap
        cameras=[source_camera(c) for c in pycolmap.Reconstruction(data['staticMap']).cameras.values()]
        if not cameras or any(not np.allclose(k,data['K']) or not np.allclose(d,cameras[0][1]) for k,d in cameras):
            raise ValueError('face_domain_intrinsics_missing_or_different')
        dist=cameras[0][1]
    rows=[];hashes={};skin_hashes={}
    for name,old in data['labels'].items():
        raw=cv2.imread(str(root/'labels'/(name+'.png')),cv2.IMREAD_GRAYSCALE)
        with np.load(root/'confidence'/(name+'.npz'),allow_pickle=False) as a:confidence=a['confidence'].astype(np.float32)
        if raw is None or raw.shape!=confidence.shape:raise ValueError('face_domain_source_missing:'+name)
        h,w=raw.shape;mx,my=cv2.initUndistortRectifyMap(data['K'],np.asarray(dist),np.eye(3),data['K'],(w,h),cv2.CV_32FC1)
        outside=(mx<0)|(my<0)|(mx>=w)|(my>=h)
        classes=cv2.remap(raw,mx,my,cv2.INTER_NEAREST);certainty=cv2.remap(confidence,mx,my,cv2.INTER_LINEAR)
        observed=observed_face_domain(classes,certainty,outside,old)
        legacy=old['face_core']|old['face_boundary']|old['glasses_visible']
        old['training_face']=observed
        # Keep physically opaque skin distinct from facial details (class 5).
        # The latter may include eyes/lenses and must not be forced opaque.
        old['training_skin']=observed&(classes==3)&(certainty>=.70)&~outside
        hashes[name]=hashlib.sha256(np.packbits(observed).tobytes()).hexdigest()
        skin_hashes[name]=hashlib.sha256(np.packbits(old['training_skin']).tobytes()).hexdigest()
        rows.append(dict(imageName=name,role=data['local'][name]['role'],legacyPixels=int(legacy.sum()),
            observedPixels=int(observed.sum()),observedOutsideLegacy=int((observed&~legacy).sum()),
            observationStatus='observed' if observed.any() else 'no_confident_face_pixels; not_filled',
            legacyReliableRoomPixels=int((legacy&(classes==0)&(certainty>=.7)&~outside).sum()),
            legacyReliableBodyPixels=int((legacy&np.isin(classes,[2,4])&(certainty>=.7)&~outside).sum())))
    # A missing semantic observation in one image is not a reason to abort
    # otherwise valid multi-view training. Never fill it with another view.
    if sum(r['role']=='train' and r['observedPixels']>0 for r in rows)<3:
        raise ValueError('face_domain_requires_three_observed_training_views')
    out=Path(out);prior_path=out/'observed-face-initial-appearance.npz'
    receipt=dict(method='connected_confident_face_skin_and_inside_oval_detail; original_eval_unchanged',
        views=rows,maskHashes=hashes,skinMaskHashes=skin_hashes,oldAppearanceSha256=data['appearanceHash'],
        geometryChanged=False,camerasChanged=False,heldoutColoursUsed=False)
    if regenerate_prior:
        data['prior']=initial_appearance(data)
        np.savez_compressed(prior_path,**data['prior'])
        data['appearanceHash']=digest(prior_path)
        receipt.update(appearancePath=str(prior_path.resolve()),appearanceSha256=data['appearanceHash'],
            surfaceCount=len(data['prior']['surface_ids']))
    if write_receipt:write_json(out/'observed-face-domain.json',receipt)
    data['face_domain_receipt']=receipt
    return receipt


def restore_recorded(data,run,config):
    """Restore the exact changed prior; never silently regenerate from defaults."""
    from reconstruction_portrait_pipeline import digest
    receipt=config.get('observedFaceDomain')
    if not receipt:return
    if data['appearanceHash']!=receipt['oldAppearanceSha256']:
        raise ValueError('face_domain_parent_appearance_changed')
    path=Path(run)/'observed-face-initial-appearance.npz'
    if digest(path)!=receipt['appearanceSha256']:raise ValueError('face_domain_prior_changed')
    regenerated=activate(data,run,regenerate_prior=False,write_receipt=False)
    if regenerated['maskHashes']!=receipt['maskHashes']:raise ValueError('face_domain_observations_changed')
    if 'skinMaskHashes' in receipt and regenerated['skinMaskHashes']!=receipt['skinMaskHashes']:
        raise ValueError('face_domain_skin_observations_changed')
    with np.load(path,allow_pickle=False) as archive:data['prior']={k:archive[k].copy() for k in archive.files}
    data['appearanceHash']=receipt['appearanceSha256'];data['face_domain_receipt']=receipt
