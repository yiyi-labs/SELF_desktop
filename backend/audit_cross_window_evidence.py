"""Bounded evidence collection for explicit current-run assets; never selects a winner.
Private image panels remain in .sources. No gradient, optimization or publishing.
"""
from pathlib import Path
import argparse,json,shutil
import cv2,numpy as np
from reconstruction_components_v3 import sha,save_json,load_v3_prepared
from reconstruction_continuity_surface import physical_masks


def summary(root,complete,out):
    root=Path(root);complete=Path(complete);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(__file__,out/Path(__file__).name)
    folders={'hair-control':root/'hair-all-window/old-patch-control','hair-candidate':root/'hair-all-window/actual-surface-candidate',
        'context':root/'context-appearance-b','face':root/'face-native-coverage'}
    records={}
    for label,folder in folders.items():
        r=json.loads((folder/'result.json').read_text());records[label]={k:r[k] for k in ('assetHash','steps','failures','allocatedMiB','reservedMiB','parameterChanges','frozenBaselineExact')}
        for key in ('seconds','trainSeconds','trainEvalSeconds'):
            if key in r:records[label][key]=r[key]
        records[label]['sourceSnapshot']={p.name:sha(p) for p in (root/'hair-all-window/algorithm-source' if label.startswith('hair') else folder/'algorithm-source').glob('*.py')}
        records[label]['fullFramePairs']=[]
        for n,a in r['baseline'].items():
            b=r['final'][n]
            for part in a:
                if part in b:records[label]['fullFramePairs'].append(dict(imageName=n,part=part,before=a[part],after=b[part]))
        if 'localFinal' in r:
            records[label]['localFramePairs']=r['localFinal']
    save_json(out/'training-summary.json',dict(records=records,HarmonyOSTested=False,productionChanged=False,published=False))
    # Source mask boundary is a diagnostic observation domain, not geometry truth.
    spec=json.loads((complete/'spec.json').read_text());data=load_v3_prepared(spec['prepared'])
    names=[n for n in json.loads((root/'context-appearance-b/result.json').read_text())['baseline']]
    masks=physical_masks(spec['prepared'],data,names);connection={}
    for n in names:
        mask=masks[n];face=mask['face'];neck=mask['neck'];kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(21,21))
        band=(cv2.dilate(face.astype(np.uint8),kernel)>0)&(cv2.dilate(neck.astype(np.uint8),kernel)>0)&(face|neck)
        if not band.any():continue
        a=dict(np.load(root/'context-appearance-b/baseline-images'/(n+'.npz')))
        b=dict(np.load(root/'context-appearance-b/final-images'/(n+'.npz')))
        row=dict(observedBandPixels=int(band.sum()),domain='within 10 native pixels of observed face/neck adjacency; cloth excluded')
        for name,r in [('before',a),('after',b)]:
            person=r['q'][...,1]+r['q'][...,4]
            row[name]=dict(rgbL1=float(np.abs(r['rgb']-data['rgb'][n]).mean(-1)[band].mean()),
                personContributionMean=float(person[band].mean()),personContributionBelow08=float((person[band]<.8).mean()),roomContributionMean=float(r['q'][...,0][band].mean()),
                totalAlphaBelow08=float((r['alpha'][band]<.8).mean()))
        connection[n]=row
        ys,xs=np.where(band);h,w=band.shape;x0=max(0,int(xs.min())-30);x1=min(w,int(xs.max())+31);y0=max(0,int(ys.min())-50);y1=min(h,int(ys.max())+51)
        panels=[data['rgb'][n],a['rgb'],b['rgb'],np.repeat((a['q'][...,1]+a['q'][...,4])[...,None],3,axis=2),np.repeat(a['q'][...,0,None],3,axis=2)]
        image=np.concatenate([p[y0:y1,x0:x1] for p in panels],1)
        cv2.imwrite(str(out/('connection-'+n)),cv2.cvtColor((image.clip(0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    save_json(out/'skin-connection.json',dict(frames=connection,coverageProxyNotGeometryTruth=True,geometryChanged=False,published=False))
    print(json.dumps(dict(trainingBranches=len(records),connectionFrames=len(connection))),flush=True)


def display(root,complete,out):
    root=Path(root);complete=Path(complete);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    folders={'baseline':complete,'context':root/'context-appearance-b','face-fixed-order':root/'face-native-fixed-order'}
    assets=[];identity={};records=[];conf=None
    for label,folder in folders.items():
        result=json.loads((folder/'result.json').read_text());d=json.loads((folder/'display.json').read_text());asset=folder/'candidate-research-only.ply';side=dict(np.load(folder/'candidate-identities.npz'))
        if sha(asset)!=result['assetHash'] or str(side['asset_hash'])!=result['assetHash']:raise ValueError('identity_changed')
        if conf is None:conf=d
        elif any(d[k]!=conf[k] for k in ('K','C','width','height','reference','sourceHash')):raise ValueError('display_camera_changed')
        side['asset_sha256']=np.array(result['assetHash']);target=out/(label+'-identities.npz');np.savez_compressed(target,**side);identity[label]=str(target.resolve())
        assets.append(dict(label=label,ply=str(asset.resolve()),hash=result['assetHash'],count=len(side['point_id'])))
        checkpoint=sha(folder/'candidate-final.pt') if (folder/'candidate-final.pt').exists() else json.loads((folder/'order-contract.json').read_text())['checkpointHash']
        records.append(dict(label=label,folder=str(folder),assetHash=result['assetHash'],checkpointHash=checkpoint,approved=False))
    conf['assets']=assets;save_json(out/'display.json',conf);save_json(out/'identity-map.json',identity);save_json(out/'provenance.json',dict(records=records,sourceHash=conf['sourceHash'],reference=conf['reference'],published=False));shutil.copyfile(__file__,out/Path(__file__).name)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--complete',required=True);p.add_argument('--out',required=True);p.add_argument('--display',action='store_true');a=p.parse_args()
    (display if a.display else summary)(a.root,a.complete,a.out)