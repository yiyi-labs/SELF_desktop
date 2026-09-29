"""Summarize actual saved images, no new fitting or asset mutation."""
from pathlib import Path
import json,numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parent/'.sources/surface-evidence-face-clothing-20260929-a'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def main():
    output={};control={}
    for label in ('normal','wide'):
        target=np.load(ROOT/'R-control'/(label+'-gsplat.npz'));control[label]={}
        for factor in ('baseline','large','fine'):
            raw=np.fromfile(ROOT/'R-control'/('playcanvas-'+factor+'-01')/(label+'.rgba'),np.uint8).reshape(1920,1080,4)[::-1].astype(np.float32)/255;mask=(raw[...,3]>.05)|(target['alpha']>.05)
            control[label][factor]={'supportPixels':int(mask.sum()),'rgbL1':float(abs(raw[...,:3]-target['rgb']).mean(-1)[mask].mean()),'alphaL1':float(abs(raw[...,3]-target['alpha'])[mask].mean())}
    output['Rcontrol']=control;output['Ractual']=read(ROOT/'R/comparison.json')['rows'];f=read(ROOT/'F-geometry-evaluation/result.json');output['F']={k:v for k,v in f.items() if k!='groups'};output['F']['groups']={k:{a:b for a,b in v.items() if a not in ('before','after')} for k,v in f['groups'].items()};output['C']=read(ROOT/'C-training/result.json');output['B']=read(ROOT/'B-replacement/result.json')
    pc={}
    for folder,label,file in [('C-training','T2','T2-gsplat.npz'),('B-replacement','B-T2','B-T2-gsplat.npz'),('final-evidence','F-local','F-local-gsplat.npz'),('B-scoped-replay','B-T2','B-T2-gsplat.npz')]:
        spec=read(ROOT/folder/'display.json');target=np.load(ROOT/folder/file);raw=np.fromfile(ROOT/folder/'playcanvas-baseline-01'/(label+'.rgba'),np.uint8).reshape(1920,1080,4)[::-1].astype(np.float32)/255;prep=Path('D:/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e/rectified_observations');lab=np.load(prep/(spec['reference']+'.npz'));source=np.array(Image.open(prep/spec['reference']).convert('RGB')).astype(np.float32)/255;rows={}
        for name,mask in [('face',lab['face_core']),('room',lab['room_visible'])]:rows[name]={'RGBL1':float(abs(raw[...,:3]-target['rgb']).mean(-1)[mask].mean()),'alphaL1':float(abs(raw[...,3]-target['alpha'])[mask].mean())}
        Image.fromarray((np.concatenate([source,target['rgb'],raw[...,:3]],1).clip(0,1)*255).round().astype(np.uint8)).save(ROOT/folder/'dual-renderer.png');pc[folder]={'assetHash':spec['assets'][0]['hash'],'reference':spec['reference'],'rows':rows,'engine':'PlayCanvas2.22.4 Chrome SwiftShader; not device FPS'}
    output['candidatePC']=pc;output['Bscoped']=read(ROOT/'B-scoped-replay/result.json');output['extraFrames']={key:read(ROOT/'final-evidence'/key/'metrics.json') for key in ('extra-R0','extra-F')};output['restoration']=read(ROOT/'final-evidence/result.json')['garmentRestore'];dest=Path(__file__).resolve().parent.parent/'docs/evidence/surface-evidence-face-clothing-20260929/results.json';dest.write_text(json.dumps(output,indent=2))
    print(json.dumps({'Rcontrol':control,'PC':pc,'F':output['F'],'Cbrief':{n:(r['fixedPatchRgbL1'],output['C']['after'][n]['fixedPatchRgbL1'],output['C']['after'][n]['patchHole08']) for n,r in output['C']['before'].items()},'Bbrief':{n:(v['face']['rgbL1'],output['B']['after'][n]['face']['rgbL1'],v['room']['rgbL1'],output['B']['after'][n]['room']['rgbL1'],v['face']['qRoom'],output['B']['after'][n]['face']['qRoom']) for n,v in output['B']['before'].items() if n in ('frame_0111.png','frame_0135.png') }},indent=2))
if __name__=='__main__':main()

