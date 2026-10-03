"""CPU replay of qualified room candidate pools; no solver or asset mutation.

Uses original corrected surfaces, filters, deduplication, and footprints. The
potential-alpha counterfactual is diagnostic only, not a new reconstruction.
"""
from pathlib import Path
import argparse, json, hashlib
import cv2
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from reconstruction_live_dense import (read_prepared, physical_masks, surface_samples,
    support_samples, mask_at, native_uv, training_name_scopes, resolve_path, select_budget)
from reconstruction_live_dense_contract import project, bilinear, digest
from reconstruction_observation_domains import attach_observation_domains
from reconstruction_live_room_completion import deduplicate_new_surface
from audit_live_boundary_coverage import original_semantics, boundary_regions
from audit_live_boundary_footprints import potential_alpha


def candidate_pool(proof, bundle, data, names, masks, rgb, root, depth_manifest):
    surface=dict(np.load(proof['surfacePath'],allow_pickle=False))
    report=json.loads(Path(proof['solverReportPath']).read_text()); ref=proof['referenceName']
    uv,xyz,basis,scales,derivative=surface_samples(surface['referenceDepthAfter'],surface['K'],surface['W2C'])
    native=native_uv(uv,surface['nativeToProcessed']); semantic=mask_at(masks[ref],native)
    colours=bilinear(rgb[ref],native); finite=np.isfinite(colours).all(1)
    proposed=derivative&semantic&finite;ids=np.flatnonzero(proposed)
    targets=[(r,dict(np.load(root/r['file'],allow_pickle=False))) for r in depth_manifest['observations']
        if r['group']=='world' and r['window']==report['window']]
    depth,free,occluded=support_samples(xyz[ids],targets,masks,confidence_gate=False)
    image=np.zeros(len(ids),np.int16);colour=image.copy()
    for name in names:
        q,z=project(xyz[ids],data['K'],data['world'][name]); static=(z>0)&mask_at(masks[name],q)
        observed=bilinear(cv2.GaussianBlur(rgb[name],(3,3),0),q)
        image+=static;colour+=static&np.isfinite(observed).all(1)&(np.abs(observed-colours[ids]).mean(1)<=.12)
    strict=(depth>=3)&(free<=1);soft=(depth<3)&(image>=3)&(colour>=3)&(free<=1)
    accepted=strict|soft;keep=ids[accepted]
    trainuv=np.array([t['referenceProcessedUV'] for t in report['tracks'] if t['role']=='fit'])
    distance=cKDTree(trainuv).query(uv[keep])[0]; confidence=np.clip(.15+.65*np.exp(-distance/24),.15,.8)
    surface_hash=digest(proof['surfacePath'])
    uid=np.array([int.from_bytes(hashlib.sha256(f'SHARED:{bundle["sourceSha256"]}:{surface_hash}:{int(i)}'.encode()).digest()[:8],'little')&((1<<63)-1) for i in keep],np.int64)
    fresh=dict(means=xyz[keep],scales=scales[keep],normal=basis[keep,:,2],
        quats=Rotation.from_matrix(basis[keep]).as_quat()[:,[3,0,1,2]],opacity=np.full(len(keep),.6),
        confidence=confidence,support=depth[accepted],uid=uid,layer=np.full(len(keep),'room'),
        source_original_index=keep,source_uv=native[keep])
    reason=np.full(len(uv),0,np.int16)
    reason[~derivative]=1;reason[derivative&~semantic]=2;reason[derivative&semantic&~finite]=3
    reason[ids[~accepted&(free>1)]]=4
    reason[ids[~accepted&(free<=1)]]=5
    reason[keep]=6
    return fresh,dict(reference=ref,totalGrid=len(uv),derivativeRejected=int((~derivative).sum()),
        nativeRoomGrid=int(semantic.sum()),derivativeRejectedInSourceRoom=int((~derivative&semantic).sum()),
        proposed=int(proposed.sum()),freeRejected=int((free>1).sum()),
        imageOrColourSupportRejected=int((~accepted&(free<=1)).sum()),accepted=len(keep)),dict(
        xyz=xyz,native_uv=native,reason=reason,grid_uv=uv,semantic=semantic,derivative=derivative)


def audit(run,output):
    run=Path(run).resolve();out=Path(output).resolve();out.mkdir(parents=True,exist_ok=False)
    cfg=json.loads((run/'config.json').read_text());data=read_prepared(cfg['prepared'])
    bundle=json.loads(Path(cfg['denseSurfaces']['manifestPath']).read_text());row=bundle['components']['room']
    root=Path(bundle['depthManifestPath']).parent;request=json.loads((root/'request.json').read_text())
    scope=training_name_scopes(data,request.get('splitPath'),expected_split_hash=request.get('splitHash'))
    names=[n for n in scope['geometryTrain'] if n in data['world']]
    labels={n:dict(np.load(data['prepared']/'rectified_observations'/(n+'.npz'))) for n in names}
    context=dict(labels=labels,K=data['K'],staticMap=str(resolve_path(data['metadata']['staticMap'],data['prepared'])))
    attach_observation_domains(context,data['prepared']);masks={n:physical_masks(labels[n])['room'] for n in names}
    rgb={n:cv2.cvtColor(cv2.imread(str(data['prepared']/'rectified_observations'/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255 for n in names}
    dm=json.loads(Path(bundle['depthManifestPath']).read_text());final=dict(np.load(row['path']))
    original_base=dict(np.load(row['surfaceBaseComponent']['path']))
    proof_paths=[row['surfaceCorrectionReceipt']]+[x['path'] for x in row['additionalSurfaceReceipts']]
    existing=[original_base];missed=[];rows=[]
    for index,proof_path in enumerate(proof_paths):
        proof=json.loads(Path(proof_path).read_text());fresh,summary,grid=candidate_pool(proof,bundle,data,names,masks,rgb,root,dm)
        wanted=proof['newSurfaceCount'] if index==0 else proof['newCandidatesBeforeDedup']
        if len(fresh['means'])!=wanted:raise ValueError('candidate_pool_replay_count_changed:'+str(index))
        unique=np.ones(len(fresh['means']),bool) if index==0 else deduplicate_new_surface(fresh,existing)
        final_ids=set(map(int,final['uid']));selected=np.asarray([int(uid) in final_ids for uid in fresh['uid']])
        removed=unique&~selected;omitted={k:v[removed] for k,v in fresh.items()}
        missed.append(omitted);summary.update(afterCrossSurfaceDedup=int(unique.sum()),selectedInCurrentAsset=int(selected.sum()),
            omittedLegalCandidates=int(removed.sum()),alreadyRepresentedOrDuplicate=int((~unique).sum()))
        if index:
            addition=row['additionalSurfaceReceipts'][index-1]
            existing.append(dict(np.load(addition['assetPath'])))
        np.savez_compressed(out/f'pool-{index}.npz',**fresh)
        np.savez_compressed(out/f'grid-{index}.npz',**grid)
        rows.append(summary);print(json.dumps(summary),flush=True)
    reference=bundle['reference']; old=dict(np.load(data['prepared']/'rectified_observations'/(reference+'.npz')))
    classes,cf,outside,lab=original_semantics(data['prepared'],data['metadata'],reference,data['K'],old)
    regions,radius=boundary_regions(classes,lab['face_core']|lab['face_boundary'],outside)
    actual=dict(np.load(run/'full-final'/(reference+'.npz')))
    prior=np.load(run.parent/'live-complete-repair-20261003-unified-boundary-footprints/room-potential.npz')['final_potential_alpha']
    # Original missing seeds keep original scale/opacity. Current points remain
    # bitwise untouched. No output PLY/production bundle is created.
    allmissing={k:np.concatenate([a[k] for a in missed]) for k in missed[0]}
    groups=np.concatenate([np.full(len(a['means']),str(i)) for i,a in enumerate(missed)])
    extra,by,projection=potential_alpha(**{k:allmissing[k] for k in ('means','scales','quats','opacity')},
        K=data['K'],C=actual['C'],size=(classes.shape[1],classes.shape[0]),groups=groups)
    potential=1-(1-prior)*(1-extra);results={}
    for name in ('room_edge','room_near','room_interior'):
        mask=regions[name]&lab['observed_room'];black=mask&(actual['q'][...,0]<.01)&(actual['alpha']<.01)
        room_black=mask&(actual['q'][...,0]<.01)
        results[name]=dict(pixels=int(mask.sum()),actualRoomQBelow01=int(room_black.sum()),actualTotalAlphaBelow01=int(black.sum()),
            initialRoomPotentialAtBlackMean=float(prior[black].mean()) if black.any() else None,
            omittedPoolPotentialAtBlackMean=float(extra[black].mean()) if black.any() else None,
            blackPixelsWithCandidatePotentialAbove01=int((black&(extra>.01)).sum()),
            blackPixelsWithCandidatePotentialAbove08=int((black&(extra>.8)).sum()),
            actualAlphaBelow08=int((mask&(actual['alpha']<.8)).sum()),
            potentialBelow08Before=int((mask&(prior<.8)).sum()),potentialBelow08After=int((mask&(potential<.8)).sum()),
            perSourceOmittedPotentialAtBlack={k:float(v[black].mean()) if black.any() else None for k,v in by.items()})
    report=dict(sourceHash=bundle['sourceSha256'],run=str(run),reference=reference,bandRadius=radius,
        roomAssetHash=digest(row['path']),candidatePools=rows,regions=results,projection=projection,
        zeroTraining=True,assetsUnchanged=True,actualOldPointsAllPreserved=True,
        limitations=['CPU potential support only; candidate predictions are conditional, not independent geometry truth.',
            'No sorting/person occlusion or shader parity is claimed.',
            'Omitted candidates use original source footprints and do not enlarge existing Gaussian scales.'])
    (out/'report.json').write_text(json.dumps(report,indent=2));np.savez_compressed(out/'potential.npz',old=prior,omitted=extra,combined=potential)
    print(json.dumps(report,indent=2));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();audit(args.run,args.output)
