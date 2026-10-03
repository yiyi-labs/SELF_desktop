"""Corrected silhouette audit from cached native renders and CPU footprints.

Rectification outside pixels never define a person's contour. Earlier reports
are retained and explicitly superseded, not overwritten.
"""
from pathlib import Path
import argparse,json
import cv2
import numpy as np
from reconstruction_live_dense import read_prepared,mask_at
from audit_live_boundary_coverage import boundary_regions,original_semantics,sha


def audit(run,comparison,footprints,pool,counterfactual,output):
    run,comparison,footprints,pool,counterfactual,output=map(Path,(run,comparison,footprints,pool,counterfactual,output))
    output.mkdir(parents=True,exist_ok=False)
    cfg=json.loads((run/'config.json').read_text());data=read_prepared(cfg['prepared'])
    bundle=json.loads(Path(cfg['denseSurfaces']['manifestPath']).read_text());reference=bundle['reference']
    old_potential=np.load(footprints/'room-potential.npz')['final_potential_alpha']
    candidate=np.load(pool/'potential.npz');retired=np.load(pool/'retired-room-potential.npz')['alpha']
    rows=[];reference_masks=None;reference_actual=None;reference_source=None
    for path in sorted((run/'full-final').glob('*.npz')):
        name=path.name[:-4];raw=dict(np.load(data['prepared']/'rectified_observations'/(name+'.npz')))
        classes,cf,outside,labels=original_semantics(data['prepared'],data['metadata'],name,data['K'],raw)
        bands,radius=boundary_regions(classes,labels['face_core']|labels['face_boundary'],outside)
        rgb=cv2.cvtColor(cv2.imread(str(data['prepared']/'rectified_observations'/name)),cv2.COLOR_BGR2RGB)/255
        statistics={}
        for stage,parent in [('baseline',run),('observed_empty',comparison)]:
            arr=dict(np.load(parent/'full-final'/(name+'.npz')));np.testing.assert_allclose(arr['K'],data['K'],atol=1e-8,rtol=0)
            statistics[stage]={key:dict(pixels=int(mask.sum()),RGBL1=float(np.abs(arr['rgb'][mask]-rgb[mask]).mean()),
                alphaBelow08=float((arr['alpha'][mask]<.8).mean()),alphaBelow001=float((arr['alpha'][mask]<.01).mean()),
                qRoomBelow001=float((arr['q'][...,0][mask]<.01).mean()),q=arr['q'][mask].mean(0).tolist())
                for key,mask in bands.items() if mask.any()}
            if name==reference and stage=='baseline':reference_actual=arr
        rows.append(dict(name=name,radius=radius,statistics=statistics))
        if name==reference:reference_masks={k:v&labels['observed_room'] for k,v in bands.items() if k.startswith('room_')};reference_source=rgb;reference_bands=bands
    effects={}
    for key,mask in reference_masks.items():
        black=mask&(reference_actual['alpha']<.01)&(reference_actual['q'][...,0]<.01)
        effects[key]=dict(pixels=int(mask.sum()),actualAlphaBelow001=int(black.sum()),
            actualAlphaBelow08=int((mask&(reference_actual['alpha']<.8)).sum()),
            currentRoomPotentialBelow08=int((mask&(old_potential<.8)).sum()),
            withAllOmittedCandidatesPotentialBelow08=int((mask&(candidate['combined']<.8)).sum()),
            blackOmittedPotentialAbove001=int((black&(candidate['omitted']>.01)).sum()),
            blackOmittedPotentialAbove08=int((black&(candidate['omitted']>.8)).sum()),
            blackRetiredPotentialAbove001=int((black&(retired>.01)).sum()),
            blackRetiredPotentialAbove08=int((black&(retired>.8)).sum()))
    black_all=(reference_masks['room_edge']|reference_masks['room_near'])&(reference_actual['alpha']<.01)&(reference_actual['q'][...,0]<.01)
    centres=dict(np.load(pool/'all_centres-nearest-centres.npz'));p=np.floor(centres['target_uv']).astype(int)
    subset=black_all[p[:,1],p[:,0]]
    if int(subset.sum())!=int(black_all.sum()):raise ValueError('cached_attribution_does_not_cover_corrected_silhouette')
    attribution=dict(pixels=int(subset.sum()),nearestAllGridDistancePixels=np.quantile(centres['distance'][subset],[.1,.5,.9]).tolist(),
        within16pxReasons={str(k):int((subset&(centres['distance']<16)&(centres['reason']==k)).sum()) for k in np.unique(centres['reason'])},
        sourceReferenceIndices={str(k):int((subset&(centres['source']==k)).sum()) for k in np.unique(centres['source'])})
    gains={}
    for part in ('room','body'):
        a=dict(np.load(counterfactual/(part+'-source-grid.npz')))
        gains[part]={band:dict(addedPassingOriginalSupport=int((a['added']&mask_at(reference_bands[part+'_'+band],a['native_uv'])).sum()),
            lostOriginalAccepted=int((a['lost']&mask_at(reference_bands[part+'_'+band],a['native_uv'])).sum())) for band in ('edge','near')}
    base=json.loads(Path(bundle['parentManifestPath']).read_text());parent_path=Path(base['parentManifestPath']);parent=json.loads(parent_path.read_text())
    original=dict(np.load(parent['components']['room']['path']));current=dict(np.load(bundle['components']['room']['path']))
    alive=set(map(int,current['uid']));indices=np.flatnonzero([int(uid) not in alive for uid in original['uid']])
    np.savez_compressed(output/'retired-original-identity.npz',original_indices=indices,uid=original['uid'][indices],
        original_parent=np.asarray(str(parent_path)),original_asset=np.asarray(parent['components']['room']['path']),
        original_asset_sha256=np.asarray(sha(parent['components']['room']['path'])))
    preview=(reference_source*255).round().astype(np.uint8);preview[black_all]=(255,40,40)
    cv2.imwrite(str(output/'actual-person-contour-black-holes.png'),cv2.cvtColor(preview,cv2.COLOR_RGB2BGR))
    report=dict(reference=reference,sourceHash=bundle['sourceSha256'],maskCodeSha256=sha(Path(__file__).with_name('audit_live_boundary_coverage.py')),
        correction='Invalid rectification canvas does not count as an opposing semantic class. Distance is to actual valid person/room pixels.',
        supersedesOnlyBandStatistics=[str(footprints/'report.json'),str(pool/'report.json'),str(pool/'black-hole-all-centres.json'),str(counterfactual/'report.json')],
        originalReportsPreserved=True,views=rows,candidateEffects=effects,blackHoleSourceAttribution=attribution,derivativeGains=gains,
        originalParentManifestPath=str(parent_path),originalParentManifestSha256=sha(parent_path),retiredIdentityCount=len(indices),
        qOrder=['room','skin','hair','glasses','body'],
        limitations=['Cached actual GPU pixels are unchanged. CPU potential is conservative, not exact renderer parity or geometry truth.',
            'Budget-pool counts and scene-global footprint arrays remain valid; earlier perimeter totals including canvas edges are superseded.',
            'No source cameras, geometry, training, masks used by the model, or assets were changed.'])
    (output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:report[k] for k in ('candidateEffects','blackHoleSourceAttribution','derivativeGains')},indent=2));return report


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('run','comparison','footprints','pool','counterfactual','output'):p.add_argument('--'+key,required=True)
    audit(**vars(p.parse_args()))
