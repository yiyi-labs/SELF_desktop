"""Post-run replay receipts for the finite dense experiment. No optimizer."""
import argparse,json
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_dense_contract import digest,write_json
from reconstruction_evidence_stage import load_stage
from reconstruction_portrait_pipeline import make_frame
from run_dense_surface_training import DenseSurfaceStage

def identical(a,b):
    if torch.is_tensor(a):return torch.is_tensor(b) and a.dtype==b.dtype and a.shape==b.shape and torch.equal(a,b)
    if isinstance(a,np.ndarray):return isinstance(b,np.ndarray) and np.array_equal(a,b)
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(identical(a[k],b[k]) for k in a)
    if isinstance(a,(list,tuple)):return type(a)==type(b) and len(a)==len(b) and all(identical(x,y) for x,y in zip(a,b))
    return a==b

@torch.no_grad()
def run(folder,surfaces,asset_audit,out):
    folder,surfaces,asset_audit,out=map(Path,(folder,surfaces,asset_audit,out));out.mkdir(exist_ok=False)
    stages={label:json.loads((folder/(label+'-images')/'metrics.json').read_text()) for label in ('R0','initial','final')}
    summary={}
    for role in ('development','fixed-regression'):
        summary[role]={}
        for label,rows in stages.items():
            selected=[v for v in rows.values() if v['role']==role]
            value={part:float(np.mean([v[part]['fixedRgbL1'] for v in selected])) for part in ('face','hair','glasses')}
            joint=[v['T2'] for v in selected if 'T2' in v]
            value['jointViewCount']=len(joint)
            for part in ('face','hair','room','neckCloth'):
                if joint:
                    value['T2-'+part]=float(np.mean([v[part]['fixedRgbL1'] for v in joint]))
                    value['T2-'+part+'-alphaBelow0.8']=float(np.mean([v[part]['hole'] for v in joint]))
            value['faceRoomContribution']=float(np.mean([v['faceRoomContribution'] for v in joint])) if joint else None
            summary[role][label]=value
    perview=[]
    for name,old in stages['R0'].items():
        if old['role']=='train':continue
        row={'name':name,'role':old['role']}
        for label in stages:
            v=stages[label][name];row[label]={p:v[p]['fixedRgbL1'] for p in ('face','hair','glasses')}
            if 'T2' in v:row[label]['T2']={p:v['T2'][p]['fixedRgbL1'] for p in ('face','hair','room','neckCloth')}
        perview.append(row)
    # Fixed previously requested comparison views, not chosen for favorable RGB.
    for name in ('frame_0035.png','frame_0075.png','frame_0145.png'):
        rows=[cv2.imread(str(folder/(label+'-images')/(name+'-head.png'))) for label in ('R0','initial','final')]
        if any(r is None for r in rows):raise ValueError('missing_comparison:'+name)
        half=rows[0].shape[1]//2
        if any(r.shape!=rows[0].shape for r in rows):raise ValueError('comparison_crop_changed')
        panels=[rows[0][:,:half]]+[r[:,half:] for r in rows]
        width=half;header=np.zeros((32,width*4,3),np.uint8)
        for i,label in enumerate(('SOURCE','R0','NEW INITIAL','OPTIMIZED REJECTED')):
            cv2.putText(header,label,(i*width+8,22),cv2.FONT_HERSHEY_SIMPLEX,.45,(220,220,220),1,cv2.LINE_AA)
        cv2.imwrite(str(out/(name+'-comparison.png')),np.concatenate([header,np.concatenate(panels,1)],0))
    initial=torch.load(folder/'initial.pt',map_location='cpu',weights_only=False)
    restored=torch.load(folder/'restored.pt',map_location='cpu',weights_only=False)
    keys=('model','optimizers','bindings','samplers','rng','strategy','trainable','contract','extra')
    restoration={key:identical(initial[key],restored[key]) for key in keys}
    if not all(restoration.values()):raise ValueError('restoration_failed:'+str(restoration))
    del initial,restored
    data,plan,base,contract=load_stage(folder/'spec.json',out/'reload')
    model=DenseSurfaceStage(base,surfaces,source_hash=data['sourceHash']);ck=torch.load(folder/'candidate-final.pt',map_location='cuda',weights_only=False)
    model.load_state_dict(ck['model'],strict=True);base.room.metadata=ck['extra']['roomMetadata'];base.body_sources=ck['extra']['bodySources']
    name=json.loads((folder/'result.json').read_text())['reference'];f=make_frame(data,name,crop=False)
    r=model.render(f,'T2');reference=dict(np.load(asset_audit/'gsplat-reference.npz'))
    roundtrip={key:{'mean':float(np.abs(r[key].cpu().numpy()-reference[key]).mean()),'max':float(np.abs(r[key].cpu().numpy()-reference[key]).max())} for key in ('rgb','alpha','q')}
    pc=json.loads((asset_audit/'playcanvas-01/report.json').read_text())
    row=pc['rows'][0];conf=pc['sourceContract'];h,w=conf['height'],conf['width']
    raw=np.fromfile(asset_audit/'playcanvas-01/candidate.rgba',np.uint8).reshape(h,w,4)[::-1].astype(np.float32)/255
    # Raw framebuffer RGB is premultiplied over black, matching gsplat compositing.
    diff=np.abs(raw[...,:3]-reference['rgb'])
    regions={}
    for label,mask in [('all',np.ones((h,w),bool)),('face', (f['masks']['face_core']|f['masks']['face_boundary']).cpu().numpy()),('room',f['masks']['room_visible'].cpu().numpy()),('hair',f['masks']['hair_visible'].cpu().numpy())]:
        regions[label]={'RGBMAE':float(diff[mask].mean()),'RGBp95':float(np.quantile(diff[mask],.95)),'alphaMAE':float(np.abs(raw[...,3]-reference['alpha'].squeeze())[mask].mean())}
    expected=np.linalg.inv(np.asarray(conf['C']))@np.diag([1,-1,-1,1]);actual=np.asarray(row['info']['world']).reshape(4,4).T
    cameraError=float(np.abs(expected-actual).max())
    images=[(reference['rgb'].clip(0,1)*255).round().astype(np.uint8),(raw[...,:3].clip(0,1)*255).round().astype(np.uint8)]
    cv2.imwrite(str(out/'gsplat-playcanvas-raw-comparison.png'),cv2.cvtColor(np.concatenate(images,1),cv2.COLOR_RGB2BGR))
    receipts={'sourceHash':contract['sourceHash'],'assetHash':digest(folder/'candidate-research-only.ply'),'reference':name,'summary':summary,'perView':perview,'restoration':restoration,'trainerToPLY':roundtrip,'PlayCanvas':{'cameraTransformMax':cameraError,'regions':regions,'contract':row['info'],'errors':row['errors'],'scope':pc['scope']},'R0Hash':digest(contract['spec']['checkpoint']),'releaseQualityPassed':False,'published':False}
    write_json(out/'result.json',receipts)
    print(json.dumps({'summary':summary,'restoration':restoration,'trainerToPLY':roundtrip,'PlayCanvas':{'cameraTransformMax':cameraError,'regions':regions}}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('folder','surfaces','asset-audit','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.folder,a.surfaces,a.asset_audit,a.out)
