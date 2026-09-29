"""Correct retirement scope with frozen already-trained physical surface.
No additional optimizer/backward; only 8 same-family points are restored.
"""
import argparse,json,time
from pathlib import Path
import numpy as np,torch
from reconstruction_evidence_stage import load_stage
from reconstruction_components_v3 import FreeComponent,pick,save_json,sha
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from audit_portrait_priority_handoff import restore_tensors
from run_haze_shared_surface import export_state
from audit_detail_controlled import png

def run(root,manifest,evidence):
    root=Path(root);out=root/'B-scoped-replay';data,plan,m,contract=load_stage(manifest,out);old=root/'B-replacement';ck=torch.load(old/'candidate-final.pt',map_location='cuda',weights_only=False);v=ck['model'];gs=GaussianState(v['base'],v['quats'],v['initial_scales'],v['opacity'].sigmoid(),v['sh'],v['parts']);new=FreeComponent(gs,v['source_ids'],v['support'],'world',v['max_offset']);new.register_buffer('stable_uid',v['stable_uid']);new.register_buffer('parent_uid',v['parent_uid']);restore_tensors(new,v)
    for p in new.parameters():p.requires_grad_(False)
    report=json.loads(Path(evidence).read_text());group=next(g for g in report['groups'] if g['sourceID']==13378);uids=torch.tensor(group['uids'],device='cuda');remove=torch.isin(m.room.metadata['point_uid'],uids);assert int(remove.sum())==6 and torch.all(m.room.metadata['source_id'][remove]==group['sourceID']);remaining=pick(m.room.state(),~remove);selection={'uids':group['uids'],'sourceID':group['sourceID'],'evidencePath':str(evidence),'evidenceHash':sha(evidence),'restoredSameFamilyPoints':int(ck['extra']['removedMask'].sum()-remove.sum()),'additionalTrainingSteps':0};save_json(out/'retirement.json',selection)
    names=list(json.loads((old/'old-images/metrics.json').read_text()));rows={}
    with torch.no_grad():
        for n in names:
            f=m.adjusted_frame(make_frame(data,n,crop=False));state=joined_state(m.head_state(f).to_world(f['C'],f['F'],m.scale),remaining,new.state(),m.body_state(n));r=draw(state,f['C'],f['K'],1080,1920,unit_scale=m.scale);err=(r['rgb']-f['rgb']).abs().mean(-1);row={}
            for key in ('face','room'):
                mask=f['masks']['face_core' if key=='face' else 'room_visible'];row[key]={'rgbL1':float(masked_mean(err,mask)),'alpha':float(masked_mean(r['alpha'],mask)),'qRoom':float(masked_mean(r['q'][...,0],mask))}
            rows[n]=row;png(out/n,[data['rgb'][n],r['rgb'].cpu().numpy()])
            if n==data['reference']:
                asset=out/'fixed-scoped-B-T2.ply';export_state(state,asset);np.savez_compressed(out/'B-T2-gsplat.npz',rgb=r['rgb'].cpu().numpy(),alpha=r['alpha'].cpu().numpy());inv=torch.linalg.inv(f['C']).cpu().numpy();spec={'assets':[{'label':'B-T2','ply':str(asset.resolve()),'hash':sha(asset),'count':len(state.means)}],'K':data['K'].tolist(),'C':f['C'].cpu().tolist(),'width':1080,'height':1920,'camera':inv[:3,3].tolist(),'target':(inv[:3,3]+inv[:3,2]).tolist(),'up':(-inv[:3,1]).tolist(),'near':.01*m.scale,'far':1e10*m.scale,'sourceHash':data['sourceHash'],'reference':n};save_json(out/'display.json',spec)
                p=m.portrait;nh=len(p.role);ns=p.surface_count;nr=int((~remove).sum());nn=len(v['stable_uid']);nb=len(m.body['means']);np.savez_compressed(out/'fixed-scoped-B-T2.identity.npz',assetHash=np.array(sha(asset)),sourceHash=np.array(data['sourceHash']),point_uid=np.r_[p.stable_uid.cpu(),m.room.metadata['point_uid'][~remove].cpu()+(1<<40),v['stable_uid'].cpu()+(1<<40),np.arange(nb)+(2<<40)],source_id=np.r_[p.source_index.cpu(),m.room.metadata['source_id'][~remove].cpu(),ck['extra']['sourceIndices'],m.body_sources['id']],source_namespace=np.r_[np.full(nh,1),np.full(nr,2),np.full(nn,5),np.full(nb,3)],binding_triangle=np.r_[p.triangle_ids.cpu(),np.full(nh+nr+nn+nb-ns,-1)],binding_bary=np.r_[p.embedding.cpu(),np.zeros((nh+nr+nn+nb-ns,3))])
    before=json.loads((old/'old-images/metrics.json').read_text());failures=[n for n in names if rows[n]['room']['rgbL1']>before[n]['room']['rgbL1']+.002];save_json(out/'result.json',{'selection':selection,'rows':rows,'roomRegressionViews':failures,'accepted':False,'optimizerCreated':False,'additionalTraining':0,'note':'narrowed retirement still requires complete true background; not an acceptance bypass','published':False});print(json.dumps({'retired':6,'restored':8,'roomRegressionViews':len(failures),'reference':rows[data['reference']]}),flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',required=True);a.add_argument('--manifest',required=True);a.add_argument('--evidence',required=True);s=a.parse_args();run(Path(s.root).resolve(),s.manifest,s.evidence)
