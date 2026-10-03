"""Full, rectified physical observation masks, independent of feature support."""
from pathlib import Path
import json
import cv2
import numpy as np


def observation_domains(classes, certainty, outside, existing):
    valid = (~outside) & (certainty >= .70)
    room = valid & (classes == 0) & (certainty >= .85)
    cloth = valid & (classes == 4)
    body_skin = valid & (classes == 2)
    return {**existing, 'observed_room': room, 'observed_cloth': cloth,
            'observed_body_skin': body_skin, 'observed_neck_cloth': cloth | body_skin}


def rectified_domains(mask_root, name, K, distortion, existing):
    root = Path(mask_root)
    raw = cv2.imread(str(root/'labels'/(name+'.png')), cv2.IMREAD_GRAYSCALE)
    path = root/'confidence'/(name+'.npz')
    if raw is None or not path.is_file():
        raise ValueError('physical_observation_source_missing:'+name)
    with np.load(path) as archive:
        certainty = archive['confidence'].astype(np.float32)
    h, w = raw.shape
    if certainty.shape != raw.shape:raise ValueError('physical_observation_size')
    mx, my = cv2.initUndistortRectifyMap(K, distortion, np.eye(3), K, (w,h), cv2.CV_32FC1)
    outside = (mx<0)|(my<0)|(mx>=w)|(my>=h)
    return observation_domains(cv2.remap(raw,mx,my,cv2.INTER_NEAREST),
        cv2.remap(certainty,mx,my,cv2.INTER_LINEAR),outside,existing)


def attach_observation_domains(data, prepared):
    prepared = Path(prepared).resolve()
    if all('observed_room' in value for value in data['labels'].values()):return
    metadata = json.loads((prepared/'preparation.json').read_text())
    root = prepared.parent.parent
    resolve = lambda value: Path(value) if Path(value).is_absolute() else (root/value).resolve()
    distortion = metadata.get('sourceDistortion')
    audit = prepared/'pose-and-scale-audit.json'
    if distortion is None and audit.is_file():
        distortion = json.loads(audit.read_text()).get('sourceRadialDistortion')
    if distortion is None:
        import pycolmap
        from components_v2 import source_camera
        cameras = [source_camera(c) for c in pycolmap.Reconstruction(data['staticMap']).cameras.values()]
        if not cameras or any(not np.allclose(k,data['K']) for k,d in cameras):
            raise ValueError('cached_camera_contract_mismatch')
        if any(not np.allclose(d,cameras[0][1]) for k,d in cameras):
            raise ValueError('cached_multiple_distortions')
        distortion = cameras[0][1]
    masks = resolve(metadata['masks'])
    for name, old in data['labels'].items():
        data['labels'][name] = rectified_domains(masks,name,data['K'],np.asarray(distortion),old)
