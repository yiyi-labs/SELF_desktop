"""Read-only local diagnostic plots from audit point results (no reconstruction)."""
from pathlib import Path
import argparse,json,hashlib
from PIL import Image,ImageDraw
import numpy as np
from audit_local_sampling_visibility import read_rows,sha


def contained(x,y,r):return r[0]<=x<=r[2] and r[1]<=y<=r[3]


def main(a):
    a.output.mkdir(parents=True,exist_ok=False)
    cfg=json.loads(a.windows.read_text());ws={w['imageName']:w for w in cfg['windows']}
    proposals=read_rows(a.audit/'local-triangle-proposals.jsonl')
    rows=read_rows(a.audit/'local-point-decisions.jsonl')
    with np.load(a.audit/'point-observations.npz',allow_pickle=False) as archive:
        z={k:archive[k] for k in archive.files}
    names=z['names'].tolist();ids=z['point_ids'].tolist();idx={v:i for i,v in enumerate(ids)}
    ims={n:Image.open(a.prepared/'rectified_observations'/n).convert('RGB') for n in ws}
    pictures=[]
    for name,w in ws.items():
        r=w['rect'];crop=ims[name].crop(r);overlay=crop.copy();d=ImageDraw.Draw(overlay)
        for p in proposals:
            if p['view']!=name:continue
            if p['firstDecision'] not in ('noInteriorSamples','geometryAccepted'):continue
            pts=[(x-r[0],y-r[1]) for x,y in p['projectedVertices']];d.line(pts+[pts[0]],fill=(90,125,160),width=1)
        counts={}
        for row in rows:
            if row['origin']!=name:continue
            pi=idx[row['pointId']];vi=names.index(name);x,y=z['uv'][vi,pi]-np.asarray(r[:2]);ok=row['original_decision']['accepted']
            color=('#63edbd' if ok else '#ffb066') if row['kind']=='d2_centroid' else '#df89ec'
            key=('centroid_accept' if ok else 'centroid_reject') if row['kind']=='d2_centroid' else 'old_rejected'
            counts[key]=counts.get(key,0)+1;d.ellipse((x-3,y-3,x+3,y+3),fill=color)
        width=360;h=round(crop.height*width/crop.width)
        panel=Image.new('RGB',(width*2,h+64),'#18202a');dr=ImageDraw.Draw(panel)
        panel.paste(crop.resize((width,h)),(0,64));panel.paste(overlay.resize((width,h)),(width,64))
        dr.text((8,5),name+' / '+w['group'],fill='white');dr.text((8,22),'Original | d2 green: pass; orange: reject; pink: old rejected',fill='white')
        dr.text((8,39),str(counts),fill='white')
        file=a.output/(name.replace('.png','')+'-window.png');panel.save(file);pictures.append(str(file))
    chosen=[]
    for group in sorted({w['group'] for w in ws.values()}):
        for kind,status in [('d2_centroid',True),('d2_centroid',False),('original_rejected',False)]:
            subset=sorted([r for r in rows if r['group']==group and r['kind']==kind and r['original_decision']['accepted']==status],key=lambda r:(r['pointId'],r['origin']))
            unique={}
            for r in subset:unique.setdefault(r['pointId'],r)
            chosen+=list(unique.values())[:2]
    extras=sorted([r for r in rows if not r['audit_interpretation']['sourceReference']['roomValid'] or r['audit_interpretation']['sourceReference']['kernelRoomPixels']<9],key=lambda r:(r['pointId'],r['origin']))
    chosen+=extras[:2]
    if a.all_local_conflicts:
        chosen=[]
        for r in sorted(rows,key=lambda r:(r['pointId'],r['origin'])):
            pi=idx[r['pointId']]
            for n in r['original_decision']['conflictViews']:
                if n in ws and ws[n]['group']==r['group']:
                    x,y=z['uv'][names.index(n),pi]
                    if contained(x,y,ws[n]['rect']):
                        chosen.append(r);break
    records=[];seen=set()
    for r in chosen:
        key=(r['pointId'],r['origin'])
        if key in seen:continue
        seen.add(key);pi=idx[r['pointId']];vi=names.index(r['origin'])
        # Only inspect the same physical window in its approved training views;
        # all other evidence stays numeric/unknown, even if its frame is approved.
        targets=[]
        for name in r['original_decision']['conflictViews']:
            if name not in ws or ws[name]['group']!=r['group']:continue
            j=names.index(name);x,y=z['uv'][j,pi]
            if not contained(x,y,ws[name]['rect']):continue
            diff=float(np.abs(z['rgb3x3'][j,pi]-z['rgb3x3'][vi,pi]).mean());targets.append((diff,name))
        targets=sorted(targets,key=lambda x:(-x[0],x[1]))[:3]
        frame_names=[r['origin']]+[x[1] for x in targets]
        card=Image.new('RGB',(250*len(frame_names),340),'#18202a');d=ImageDraw.Draw(card)
        for k,n in enumerate(frame_names):
            j=names.index(n);x,y=z['uv'][j,pi];rect=ws[n]['rect'];cx=int(round(x));cy=int(round(y))
            # Bound all contextual pixels to the pre-frozen review rectangle.
            box=(max(rect[0],cx-36),max(rect[1],cy-36),min(rect[2],cx+36),min(rect[3],cy+36))
            patch=ims[n].crop(box);pw,ph=patch.size
            draw=ImageDraw.Draw(patch);draw.line((cx-box[0]-4,cy-box[1],cx-box[0]+4,cy-box[1]),fill='#f77bd0');draw.line((cx-box[0],cy-box[1]-4,cx-box[0],cy-box[1]+4),fill='#f77bd0')
            patch.thumbnail((230,220));patch=patch.resize((max(1,round(pw*min(230/pw,220/ph))),max(1,round(ph*min(230/pw,220/ph)))),Image.Resampling.NEAREST)
            card.paste(patch,(k*250+10,45));d.text((k*250+8,6),('SOURCE ' if k==0 else 'CONFLICT ')+n,fill='white')
            diff=float(np.abs(z['rgb3x3'][j,pi]-z['rgb3x3'][vi,pi]).mean())
            d.text((k*250+8,24),f'pixel {cx},{cy}  delta={diff:.4f}',fill='white')
            d.text((k*250+8,270),f'valid={bool(z["valid"][j,pi])}; room kernel={z["kernelRoomCount"][j,pi]}/9',fill='white')
            d.text((k*250+8,288),'No independent first-surface depth',fill='#bdc9db')
        title=f'{r["kind"]}-{r["pointId"][:12]}-{r["origin"][:10]}'
        file=a.output/(title+'.png');card.save(file)
        records.append({'file':str(file),'pointId':r['pointId'],'surfaceId':r['surfaceId'],'origin':r['origin'],
                        'kind':r['kind'],'group':r['group'],'originalDecision':r['original_decision'],
                        'detailedTargetViews':[x[1] for x in targets],'reviewScope':'same frozen window only',
                        'independentOccluderEvidence':False})
    (a.output/'figure-index.json').write_text(json.dumps({'windows':pictures,'examples':records,'windowsSha256':sha(a.windows),'scriptSha256':sha(__file__)},indent=2))
    print(json.dumps({'windowFigures':len(pictures),'examples':len(records)}))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ['audit','prepared','windows','output']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--all-local-conflicts',action='store_true')
    main(p.parse_args())