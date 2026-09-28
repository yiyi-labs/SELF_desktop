"""New v3 per-view evidence. Reuses existing E1/PLY numerical probes."""
import json
from pathlib import Path
import cv2
import numpy as np
import torch
from reconstruction_components_v3 import sha,save_json
from reconstruction_portrait_pipeline import make_frame,metrics,draw,masked_mean
from reconstruction_portrait_local_v3 import draw_head
from reconstruction_compose_v3 import draw_composed


def audit_observations(data,prepared,out):
    manifest_path=data['source']/'frame_manifest.audit.json'
    manifest=json.loads(manifest_path.read_text())
    if manifest['captureSha256']!=data['sourceHash']:raise ValueError('manifest_video_mismatch')
    rows={r['name']:r for r in manifest['frames']}
    if len(rows)!=len(manifest['frames']):raise ValueError('duplicate_observation_name')
    import pycolmap
    reconstruction=pycolmap.Reconstruction(Path(data['staticMap']))
    image_map={im.name:im for im in reconstruction.images.values()}
    report=[]
    for name,local in data['local'].items():
        if name not in rows:raise ValueError('local_frame_not_in_source_manifest:'+name)
        r=rows[name];rgb=data['rgb'][name];labels=data['labels'][name]
        if not np.isfinite(local['F']).all() or local['F'].shape!=(4,4):raise ValueError('bad_F')
        if any(x.shape!=rgb.shape[:2] for x in labels.values()):raise ValueError('mask_shape_mismatch')
        if sha(data['source']/'frames'/name)!=r['pngSha256']:raise ValueError('source_frame_changed')
        world=data['worlds'].get(name)
        actual=None
        if world is not None:
            if name not in image_map:raise ValueError('world_name_missing_from_real_map')
            im=image_map[name];matrix=np.eye(4);matrix[:3]=im.cam_from_world().matrix()
            delta=float(np.max(np.abs(matrix-world)))
            if delta>1e-5:raise ValueError('prepared_world_camera_differs_from_map:'+name)
            camera=reconstruction.cameras[im.camera_id]
            actual={'imageId':im.image_id,'cameraId':im.camera_id,'model':camera.model.name,'params':camera.params.tolist(),'storedCMaxDifference':delta}
        candidates=[{'candidate':k,'imageId':v.get('imageId'),'cameraId':v.get('cameraId')} for k,v in r.get('candidates',{}).items() if v.get('registered')]
        report.append({'name':name,'sourceFrame':r['sourceIndexZeroBased'],'pts':r['timestampSeconds'],
            'sourcePngSha256':r['pngSha256'],'rectifiedPngSha256':sha(prepared/'rectified_observations'/name),
            'maskSha256':sha(prepared/'rectified_observations'/(name+'.npz')),'role':local['role'],
            'localF':local['F'].tolist(),'worldC':world.tolist() if world is not None else None,
            'worldStatus':'research_estimate_not_E1_accepted' if world is not None else 'missing_not_synthesized',
            'actualStaticMapImage':actual,'candidateIDsNotFrameIndices':candidates})
    result={'sourceSha256':data['sourceHash'],'sourceManifestSha256':sha(manifest_path),'rows':report,
        'KRectified':data['K'].tolist(),'intrinsicsStatus':manifest['intrinsicsStatus'],
        'transformContract':'prepared undistorted upright pixels; crop subtracts principal point; half resize scales K',
        'localCount':len(report),'worldEstimateCount':len(data['worlds']),'verifiedWorldCount':0,
        'trainCount':sum(x['role']=='train' for x in report),'developmentCount':sum(x['role']=='development' for x in report)}
    save_json(out/'A-observations.json',result);return result


def region_details(output,frame):
    result=metrics(output,frame)
    result['faceCoreRgbL1']=float(masked_mean((output['rgb']-frame['rgb']).abs().mean(-1),frame['masks']['face_core']))
    rgb=output['rgb'];source=frame['rgb'];m=frame['masks']
    for label,maskkey in [('face','face_core'),('hair','hair_visible'),('glasses','glasses_visible'),('neckCloth','neck_cloth_visible'),('room','room_visible')]:
        mask=m[maskkey];dx=mask[:,1:]&mask[:,:-1];dy=mask[1:]&mask[:-1]
        gx=(rgb[:,1:]-rgb[:,:-1])-(source[:,1:]-source[:,:-1]);gy=(rgb[1:]-rgb[:-1])-(source[1:]-source[:-1])
        result[label]['edgeL1']=float((masked_mean(gx.abs().mean(-1),dx)+masked_mean(gy.abs().mean(-1),dy))/2)
    result['hair']['visibleCoverageQ05']=float(masked_mean((output['q'][...,2]>.5).float(),m['hair_visible']))
    result['hair']['reliableEmptyContribution']=float(masked_mean(output['q'][...,2],m['room_visible'] & ~m['unknown_or_occluded']))
    result['glasses']['labelStatus']='edge_candidate_proxy_not_manual_truth'
    return result


def png(path,tiles,labels):
    panels=[]
    for tile,label in zip(tiles,labels):
        rgb=(tile*255).round().clip(0,255).astype(np.uint8)
        band=np.zeros((30,rgb.shape[1],3),np.uint8)
        cv2.putText(band,label,(8,21),cv2.FONT_HERSHEY_SIMPLEX,.48,(225,225,225),1,cv2.LINE_AA)
        panels.append(np.concatenate((band,rgb),0))
    image=np.concatenate(panels,1)
    cv2.imwrite(str(path),cv2.cvtColor(image,cv2.COLOR_RGB2BGR))


@torch.no_grad()
def evaluate(face,attachments,body,room,data,out,*,include_legacy=True):
    out.mkdir(parents=True,exist_ok=False)
    names=[n for n,r in data['local'].items() if r['role']=='development']
    report={}
    for name in names:
        frame=make_frame(data,name)
        views={}
        if include_legacy:
            h,w=frame['rgb'].shape[:2]
            views['retained_old_head']=draw(face.local_state(frame['mesh']),frame['F'],frame['K'],w,h)
        views['v3_local']=draw_head(face,attachments,frame)
        if frame['C'] is not None:views['v3_composed_diagnostic']=draw_composed(face,attachments,body,room,data,frame)
        row={key:region_details(value,frame) for key,value in views.items()}
        row['crop']=frame['rectangle'];row['K']=frame['K'].cpu().tolist();row['F']=frame['F'].cpu().tolist()
        source=frame['rgb'].cpu().numpy();tiles=[source]+[x['rgb'].cpu().numpy() for x in views.values()]
        png(out/(name+'-head-overview.png'),tiles,['source']+list(views))
        # Fixed landmark-defined features, identical pixels in all comparisons.
        from reconstruction_shared_v2 import boxes
        for label,b in boxes(data,name).items():
            if b is None:continue
            x0,y0,x1,y1=b;ox,oy,_,_=frame['rectangle']
            x0,x1=max(0,x0-ox),min(source.shape[1],x1-ox);y0,y1=max(0,y0-oy),min(source.shape[0],y1-oy)
            if x1>x0 and y1>y0:png(out/(name+'-'+label+'.png'),[x[y0:y1,x0:x1] for x in tiles],['source']+list(views))
        if frame['C'] is not None:
            full=make_frame(data,name,crop=False,half=True);h,w=full['rgb'].shape[:2]
            combined=draw_composed(face,attachments,body,room,data,full)
            static=draw(room.state(),full['C'],full['K'],w,h,unit_scale=data['scale'])
            row['full_scene']=region_details(combined,full);row['room_only']=region_details(static,full)
            rgb=combined['rgb'].cpu().numpy();q=combined['q'].cpu().numpy();alpha=combined['alpha'].cpu().numpy()
            # Contribution images are diagnostics, never replacement backgrounds.
            png(out/(name+'-scene.png'),[full['rgb'].cpu().numpy(),rgb,static['rgb'].cpu().numpy(),
                np.repeat(alpha[...,None],3,-1),np.repeat(q[...,0,None],3,-1),np.repeat(q[...,1:].sum(-1)[...,None],3,-1)],
                ['source','full one-pass','room diagnostic','alpha','q room','q person'])
        report[name]=row
    save_json(out/'metrics.json',report);return report


def compare(initial,final):
    result={}
    for name,before in initial.items():
        after=final[name];row={}
        for mode in ('v3_local','full_scene','room_only'):
            if mode not in before or mode not in after:continue
            row[mode]={region:{key:[before[mode][region][key],after[mode][region][key]] for key in ('fixedRgbL1','hole','edgeL1')}
                       for region in ('face','hair','glasses','room','neckCloth')}
        result[name]=row
    return result
