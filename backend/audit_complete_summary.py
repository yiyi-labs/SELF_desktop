"""Reproducible summary/visual panels from recorded results, no new training."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np,torch
from PIL import Image,ImageDraw

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def panel(images,labels,path,maxheight=1050):
    height=max(x.shape[0] for x in images);width=sum(x.shape[1] for x in images);dst=Image.new('RGB',(width,height+32),(15,17,22));d=ImageDraw.Draw(dst);left=0
    for a,label in zip(images,labels):
        im=Image.fromarray((np.clip(a,0,1)*255).round().astype(np.uint8));dst.paste(im,(left,32));d.text((left+8,8),label,fill='white');left+=a.shape[1]
    if dst.height>maxheight:dst=dst.resize((round(dst.width*maxheight/dst.height),maxheight),Image.Resampling.LANCZOS)
    dst.save(path)
def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=False);room=read(root/'room-full-training/result.json');f=read(root/'face-surface-check/result.json');b={}
    for stage in ['before','initial','after']:
        b[stage]={k:float(np.mean([v[k]['rgbL1'] for v in room[stage].values()])) for k in ['face','room']}
    train=list(room['before'])[:7];b['trainingRoom']={stage:float(np.mean([room[stage][n]['room']['rgbL1'] for n in train])) for stage in ['before','initial','after']}
    face={k:{role:float(np.mean([v['face']['fixedRgbL1'] for v in result['images'].values() if v['use']==role])) for role in ['development','review_audit']} for k,result in f['branches'].items()}
    source=Path(read(root/'stage.json')['prepared'])/'rectified_observations';frame='frame_0111.png';actual=np.array(Image.open(source/frame))/255
    old=np.load(root/'room-full-training/old-images'/(frame+'.npz'))['rgb'];new=np.load(root/'room-full-training/final-images'/(frame+'.npz'))['rgb'];panel([actual,old,new],['Source same time','R0 full scene','480-step candidate REJECTED'],out/'full-scene-comparison.jpg')
    face_rows=[]
    for name in ['frame_0035.png','frame_0075.png','frame_0145.png','frame_0058.png']:
        a=np.array(Image.open(root/'face-surface-check/R0-images'/name))/255;w=a.shape[1]//2;images=[a[:,:w],a[:,w:]]
        for lab in ['fixed-F','bounded-F']:images.append(np.load(root/'face-surface-check'/(lab+'-images')/(name+'.npz'))['rgb'])
        path=out/('face-'+name);panel(images,['Source','R0','Fixed F continuous field','Bounded F continuous field'],path,maxheight=1200);face_rows.append(str(path))
    comparisons={}
    for label,folder,npz in [('reference',root/'room-full-training','B-T2-gsplat.npz'),('orbit12',root/'handoff-repair/view-12','gsplat.npz'),('orbit35',root/'handoff-repair/view-35','gsplat.npz')]:
        report=read(folder/'playcanvas-baseline-01/report.json');asset=report['rows'][0]['asset'];raw=np.fromfile(folder/'playcanvas-baseline-01'/ (asset['label']+'.rgba'),np.uint8).reshape(1920,1080,4)[::-1].astype(np.float32)/255;g=np.load(folder/npz);valid=(g['alpha']>.01)|(raw[...,3]>.01)
        record={'assetHash':asset['hash'],'rgbL1Full':float(abs(raw[...,:3]-g['rgb']).mean()),'rgbL1UnionAlphaSupport':float(abs(raw[...,:3]-g['rgb']).mean(-1)[valid].mean()),'alphaL1Full':float(abs(raw[...,3]-g['alpha']).mean()),'nativeCanvas':report['rows'][0]['info']['canvas'],'errors':report['rows'][0]['errors'],'renderer':'PlayCanvas2.22.4 SwiftShader; not HarmonyOS'}
        if label=='reference':
            masks=np.load(source/(frame+'.npz'))
            for key in ['face_core','room_visible','neck_cloth_visible']:
                mask=masks[key];record[key]={'rendererRgbL1':float(abs(raw[...,:3]-g['rgb']).mean(-1)[mask].mean()),'pcSourceL1':float(abs(raw[...,:3]-actual).mean(-1)[mask].mean()),'gsSourceL1':float(abs(g['rgb']-actual).mean(-1)[mask].mean())}
        comparisons[label]=record;panel([g['rgb'],raw[...,:3]],['gsplat fixed PLY','PlayCanvas same PLY/camera'],out/(label+'-renderers.jpg'))
    ci=torch.load(root/'room-full-training/initial.pt',map_location='cpu',weights_only=False);cf=torch.load(root/'room-full-training/candidate-final.pt',map_location='cpu',weights_only=False);updates={k:{'meanAbs':float((cf['model'][k]-ci['model'][k]).abs().mean()),'maxAbs':float((cf['model'][k]-ci['model'][k]).abs().max())} for k in ['offset','log_scales','quats','opacity','sh']}
    restored=torch.load(root/'room-full-training/restored.pt',map_location='cpu',weights_only=False)
    def equal(a,b):
        if isinstance(a,torch.Tensor):return torch.equal(a,b)
        if isinstance(a,np.ndarray):return np.array_equal(a,b)
        if isinstance(a,dict):return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
        if isinstance(a,(tuple,list)):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
        return a==b
    state_keys=list(ci);restoration={k:equal(ci[k],restored[k]) for k in ci if k in ['model','optimizers','samplers','rng','strategy']}
    memory=read(root/'room-full-training/device-memory.json');used=[int(x['usedTotalMiB'].split(',')[0]) for x in memory['samples'] if 'usedTotalMiB' in x and x['usedTotalMiB'].split(',')[0].strip().isdigit()]
    summary={'face':face,'room':b,'roomParameterChanges':updates,'roomSteps':room['steps'],'roomSeconds':room['totalSeconds'],'torchAllocatedMiB':room['allocatedMiB'],'torchReservedMiB':room['reservedMiB'],'deviceSamplePeakMiB':max(used) if used else None,'deviceSamples':len(used),'roomInitialRestored':restoration,'checkpointKeys':state_keys,'renderers':comparisons,'fixedAssetHash':sha(root/'room-full-training/fixed-B-T2.ply'),'notPublished':True}
    (out/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.root,a.out)
