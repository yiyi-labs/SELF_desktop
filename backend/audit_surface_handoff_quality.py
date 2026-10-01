"""Source-fixed appearance/coverage audit of a same-budget surface experiment."""
from pathlib import Path
import argparse,json,cv2,numpy as np
from reconstruction_continuity_surface import physical_masks
from reconstruction_components_v3 import save_json,sha


def write(path,images):
    im=np.concatenate([np.clip(x,0,1) for x in images],axis=1)
    cv2.imwrite(str(path),cv2.cvtColor(np.rint(im*255).astype(np.uint8),cv2.COLOR_RGB2BGR))


def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(exist_ok=False)
    spec=json.loads((root/'spec.json').read_text());prep=Path(spec['prepared'])
    result={k:json.loads((root/k/'result.json').read_text()) for k in ('original-control','surface-replacement')}
    names=list(result['surface-replacement']['baseline']);g=dict(np.load(prep/'local_geometry.npz'))
    data=dict(K=g['K'],rgb={},labels={})
    for n in names:
        data['rgb'][n]=cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        data['labels'][n]=dict(np.load(prep/'rectified_observations'/(n+'.npz')))
    masks=physical_masks(prep,data,names);rows={}
    for n in names:
        target=data['rgb'][n];records={label:dict(np.load(root/path/(n+'.npz'))) for label,path in [('baseline','baseline-images'),('original-control','original-control/final-images'),('surface-replacement','surface-replacement/final-images')]}
        gray=cv2.cvtColor(target,cv2.COLOR_RGB2GRAY);gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)/8;gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)/8
        low=masks[n]['room']&(np.sqrt(gx*gx+gy*gy)<.015);regions=dict(masks[n],low_texture_room=low)
        row={}
        for region,m in regions.items():
            if not m.any():continue
            row[region]={}
            for label,r in records.items():
                error=np.abs(r['rgb']-target).mean(-1);luma=(r['rgb']-target)@np.array([.2126,.7152,.0722])
                row[region][label]=dict(rgb=float(error[m].mean()),positiveLuminanceBias=float(np.maximum(luma[m],0).mean()),brightOvershoot015=float((luma[m]>.15).mean()),holes=float((r['alpha'][m]<.8).mean()),roomContribution=float(r['q'][...,0][m].mean()),pixels=int(m.sum()))
        rows[n]=row
        write(out/(n+'.jpg'),[target]+[records[k]['rgb'] for k in ('baseline','original-control','surface-replacement')])
        for layer in ('face','hair','neck','cloth','room'):
            y,x=np.where(masks[n][layer])
            if not len(x):continue
            x0=max(0,x.min()-10);x1=min(target.shape[1],x.max()+11);y0=max(0,y.min()-10);y1=min(target.shape[0],y.max()+11)
            imgs=[target]+[records[k]['rgb'] for k in ('baseline','original-control','surface-replacement')]
            write(out/(n+'.'+layer+'.png'),[v[y0:y1,x0:x1] for v in imgs])
    summary={}
    for region in ('face','hair','neck','cloth','room','low_texture_room'):
        group=[r[region] for r in rows.values() if region in r];summary[region]={label:{metric:float(np.mean([g[label][metric] for g in group])) for metric in ('rgb','positiveLuminanceBias','brightOvershoot015','holes','roomContribution')} for label in ('baseline','original-control','surface-replacement')}
    save_json(out/'quality.json',dict(rows=rows,summary=summary,columns=['source','baseline','control','surface'],
        limits='Positive brightness bias is only a haze proxy, not proof of geometry correctness. Low texture selected from source gradients, never SIFT or candidate coverage.',
        sourceHash=result['surface-replacement']['sourceHash'],assets={k:v['assetHash'] for k,v in result.items()},published=False))
    reference=json.loads((root/'contract.json').read_text())['reference'];target=data['rgb'][reference];desktop=root/'display/playcanvas-01'
    if desktop.exists():
        measured={};pc_images=[];h,w=target.shape[:2]
        for label,path in [('baseline','baseline-images'),('control','original-control/final-images'),('candidate','surface-replacement/final-images')]:
            raw=np.fromfile(desktop/(label+'.rgba'),np.uint8).reshape(h,w,4)[::-1].astype(np.float32)/255
            rgb=raw[:,:,:3];gs=dict(np.load(root/path/(reference+'.npz')))['rgb'];pc_images.append(rgb)
            row=dict(fullframeRendererMAE=float(np.abs(rgb-gs).mean()),rawPremultiplied=True)
            for part,m in masks[reference].items():
                if m.any():row[part]=dict(rgbToSource=float(np.abs(rgb-target).mean(-1)[m].mean()),rendererMAE=float(np.abs(rgb-gs).mean(-1)[m].mean()))
            measured[label]=row
        save_json(out/'desktop-comparison.json',dict(rows=measured,renderer='PlayCanvas2.22.4 actual desktop SwiftShader',notHarmonyOS=True,reference=reference))
        write(out/'source-baseline-control-candidate-PlayCanvas.jpg',[target]+pc_images)
    print(json.dumps(summary),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.root,a.out)
