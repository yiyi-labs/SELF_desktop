"""Fixed-asset handoff, point identity and two matched orbit views.
This does not accept a failed candidate or alter production edit masks.
"""
import argparse,json,shutil
from pathlib import Path
import numpy as np,torch,cv2
from reconstruction_components_v3 import save_json,sha
from reconstruction_joint_visibility import load_recorded_ply
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import draw
from audit_complete_content import first_mvs_camera

def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=False);shutil.copyfile(__file__,out/Path(__file__).name)
    room=root/'room-full-training';display=json.loads((room/'display.json').read_text());asset=Path(display['assets'][0]['ply']);h=sha(asset)
    if h!=display['assets'][0]['hash']:raise ValueError('asset_changed')
    baseline=torch.load(root/'R0-frozen-copy.pt',map_location='cpu',weights_only=False);b=baseline['model'];meta=baseline['extra']['roomMetadata'];candidate=torch.load(room/'candidate-final.pt',map_location='cpu',weights_only=False);c=candidate['model'];keep=~candidate['extra']['removedMask'].cpu().numpy();nh=len(b['portrait.role']);nr=int(keep.sum());nn=len(c['stable_uid']);nb=len(b['body.means']);ns=len(b['portrait.triangle_ids'])
    uid=np.r_[b['portrait.stable_uid'].numpy(),meta['point_uid'].numpy()[keep]+(1<<40),c['stable_uid'].numpy()+(1<<40),np.arange(nb)+(2<<40)]
    namespace=np.r_[np.full(nh,1),np.full(nr,2),np.full(nn,5),np.full(nb,3)]
    source=np.r_[b['portrait.source_index'].numpy(),meta['source_id'].numpy()[keep],candidate['extra']['sourceIndices'],baseline['extra']['bodySources']['id']]
    triangle=np.r_[b['portrait.triangle_ids'].numpy(),np.full(nh-ns,-1),np.full(nr+nn+nb,-1)]
    bary=np.r_[b['portrait.embedding'].numpy(),np.zeros((nh-ns+nr+nn+nb,3))]
    if len(uid)!=display['assets'][0]['count'] or len(np.unique(uid))!=len(uid):raise ValueError('identity_mismatch')
    np.savez_compressed(out/'candidate.identity.npz',point_uid=uid,source_id=source,source_namespace=namespace,binding_triangle=triangle,binding_bary=bary,assetHash=np.array(h),sourceHash=np.array(display['sourceHash']))
    component={'sourceHash':display['sourceHash'],'assetHash':h,'reference':display['reference'],'role':'assembled_research','checkpointHash':sha(room/'candidate-final.pt'),'canonicalFrame':'R0 world; body remains original reference motion','unitScale':float(display['near']/.01),'groups':{'old_head':nh,'retained_old_room':nr,'new_MVS_room':nn,'retained_old_body':nb},'retiredUIDs':candidate['contract']['retiredUID'],'addedUIDHash':sha(out/'candidate.identity.npz'),'headGeometryCandidateIncluded':False,'newClothPatchIncluded':False,'releaseQualityPassed':False,'failure':'all 13 room views regress; incomplete shoulders/collar; no accepted head refinement','productionEditMasksMigrated':False,'published':False}
    save_json(out/'assembly-failure.json',component)
    z=load_recorded_ply(asset,ns);state=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],torch.zeros(len(uid),device='cuda',dtype=torch.long));K=torch.tensor(display['K'],device='cuda',dtype=torch.float32);cams=json.loads((room/'fixed-orbit/contract.json').read_text())['cameras']
    with torch.no_grad():
        for i in [12,35]:
            dest=out/f'view-{i}';dest.mkdir();C=np.array(cams[i]['C']);inv=np.linalg.inv(C);spec={**display,'C':C.tolist(),'camera':inv[:3,3].tolist(),'target':(inv[:3,3]+inv[:3,2]).tolist(),'up':(-inv[:3,1]).tolist(),'orbitIndex':i,'noSourcePixelTruthAtThisOrbit':True};save_json(dest/'display.json',spec);r=draw(state,torch.tensor(C,device='cuda',dtype=torch.float32),K,1080,1920,unit_scale=display['near']/.01);np.savez_compressed(dest/'gsplat.npz',rgb=r['rgb'].cpu().numpy(),alpha=r['alpha'].cpu().numpy());cv2.imwrite(str(dest/'gsplat.png'),cv2.cvtColor((r['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    K,info=first_mvs_camera(root/'pixel-handoff/scene.mvs');expected=np.array(json.loads((root/'pixel-handoff/contract.json').read_text())['nativeK']);save_json(out/'pixel-handoff.json',{'actualMvsK':K.tolist(),'nativeK':expected.tolist(),'maxDifference':float(abs(K-expected).max()),'pass':bool(np.allclose(K,expected,atol=1e-10)),'actualImportedSceneHash':sha(root/'pixel-handoff/scene.mvs'),'onlyInterfaceTestNotQuality':True})
    if sha(asset)!=h:raise ValueError('asset_mutated')
    print(json.dumps(component),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.root,a.out)
