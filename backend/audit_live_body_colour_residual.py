"""CPU attribution of cached fixed-geometry body-colour trials, not training."""
from pathlib import Path
import argparse
import json
import cv2
import numpy as np

from compare_live_opaque_person_runs import (read_json, digest, mask_hash, resolve,
    region_metrics, _save_strip, _bbox)
from audit_live_boundary_coverage import original_semantics
from reconstruction_live_face_domain import observed_face_domain
from reconstruction_live_opaque_person import prepare_opaque_interiors, OpaquePersonConfig
from reconstruction_live_body_appearance import body_preservation_decision


def audit(run, output):
    run=resolve(run);out=resolve(output)
    if out.exists():raise FileExistsError(out)
    config=read_json(run/'config.json');prepared=resolve(config['prepared'])
    meta=read_json(prepared/'preparation.json');receipt=read_json(run/'opaque-interiors.json')
    if digest(run/'opaque-interiors.json')!=config['opaqueInteriorsReceiptSha256']:
        raise ValueError('body_residual_mask_receipt_changed')
    if meta['sourceHash']!=config['sourceSha256']:raise ValueError('body_residual_source_changed')
    before=read_json(run/'body-initial'/'report.json');after=read_json(run/'body-final'/'report.json')
    if set(before)!=set(after):raise ValueError('body_residual_view_mismatch')
    with np.load(prepared/'local_geometry.npz',allow_pickle=False) as a:
        K=a['K'].copy();F=dict(zip(a['names'].tolist(),a['F']));C=dict(zip(a['world_names'].tolist(),a['C']))
    out.mkdir(parents=True);rows={};hashes={}
    def remember(path):hashes[str(path)]=digest(path)
    for path in (run/'config.json',run/'opaque-interiors.json',prepared/'preparation.json',prepared/'local_geometry.npz'):
        remember(path)
    for name in sorted(before):
        raw=prepared/'rectified_observations'/(name+'.npz');remember(raw)
        with np.load(raw,allow_pickle=False) as a:old={key:a[key].copy() for key in a.files}
        classes,confidence,outside,labels=original_semantics(prepared,meta,name,K,old)
        face=observed_face_domain(classes,confidence,outside,labels)
        labels.update(training_face=face,training_skin=face&(classes==3)&(confidence>=.70)&~outside)
        masks,actual=prepare_opaque_interiors(labels,OpaquePersonConfig(**receipt[name]['config']))
        if actual!=receipt[name]:raise ValueError('body_residual_opaque_mask_changed:'+name)
        source_path=prepared/'rectified_observations'/name;remember(source_path)
        source=cv2.cvtColor(cv2.imread(str(source_path)),cv2.COLOR_BGR2RGB).astype(np.float32)/255.
        render=[]
        for stage in ('body-initial','body-final'):
            path=run/stage/(name+'.npz');remember(path)
            with np.load(path,allow_pickle=False) as a:r={key:a[key].copy() for key in a.files}
            for key,expected in [('K',K),('C',C[name]),('F',F[name])]:np.testing.assert_allclose(r[key],expected,rtol=0,atol=1e-8)
            if r['rgb'].shape!=source.shape:raise ValueError('body_residual_native_canvas_changed')
            render.append(r)
        for key in ('q','alpha'):np.testing.assert_array_equal(render[0][key],render[1][key])
        neck=masks['opaque_body_skin'];q=render[0]['q']
        # Fixed recorded semantic boundary, independent of candidate RGB.
        dist=cv2.distanceTransform(neck.astype(np.uint8),cv2.DIST_L2,5)
        partitions={'neck_all':neck,'neck_semantic_boundary8':neck&(dist<=8),
            'neck_interior8':neck&(dist>8),
            'neck_head_dominant':neck&(q[...,1]>=q[...,4]),
            'neck_body_dominant':neck&(q[...,4]>q[...,1]),
            'neck_layer_mix':neck&(q[...,1]>.05)&(q[...,4]>.05),
            'cloth_all':masks['opaque_cloth']}
        values={}
        delta=render[1]['rgb']-render[0]['rgb']
        for region,mask in partitions.items():
            pair=[region_metrics(r,source,mask) for r in render]
            row={'maskHash':mask_hash(mask),'before':pair[0],'after':pair[1]}
            if mask.any():row.update(changeAbsMean=float(np.abs(delta[mask]).mean(dtype=np.float64)),
                changeSignedMean=delta[mask].mean(0,dtype=np.float64).tolist(),
                headContributionMean=float(q[...,1][mask].mean(dtype=np.float64)),
                bodyContributionMean=float(q[...,4][mask].mean(dtype=np.float64)))
            values[region]=row
        rows[name]={'regions':values,'qAndAlphaBitwiseUnchanged':True}
        box=_bbox(neck,padding=24)
        if box:
            x0,y0,x1,y1=box
            _save_strip(out/(name+'.neck.png'),
                [v[y0:y1,x0:x1] for v in (source,render[0]['rgb'],render[1]['rgb'])],
                ['Source','Opaque before body SH','Body SH only / rejected'])
    for path,expected in hashes.items():
        if digest(path)!=expected:raise ValueError('body_residual_input_changed:'+path)
    result={'sourceSha256':config['sourceSha256'],'run':str(run),'inputHashes':hashes,'views':rows,
        'retrospectiveGate':body_preservation_decision(before,after),
        'zeroTraining':True,'gpuUsed':False,'colourContract':'native float; no clipping for metrics',
        'limitations':['Gate was added after this finite trial: retrospective rejection only.',
            'Semantic boundary and q-layer partitions diagnose color changes, not measured depth.',
            'The five body views were used in this trial and are not independent validation.',
            'Person-only RGB is not present in these caches; total RGB/q_person is not a valid substitute.']}
    (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'status':'CPU attribution complete','accepted':result['retrospectiveGate']['accepted'],
        'failures':result['retrospectiveGate']['failures']}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--output',required=True)
    audit(**vars(parser.parse_args()))
