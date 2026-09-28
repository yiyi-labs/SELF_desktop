"""Fit one person-and-room Gaussian scene with face-weighted source pixels.

All geometry uses the same COLMAP cameras and one gsplat rasterization. A
zero-learning-rate lineage field follows face seeds through densification so
the existing viewer may still constrain edits to editable face splats.
"""
from pathlib import Path
import hashlib
import json
import math
import random
import sys

import numpy as np
import pycolmap
import torch
import torch.nn.functional as F
from PIL import Image
from scipy.spatial import cKDTree
from gsplat import export_splats
from gsplat.rendering import rasterization
from gsplat.strategy import DefaultStrategy

from reconstruction_train import load_scene, update_progress
from reconstruction_schedule import training_view_and_mode
from reconstruction_joint_visibility import render_shared


def fidelity_warnings(metrics: dict) -> list[str]:
    """Advisory image-quality checks, separate from asset integrity."""
    warnings = []
    if metrics['headPsnrDb'] < 24:
        warnings.append('head_detail_below_review_target')
    if metrics['roomPsnrDb'] < 20:
        warnings.append('room_detail_below_review_target')
    if metrics['roomAlpha'] < .95:
        warnings.append('room_coverage_below_review_target')
    if metrics['editableSplats'] < 8000:
        warnings.append('face_capacity_below_review_target')
    if metrics['roomSplats'] < 5000:
        warnings.append('room_capacity_below_review_target')
    return warnings


def check_export_policy(metrics: dict, *, best_effort: bool) -> list[str]:
    """Never invent a portrait, but keep a valid captured reconstruction viewable."""
    if (metrics['gaussians'] < 32 or metrics['editableSplats'] < 16 or
            not all(math.isfinite(float(metrics[key])) for key in
                    ('headPsnrDb', 'roomPsnrDb', 'roomAlpha'))):
        raise RuntimeError('personal_gaussian_geometry_invalid')
    warnings = fidelity_warnings(metrics)
    if warnings and not best_effort:
        raise RuntimeError('joint_scene_fidelity_gate_failed')
    return warnings


def source_edge_alignment(image: torch.Tensor, target: torch.Tensor,
                          observed: torch.Tensor) -> torch.Tensor:
    """Signed neighbouring RGB differences inside observed source pixels.

    This trains source phase and colour, not merely edge magnitude. The
    observation's silhouette boundary is excluded from the derivative loss.
    """
    horizontal = observed[:, :, 1:] * observed[:, :, :-1]
    vertical = observed[:, 1:, :] * observed[:, :-1, :]
    dx = ((image[:, :, 1:] - image[:, :, :-1]) -
          (target[:, :, 1:] - target[:, :, :-1])).abs().mean(3, keepdim=True)
    dy = ((image[:, 1:, :] - image[:, :-1, :]) -
          (target[:, 1:, :] - target[:, :-1, :])).abs().mean(3, keepdim=True)
    return .5 * ((dx * horizontal).sum() / horizontal.sum().clamp_min(1) +
                 (dy * vertical).sum() / vertical.sum().clamp_min(1))


def train(path: Path, steps:int=3000, model_path: Path | None = None,
          enforce_quality_gate: bool = True, shared_research: bool = False,
          clean_research: bool = False, detail_research: bool = False):
    if (clean_research or detail_research) and not shared_research:
        raise ValueError('research_ablation_requires_shared_visibility')
    if steps < (400 if shared_research else 3000):
        raise ValueError('joint_training_below_fidelity_floor')
    model_path=model_path or path/'sparse'/'0'
    random.seed(171);torch.manual_seed(171)
    torch.cuda.reset_peak_memory_stats()
    cameras,_,_=load_scene(path,model_path)
    cameras.sort(key=lambda x:x[0].name)
    with np.load(path / 'face_camera_poses.npz') as face_poses:
        face_views = {str(name): pose for name, pose in
                      zip(face_poses['names'], face_poses['w2c'])}
    if any(entry[0].name not in face_views for entry in cameras):
        raise RuntimeError('registered_face_camera_missing')
    model=pycolmap.Reconstruction(model_path)
    masks={}
    for name,_,_,_,_ in cameras:
        with Image.open(path/'face_masks'/(name.name+'.png')) as source:
            masks[name.name]=np.array(source.convert('L'),copy=True)
    # pycolmap materializes Python wrappers for these maps. Fetch them once;
    # looking up model.images inside every feature track can dominate startup.
    images_by_id = model.images
    observations_by_id = {image_id: image.points2D
                          for image_id, image in images_by_id.items()}
    xyz=[];rgb=[];semantic=[];transition=0
    source_ids=[];source_kinds=[]
    for point_id, point in model.points3D.items():
        if point.error>3 or point.track.length()<3:continue
        face=room=0
        for element in point.track.elements:
            im=images_by_id[element.image_id]
            if not im.has_pose or im.name not in masks:continue
            u,v=observations_by_id[element.image_id][element.point2D_idx].xy
            mask=masks[im.name]
            u=int(u);v=int(v)
            if not (0<=u<mask.shape[1] and 0<=v<mask.shape[0]):continue
            if mask[v,u]>0:face+=1
            else:room+=1
        if face+room<3:continue
        xyz.append(point.xyz);rgb.append(point.color)
        semantic.append(face>=3 and face>room*1.5)
        source_ids.append(int(point_id));source_kinds.append(0)
        if face and room:transition+=1
    with np.load(path/'environment_seeds.npz') as seeds:
        xyz.extend(seeds['xyz']);rgb.extend(seeds['rgb'])
        semantic.extend([False]*len(seeds['xyz']))
        source_ids.extend(range(len(seeds['xyz'])))
        source_kinds.extend([1]*len(seeds['xyz']))
    xyz=np.asarray(xyz,dtype=np.float32)
    rgb=np.asarray(rgb,dtype=np.float32)/255
    semantic=np.asarray(semantic,dtype=np.float32)
    print('initial',len(xyz),'face',int(semantic.sum()),'transitionTracks',transition,flush=True)
    distances,_=cKDTree(xyz).query(xyz,k=4)
    spacing=np.sqrt(np.maximum((distances[:,1:]**2).mean(1),1e-8))
    spacing=np.clip(spacing,.003,.5)
    params=torch.nn.ParameterDict({
        'means':torch.nn.Parameter(torch.from_numpy(xyz.copy())),
        'scales':torch.nn.Parameter(torch.from_numpy(np.log(spacing)[:,None].repeat(3,1).astype(np.float32))),
        'quats':torch.nn.Parameter(torch.tensor([[1.,0.,0.,0.]]).repeat(len(xyz),1)),
        'opacities':torch.nn.Parameter(torch.full((len(xyz),),-2.1972246)),
        'sh0':torch.nn.Parameter(torch.from_numpy(((rgb-.5)/.28209479177387814)[:,None,:].copy())),
        'shN':torch.nn.Parameter(torch.zeros(len(xyz),15,3)),
        # A zero-LR lineage marker follows clone/split/prune through gsplat.
        'semantic':torch.nn.Parameter(torch.from_numpy(semantic[:,None].copy())),
        # Densification copies this frozen origin index along with every new
        # point.  The exact COLMAP ID / seed index remains in a separate int64
        # lookup table; float32 stores only the small contiguous table index.
        'source_index':torch.nn.Parameter(torch.arange(len(xyz),dtype=torch.float32)[:,None]),
    }).cuda()
    centers=np.stack([np.linalg.inv(pose)[:3,3] for _,pose,_,_,_ in cameras])
    scale=float(np.linalg.norm(centers-centers.mean(0),axis=1).max())
    rates={'means':1.2e-4*scale,'scales':3e-3,'quats':1e-3,
           'opacities':4e-2,'sh0':2e-3,'shN':1e-4,'semantic':0.,
           'source_index':0.}
    opts={key:torch.optim.Adam([{'params':params[key],'lr':rate}],eps=1e-15)
          for key,rate in rates.items()}
    scheduler=torch.optim.lr_scheduler.ExponentialLR(opts['means'],gamma=.01**(1/steps))
    strategy=DefaultStrategy(refine_start_iter=250,refine_stop_iter=steps-350,
                             refine_every=100)
    strategy.check_sanity(params,opts)
    state=strategy.initialize_state(scene_scale=scale)
    validation=cameras[::max(5,len(cameras)//10)]
    held={item[0].name for item in validation}
    training=[item for item in cameras if item[0].name not in held]
    random.shuffle(training)
    cache={}
    scene_cache={}
    face_regions=json.loads((path/'face_regions.json').read_text())
    def render(entry,degree,mode):
        name,pose,K,width,height=entry
        if mode=='face' and not shared_research:
            pose=face_views[name.name]
        if name not in cache:
            with Image.open(name) as source:
                image=np.array(source.convert('RGB'),dtype=np.uint8,copy=True)
            cache[name]=image
        image=cache[name]
        K=K.copy()
        if mode=='scene':
            if name not in scene_cache:
                scene_cache[name] = (
                    np.array(Image.fromarray(image).resize((width//2,height//2),
                             Image.Resampling.BILINEAR),dtype=np.uint8,copy=True),
                    np.array(Image.fromarray(masks[name.name]).resize((width//2,height//2),
                             Image.Resampling.NEAREST),dtype=np.uint8,copy=True))
            image,mask=scene_cache[name]
            K[:2,:]*=.5
            width//=2;height//=2
        elif mode=='face':
            x,y,w,h=face_regions[name.name]
            margin_x=round(w*.35);margin_y=round(h*.35)
            x0=max(0,x-margin_x);y0=max(0,y-margin_y)
            x1=min(width,x+w+margin_x);y1=min(height,y+h+margin_y)
            image=image[y0:y1,x0:x1]
            mask=masks[name.name][y0:y1,x0:x1]
            K[0,2]-=x0;K[1,2]-=y0
            width=x1-x0;height=y1-y0
        else:
            mask=masks[name.name]
        target=torch.from_numpy(np.ascontiguousarray(image)).cuda().float()[None]/255
        face=torch.from_numpy(np.ascontiguousarray(mask)).cuda().float()[None,:,:,None]/255
        colors=torch.cat([params['sh0'],params['shN']],1)
        if shared_research:
            # Every group participates in sorting and transmittance.  The
            # head alone follows its measured relative transform; clothing
            # remains in the uncertain static group until body motion is
            # independently constrained.  This branch is research-only.
            shared=render_shared({
                'means':params['means'],'quats':params['quats'],
                'scales':torch.exp(params['scales']),
                'opacity':torch.sigmoid(params['opacities']),
                'sh':colors,
                'person_mask':params['semantic'].flatten()>.5},
                pose,face_views[name.name],K,width,height,degree=degree)
            out=shared['rgb'][None];alpha=shared['alpha'][None,:,:,None]
            info=shared['projection']
        else:
            # Historical production baseline alternates hidden groups. It
            # remains unchanged until the joint candidate passes visual E3.
            visible=params['semantic'].flatten()>.5
            visible=visible if mode=='face' else ~visible
            opacity=torch.where(visible,torch.sigmoid(params['opacities']),
                                torch.zeros_like(params['opacities']))
            out,alpha,info=rasterization(params['means'],params['quats'],
                torch.exp(params['scales']),opacity,colors,
                torch.from_numpy(pose).cuda()[None],torch.from_numpy(K).cuda()[None],
                width,height,packed=True,sh_degree=degree,near_plane=.01)
        return out,target,face,alpha,info,shared if shared_research else None
    samples=[]
    for step in range(steps):
        view_index,mode=training_view_and_mode(step,len(training))
        if mode=='full':mode='scene'
        entry=training[view_index]
        degree=min(step//900,3)
        out,target,face,alpha,info,shared=render(entry,degree,mode)
        strategy.step_pre_backward(params,opts,state,step,info)
        error=(out-target).abs().mean(3,keepdim=True)
        face_error=(error*face).sum()/face.sum().clamp_min(1)
        room=(1-face)
        room_error=(error*room).sum()/room.sum().clamp_min(1)
        if shared_research and mode=='face':
            loss=face_error+.12*room_error+.025*((1-alpha)*face).mean()
        elif shared_research:
            loss=room_error+.45*face_error+.02*((1-alpha)*room).mean()
        elif mode=='face':
            loss=face_error+.025*((1-alpha)*face).mean()+.02*(alpha*room).mean()
        else:
            loss=room_error+.02*((1-alpha)*room).mean()
        if clean_research:
            # Only the well-inside 2D head observation supplies a weak
            # foreground constraint.  This is neither a measured 3D surface
            # nor permission to delete an environment splat.  RGB, coverage,
            # and visible room losses remain in the same full-scene forward.
            core = 1 - F.max_pool2d((1-face).permute(0,3,1,2),
                                    kernel_size=25 if mode=='face' else 13,
                                    stride=1,
                                    padding=12 if mode=='face' else 6)[0,0]
            loss = loss + .04 * (shared['q_environment'] * core).sum() / core.sum().clamp_min(1)
        if detail_research and mode == 'face':
            # Source-space native crop; no sharpening of an output image and
            # no gradient target across the cut-out silhouette.
            loss = loss + .1 * source_edge_alignment(out, target, face)
        loss=loss+(params['semantic'].sum()+params['source_index'].sum())*0
        if not torch.isfinite(loss):raise RuntimeError('joint_loss_nonfinite')
        loss.backward()
        for opt in opts.values():opt.step();opt.zero_grad(set_to_none=True)
        scheduler.step()
        strategy.step_post_backward(params,opts,state,step,info,packed=True)
        if step%100==0:
            samples.append((step,round(float(loss.detach().cpu()),5),len(params['means'])))
            print('step',*samples[-1],flush=True)
            update_progress(path,step,steps,base=62,span=22)
        del out,target,face,room,alpha,info,error,face_error,room_error,loss,shared
        if len(params['means'])>500000 or torch.cuda.max_memory_allocated()>7.4*1024**3:
            raise RuntimeError('joint_capacity_exceeded')
    face_errors=[];room_errors=[];room_alphas=[]
    with torch.no_grad():
        for entry in validation:
            out,target,face,alpha,_,_=render(entry,3,'face')
            e=((out-target)**2).mean(3,keepdim=True)
            face_errors.append(float((e*face).sum()/face.sum().clamp_min(1)))
            out,target,face,alpha,_,_=render(entry,3,'scene')
            e=((out-target)**2).mean(3,keepdim=True)
            room=1-face
            room_errors.append(float((e*room).sum()/room.sum().clamp_min(1)))
            room_alphas.append(float((alpha*room).sum()/room.sum().clamp_min(1)))
    face_ids=torch.nonzero(params['semantic'].detach().flatten()>.5,as_tuple=False).flatten()
    room_ids=torch.nonzero(params['semantic'].detach().flatten()<=.5,as_tuple=False).flatten()
    order=torch.cat([face_ids,room_ids])
    metrics={'steps':steps,'gaussians':len(order),'editableSplats':len(face_ids),
             'roomSplats':len(room_ids),'headPsnrDb':round(-10*math.log10(np.mean(face_errors)),2),
             'roomPsnrDb':round(-10*math.log10(np.mean(room_errors)),2),
             'roomAlpha':round(float(np.mean(room_alphas)),4),
             'peakCudaMiB':round(torch.cuda.max_memory_allocated()/1024**2),
             'lossSamples':samples}
    metrics['sharedFullSceneRasterizationResearch'] = shared_research
    metrics['observedFaceInteriorCleanResearch'] = clean_research
    metrics['sourceEdgeDetailResearch'] = detail_research
    warnings = fidelity_warnings(metrics)
    metrics['fidelityWarnings'] = warnings
    metrics['fidelityGatePassed'] = not warnings
    (path/'training_metrics.json').write_text(json.dumps(metrics,indent=2))
    print('metrics',json.dumps({k:v for k,v in metrics.items() if k!='lossSamples'}),flush=True)
    check_export_policy(metrics, best_effort=not enforce_quality_gate)
    dest=path/'portrait.gaussian.ply'
    export_splats(**{key:params[key].detach()[order] for key in
                    ('means','scales','quats','opacities','sh0','shN')},
                  format='ply',save_to=str(dest))
    final_source = params['source_index'].detach()[order,0].cpu().numpy()
    source_index = np.rint(final_source).astype(np.int64)
    if (not np.allclose(final_source, source_index, atol=1e-4) or
            np.any(source_index < 0) or np.any(source_index >= len(source_ids))):
        raise RuntimeError('densification_source_lineage_invalid')
    ply_hash = hashlib.sha256(dest.read_bytes()).hexdigest()
    np.savez_compressed(path/'portrait.provenance.npz',
        plySha256=np.asarray(ply_hash),
        pointIndex=np.arange(len(order),dtype=np.int32),
        initialSourceKind=np.asarray(source_kinds,dtype=np.uint8)[source_index],
        initialSourceId=np.asarray(source_ids,dtype=np.int64)[source_index],
        initialSourceIndex=source_index.astype(np.int32),
        personPartition=(params['semantic'].detach()[order,0].cpu().numpy()>.5).astype(np.uint8))
    view=json.loads((path/'portrait.view.json').read_text())
    view['editableSplats']=len(face_ids);view['recordedEnvironmentSplats']=len(room_ids)
    (path/'portrait.view.json').write_text(json.dumps(view,ensure_ascii=False,separators=(',',':')))
    print('output',dest.stat().st_size,flush=True)

if __name__=='__main__':
    if len(sys.argv) not in (2,3,4) or any(arg not in
        ('--best-effort','--strict-fidelity','--shared-research') for arg in sys.argv[2:]):
        raise SystemExit('Usage: reconstruction_train_joint.py JOB_DIR [--best-effort|--strict-fidelity] [--shared-research]')
    # Older workers invoke this CLI with only JOB_DIR.  They must also return
    # a structurally valid portrait when only the advisory image score misses.
    train(Path(sys.argv[1]),enforce_quality_gate='--strict-fidelity' in sys.argv[2:],
          shared_research='--shared-research' in sys.argv[2:])
