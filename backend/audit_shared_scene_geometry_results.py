"""Complete frozen-scene quality and standard PLY replay evidence.
Uses source-derived masks/gradients; no training, screening changes or adoption.
"""
from pathlib import Path
import argparse,json,shutil
import numpy as np,cv2
from reconstruction_components_v3 import save_json,sha
from reconstruction_continuity_surface import physical_masks


def image(path,panels):
    rgb=np.concatenate([np.clip(x,0,1) for x in panels],1)
    cv2.imwrite(str(path),cv2.cvtColor(np.rint(rgb*255).astype(np.uint8),cv2.COLOR_RGB2BGR))


def run(root,out,orbit=False):
    root=Path(root);out=Path(out);out.mkdir(exist_ok=False)
    shutil.copyfile(__file__,out/Path(__file__).name)
    contract=json.loads((root/'contract.json').read_text());prep=Path(contract['spec']['prepared'])
    config=json.loads((root/'config.json').read_text());reference=contract['reference']
    paths={'baseline':root/'baseline-images','control':root/'appearance-control/final-images','shared':root/'shared-geometry/final-images'}
    results={label:json.loads((root/folder/'result.json').read_text()) for label,folder in [('control','appearance-control'),('shared','shared-geometry')]}
    names=list(results['shared']['final']);raw=dict(np.load(prep/'local_geometry.npz'))
    data=dict(K=raw['K'],rgb={},labels={});rows={}
    for n in names:
        data['rgb'][n]=cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        data['labels'][n]=dict(np.load(prep/'rectified_observations'/(n+'.npz')))
    masks=physical_masks(prep,data,names)
    for n in names:
        target=data['rgb'][n];a={k:dict(np.load(path/(n+'.npz'))) for k,path in paths.items()}
        gray=cv2.cvtColor(target,cv2.COLOR_RGB2GRAY)
        gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)/8;gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)/8
        low=masks[n]['room']&(np.sqrt(gx*gx+gy*gy)<.015)
        cloth=masks[n]['cloth'].astype(np.uint8)
        band=(cv2.dilate(cloth,np.ones((9,9),np.uint8))>0)&~(cv2.erode(cloth,np.ones((9,9),np.uint8))>0)
        region=dict(masks[n],low_texture_room=low,cloth_boundary=band);row={}
        for part,m in region.items():
            if not m.any():continue
            row[part]={}
            for label,r in a.items():
                error=np.abs(r['rgb']-target).mean(-1);luma=(r['rgb']-target)@np.array([.2126,.7152,.0722])
                row[part][label]=dict(rgb=float(error[m].mean()),positiveLuminanceBias=float(np.maximum(luma[m],0).mean()),
                    brightOvershoot015=float((luma[m]>.15).mean()),alpha=float(r['alpha'][m].mean()),
                    holes=float((r['alpha'][m]<.8).mean()),roomContribution=float(r['q'][...,0][m].mean()),
                    qConservationMax=float(np.abs(r['q'].sum(-1)-r['alpha']).max()),pixels=int(m.sum()))
        rows[n]=row;panels=[target]+[a[k]['rgb'] for k in paths]
        image(out/(n+'.jpg'),panels)
        for part in ('face','hair','neck','cloth','cloth_boundary'):
            y,x=np.where(region[part])
            if not len(x):continue
            x0=max(0,x.min()-12);x1=min(target.shape[1],x.max()+13);y0=max(0,y.min()-12);y1=min(target.shape[0],y.max()+13)
            image(out/(n+'.'+part+'.png'),[v[y0:y1,x0:x1] for v in panels])
    summary={}
    for group,selected in [('complete_evaluation',names),('world_development',[n for n in names if n in config['development']])]:
        summary[group]={}
        for part in ('face','hair','neck','cloth','room','low_texture_room','cloth_boundary'):
            rr=[rows[n][part] for n in selected if part in rows[n]]
            summary[group][part]={label:{metric:float(np.mean([r[label][metric] for r in rr])) for metric in ('rgb','positiveLuminanceBias','brightOvershoot015','alpha','holes','roomContribution')} for label in paths}
    result=dict(rows=rows,summary=summary,sourceHash=contract['sourceHash'],reference=reference,assets={k:v['assetHash'] for k,v in results.items()},
        columns=['source','frozen_complete_baseline','appearance_control','shared_geometry'],
        notes='Low texture from original gradients, not SIFT/support mask. Alpha<.8 is a rendering proxy, not absence of geometry. Bright bias is a haze proxy, not proof of correct surfaces.',
        changedPersonParameters=0,HarmonyOSTested=False,published=False)
    save_json(out/'quality.json',result);print(json.dumps(summary['world_development']),flush=True)
    if orbit:
        # Isolated metadata adapter: copied bytes must remain the exact same PLY.
        folder=root/'shared-geometry';proxy=out/'frozen-asset-input';proxy.mkdir()
        shutil.copyfile(folder/'candidate-research-only.ply',proxy/'candidate-research-only.ply')
        if sha(proxy/'candidate-research-only.ply')!=results['shared']['assetHash']:raise ValueError('orbit_asset_changed')
        side=dict(np.load(folder/'candidate-identities.npz'));side['asset_sha256']=side['asset_hash']
        np.savez_compressed(proxy/'candidate-identities.npz',**side)
        save_json(proxy/'result.json',results['shared']);save_json(proxy/'spec.json',contract['spec'])
        from audit_dense_surface_asset import run as frozen_asset
        frozen_asset(proxy,out/'frozen-ply')
        r=dict(np.load(out/'frozen-ply/gsplat-reference.npz'));old=dict(np.load(paths['shared']/(reference+'.npz')))
        save_json(out/'export-reload.json',dict(maxError={k:float(np.abs(r[k]-old[k]).max()) for k in ('rgb','alpha','q')},
            assetHash=results['shared']['assetHash'],sourceHash=contract['sourceHash'],reference=reference,renderer='gsplat1.5.3',published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);p.add_argument('--orbit',action='store_true')
    a=p.parse_args();run(a.root,a.out,a.orbit)