"""CPU-only fixed-observation comparison of two actual saved scene renders.

No rasterization, training, masks chosen from candidate RGB, or model editing.
All numeric errors use stored native floats, without display clipping/gamma.
Only PNG previews are clipped to their ordinary 8-bit display range.
"""
from pathlib import Path
import argparse
import hashlib
import json
import cv2
import numpy as np

from audit_live_boundary_coverage import original_semantics, boundary_regions
from reconstruction_live_face_domain import observed_face_domain
from reconstruction_live_opaque_person import prepare_opaque_interiors, OpaquePersonConfig


NIGHT_SKY = np.array([24., 39., 72.], np.float32)/255.


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def mask_hash(mask):
    return hashlib.sha256(np.packbits(mask).tobytes()).hexdigest()


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def resolve(value):
    path=Path(value)
    return path.resolve() if path.is_absolute() else (Path(__file__).resolve().parent/path).resolve()


def gradient_l1(prediction,target,mask):
    numerator=0.;denominator=0
    for axis in (0,1):
        valid=(mask[1:]&mask[:-1]) if axis==0 else (mask[:,1:]&mask[:,:-1])
        difference=np.abs(np.diff(prediction,axis=axis)-np.diff(target,axis=axis))
        numerator+=float(difference[valid].sum(dtype=np.float64))
        denominator+=int(valid.sum())*3
    return numerator/denominator if denominator else None


def region_metrics(render,source,mask):
    count=int(mask.sum());row={'pixels':count}
    if not count:return row
    rgb=render['rgb'];alpha=render['alpha'];q=render['q']
    person=q[...,1]+q[...,4];all_person=q[...,1:].sum(-1)
    residual=rgb-source
    white=rgb+(1-alpha)[...,None]
    night=rgb+(1-alpha)[...,None]*NIGHT_SKY
    row.update(premultRgbL1=float(np.abs(residual[mask]).mean(dtype=np.float64)),
        whiteBackdropRgbL1=float(np.abs(white[mask]-source[mask]).mean(dtype=np.float64)),
        nightBackdropRgbL1=float(np.abs(night[mask]-source[mask]).mean(dtype=np.float64)),
        qPersonMean=float(person[mask].mean(dtype=np.float64)),
        qAllPersonMean=float(all_person[mask].mean(dtype=np.float64)),
        qRoomMean=float(q[...,0][mask].mean(dtype=np.float64)),
        qHairMean=float(q[...,2][mask].mean(dtype=np.float64)),
        qBodyMean=float(q[...,4][mask].mean(dtype=np.float64)),
        personBelow095=float((person[mask]<.95).mean()),
        personBelow08=float((person[mask]<.8).mean()),
        alphaMean=float(alpha[mask].mean(dtype=np.float64)),
        alphaBelow095=float((alpha[mask]<.95).mean()),
        alphaBelow08=float((alpha[mask]<.8).mean()),
        residualChannelVariance=np.var(residual[mask].astype(np.float64),axis=0).tolist(),
        nativeGradientL1=gradient_l1(rgb,source,mask))
    # An explicitly auxiliary blotch proxy, not a surface/skin diagnosis.
    # Weighted local residual avoids blurring fabricated zeros across the mask.
    weights=cv2.GaussianBlur(mask.astype(np.float32),(0,0),3.)
    stable=mask&(weights>.95)
    if stable.any():
        low=cv2.GaussianBlur(residual*mask[...,None],(0,0),3.)/np.maximum(weights[...,None],1e-6)
        row['lowFrequencyResidualStdSigma3']=np.std(low[stable].astype(np.float64),axis=0).tolist()
        row['lowFrequencyProxyPixels']=int(stable.sum())
    else:row.update(lowFrequencyResidualStdSigma3=None,lowFrequencyProxyPixels=0)
    return row


def _save_strip(path,images,labels):
    if len(images)!=len(labels) or not images:raise ValueError('opaque_compare_preview_columns')
    if len({image.shape for image in images})!=1:raise ValueError('opaque_compare_preview_shape')
    image=np.concatenate(images,axis=1)
    pixels=np.clip(image*255.,0,255).round().astype(np.uint8)
    pixels=cv2.cvtColor(pixels,cv2.COLOR_RGB2BGR)
    header=np.zeros((34,pixels.shape[1],3),np.uint8)
    for i,label in enumerate(labels):
        cv2.putText(header,label,(i*images[0].shape[1]+10,23),cv2.FONT_HERSHEY_SIMPLEX,.60,(235,235,235),1,cv2.LINE_AA)
    if not cv2.imwrite(str(path),np.concatenate((header,pixels),axis=0)):
        raise OSError('opaque_compare_preview_write')


def _q_heatmap(q):
    image=cv2.applyColorMap((np.clip(q,0,1)*255).round().astype(np.uint8),cv2.COLORMAP_VIRIDIS)
    return cv2.cvtColor(image,cv2.COLOR_BGR2RGB).astype(np.float32)/255.


def _bbox(mask,padding=12):
    y,x=np.where(mask)
    if not len(x):return None
    h,w=mask.shape
    return max(0,int(x.min())-padding),max(0,int(y.min())-padding),min(w,int(x.max())+padding+1),min(h,int(y.max())+padding+1)


def compare(before,candidate,output):
    roots=[resolve(before),resolve(candidate)];out=resolve(output)
    if out.exists():raise FileExistsError(out)
    configs=[read_json(root/'config.json') for root in roots]
    prepared=[resolve(config['prepared']) for config in configs]
    metas=[read_json(root/'preparation.json') for root in prepared]
    frozen={}
    def remember(path):frozen[str(path)]=digest(path);return frozen[str(path)]
    for name in ('preparation.json','local_geometry.npz'):
        if len({remember(root/name) for root in prepared})!=1:
            raise ValueError('opaque_compare_different_preparation:'+name)
    if len({config['sourceSha256'] for config in configs}|{meta['sourceHash'] for meta in metas})!=1:
        raise ValueError('opaque_compare_source_mismatch')
    if configs[0].get('antialiased')!=configs[1].get('antialiased'):
        raise ValueError('opaque_compare_rasterization_mode_mismatch')
    domains=[config.get('observedFaceDomain') for config in configs]
    if any(not value for value in domains):raise ValueError('opaque_compare_observed_domain_required')
    for key in ('maskHashes','skinMaskHashes'):
        if domains[0].get(key)!=domains[1].get(key) or not domains[0].get(key):
            raise ValueError('opaque_compare_observation_domain_mismatch:'+key)
    views=[read_json(root/'portrait.view.json') for root in roots]
    if len({view['sourceFrame'] for view in views})!=1:raise ValueError('opaque_compare_reference_mismatch')
    sets=[{path.name[:-4] for path in (root/'full-final').glob('*.npz')} for root in roots]
    if not sets[0] or sets[0]!=sets[1]:raise ValueError('opaque_compare_full_view_set_mismatch')
    names=sorted(sets[0])
    with np.load(prepared[0]/'local_geometry.npz',allow_pickle=False) as a:
        geometry={key:a[key].copy() for key in ('names','roles','F','world_names','C','K')}
    K=geometry['K'];F=dict(zip(geometry['names'].tolist(),geometry['F']))
    C=dict(zip(geometry['world_names'].tolist(),geometry['C']))
    roles=dict(zip(geometry['names'].tolist(),geometry['roles'].tolist()))
    opaque_configs=[]
    for root,config in zip(roots,configs):
        if config.get('opaquePerson'):
            receipt=read_json(root/'opaque-interiors.json')
            if remember(root/'opaque-interiors.json')!=config['opaqueInteriorsReceiptSha256']:
                raise ValueError('opaque_compare_opaque_receipt_changed')
            opaque_configs.append(receipt)
        else:opaque_configs.append(None)
    active_configs=[receipt for receipt in opaque_configs if receipt]
    conf=OpaquePersonConfig(**active_configs[0][names[0]]['config']) if active_configs else OpaquePersonConfig()
    report=dict(sourceSha256=configs[0]['sourceSha256'],reference=views[0]['sourceFrame'],
        preparedSha256=frozen[str(prepared[0]/'preparation.json')],
        localGeometrySha256=frozen[str(prepared[0]/'local_geometry.npz')],
        colourContract='stored_native_float; no clipping, gamma, exposure or tonemapping for metrics',
        backgroundContract={'white':[1,1,1],'nightSky':NIGHT_SKY.tolist(),
            'purpose':'transmission diagnostic, not viewer screenshot or room completion'},
        qContract={'qPerson':[1,4],'qAllPerson':[1,2,3,4],'qRoom':0,
            'roomRgbAvailable':False,'roomMap':'actual alpha-weighted group contribution, not RGB'},
        antialiased=configs[0].get('antialiased'),views={},runs=[],zeroTraining=True,gpuUsed=False,
        limitations=['Current development/reference images are not new independent blind tests.',
            'All fixed-mask pixels enter primary RGB errors, including missing pixels.',
            'Alpha/contribution thresholds do not establish measured geometry.',
            'Blotch proxies do not replace the original/candidate visual comparison.',
            'This reads cached gsplat renders; it is not PlayCanvas or HarmonyOS evidence.'])
    for root,config,view in zip(roots,configs,views):
        asset_hash=remember(root/'portrait.gaussian.ply')
        if asset_hash!=view['assetSha256']:raise ValueError('opaque_compare_ply_view_identity')
        report['runs'].append(dict(path=str(root),assetSha256=asset_hash,
            configSha256=remember(root/'config.json'),reference=remember(root/'portrait.view.json'),
            implementation=config.get('implementation'),opaquePerson=config.get('opaquePerson',False)))
    out.mkdir(parents=True)
    for name in names:
        source_path=prepared[0]/'rectified_observations'/name
        mask_path=prepared[0]/'rectified_observations'/(name+'.npz')
        remember(source_path);remember(mask_path)
        with np.load(mask_path,allow_pickle=False) as a:old={key:a[key].copy() for key in a.files}
        classes,confidence,outside,labels=original_semantics(prepared[0],metas[0],name,K,old)
        mask_root=Path(metas[0]['masks'])
        remember(mask_root/'labels'/(name+'.png'));remember(mask_root/'confidence'/(name+'.npz'))
        training_face=observed_face_domain(classes,confidence,outside,labels)
        training_skin=training_face&(classes==3)&(confidence>=.70)&~outside
        for domain in domains:
            if mask_hash(training_face)!=domain['maskHashes'][name] or mask_hash(training_skin)!=domain['skinMaskHashes'][name]:
                raise ValueError('opaque_compare_recorded_face_mask_changed:'+name)
        labels.update(training_face=training_face,training_skin=training_skin)
        opaque,receipt=prepare_opaque_interiors(labels,config=conf)
        for saved in active_configs:
            if receipt!=saved[name]:raise ValueError('opaque_compare_recorded_opaque_mask_changed:'+name)
        regions={**opaque,'observed_face':training_face,'observed_room':labels['observed_room'],
            'observed_cloth':labels['observed_cloth'],'observed_neck_skin':labels['observed_body_skin'],
            'hair':labels['hair_visible'],'glasses':labels['glasses_visible']}
        bands,radius=boundary_regions(classes,labels['face_core']|labels['face_boundary'],outside)
        regions.update({key:value for key,value in bands.items() if key.endswith(('_edge','_near'))})
        source_bgr=cv2.imread(str(source_path))
        if source_bgr is None:raise ValueError('opaque_compare_source_image_missing')
        source=cv2.cvtColor(source_bgr,cv2.COLOR_BGR2RGB).astype(np.float32)/255.
        rendered=[]
        for root in roots:
            path=root/'full-final'/(name+'.npz');remember(path)
            with np.load(path,allow_pickle=False) as a:r={key:a[key].copy() for key in a.files}
            for key,expected in (('K',K),('C',C[name]),('F',F[name])):
                np.testing.assert_allclose(r[key],expected,rtol=0,atol=1e-8)
            for key in ('K','C','F'):
                if rendered:np.testing.assert_array_equal(r[key],rendered[0][key])
            if r['rgb'].shape!=source.shape or r['alpha'].shape!=source.shape[:2] or r['q'].shape!=(*source.shape[:2],5):
                raise ValueError('opaque_compare_native_shape_changed')
            if not all(np.isfinite(r[key]).all() for key in ('rgb','alpha','q')):
                raise ValueError('opaque_compare_nonfinite')
            if np.max(np.abs(r['q'].sum(-1)-r['alpha']))>2e-5:
                raise ValueError('opaque_compare_source_conservation')
            rendered.append(r)
        values={key:[region_metrics(r,source,mask) for r in rendered] for key,mask in regions.items()}
        report['views'][name]=dict(role=roles[name],nativeSize=[source.shape[1],source.shape[0]],
            maskHashes={key:mask_hash(value) for key,value in regions.items()},
            opaqueReceipt=receipt,boundaryRadiusNativePixels=radius,regions=values)
        _save_strip(out/(name+'.full.png'),[source]+[r['rgb'] for r in rendered],['Source','Before','Candidate'])
        for label,bg in (('white',np.ones(3,np.float32)),('night',NIGHT_SKY)):
            _save_strip(out/(name+'.'+label+'.png'),[source]+[r['rgb']+(1-r['alpha'])[...,None]*bg for r in rendered],
                ['Source','Before / '+label,'Candidate / '+label])
        maps=[_q_heatmap(r['q'][...,0]) for r in rendered]
        _save_strip(out/(name+'.qroom.png'),[source]+maps,['Source','Before q_room 0..1','Candidate q_room 0..1'])
        for label,mask in (('face',training_face),('hair',labels['hair_visible']),
                           ('neck',labels['observed_body_skin']),('clothing',labels['observed_cloth'])):
            box=_bbox(mask)
            if box is None:continue
            x0,y0,x1,y1=box
            _save_strip(out/(name+'.'+label+'.png'),
                [image[y0:y1,x0:x1] for image in [source,rendered[0]['rgb'],rendered[1]['rgb'],*maps]],
                ['Source','Before','Candidate','Before q_room','Candidate q_room'])
    summary={}
    for region in next(iter(report['views'].values()))['regions']:
        rows=[view['regions'][region] for view in report['views'].values()]
        valid=[pair for pair in rows if pair[0]['pixels']]
        if not valid:continue
        summary[region]={'viewCount':len(valid),'pixels':sum(pair[0]['pixels'] for pair in valid)}
        for metric in ('premultRgbL1','whiteBackdropRgbL1','nightBackdropRgbL1','qPersonMean','qAllPersonMean','qRoomMean','qHairMean','qBodyMean',
                       'personBelow095','personBelow08','alphaMean','alphaBelow08','nativeGradientL1'):
            useful=[pair for pair in valid if all(item[metric] is not None for item in pair)]
            if not useful:continue
            means=[float(np.mean([pair[i][metric] for pair in useful])) for i in (0,1)]
            weighted=[float(np.average([pair[i][metric] for pair in useful],weights=[pair[i]['pixels'] for pair in useful])) for i in (0,1)]
            summary[region][metric]=dict(viewMean=means,pixelWeightedMean=weighted,
                candidateMinusBefore=means[1]-means[0],
                perViewDelta=[pair[1][metric]-pair[0][metric] for pair in useful])
    report.update(summary=summary,inputHashes=frozen,renderSource='cached_gsplat_native_full_frame',
        status='diagnostic_comparison_not_quality_acceptance')
    # Confirm the immutable inputs still match after writing independent images.
    for path,expected in frozen.items():
        if digest(path)!=expected:raise ValueError('opaque_compare_input_changed_during_read:'+path)
    (out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--before',required=True)
    parser.add_argument('--candidate',required=True);parser.add_argument('--output',required=True)
    result=compare(**vars(parser.parse_args()))
    print(json.dumps(dict(status=result['status'],views=len(result['views']),zeroTraining=True,gpuUsed=False)))
