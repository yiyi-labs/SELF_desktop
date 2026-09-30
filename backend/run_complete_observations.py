"""Pinned CoTracker3 proposals with native-image checks; research only.
No hub/download/install calls; all model and image paths are explicit.
"""
from pathlib import Path
import argparse,json,sys,time,hashlib,gc,shutil
import numpy as np,cv2,torch
from reconstruction_components_v3 import save_json,sha


def regional_masks(labels):
    """Spatial inspection bins, NOT claimed anatomical segmentation.
    Their union retains every original neck_cloth pixel, including low texture.
    """
    cloth=labels['neck_cloth_visible'].copy(); y,x=np.where(cloth); h,w=cloth.shape
    bins={k:np.zeros_like(cloth) for k in ('upper_left','upper_middle','upper_right','lower_left','lower_middle','lower_right')}
    if len(x):
        xs=[np.quantile(x,.33),np.quantile(x,.67)];ym=np.quantile(y,.4); yy,xx=np.indices(cloth.shape)
        for half,ymask in [('upper',yy<=ym),('lower',yy>ym)]:
            for part,xmask in [('left',xx<xs[0]),('middle',(xx>=xs[0])&(xx<xs[1])),('right',xx>=xs[1])]:bins[half+'_'+part]=cloth&ymask&xmask
    return {'face':labels['face_core']&~labels['glasses_visible'],'hair':labels['hair_visible'],'glasses':labels['glasses_visible'],**bins}


def distributed_queries(image,labels,quotas=None):
    quotas=quotas or {'face':72,'hair':48,'glasses':24,**{k:32 for k in regional_masks(labels) if k.startswith(('upper_','lower_'))}}
    gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY);response=cv2.cornerMinEigenVal(gray,3);queries=[];regions=[]
    for name,mask in regional_masks(labels).items():
        valid=mask&~labels['unknown_or_occluded']; valid[:15]=False;valid[-15:]=False;valid[:,:15]=False;valid[:,-15:]=False
        ys,xs=np.where(valid)
        if not len(xs):continue
        quota=quotas[name];cols=max(1,int(np.sqrt(quota*(xs.max()-xs.min()+1)/(ys.max()-ys.min()+1))));rows=int(np.ceil(quota/cols));xe=np.linspace(xs.min(),xs.max()+1,cols+1).astype(int);ye=np.linspace(ys.min(),ys.max()+1,rows+1).astype(int)
        for iy in range(rows):
            for ix in range(cols):
                m=valid[ye[iy]:ye[iy+1],xe[ix]:xe[ix+1]]
                if not m.any():continue
                score=np.where(m,response[ye[iy]:ye[iy+1],xe[ix]:xe[ix+1]],-1);y,x=np.unravel_index(np.argmax(score),score.shape);queries.append([x+xe[ix],y+ye[iy]]);regions.append(name)
    return np.asarray(queries,np.float32),regions


def letterbox(image):
    h,w=image.shape[:2];ratio=min(512/w,384/h);nw,nh=round(w*ratio),round(h*ratio);ox=(512-nw)//2;oy=(384-nh)//2
    canvas=np.zeros((384,512,3),np.uint8);canvas[oy:oy+nh,ox:ox+nw]=cv2.resize(image,(nw,nh),interpolation=cv2.INTER_AREA)
    # OpenCV resize pixel centres: destination=(source+.5)*scale-.5+offset.
    return canvas,{'sx':nw/w,'sy':nh/h,'ox':ox,'oy':oy,'width':w,'height':h}


def map_pixels(p,m,inverse=False):
    scale=np.array([m['sx'],m['sy']]);off=np.array([m['ox'],m['oy']]);p=np.asarray(p)
    return (p-off+.5)/scale-.5 if inverse else (p+.5)*scale-.5+off


def propose(model,video,queries,times=None):
    times=np.zeros(len(queries),np.float32) if times is None else np.asarray(times,np.float32)
    q=torch.cat([torch.as_tensor(times[:,None]),torch.as_tensor(queries,dtype=torch.float32)],1)[None].cuda()
    model(video[:,:1],is_first_step=True,queries=q,add_support_grid=True)
    result=None
    for start in range(0,video.shape[1],model.step):
        result=model(video[:,start:start+model.step*2],add_support_grid=True)
        if start+model.step*2>=video.shape[1]:break
    return result[0][0,:video.shape[1]].cpu().numpy(),result[1][0,:video.shape[1]].cpu().numpy()


def run(prepared,tool,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=False);prep=Path(prepared);tool=Path(tool);manifest=json.loads((tool/'manifest.json').read_text(encoding='utf-8-sig'));assert sha(tool/'scaled_online.pth')==manifest['sha256'];sys.path.insert(0,str(tool/'source'/('co-tracker-'+manifest['codeCommit'])))
    from cotracker.predictor import CoTrackerOnlinePredictor
    if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; no tracking results produced')
    meta=json.loads((prep/'preparation.json').read_text());geom=dict(np.load(prep/'local_geometry.npz'));train=sorted(set(meta['train'])&set(geom['names']));windows=[]
    # Select largest connected world/local run, with overlapping second window.
    # IDs only order the explicit imageName list; cameras always join by name.
    world=set(geom['world_names']);candidates=[]
    for n in train:
        a=[v for v in train if v in world and 0<=int(v[6:10])-int(n[6:10])<=14]
        if 8<=len(a)<=16:candidates.append(a)
    def coverage_score(names):
        z=dict(np.load(prep/'rectified_observations'/(names[0]+'.npz')));ms=regional_masks(z);return min([int(v.sum()) for k,v in ms.items() if k.startswith(('upper_','lower_'))]),len(names)
    first=max(candidates,key=coverage_score);windows.append(first)
    remain=[v for v in train if v in world and int(first[len(first)//2][6:10])<=int(v[6:10])<=int(first[-1][6:10])+18][:16]
    if len(remain)>=8 and len(set(remain)&set(first))>=3:windows.append(remain)
    save_json(out/'config.json',{'windows':windows,'codeCommit':manifest['codeCommit'],'weightHash':manifest['sha256'],'native':[1080,1920],'networkCanvas':[512,384],'queries':'stratified face/hair/glasses plus six full-cloth spatial bins','noRGBAuditUse':True,'networkVisibilityIsProposalOnly':True,'reverseQuery':'last_visible_per_track_not_occluded_final_frame','NCC':.78,'patchStd':.010,'FBpixels':2.,'ECCtranslationCap':3.,'published':False});src=out/'algorithm-source';src.mkdir();shutil.copyfile(__file__,src/Path(__file__).name)
    model=CoTrackerOnlinePredictor(checkpoint=str(tool/'scaled_online.pth'),v2=False).cuda().eval();report=[]
    for wi,names in enumerate(windows):
        dest=out/f'window-{wi}';dest.mkdir();start=time.perf_counter();torch.cuda.reset_peak_memory_stats();images={n:cv2.cvtColor(cv2.imread(str(prep/'rectified_observations'/n)),cv2.COLOR_BGR2RGB) for n in names};labels={n:dict(np.load(prep/'rectified_observations'/(n+'.npz'))) for n in names};queries,roles=distributed_queries(images[names[0]],labels[names[0]]);frames=[]
        for n in names:canvas,mapping=letterbox(images[n]);frames.append(canvas)
        video=torch.tensor(np.stack(frames)).permute(0,3,1,2)[None].float().cuda();netq=map_pixels(queries,mapping)
        with torch.inference_mode():
            forward,vis=propose(model,video,netq)
            # Reverse query each physical point at its last model-visible frame.
            # An occluded extrapolation cannot seed a measurement check.
            last=np.array([np.where(vis[:,i])[0][-1] if vis[:,i].any() else 0 for i in range(len(queries))])
            reverse,rvis=propose(model,video.flip(1),forward[last,np.arange(len(queries))].copy(),len(names)-1-last)
        native=map_pixels(forward,mapping,True);back=map_pixels(reverse[::-1],mapping,True);fb=np.linalg.norm(native-back,axis=-1);np.savez_compressed(dest/'proposals.npz',native=native,reverse=back,visible=vis,reverseVisible=rvis[::-1],queries=queries,roles=np.array(roles));gray={n:cv2.cvtColor(images[n],cv2.COLOR_RGB2GRAY) for n in names};tracks=[];counts={};rejected={}
        for qi,role in enumerate(roles):
            obs=[];source=cv2.getRectSubPix(gray[names[0]],(25,25),tuple(queries[qi])).astype(np.float32)/255
            for ti,n in enumerate(names):
                p=native[ti,qi];x,y=np.rint(p).astype(int);reason=None
                if not(vis[ti,qi] and rvis[::-1][ti,qi]) or fb[ti,qi]>2:reason='visibility_or_reverse_cycle'
                elif not(15<x<1064 and 15<y<1904) or labels[n]['unknown_or_occluded'][y,x]:reason='boundary_unknown'
                elif not (labels[n]['face_core'][y,x] if role=='face' else labels[n]['hair_visible'][y,x] if role=='hair' else labels[n]['glasses_visible'][y,x] if role=='glasses' else labels[n]['neck_cloth_visible'][y,x]):reason='component_mismatch'
                else:
                    target=cv2.getRectSubPix(gray[n],(25,25),tuple(p.astype(np.float32))).astype(np.float32)/255
                    if min(source.std(),target.std())<.010:reason='insufficient_native_texture'
                    else:
                        try:
                            corr,warp=cv2.findTransformECC(source,target,np.eye(2,3,dtype=np.float32),cv2.MOTION_TRANSLATION,(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,25,1e-4),None,3)
                            corr2,inv=cv2.findTransformECC(target,source,np.eye(2,3,dtype=np.float32),cv2.MOTION_TRANSLATION,(cv2.TERM_CRITERIA_COUNT|cv2.TERM_CRITERIA_EPS,25,1e-4),None,3)
                            if min(corr,corr2)<.78 or np.linalg.norm(warp[:,2])>3 or np.linalg.norm(warp[:,2]+inv[:,2])>1:reason='native_patch_ambiguous'
                            else:obs.append({'name':n,'uv':(p+warp[:,2]).tolist(),'sigma':float(np.clip(.5+fb[ti,qi]*.4+(1-min(corr,corr2))*2,.5,2.)),'fb':float(fb[ti,qi]),'correlation':float(min(corr,corr2)),'visibleMeasured':True})
                        except cv2.error:reason='native_patch_failure'
                if reason:rejected[reason]=rejected.get(reason,0)+1
            if len(obs)>=3 and obs[0]['name']==names[0]:tracks.append({'id':f'{names[0]}:{qi}','region':role,'observations':obs});counts[role]=counts.get(role,0)+1
        save_json(dest/'tracks.json',{'sourceHash':meta['sourceHash'],'names':names,'tracks':tracks,'mapping':mapping,'sourceReference':names[0],'measurement':'pinned CoTracker3 + reverse visible cycle + symmetric native patch ECC','networkConfidenceIsNotGeometry':True});canvas=images[names[0]].copy()
        for p,role in zip(queries,roles):cv2.circle(canvas,tuple(np.rint(p).astype(int)),5,(80,255,130) if role.startswith(('upper_','lower_')) else (255,170,80),-1)
        cv2.imwrite(str(dest/'queries.png'),cv2.cvtColor(canvas,cv2.COLOR_RGB2BGR));row={'window':wi,'names':names,'queryCount':len(queries),'acceptedTracksByRegion':counts,'rejections':rejected,'seconds':time.perf_counter()-start,'allocatedMiB':torch.cuda.max_memory_allocated()/1048576,'reservedMiB':torch.cuda.max_memory_reserved()/1048576};report.append(row);save_json(dest/'result.json',row);print(json.dumps(row),flush=True);del video;torch.cuda.empty_cache()
    del model;gc.collect();torch.cuda.empty_cache();save_json(out/'result.json',{'windows':report,'sourceHash':meta['sourceHash'],'modelUnloadedBeforeGS':True,'published':False})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepared',required=True);p.add_argument('--tool',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.prepared,a.tool,a.out)
