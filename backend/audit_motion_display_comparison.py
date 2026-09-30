"""Frozen gsplat/PlayCanvas raw-pixel comparison. No viewer setting changes.
Input sidecars are exact identities for the same PLY, never inferred from RGB.
The browser capture is supplied explicitly; cached runs are not auto-selected.
"""
import argparse,json,shutil
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_portrait_pipeline import draw
from reconstruction_portrait_model import GaussianState
from reconstruction_joint_visibility import load_recorded_ply
from reconstruction_components_v3 import save_json,sha


def host_path(value):
    return Path(str(value).replace(chr(92),'/'))


@torch.no_grad()
def run(prepared,browser_report,identity_map,out):
    prepared=host_path(prepared);browser_report=host_path(browser_report);out=Path(out)
    identities=json.loads(Path(identity_map).read_text(encoding='utf-8-sig'))
    capture=json.loads(browser_report.read_text(encoding='utf-8-sig'));conf=capture['sourceContract']
    raw=dict(np.load(prepared/'local_geometry.npz'))
    ref=conf['reference'];labels=dict(np.load(prepared/'rectified_observations'/(ref+'.npz')))
    source=cv2.cvtColor(cv2.imread(str(prepared/'rectified_observations'/ref)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
    h,w=source.shape[:2]
    if [w,h]!=[conf['width'],conf['height']]:raise ValueError('canvas_contract_changed')
    wi={str(n):i for i,n in enumerate(raw['world_names'])}
    if ref not in wi or not np.array_equal(np.asarray(conf['C'],np.float32),raw['C'][wi[ref]].astype(np.float32)):raise ValueError('world_camera_changed')
    if not np.array_equal(np.asarray(conf['K'],np.float32),raw['K'].astype(np.float32)):raise ValueError('intrinsics_changed')
    sourceHash=str(raw['source_hash']) if 'source_hash' in raw else json.loads((prepared/'preparation.json').read_text())['sourceHash']
    if sourceHash!=conf['sourceHash']:raise ValueError('source_identity_changed')
    out.mkdir(exist_ok=False);shutil.copyfile(__file__,out/Path(__file__).name)
    images=[source];rows={}
    C=torch.tensor(conf['C'],device='cuda',dtype=torch.float32);K=torch.tensor(conf['K'],device='cuda',dtype=torch.float32)
    for recorded in capture['rows']:
        asset=recorded['asset'];name=asset['label'];path=host_path(asset['ply']);identityPath=host_path(identities[name]);ids=dict(np.load(identityPath))
        if sha(path)!=asset['hash'] or str(ids['asset_sha256'])!=asset['hash']:raise ValueError('asset_identity_changed')
        n=len(ids['point_id'])
        if not np.array_equal(ids['point_id'],np.arange(n)) or len(ids['component'])!=n:raise ValueError('sidecar_order_changed')
        z=load_recorded_ply(path,max(1,int((ids['source_namespace']==0).sum())))
        if len(z['means'])!=n or recorded['info']['count']!=n:raise ValueError('point_count_changed')
        if recorded['info']['canvas']!=[w,h] or recorded['errors']:raise ValueError('browser_capture_invalid')
        state=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],torch.as_tensor(ids['component'],device='cuda'))
        r=draw(state,C,K,w,h,unit_scale=float(raw['scale']));rgb=r['rgb'].cpu().numpy();alpha=r['alpha'].cpu().numpy()
        browser=np.fromfile(browser_report.parent/(name+'.rgba'),np.uint8)
        if browser.size!=w*h*4:raise ValueError('raw_capture_size')
        browser=browser.reshape(h,w,4)[::-1].astype(np.float32)/255
        error=np.abs(rgb-browser[...,:3]).mean(-1);alphaError=np.abs(alpha-browser[...,3]);regions={}
        for region,keys in [('face',['face_core','face_boundary']),('hair',['hair_visible']),('cloth',['neck_cloth_visible']),('room',['room_visible'])]:
            mask=np.logical_or.reduce([labels[k] for k in keys])&~labels['unknown_or_occluded']
            regions[region]=dict(rgb=float(error[mask].mean()),alpha=float(alphaError[mask].mean()),gsplatToSource=float(np.abs(rgb-source).mean(-1)[mask].mean()),playcanvasToSource=float(np.abs(browser[...,:3]-source).mean(-1)[mask].mean())) if mask.any() else None
        # CV camera axes are x right, y down, z forward. GL is x right,
        # y up, z backward. Compare camera matrices, not visual resemblance.
        expected=np.linalg.inv(np.asarray(conf['C']))@np.diag([1,-1,-1,1])
        actual=np.asarray(recorded['info']['world']).reshape(4,4,order='F')
        cameraError=float(np.abs(actual-expected).max())
        rows[name]=dict(assetHash=asset['hash'],identityHash=sha(identityPath),pointCount=n,fullRGBMean=float(error.mean()),fullRGBMax=float(error.max()),fullAlphaMean=float(alphaError.mean()),cameraMatrixMax=cameraError,regions=regions,settings=recorded['info'])
        np.savez_compressed(out/(name+'-gsplat.npz'),rgb=rgb,alpha=alpha,q=r['q'].cpu().numpy())
        cv2.imwrite(str(out/(name+'-gsplat.png')),cv2.cvtColor((rgb.clip(0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        images.extend([rgb.clip(0,1),browser[...,:3]])
    collage=np.concatenate(images,1)
    cv2.imwrite(str(out/'source-gsplat-playcanvas.png'),cv2.cvtColor((collage.clip(0,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    result=dict(assets=rows,reference=ref,sourceHash=sourceHash,browserReportHash=sha(browser_report),colour='raw GL premultiplied RGBA8; vertical flip only; no second alpha, gamma or exposure transform',sameNativeCanvas=True,renderer='gsplat1.5.3 and actual PlayCanvas2.22.4 Chrome SwiftShader',productionViewerChanged=False,HarmonyOSTested=False,published=False,releaseQualityPassed=False)
    save_json(out/'result.json',result);print(json.dumps(rows),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('prepared','browser-report','identity-map','out'):p.add_argument('--'+key,required=True)
    a=p.parse_args();run(a.prepared,a.browser_report,a.identity_map,a.out)
