"""Exact research-only handoff identities for fixed candidate PLY files.
These sidecars never migrate production editing data or grant publication.
"""
import argparse,json
from pathlib import Path
import numpy as np,torch
from reconstruction_components_v3 import save_json,sha

def run(root):
    root=Path(root);f=torch.load(root/'F-geometry-evaluation/candidate-final.pt',map_location='cpu',weights_only=False);state=f['model'];meta=f['extra']['roomMetadata'];nh=len(state['portrait.role']);ns=len(state['portrait.triangle_ids']);nr=len(meta['point_uid']);nb=len(state['body.means'])
    head={'uid':state['portrait.stable_uid'].numpy(),'source':state['portrait.source_index'].numpy(),'namespace':np.full(nh,1),'binding_triangle':np.r_[state['portrait.triangle_ids'].numpy(),np.full(nh-ns,-1)],'binding_bary':np.r_[state['portrait.embedding'].numpy(),np.zeros((nh-ns,3))]}
    room={'uid':meta['point_uid'].numpy()+(1<<40),'source':meta['source_id'].numpy(),'namespace':np.full(nr,2),'binding_triangle':np.full(nr,-1),'binding_bary':np.zeros((nr,3))}
    body={'uid':np.arange(nb)+(2<<40),'source':np.array(f['extra']['bodySources']['id']),'namespace':np.full(nb,3),'binding_triangle':np.full(nb,-1),'binding_bary':np.zeros((nb,3))}
    c=torch.load(root/'C-training/candidate-final.pt',map_location='cpu',weights_only=False);cv=c['model'];nc=len(cv['stable_uid']);cloth={'uid':cv['stable_uid'].numpy()+(3<<40),'source':cv['surface_triangle'].numpy(),'namespace':np.full(nc,4),'binding_triangle':cv['surface_triangle'].numpy(),'binding_bary':cv['surface_bary'].numpy()}
    b=torch.load(root/'B-replacement/candidate-final.pt',map_location='cpu',weights_only=False);bv=b['model'];idx=b['extra']['sourceIndices'];keep=~b['extra']['removedMask'].numpy();oldroom={k:v[keep] for k,v in room.items()};newroom={'uid':bv['stable_uid'].numpy()+(1<<40),'source':idx,'namespace':np.full(len(idx),5),'binding_triangle':np.full(len(idx),-1),'binding_bary':np.zeros((len(idx),3))}
    rows=[]
    for folder,ply,groups in [('final-evidence','fixed-F-local.ply',[head]),('C-training','fixed-T2-garment-diagnostic.ply',[head,room,cloth]),('B-replacement','fixed-B-T2.ply',[head,oldroom,newroom,body])]:
        path=root/folder/ply;arrays={k:np.concatenate([g[k] for g in groups]) for k in head};N=len(arrays['uid']);assert len(np.unique(arrays['uid']))==N
        with path.open('rb') as stream:
            count=None
            while True:
                line=stream.readline()
                if line.startswith(b'element vertex '):count=int(line.split()[-1])
                if line.strip()==b'end_header':break
                if not line:raise ValueError('bad PLY')
        assert count==N
        side=path.with_suffix('.identity.npz');np.savez_compressed(side,**arrays,assetHash=np.array(sha(path)),sourceHash=np.array(f['contract']['sourceHash']),surfaceResidual=state['portrait.surface_residual'].numpy(),measuredField=state['measured_surface_field'].numpy() if folder=='final-evidence' else np.zeros_like(state['measured_surface_field'].numpy()))
        row={'asset':str(path),'assetHash':sha(path),'count':N,'sidecarHash':sha(side),'schema':'self.research.surface.identity.v1','originalPrefixOrderRetained':True,'sourceNamespaces':{'1':'original head source indices','2':'original room SfM/triangle ancestry; kind in frozen metadata','3':'original body source seeds','4':'new cloth interpolated triangle; three measured vertex tracks retained in C-surface','5':'OpenMVS fused vertex index; original view_indices/view_weights retained in dense.ply'},'productionEditingMigrated':False,'published':False};save_json(side.with_suffix('.json'),row);rows.append(row)
    save_json(root/'identity-receipts.json',rows);print(json.dumps(rows),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();run(Path(a.root).resolve())
