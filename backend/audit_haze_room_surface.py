"""Finite multi-anchor surface feasibility for ONE observed room region.
Never interprets a source family or a point covariance as a physical wall.
No deletion, opacity edits or fake depth when bounded support is insufficient.
"""
import json,itertools
import cv2,numpy as np,torch,pycolmap
from scipy.spatial import ConvexHull
from run_haze_shared_surface import setup,attach_zero,ROOT,BASE
from reconstruction_components_v3 import save_json,exact_state_hash
from reconstruction_portrait_pipeline import make_frame,draw
from reconstruction_portrait_model import GaussianState,joined_state

def run():
    out,contract,data,plan,m=setup('B-surface-support');attach_zero(m)
    personhash=exact_state_hash(m.portrait);old=json.loads((BASE/'.sources/fullframe-t2-source-recovery-20260929-a/result.json').read_text())
    group=max(old['groups'],key=lambda g:g['faceWeight']);sid=group['sourceID'];observations=group['observations']
    # Three TRAIN views where the original measured source was observed; dev never selects a plane.
    selected=[observations[i] for i in np.linspace(0,len(observations)-1,min(3,len(observations))).round().astype(int)]
    mapping=pycolmap.Reconstruction(data['staticMap']);imgs={im.name:im for im in mapping.images.values()};source=mapping.points3D[sid]
    roomids=torch.where((m.room.metadata['source_id']==sid)&(m.room.metadata['source_kind']==0))[0]
    all_results=[];detail=[]
    for obs in selected:
        name=obs['name'];f=m.adjusted_frame(make_frame(data,name,crop=False));s=joined_state(m.head_state(f).to_world(f['C'],f['F'],m.scale),m.room.state(),m.body_state(name))
        parts=torch.full_like(s.parts,2);parts[len(m.portrait.role)+roomids]=1
        marked=GaussianState(s.means,s.quats,s.scales,s.opacity,s.sh,parts)
        with torch.no_grad():r=draw(marked,f['C'],f['K'],1080,1920,unit_scale=m.scale)
        q=r['q'][...,1].cpu().numpy();labels=data['labels'][name];valid=labels['room_visible']&~labels['unknown_or_occluded'];uv0=np.array(obs['rectifiedXY']);radius=1080/6
        mask=np.zeros_like(valid);x0,y0=np.maximum(0,np.floor(uv0-radius)).astype(int);x1,y1=np.minimum([1080,1920],np.ceil(uv0+radius)).astype(int);mask[y0:y1,x0:x1]=True;mask&=valid
        im=imgs[name];cam=mapping.cameras[im.camera_id];candidates=[]
        for p2 in im.points2D:
            if not p2.has_point3D():continue
            p=mapping.points3D[p2.point3D_id];ray=cam.cam_from_img(p2.xy);uv=data['K']@np.r_[ray,1.];uv=uv[:2]/uv[2];x,y=np.rint(uv).astype(int)
            if not(0<=x<1080 and 0<=y<1920) or not mask[y,x] or p.error>2.5:continue
            ob=[]
            for t in p.track.elements:
                im2=mapping.images[t.image_id];n=im2.name
                if n not in data['train'] or n not in data['worlds']:continue
                ray2=mapping.cameras[im2.camera_id].cam_from_img(im2.points2D[t.point2D_idx].xy);u=data['K']@np.r_[ray2,1.];u=u[:2]/u[2];xx,yy=np.rint(u).astype(int);lab=data['labels'][n]
                if 0<=xx<1080 and 0<=yy<1920 and lab['room_visible'][yy,xx] and not lab['unknown_or_occluded'][yy,xx]:ob.append({'name':n,'uv':u.tolist()})
            if len(ob)>=3:candidates.append({'id':int(p2.point3D_id),'xyz':p.xyz.tolist(),'uv':uv.tolist(),'observations':ob,'error':float(p.error)})
        xyz=np.array([p['xyz'] for p in candidates]);row={'name':name,'sourceID':sid,'region':[int(x0),int(y0),int(x1),int(y1)],'spatiallyDistinctTracks':len(candidates),'validRoomPixels':int(mask.sum()),'familyContribution':float(q[mask].sum()),'points':candidates}
        best=[];plane=None
        if len(xyz)>=6:
            camera=xyz@data['worlds'][name][:3,:3].T+data['worlds'][name][:3,3];tol=3*np.median(camera[:,2])/data['K'][0,0]
            triples=list(itertools.combinations(range(len(xyz)),3));rng=np.random.default_rng(7299);use=rng.choice(len(triples),min(256,len(triples)),replace=False)
            for ti in use:
                tri=xyz[list(triples[ti])];normal=np.cross(tri[1]-tri[0],tri[2]-tri[0]);norm=np.linalg.norm(normal)
                if norm<1e-5:continue
                normal/=norm;good=np.where(abs((xyz-tri[0])@normal)<tol)[0]
                if len(good)>len(best):best=good;plane=(normal,float(normal@tri[0]))
            if len(best)>=3:
                points=xyz[best];center=points.mean(0);_,_,V=np.linalg.svd(points-center,full_matrices=False);n=V[-1];coords=(points-center)@V[:2].T
                rms=float(np.sqrt(np.mean(((points-center)@n)**2)));hull=ConvexHull(coords);hull3=points[hull.vertices];C=data['worlds'][name];v=hull3@C[:3,:3].T+C[:3,3];pix=v@data['K'].T;pix=pix[:,:2]/pix[:,2:]
                hm=np.zeros_like(mask,dtype=np.uint8);cv2.fillConvexPoly(hm,np.rint(pix).astype(np.int32),1);hm=hm.astype(bool)&mask
                evidence={p['name'] for i in best for p in candidates[i]['observations']};support_fraction=float(q[hm].sum()/max(q[mask].sum(),1e-9))
                row.update(planeInliers=len(best),planeRMS=rms,tolerance=tol,normal=n.tolist(),centroid=center.tolist(),hullXYZ=hull3.tolist(),hullRoomPixels=int(hm.sum()),hullContributionFraction=support_fraction,observedTrainingNames=sorted(evidence),planeSourceIds=[candidates[i]['id'] for i in best],
                    planeStatus='finite_hypothesis_not_ground_truth',mayReplaceWholeFamily=bool(len(best)>=8 and len(evidence)>=3 and support_fraction>.9))
                image=(data['rgb'][name]*255).round().astype(np.uint8).copy();cv2.polylines(image,[np.rint(pix).astype(np.int32)],True,(0,230,170),2)
                for p in candidates:cv2.circle(image,tuple(np.rint(p['uv']).astype(int)),3,(230,170,0),1)
                cv2.rectangle(image,(x0,y0),(x1,y1),(180,80,240),2);cv2.imwrite(str(out/name),cv2.cvtColor(image,cv2.COLOR_RGB2BGR))
        np.savez_compressed(out/(name+'.npz'),family_q=q,room=valid,window=mask)
        all_results.append(row)
    assert personhash==exact_state_hash(m.portrait)
    report={'sourceSelection':'largest suspect family in frozen prior contribution audit; not a physical plane claim','sourceID':sid,'groups':all_results,'frozenPortraitHash':personhash,
        'replacementExecuted':False,'trainingSteps':0,'published':False,'scope':'bounded three training regions, original static tracks, no rematch/MVS/camera change',
        'decision':'inspect supported convex regions before any replacement; a family covers multiple surfaces and unknown space'}
    save_json(out/'result.json',report)
    print(json.dumps({'views':[{k:r.get(k) for k in ('name','spatiallyDistinctTracks','planeInliers','hullContributionFraction','mayReplaceWholeFamily')} for r in all_results]}),flush=True)
if __name__=='__main__':run()
