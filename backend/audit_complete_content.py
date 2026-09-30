"""Target-preserving diagnostics for measured movement and component handoff.
The MVS pair score audit follows installed v2.4.0, not a new matching pass.
"""
import argparse,json,struct,shutil,time
from pathlib import Path
from collections import Counter
import numpy as np,torch,cv2,pycolmap
from reconstruction_evidence_stage import load_stage
from reconstruction_surface_evidence import project,triangulate_track
from reconstruction_portrait_pipeline import make_frame,draw
from reconstruction_portrait_model import joined_state
from reconstruction_complete_contract import observed_completeness
from reconstruction_components_v3 import save_json,sha
from run_complete_observations import regional_masks

def first_mvs_camera(path):
    with Path(path).open('rb') as f:
        def n(fmt):return struct.unpack('<'+fmt,f.read(struct.calcsize('<'+fmt)))
        def string():return f.read(n('Q')[0]).decode()
        if f.read(4)!=b'MVSI' or n('I')[0]!=7:raise ValueError('only_pinned_v7_supported')
        n('I');platforms=n('Q')[0]
        if platforms!=1:raise ValueError('probe_expects_one_platform')
        platform=string();cameras=n('Q')[0]
        if cameras!=1:raise ValueError('probe_expects_one_camera')
        name=string();band=string();w,h=n('II');K=np.array(n('9d')).reshape(3,3)
        return K,{'platform':platform,'camera':name,'band':band,'width':w,'height':h}

def pair_audit(folder):
    folder=Path(folder);r=pycolmap.Reconstruction(folder/'colmap/sparse');K,info=first_mvs_camera(folder/'scene.mvs');ids=[]
    lines=(folder/'colmap/sparse/images.txt').read_text().splitlines()
    for k in range(0,len(lines),2):ids.append(int(lines[k].split()[0]))
    index={x:i for i,x in enumerate(ids)};points={};rows=[];per_view={};repro=[]
    for pid,p in r.points3D.items():
        views={e.image_id for e in p.track.elements};points[pid]=(p.xyz,views)
        for e in p.track.elements:
            im=r.images[e.image_id];C=np.vstack([im.cam_from_world().matrix(),[0,0,0,1]]);uv,z=project(p.xyz[None],C,r.cameras[im.camera_id].calibration_matrix());repro.append(float(np.linalg.norm(uv[0]-im.points2D[e.point2D_idx].xy)))
    for a in ids:
        ca=np.vstack([r.images[a].cam_from_world().matrix(),[0,0,0,1]]);ea=np.linalg.inv(ca)[:3,3];local=[]
        for b in ids:
            if a==b:continue
            cb=np.vstack([r.images[b].cam_from_world().matrix(),[0,0,0,1]]);eb=np.linalg.inv(cb)[:3,3];shared=[v[0] for v in points.values() if a in v[1] and b in v[1]];count=len(shared)
            if not count:rows.append({'a':index[a],'b':index[b],'shared':0,'stage':'SelectNeighborViews:no_shared_points'});continue
            xyz=np.array(shared);ua,za=project(xyz,ca,K);ub,zb=project(xyz,cb,K);pos=(za>0)&(zb>0);ray1=xyz-ea;ray2=xyz-eb;ang=np.arccos(np.clip(np.sum(ray1*ray2,axis=1)/(np.linalg.norm(ray1,axis=1)*np.linalg.norm(ray2,axis=1)),-1,1));scale=zb/za
            # Equal focal lengths in this recorded single-camera contract.
            opt=np.deg2rad(12);sig=np.where(ang<opt,.38,.7)*opt;weight=np.maximum(np.exp(-.5*((ang-opt)/sig)**2),.1)*np.where(scale>1.6,(1.6/scale)**2,np.where(scale>=1,1,scale**2))
            inside=pos&(ua[:,0]>=0)&(ua[:,1]>=0)&(ua[:,0]<info['width'])&(ua[:,1]<info['height'])&(ub[:,0]>=0)&(ub[:,1]>=0)&(ub[:,0]<info['width'])&(ub[:,1]<info['height'])
            cells=np.floor(ua[inside]/[info['width'],info['height']]*16).astype(int);area=len(np.unique(cells,axis=0))/256;score=float(weight[pos].sum()*max(area,.01));stage='SelectNeighborViews:shared_below_3' if pos.sum()<3 else 'SelectNeighborViews:no_inside_projection' if not inside.any() else 'InitViews:score_below_2' if score<2 else 'InitViews:score_eligible'
            row={'a':index[a],'b':index[b],'imageIDs':[a,b],'names':[r.images[a].name,r.images[b].name],'shared':count,'positive':int(pos.sum()),'insideBoth':int(inside.sum()),'depthRangeA':[float(za.min()),float(za.max())],'angleMedianDeg':float(np.degrees(np.median(ang))),'scaleMean':float(scale.mean()),'coveredCells':len(np.unique(cells,axis=0)),'areaFraction':area,'score':score,'baseline':float(np.linalg.norm(ea-eb)),'stage':stage};rows.append(row);local.append(row)
        valid=[x for x in local if x['positive']>=3 and x['insideBoth']>0];per_view[r.images[a].name]={'mvsIndex':index[a],'externalID':a,'selectNeighbors':len(valid),'SelectViewsPass':len(valid)>=2,'maxScore':max([x['score'] for x in valid],default=0),'InitViewsEligible':sum(x['score']>=max(2,.03*max([y['score'] for y in valid],default=0)) for x in valid)}
    kexport=r.cameras[r.images[ids[0]].camera_id].calibration_matrix();return {'folder':str(folder),'sceneHash':sha(folder/'scene.mvs'),'imageIndexMapping':per_view,'pointCount':len(points),'pairs':rows,'realMvsK':K.tolist(),'exportK':kexport.tolist(),'mvsMinusExportK':(K-kexport).tolist(),'reprojectionOriginalNativeMedian':float(np.median(repro)),'reprojectionOriginalNativeP90':float(np.quantile(repro,.9)),'pixelConventionFinding':'Recorded importer subtracts 0.5 from principal point. Native exporter wrote integer-centre K without +0.5. Real MVSI confirms -0.5; do not apply another -0.5. Not explanation for zero score alone.','rules':'v2.4.0 score; ROI disabled in recorded run; <=6 neighbors so size-conditional filter cannot remove entries (minimum 9); InitViews floor=2; no threshold changed','info':info}

def run(manifest,measurements,old,extra_mvs,out):
    start=time.perf_counter();out=Path(out);old=Path(old);data,plan,m,contract=load_stage(manifest,out);shutil.copyfile(__file__,out/'algorithm-source'/Path(__file__).name)
    pair=[pair_audit(old/'C-motion-diagnostic'),pair_audit(extra_mvs)];save_json(out/'MVS-pairs.json',pair)
    windows=[];appendages=[];target_stats={};cams={n:m.adjusted_frame(make_frame(data,n,crop=False))['F'].cpu().numpy() for n in data['local']}
    for file in sorted(Path(measurements).glob('window-*/tracks.json')):
        j=json.loads(file.read_text());tracks=j['tracks'];counts=Counter(t['region'] for t in tracks);cloth=[t for t in tracks if t['region'].startswith(('upper_','lower_'))];spans=all(counts[x]>0 for x in ['upper_left','upper_right','lower_middle']);windows.append({'file':str(file),'counts':dict(counts),'clothTracks':len(cloth),'bilateralUpperAndChest':spans,'geometryAdmissible':len(cloth)>=40 and spans,'QExecuted':False,'reason':'No bilateral shoulder/collar-supported trajectory; no free SE3 fitted to chest-only texture'})
        for t in tracks:
            if t['region'] not in ['hair','glasses']:continue
            fitted={'observations':t['observations'][:-1]}
            if len(fitted['observations'])<2:continue
            x,s=triangulate_track(fitted,cams,data['K']);third=t['observations'][-1];uv,z=project(x[None],cams[third['name']],data['K']);third_err=float(np.linalg.norm(uv[0]-third['uv']));line_support=[]
            if t['region']=='glasses':
                for o in t['observations']:
                    n=o['name'];gray=cv2.cvtColor((data['rgb'][n]*255).astype(np.uint8),cv2.COLOR_RGB2GRAY);xy=np.rint(o['uv']).astype(int);x0,y0=np.maximum(xy-24,0);x1,y1=np.minimum(xy+25,[1080,1920]);patch=gray[y0:y1,x0:x1];lines=cv2.createLineSegmentDetector().detect(patch)[0];near=0
                    if lines is not None:
                        for l in lines[:,0]:
                            a=l[:2]+[x0,y0];b=l[2:]+[x0,y0];v=b-a;u=np.clip(np.dot(xy-a,v)/max(np.dot(v,v),1e-8),0,1)
                            if np.linalg.norm(xy-a-u*v)<=2.5 and np.linalg.norm(v)>=6:near+=1
                    line_support.append(near)
            appendages.append({'id':t['id'],'part':t['region'],'names':[o['name'] for o in t['observations']],'xyz':x.tolist(),**s,'thirdError':third_err,'thirdPositive':bool(z[0]>0),'nearbyNativeLineCounts':line_support,'acceptedStructure':False,'reason':'Point proposal alone cannot establish connected external hair surface or verified physical frame curve; no cap or reflection points installed'})
    with torch.no_grad():
        for n in list(dict.fromkeys([data['reference'],plan['train'][0],'frame_0025.png'])):
            if n not in data['worlds']:continue
            f=m.adjusted_frame(make_frame(data,n,crop=False));body=draw(m.body_state(n),f['C'],f['K'],1080,1920,unit_scale=m.scale);a=body['alpha'].cpu().numpy();lab=data['labels'][n];regions=regional_masks(lab);target_stats[n]={k:observed_completeness(mask,lab['unknown_or_occluded'],a) for k,mask in regions.items() if k.startswith(('upper_','lower_'))};target_stats[n]['full_neck_cloth']=observed_completeness(lab['neck_cloth_visible'],lab['unknown_or_occluded'],a)
            image=(data['rgb'][n]*255).astype(np.uint8).copy();bad=lab['neck_cloth_visible']&~lab['unknown_or_occluded']&(a<.8);image[bad]=(image[bad]*.5+np.array([180,35,35])*.5).astype(np.uint8);cv2.imwrite(str(out/(n.replace('.png','')+'-body-unexplained.png')),cv2.cvtColor(image,cv2.COLOR_RGB2BGR))
    save_json(out/'local-evidence.json',{'windows':windows,'appendages':appendages,'targets':target_stats})
    identity=[]
    for file in [old/'C-training/fixed-T2-garment-diagnostic.identity.npz',old/'B-scoped-replay/fixed-scoped-B-T2.identity.npz']:
        z=np.load(file);u=z['uid'] if 'uid' in z else z['point_uid'];ns=z['namespace'] if 'namespace' in z else z['source_namespace'];identity.append({'path':str(file),'hash':sha(file),'total':len(u),'uniqueUIDs':len(np.unique(u)),'namespaces':{str(v):int((ns==v).sum()) for v in np.unique(ns)},'UIDRangeByNamespace':{str(v):[int(u[ns==v].min()),int(u[ns==v].max())] for v in np.unique(ns)}})
    save_json(out/'result.json',{'windows':windows,'appendageGeometry':appendages,'fullObservedClothing':target_stats,'existingTensorSidecars':identity,'anatomicalMaskLimit':'Current source only contains combined neck_cloth_visible. Six spatial bins retain its full union but are NOT ground-truth neck/collar/shoulder/sleeve segmentation. No separate anatomical completeness claimed.','newClothTrainingExecuted':False,'newHairOrGlassesInstalled':False,'published':False,'seconds':time.perf_counter()-start})
    print(json.dumps({'windows':windows,'appendageCount':len(appendages),'MVS':[x['imageIndexMapping'] for x in pair]}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ['manifest','measurements','old','extra-mvs','out']:p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.manifest,a.measurements,a.old,a.extra_mvs,a.out)
