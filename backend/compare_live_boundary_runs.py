"""Compare frozen native renders on source-derived boundaries; never training input."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from audit_live_boundary_coverage import boundary_regions, original_semantics
from reconstruction_live_dense import read_prepared, physical_masks
from reconstruction_live_dense_contract import digest, write_json


def compare(runs, output):
    paths=[Path(x).resolve() for x in runs];out=Path(output).resolve()
    if out.exists():raise FileExistsError(out)
    configs=[json.loads((p/'config.json').read_text()) for p in paths]
    data=read_prepared(configs[0]['prepared'])
    if any(c['sourceSha256']!=data['metadata']['sourceHash'] for c in configs):
        raise ValueError('boundary_compare_source_mismatch')
    if any(digest(Path(c['prepared'])/'local_geometry.npz')!=digest(data['prepared']/'local_geometry.npz') for c in configs):
        raise ValueError('boundary_compare_geometry_mismatch')
    names=sorted(set.intersection(*[set(p.name[:-4] for p in (r/'full-final').glob('*.npz')) for r in paths]))
    if not names:raise ValueError('boundary_compare_no_common_native_renders')
    report=dict(sourceHash=data['metadata']['sourceHash'],runs=[dict(path=str(p),
        assetSha256=digest(p/'portrait.gaussian.ply'),configSha256=digest(p/'config.json')) for p in paths],
        views={},zeroTraining=True,sourceMasksUnchanged=True,
        limitations=['Existing development observations are not independent blind tests.',
            'Alpha thresholds describe transmission, not measured geometric truth.',
            'Semantic contour bands locate diagnostics; no candidate RGB selects the region.'])
    out.mkdir(parents=True)
    for name in names:
        old=dict(np.load(data['prepared']/'rectified_observations'/(name+'.npz'),allow_pickle=False))
        classes,confidence,outside,lab=original_semantics(data['prepared'],data['metadata'],name,data['K'],old)
        domains=physical_masks(lab);regions,radius=boundary_regions(classes,lab['face_core']|lab['face_boundary'],outside)
        for band in ('edge','near','interior'):regions['room_'+band]&=domains['room']
        regions.update(observedRoom=domains['room'],observedClothing=domains['body'],observedHair=domains['hair'],
                       observedSkin=(classes==3)&(confidence>=.7)&~outside)
        source=cv2.cvtColor(cv2.imread(str(data['prepared']/'rectified_observations'/name)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        results=[];images=[source];reference=None
        for p in paths:
            f=dict(np.load(p/'full-final'/(name+'.npz'),allow_pickle=False))
            if reference is None:reference=f
            for key in ('K','C','F'):np.testing.assert_array_equal(f[key],reference[key])
            if f['rgb'].shape!=source.shape or not all(np.isfinite(f[k]).all() for k in ('rgb','alpha','q')):
                raise ValueError('boundary_compare_invalid_native_render')
            values={}
            for key,mask in regions.items():
                item=dict(pixels=int(mask.sum()))
                if mask.any():
                    item.update(rgbL1=float(np.abs(f['rgb'][mask]-source[mask]).mean()),
                        alphaBelow01=int((f['alpha'][mask]<.01).sum()),alphaBelow08=int((f['alpha'][mask]<.8).sum()),
                        qRoomBelow01=int((f['q'][mask,0]<.01).sum()),qMean=f['q'][mask].mean(0).tolist())
                values[key]=item
            results.append(values);images.append(f['rgb'])
        report['views'][name]=dict(nativeBandRadius=radius,results=results)
        strip=np.concatenate(images,axis=1)
        cv2.imwrite(str(out/(name+'.comparison.png')),cv2.cvtColor((np.clip(strip,0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    write_json(out/'report.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runs',nargs='+',required=True);p.add_argument('--output',required=True)
    r=compare(**vars(p.parse_args()));print(json.dumps(dict(views=len(r['views']),zeroTraining=True)))
