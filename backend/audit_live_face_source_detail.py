"""CPU evidence for native face detail, local registration and source sampling.

No images from development observations are used for appearance proposals.
Source sharpness and landmark error are diagnostics, not geometry truth.
"""
from pathlib import Path
import argparse
import json
import cv2
import numpy as np

from compare_live_opaque_person_runs import resolve,read_json,digest,mask_hash
from audit_live_boundary_coverage import original_semantics
from reconstruction_live_face_domain import observed_face_domain
from reconstruction_local_sampling import schedule_receipt
from flame_open_model import FlameOpen,EMBEDDING
from probe_flame_real_appearance import barycentric_samples,bound_points
from appearance_direction_contract import C0


def quant(values):
    a=np.asarray(values);a=a[np.isfinite(a)]
    return np.quantile(a,[.1,.5,.9,.99]).tolist() if a.size else None


def masked_detail(rgb,mask):
    inside=cv2.erode(mask.astype(np.uint8),np.ones((5,5),np.uint8)).astype(bool)
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    dx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)/8
    dy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)/8
    lap=cv2.Laplacian(gray,cv2.CV_32F,ksize=3)/4
    return {'pixels':int(inside.sum()),'gradientQuantiles':quant(np.hypot(dx,dy)[inside]),
        'laplacianVariance':float(np.var(lap[inside],dtype=np.float64)) if inside.any() else None,
        'note':'Native image structure proxy; skin texture/lighting affect it, not a pure focus or quality score.'}


def audit(run,output):
    run=resolve(run);out=resolve(output)
    if out.exists():raise FileExistsError(out)
    config=read_json(run/'config.json');prepared=resolve(config['prepared']);meta=read_json(prepared/'preparation.json')
    with np.load(prepared/'local_geometry.npz',allow_pickle=False) as a:g={k:a[k].copy() for k in a.files}
    names=g['names'].tolist();roles=g['roles'].tolist();train=[n for n,r in zip(names,roles) if r=='train']
    K=g['K'];by_name={n:i for i,n in enumerate(names)}
    prior_path=run/'observed-face-initial-appearance.npz'
    with np.load(prior_path,allow_pickle=False) as a:prior={k:a[k].copy() for k in a.files}
    if digest(prior_path)!=config['appearanceHash']:raise ValueError('face_detail_prior_identity')
    if config['sourceSha256']!=meta['sourceHash']:raise ValueError('face_detail_source_identity')
    model=FlameOpen(24,12);faces=model.faces.numpy()
    ids,bary,spacing=barycentric_samples(g['meshes'][by_name[train[0]]],faces,20000)
    surface_count=len(prior['surface_ids']);original_ids=prior['source_index'][:surface_count]
    np.testing.assert_array_equal(ids[original_ids],prior['surface_ids'])
    np.testing.assert_array_equal(bary[original_ids],prior['surface_bary'])
    with np.load(EMBEDDING,allow_pickle=False) as a:
        landmark_faces=a['lmk_face_idx'];landmark_bary=a['lmk_b_coords'];landmark_indices=a['landmark_indices']
    fitting=np.arange(len(landmark_indices))%5!=0
    view_reference=read_json(run/'portrait.view.json')['sourceFrame']
    center_ref=-g['F'][by_name[view_reference],:3,:3].T@g['F'][by_name[view_reference],:3,3]
    angle_ref=np.arctan2(center_ref[0],center_ref[2]);rows=[];colors=[];validity=[];cosines=[];footprints=[]
    sampling_quantization=[];all_support=np.zeros(20000,np.int32);all_sum=np.zeros((20000,3),np.float64)
    hashes={str(path):digest(path) for path in (prepared/'local_geometry.npz',prepared/'preparation.json',prior_path,run/'config.json')}
    out.mkdir(parents=True)
    for name,role in zip(names,roles):
        i=by_name[name];F=g['F'][i];mesh=g['meshes'][i]
        source_path=prepared/'rectified_observations'/name;mask_path=prepared/'rectified_observations'/(name+'.npz')
        hashes[str(source_path)]=digest(source_path);hashes[str(mask_path)]=digest(mask_path)
        rgb=cv2.cvtColor(cv2.imread(str(source_path)),cv2.COLOR_BGR2RGB).astype(np.float32)/255.
        with np.load(mask_path,allow_pickle=False) as a:old={k:a[k].copy() for k in a.files}
        classes,confidence,outside,labels=original_semantics(prepared,meta,name,K,old)
        mask=observed_face_domain(classes,confidence,outside,labels)
        if mask_hash(mask)!=config['observedFaceDomain']['maskHashes'][name]:raise ValueError('face_detail_mask_identity:'+name)
        skin=mask&(classes==3)&(confidence>=.7)&~outside
        y,x=np.where(mask);box=[int(x.min()),int(y.min()),int(x.max()+1),int(y.max()+1)]
        embedded=(mesh[faces[landmark_faces]]*landmark_bary[...,None]).sum(1)
        cam=embedded@F[:3,:3].T+F[:3,3];p=cam@K.T;uv=p[:,:2]/p[:,2:]
        errors=np.linalg.norm(uv-g['marks'][i][landmark_indices],axis=1)
        center=-F[:3,:3].T@F[:3,3];angle=np.arctan2(center[0],center[2])-angle_ref
        angle=np.degrees(np.arctan2(np.sin(angle),np.cos(angle)))
        row={'name':name,'role':role,'nativeSize':[rgb.shape[1],rgb.shape[0]],'faceBox':box,
            'relativeHeadCameraAzimuthDegrees':float(angle),'faceDetail':masked_detail(rgb,mask),
            'skinDetail':masked_detail(rgb,skin),'landmarkFit84Px':quant(errors[fitting]),
            'landmarkReserved21Px':quant(errors[~fitting]),'landmarkAll105Px':quant(errors),
            'registrationNote':'MediaPipe-to-FLAME reprojection, not independent surface truth; F from current prepared.'}
        # CPU replay of the real 20k sampling visibility, before selecting the
        # retained prior points. Replaying only retained points changes z-buffer.
        if role=='train':
            points,normals=bound_points(mesh,faces,ids,bary)
            camera=points@F[:3,:3].T+F[:3,3];p=camera@K.T;floatpixel=p[:,:2]/np.maximum(p[:,2:],.01)
            pixel=np.rint(floatpixel).astype(int);u,v=pixel.T;h,w=rgb.shape[:2]
            valid=(camera[:,2]>.05)&(u>=0)&(u<w)&(v>=0)&(v<h)
            view=(-camera)/np.linalg.norm(camera,axis=1,keepdims=True)
            cosine=((normals@F[:3,:3].T)*view).sum(1)
            valid&=cosine>0;xclip=u.clip(0,w-1);yclip=v.clip(0,h-1)
            depth=np.full(((h+1)//2,(w+1)//2),np.inf)
            np.minimum.at(depth,(yclip[valid]//2,xclip[valid]//2),camera[valid,2])
            valid&=camera[:,2]<=depth[yclip//2,xclip//2]+.0035
            valid&=mask[yclip,xclip]&~labels['hair_visible'][yclip,xclip]
            sampled=rgb[yclip,xclip]
            all_support[valid]+=1;all_sum[valid]+=sampled[valid]
            colors.append(sampled[original_ids]);validity.append(valid[original_ids]);cosines.append(cosine[original_ids])
            # Explicit camera Jacobian and original covariance: sigma eigenvalue
            # is not a raster radius, conic support or measured optical PSF.
            z=camera[original_ids,2];xx=camera[original_ids,0];yy=camera[original_ids,1]
            J=np.zeros((surface_count,2,3));J[:,0,0]=K[0,0]/z;J[:,1,1]=K[1,1]/z
            J[:,0,2]=-K[0,0]*xx/z**2;J[:,1,2]=-K[1,1]*yy/z**2
            cov=np.zeros((surface_count,3,3));diag=np.exp(prior['log_scales'][:surface_count])**2
            cov[:,range(3),range(3)]=diag
            camcov=F[:3,:3][None]@cov@F[:3,:3].T[None]
            cov2=J@camcov@J.transpose(0,2,1);major=np.sqrt(np.linalg.eigvalsh(cov2)[:,-1])
            footprints.append(major);sv=valid[original_ids]
            row.update(retainedPointSamples=int(sv.sum()),sourceFacingCosine=quant(cosine[original_ids][sv]),
                grazingSamplesCosineBelow02=int((sv&(cosine[original_ids]<.2)).sum()),
                initialProjectedSigmaMajorPx=quant(major[sv]),
                nearestSamplingDisplacementPx=quant(np.linalg.norm(pixel[original_ids]-floatpixel[original_ids],axis=1)[sv]))
        rows.append(row)
    original_colors=prior['sh_coeff'][:surface_count,0]*C0+.5
    replay=all_sum[original_ids]/all_support[original_ids,None]
    np.testing.assert_allclose(replay,original_colors,atol=2e-7,rtol=0)
    colors=np.stack(colors);validity=np.stack(validity);cosines=np.stack(cosines);footprints=np.stack(footprints)
    support=validity.sum(0)
    variance=((colors-replay[None])**2*validity[...,None]).sum(0)/support[:,None]
    # Propose weights from measured training observations only, never dev RGB.
    # This is a color estimate comparison, not a replacement trained candidate.
    sharp=np.asarray([r['faceDetail']['laplacianVariance'] for r in rows if r['role']=='train'])
    sharp=np.clip(sharp/np.median(sharp),.5,2.)
    # Footprints grow for nearer/greater projected area. The desired projected
    # sampling density is reciprocal metric-per-pixel squared, i.e. sigma^2
    # for this same fixed initial point size, not inverse sigma^2.
    raw_weight=validity*np.clip(cosines,0,1)**2*sharp[:,None]*footprints**2
    weight=raw_weight/np.maximum(raw_weight.sum(0,keepdims=True),1e-12)
    weighted=(colors*weight[...,None]).sum(0)
    loo=[]
    for t,name in enumerate(train):
        active=validity[t]&(support>=3)
        denominator=support-validity[t]
        old=(replay*support[:,None]-colors[t]*validity[t,:,None])/np.maximum(denominator[:,None],1)
        rest=raw_weight.copy();rest[t]=0
        new=(colors*rest[...,None]).sum(0)/np.maximum(rest.sum(0)[:,None],1e-12)
        loo.append({'name':name,'pixelsOrPoints':'same retained surface points, not independent measured geometry',
            'points':int(active.sum()),'oldMeanL1':float(np.abs(old[active]-colors[t,active]).mean()),
            'weightedMeanL1':float(np.abs(new[active]-colors[t,active]).mean())})
    receipt=schedule_receipt(train,config['localSteps'])
    result={'run':str(run),'sourceHash':meta['sourceHash'],'modelHash':model.model_sha256,
        'inputHashes':hashes,'K':K.tolist(),'nativeScale':1,'viewCount':len(names),'trainCount':len(train),
        'views':rows,'initialColour':{'replayMaximumAbsError':float(np.max(np.abs(replay-original_colors))),
            'retainedSurfacePoints':surface_count,'originalSamplingCount':len(ids),
            'supportQuantiles':quant(support),'betweenSourceRgbStdQuantiles':quant(np.sqrt(variance.mean(-1))),
            'weightedProposalDifferenceQuantiles':quant(np.abs(weighted-replay).mean(-1)),
            'weightedProposal':'training-only cosine^2 x bounded native source detail proxy x projected area; no prior mutation',
            'leaveOneTrainingViewOut':loo,
            'caveat':'LOO tests colors at the old assumed geometry, not quality or correct alignment; specularity and semantic/pose errors remain.'},
        'schedule':receipt,'zeroTraining':True,'gpuUsed':False,
        'limitations':['No development image colors enter any appearance estimate.',
            'No training or deployment, no promise that initialization weighting fixes final blur.',
            'Median reprojection improvement does not verify skin depth, glasses or fine texture.',
            'Azimuth is relative local-camera direction from F, not viewer yaw or anatomical ground truth.']}
    np.savez_compressed(out/'sampling-diagnostics.npz',train_names=np.asarray(train),
        colors=colors,valid=validity,cosines=cosines,projected_sigma=footprints,
        original_mean=replay,weighted_proposal=weighted,source_index=original_ids)
    for path,expected in hashes.items():
        if digest(path)!=expected:raise ValueError('face_detail_input_changed:'+path)
    (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'status':'CPU face detail evidence complete','train':len(train),
        'oldMissingGeometry':len(receipt['oldMissingGeometry']),'newMissingGeometry':len(receipt['newMissingGeometry']),
        'sourceVariance':result['initialColour']['betweenSourceRgbStdQuantiles']}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True);parser.add_argument('--output',required=True)
    audit(**vars(parser.parse_args()))
