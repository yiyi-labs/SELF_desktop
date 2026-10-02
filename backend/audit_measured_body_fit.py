"""Per-observation measured clothing residuals, never a repaired-model image."""
from pathlib import Path
import argparse,json,shutil
import cv2,numpy as np
from reconstruction_components_v3 import save_json,sha
from reconstruction_dense_contract import project


def run(prepared,tracks,result,out):
    out=Path(out);out.mkdir(exist_ok=False);prep=Path(prepared)
    data=json.loads(Path(tracks).read_text());fit=json.loads(Path(result).read_text());meta=json.loads((prep/'preparation.json').read_text())
    if data['sourceHash']!=fit['sourceHash'] or meta['sourceHash']!=fit['sourceHash']:raise ValueError('residual_source_changed')
    raw=dict(np.load(prep/'local_geometry.npz'));C={str(n):raw['C'][i] for i,n in enumerate(raw['world_names'])};by_id={t['id']:t for t in data['tracks']};rows={};panels=[]
    for name in fit['names']:
        source=cv2.imread(str(prep/'rectified_observations'/name));predictions=[];measurements=[];errors=[];region={}
        for r in fit['records']:
            obs=next((o for o in by_id[r['id']]['observations'] if o['name']==name),None)
            if obs is None:continue
            M=np.asarray(fit['B'][name]) if fit['B'] else np.asarray(fit['nodeTransforms'][name])[0]*r['upperWeight']+np.asarray(fit['nodeTransforms'][name])[1]*(1-r['upperWeight'])
            uv,z=project(np.asarray(r['xyz'])[None],raw['K'],C[name]@M)
            expected=r['errors'][r['names'].index(name)];actual=float(np.linalg.norm(uv[0]-obs['uv']))
            if abs(expected-actual)>1e-5:raise ValueError('recorded_residual_changed')
            predictions.append(uv[0]);measurements.append(np.asarray(obs['uv']));errors.append(actual);region.setdefault(r['region'],[]).append(actual)
        row=dict(count=len(errors),median=float(np.median(errors)),p90=float(np.quantile(errors,.9)),
            byRegion={k:dict(count=len(v),median=float(np.median(v)),p90=float(np.quantile(v,.9))) for k,v in region.items()})
        rows[name]=row
        points=np.asarray(measurements);h,w=source.shape[:2];x0=max(0,int(points[:,0].min())-20);x1=min(w,int(points[:,0].max())+21);y0=max(0,int(points[:,1].min())-20);y1=min(h,int(points[:,1].max())+21)
        for p,q in zip(measurements,predictions):
            p=np.rint(p).astype(int);q=np.rint(q).astype(int)
            cv2.circle(source,tuple(p),3,(0,210,0),1);cv2.drawMarker(source,tuple(q),(0,0,230),cv2.MARKER_CROSS,7,1);cv2.line(source,tuple(p),tuple(q),(0,180,220),1)
        crop=source[y0:y1,x0:x1];height=480;width=max(1,int(crop.shape[1]*height/crop.shape[0]));crop=cv2.resize(crop,(width,height),interpolation=cv2.INTER_AREA)
        cv2.putText(crop,name+' P90 '+format(row['p90'],'.2f')+'px',(6,22),cv2.FONT_HERSHEY_SIMPLEX,.43,(255,255,255),1,cv2.LINE_AA)
        cv2.imwrite(str(out/(name+'.png')),crop);panels.append(crop)
    cv2.imwrite(str(out/'measured-clothing-residuals.jpg'),np.concatenate(panels,1))
    save_json(out/'result.json',dict(rows=rows,sourceHash=fit['sourceHash'],fitHash=sha(result),tracksHash=sha(tracks),
        meaning='green actual native measurement; red shared 3D prediction; diagnostic crop only, not trained clothing or final asset',published=False))
    shutil.copyfile(__file__,out/Path(__file__).name);print(json.dumps(rows),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('prepared','tracks','result','out'):p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.prepared,a.tracks,a.result,a.out)