"""Confidence and multiview filtered depth proposals -> standard SELF Gaussians.
Dense predictions are hypotheses. No camera fitting, generated colour or
production publishing. Head-local and world data are NEVER fused together.
"""
from pathlib import Path
import json,hashlib
import cv2,numpy as np
from scipy.spatial.transform import Rotation
from reconstruction_dense_contract import project,unproject,bilinear,digest,write_json

PART_MASKS={0:('room_visible',),1:('face_core','face_boundary'),2:('hair_visible',),3:('glasses_visible',)}

def native_uv(uv,A):
    q=np.c_[uv,np.ones(len(uv))]@np.linalg.inv(A).T
    return q[:,:2]/q[:,2:]

def label_at(labels,uv,part):
    h,w=next(iter(labels.values())).shape
    finite=np.isfinite(uv).all(1)
    xy=np.rint(np.nan_to_num(uv)).astype(int)
    inside=finite&(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h)
    xy=xy.clip([0,0],[w-1,h-1])
    visible=np.logical_or.reduce([labels[k] for k in PART_MASKS[part]])
    # Boundaries are observations, but uncertainty is not negative evidence.
    return inside&visible[xy[:,1],xy[:,0]]&~labels['unknown_or_occluded'][xy[:,1],xy[:,0]]

def surface_samples(depth,K,T,stride=2):
    h,w=depth.shape;y,x=np.mgrid[1:h-1:stride,1:w-1:stride]
    uv=np.c_[x.ravel(),y.ravel()].astype(float);z=depth[y,x].ravel()
    xyz=unproject(uv,z,K,T)
    xp=unproject(uv+[1,0],depth[y,x+1].ravel(),K,T)
    yp=unproject(uv+[0,1],depth[y+1,x].ravel(),K,T)
    a=xp-xyz;b=yp-xyz;n=np.cross(a,b)
    norm=np.linalg.norm(n,axis=1);tangent_a=np.linalg.norm(a,axis=1);tangent_b=np.linalg.norm(b,axis=1)
    valid=np.isfinite(xyz).all(1)&np.isfinite(norm)&(z>0)&(norm>1e-12)
    # Depth discontinuities cannot make a broad kernel bridging separate layers.
    valid&=(np.abs(depth[y,x+1].ravel()-z)<.03*z)&(np.abs(depth[y+1,x].ravel()-z)<.03*z)
    axis_a=a/np.maximum(tangent_a[:,None],1e-12);normal=n/np.maximum(norm[:,None],1e-12)
    axis_b=np.cross(normal,axis_a);basis=np.stack([axis_a,axis_b,normal],axis=-1)
    scale=np.stack([tangent_a,tangent_b,np.minimum(tangent_a,tangent_b)*.28],1)*stride*.65
    return uv,xyz,basis,scale,valid

def multiview_support(xyz,part,targets,labels,min_views=3,tolerance=.03):
    """Count distinct original images. Prediction agreement is NOT ground truth.
    Foreground blocking a head/room proposal is unknown, not free-space error.
    """
    support=np.zeros(len(xyz),np.int16);free=np.zeros(len(xyz),np.int16);occluded=np.zeros(len(xyz),np.int16)
    seen=set()
    for row,arr in targets:
        if row['imageName'] in seen:continue
        seen.add(row['imageName']);uv,z=project(xyz,arr['K'],arr['W2C'])
        h,w=arr['depth'].shape;inside=(uv[:,0]>=0)&(uv[:,0]<w-1)&(uv[:,1]>=0)&(uv[:,1]<h-1)&(z>0)
        obs=bilinear(arr['depth'],uv);conf=bilinear(arr['confidence'],uv)
        nuv=native_uv(uv,arr['nativeToProcessed']);observed=label_at(labels[row['imageName']],nuv,part)
        valid=inside&observed&np.isfinite(obs)&(obs>0)&(conf>=np.quantile(arr['confidence'],.2))
        tol=tolerance*obs
        support+= (valid&(np.abs(z-obs)<=tol)).astype(np.int16)
        free+=(valid&(z<obs-tol)).astype(np.int16)
        occluded+=(valid&(z>obs+tol)).astype(np.int16)
    return support,free,occluded,(support>=min_views)&(free<=1)

def build_surfaces(prepared,depth_dir,out,*,head_budget=22000,room_budget=30000,stride=2,min_views=3):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);prep=Path(prepared);depth_dir=Path(depth_dir)
    spec=json.loads((depth_dir/'manifest.json').read_text());rows=spec['observations']
    # Grouped only by explicit coordinate namespace AND prediction window.
    groups={};labels={};rgb={}
    for row in rows:
        if row['role']!='train' or row['imageName'] in spec['forbidden']:raise ValueError('training_role_leak')
        if row['sourceHash']!=spec['sourceHash']:raise ValueError('source_mismatch')
        if not row['scaleGatePassed']:continue
        n=row['imageName']
        if digest(prep/'rectified_observations'/n)!=row['imageHash']:raise ValueError('native_image_changed')
        groups.setdefault((row['group'],row['window']),[]).append((row,dict(np.load(depth_dir/row['file']))))
        if n not in labels:
            labels[n]=dict(np.load(prep/'rectified_observations'/(n+'.npz')))
            rgb[n]=cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
    buckets={'head-local':[],'world':[]};counts=[]
    for (group,window),targets in groups.items():
        parts=[0] if group=='world' else [1,2,3]
        for row,arr in targets:
            uv,xyz,basis,scale,ok=surface_samples(arr['depth'],arr['K'],arr['W2C'],stride)
            nuv=native_uv(uv,arr['nativeToProcessed']);confidence=bilinear(arr['confidence'],uv)
            ok&=confidence>=np.quantile(arr['confidence'],.2)
            for part in parts:
                chosen=ok&label_at(labels[row['imageName']],nuv,part)
                ids=np.flatnonzero(chosen)
                if not len(ids):continue
                sup,free,occ,accepted=multiview_support(xyz[ids],part,targets,labels,min_views)
                ids=ids[accepted]
                counts.append(dict(group=group,window=window,name=row['imageName'],part=part,
                    proposed=int(chosen.sum()),accepted=len(ids),freeRejected=int((free>1).sum()),
                    occludedObservations=int(occ.sum())))
                if not len(ids):continue
                colours=bilinear(rgb[row['imageName']],nuv[ids])
                valid=np.isfinite(colours).all(1);ids=ids[valid];colours=colours[valid]
                q=Rotation.from_matrix(basis[ids]).as_quat()[:,[3,0,1,2]]
                # Original-pixel colour; no filled holes, learned skin or DC paint.
                sh=np.zeros((len(ids),4,3),np.float32);sh[:,0]=(colours-.5)/.28209479177387814
                ids64=np.array([int.from_bytes(hashlib.sha256(f'{group}:{window}:{row["imageName"]}:{part}:{int(i)}'.encode()).digest()[:8],'little')&((1<<63)-1) for i in ids],np.int64)
                buckets[group].append(dict(means=xyz[ids],quats=q,scales=scale[ids],sh=sh,
                    opacity=np.full(len(ids),.6),parts=np.full(len(ids),part,np.int64),uid=ids64,
                    confidence=confidence[ids],support=sup[accepted][valid],source_image=np.full(len(ids),row['imageName']),source_uv=nuv[ids]))
        print('SURFACE_WINDOW',group,window,flush=True)
    output={}
    for group,pieces in buckets.items():
        if not pieces:continue
        arrays={k:np.concatenate([p[k] for p in pieces]) for k in pieces[0]}
        initial=len(arrays['means']);step=float(np.median(arrays['scales'][:,:2]))
        # Different semantically physical layers are never collapsed together.
        voxel=np.floor(arrays['means']/step).astype(np.int64)
        keys=np.c_[arrays['parts'],voxel];order=np.lexsort((arrays['uid'],-arrays['confidence'],-arrays['support']))
        _,ix=np.unique(keys[order],axis=0,return_index=True);select=order[ix]
        budget=head_budget if group=='head-local' else room_budget
        if len(select)>budget:
            # Deterministic distributed budget, not choosing favourable dev RGB.
            ranks=np.argsort(arrays['uid'][select]);select=select[ranks[np.rint(np.linspace(0,len(ranks)-1,budget)).astype(int)]]
        arrays={k:v[select] for k,v in arrays.items()}
        np.savez_compressed(out/(group+'.npz'),**arrays,source_hash=np.array(spec['sourceHash']))
        output[group]=dict(beforeDedup=initial,count=len(select),voxelSize=step,
            partCounts={str(p):int((arrays['parts']==p).sum()) for p in np.unique(arrays['parts'])})
    write_json(out/'result.json',dict(sourceHash=spec['sourceHash'],depthManifestHash=digest(depth_dir/'manifest.json'),
        config=dict(headBudget=head_budget,roomBudget=room_budget,stride=stride,minViews=min_views,relativeDepthTolerance=.03),
        groups=output,counts=counts,knownCamerasUnchanged=True,supervision='predicted_multiview_depth_hypothesis_not_measurement_truth',published=False))
    return output