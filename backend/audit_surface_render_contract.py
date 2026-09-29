"""Raw fixed-canvas renderer factor comparison; never beautifies source RGB."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image

def run(root,old):
    root=Path(root);old=Path(old);a=np.load(old/'R0-gsplat.npz');ref=np.load(old/'source-reference.npz');rows={};ims=[ref['rgb'],a['rgb']]
    for key,path in [('compact-2',old/'playcanvas-02/R0.rgba'),('large-2',root/'playcanvas-large-01/R0.rgba'),('compact-.2',root/'playcanvas-fine-01/R0.rgba')]:
        raw=np.fromfile(path,np.uint8).reshape(1920,1080,4)[::-1].astype(np.float32)/255;ims.append(raw[...,:3]);row={}
        for maskname in ('face','room'):
            mask=ref[maskname];row[maskname]={'rgbL1':float(abs(raw[...,:3]-a['rgb']).mean(-1)[mask].mean()),'alphaL1':float(abs(raw[...,3]-a['alpha'])[mask].mean()),'sourceL1':float(abs(raw[...,:3]-ref['rgb']).mean(-1)[mask].mean())}
        rows[key]=row
    Image.fromarray((np.concatenate(ims,1).clip(0,1)*255).round().astype(np.uint8)).save(root/'factor-comparison.png')
    (root/'comparison.json').write_text(json.dumps({'rows':rows,'columns':['source','gsplat','compact2','large2','compact.2'],'interpretation':'same frozen R0, raw premultiplied GL RGBA8; no postprocessing','published':False},indent=2))
    print(json.dumps(rows))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--old',required=True);a=p.parse_args();run(a.root,a.old)
