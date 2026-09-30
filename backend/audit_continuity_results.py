"""Explicit-run, zero-training evidence/rollback audit. No auto candidate choice."""
import argparse,json,shutil
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_dense_contract import digest,write_json


def equal(a,b):
    if isinstance(a,torch.Tensor):return isinstance(b,torch.Tensor) and a.shape==b.shape and a.dtype==b.dtype and torch.equal(a,b)
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
    if isinstance(a,(tuple,list)):return type(a)==type(b) and len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    return a==b


def state_audit(folder):
    folder=Path(folder);a=torch.load(folder/'initial.pt',map_location='cpu',weights_only=False)
    b=torch.load(folder/'candidate-final.pt',map_location='cpu',weights_only=False)
    c=torch.load(folder/'restored.pt',map_location='cpu',weights_only=False)
    changed={k:dict(max=float((v-b['model'][k]).abs().max()),mean=float((v-b['model'][k]).abs().float().mean())) for k,v in a['model'].items() if not torch.equal(v,b['model'][k])}
    frozen=[k for k in a['model'] if k.startswith('baseline.')]
    scope=all(torch.equal(a['model'][k],b['model'][k]) for k in frozen)
    if not frozen:
        permitted={'surface_control','pose.delta','portrait.sh','portrait.opacity_logits','portrait.log_scales','portrait.quats'}
        scope=all(torch.equal(v,b['model'][k]) for k,v in a['model'].items() if k not in permitted)
        p=a['model'];skin=(p['component_origin'][p['portrait.origin_index']]==0)&(p['portrait.role']!=2)
        scope=scope and all(torch.equal(p['portrait.'+k][~skin],b['model']['portrait.'+k][~skin]) for k in ('sh','opacity_logits','log_scales','quats'))
    recovered={k:equal(a[k],c[k]) for k in ('model','optimizers','bindings','samplers','rng','strategy','trainable')}
    if not scope or not all(recovered.values()):raise ValueError('state_protection_failed:'+str(folder))
    return dict(changed=changed,frozenScopeExact=scope,recovered=recovered,checkpointHashes={n:digest(folder/(n+'.pt')) for n in ('initial','mid','candidate-final','restored')})


def montage(path,panels,labels,rectangle=None):
    images=[]
    for im,label in zip(panels,labels):
        if rectangle is not None:
            x0,y0,x1,y1=rectangle;im=im[y0:y1,x0:x1]
        im=(np.clip(im,0,1)*255).round().astype(np.uint8)
        header=np.zeros((32,im.shape[1],3),np.uint8);cv2.putText(header,label,(8,22),cv2.FONT_HERSHEY_SIMPLEX,.55,(235,235,235),1,cv2.LINE_AA)
        images.append(np.concatenate([header,im],0))
    cv2.imwrite(str(path),cv2.cvtColor(np.concatenate(images,1),cv2.COLOR_RGB2BGR))


def run(root,hair,prepared,out,transition='body-transition'):
    root=Path(root);hair=Path(hair);prep=Path(prepared);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    shutil.copyfile(__file__,out/Path(__file__).name);runs={};states={}
    transition=root/transition
    for label,path in [('body-static',root/'body-static-control'),('body-transition',transition),('hair',hair),('room',root/'room-training')]:
        r=json.loads((path/'result.json').read_text());runs[label]={k:r[k] for k in ('sourceHash','seconds','allocatedMiB','reservedMiB','pointCount','assetHash','parameterChanges','transactionAccepted','baselineExact')}
        runs[label]['actualRunPath']=str(path)
        runs[label]['failures']=r['screen']['failures'];runs[label]['fullSceneFailures']=r['fullScreen']['failures'] if r['fullScreen'] else None
        runs[label]['fixedViews']={n:dict(before=r['baseline'][n],after=r['final'][n]) for n in r['final'] if n not in r['config'].get('trainingNames',[]) and n in ('frame_0015.png','frame_0035.png','frame_0055.png','frame_0075.png','frame_0095.png','frame_0115.png','frame_0130.png','frame_0145.png')}
        states[label]=state_audit(path)
    face=root/'face-multiview-gray';fr=json.loads((face/'result.json').read_text());runs['face']=fr
    for branch in fr['branches']:states['face-'+branch]=state_audit(face/branch)
    hashes={r['sourceHash'] for r in runs.values()}
    if len(hashes)!=1:raise ValueError('cross_run_source_mismatch')
    # Explicit diagnostic views, never used to select training points/thresholds.
    for name in ('frame_0010.png','frame_0035.png'):
        source=cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/name)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
        old=np.load(transition/'baseline-images'/(name+'.npz'))['rgb']
        static=np.load(root/'body-static-control/final-images'/(name+'.npz'))['rgb']
        moved=np.load(transition/'final-images'/(name+'.npz'))['rgb']
        masks=dict(np.load(prep/'rectified_observations'/(name+'.npz')));mask=masks['face_core']|masks['face_boundary']|masks['neck_cloth_visible']|masks['hair_visible']
        ys,xs=np.where(mask);h,w=mask.shape;rect=(max(0,xs.min()-16),max(0,ys.min()-16),min(w,xs.max()+17),min(h,ys.max()+17))
        montage(out/('body-'+name+'.png'),[source,old,static,moved],['Source','R0','Static control','Head-body transition'],rect)
        montage(out/('scene-'+name+'.png'),[source,old,moved],['Source','R0 full scene','Candidate full scene'])
    for name in ('frame_0035.png','frame_0075.png'):
        panels=[]
        for folder in (face/'baseline-images',face/'appearance-control/final-images',face/'measured-surface/final-images'):
            img=cv2.cvtColor(cv2.imread(str(folder/(name+'-head.png'))),cv2.COLOR_BGR2RGB).astype(np.float32)/255
            if not panels:panels.append(img[:,:img.shape[1]//2])
            panels.append(img[:,img.shape[1]//2:])
        montage(out/('face-'+name+'.png'),panels,['Source','R0','Appearance control','Measured shared surface'])
    write_json(out/'state-audit.json',states);write_json(out/'summary.json',dict(runs=runs,sourceHash=next(iter(hashes)),published=False,HarmonyOSTested=False))
    print(json.dumps(dict(stateScopesExact=True,completeStateRestored=True,sourceHash=next(iter(hashes)),out=str(out))),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('root','hair','prepared','out'):p.add_argument('--'+k,required=True)
    p.add_argument('--body-transition',default='body-transition')
    a=p.parse_args();run(a.root,a.hair,a.prepared,a.out,a.body_transition)
