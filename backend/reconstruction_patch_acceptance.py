"""Local-region rejection supplements full-face metrics; never publication."""
import numpy as np
from reconstruction_surface_patch import patch_mask

def region_check(data,plan,side,before,after):
    rows={};passed=True
    for name in plan['development']+plan['audit']:
        mask=patch_mask(data,name,side);b=np.load(before/(name+'.npz'));a=np.load(after/(name+'.npz'))
        # Evaluation NPZs contain the recorded head crop; use the matching metrics.
        import json
        rect=json.loads((before/'metrics.json').read_text())[name]['crop'];x0,y0,x1,y1=rect;mask=mask[y0:y1,x0:x1]
        source=data['rgb'][name][y0:y1,x0:x1]
        if mask.sum()<50:continue
        def loss(z):return float(np.abs(z['rgb']-source).mean(-1)[mask].mean())
        old,new=loss(b),loss(a);ok=new<=old+.002 and new<=old*1.05+.0001
        hole0=float((b['alpha'][mask]<.8).mean());hole1=float((a['alpha'][mask]<.8).mean());ok=ok and hole1<=hole0+.005
        rows[name]={'before':old,'after':new,'holeBefore':hole0,'holeAfter':hole1,'passed':bool(ok)};passed &= ok
    return {'passed':bool(passed),'rows':rows,'scope':'local rejection screen; visible original structure and orbit still required'}
