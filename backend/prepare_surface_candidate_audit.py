"""Explicit prepare-only Stage 2A research entry; no publisher or training path."""
from __future__ import annotations
import argparse
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import shutil
import subprocess
import time
import traceback

import numpy as np
import pycolmap
import torch
from audit_reconstruction_stage_coverage import (Inputs, freeze_contract, load_data,
    zero_training, sha, json_write, support_surface, effective_footprints,
    termination_check, analyze, png, labeled_tile, cpu, state_hash, state_stats,
    read_asset, subset, FIELDS)
from reconstruction_scene import collect_supported_surface_pool, allocate_surface_pool, _surface_token
from reconstruction_shared_v2 import initialize
from reconstruction_portrait_model import GaussianState, joined_state
from reconstruction_portrait_pipeline import draw, make_frame


def git_info(root):
    pointer=(root/'.git').read_text().removeprefix('gitdir: ').strip()
    if len(pointer)>1 and pointer[1]==':':pointer='/mnt/'+pointer[0].lower()+pointer[2:].replace('\\','/')
    base=['git','--git-dir='+pointer,'--work-tree='+str(root)]
    head=subprocess.check_output(base+['rev-parse','HEAD'],text=True).strip()
    return head,subprocess.check_output(base+['diff','HEAD','--','backend/reconstruction_scene.py'],text=True)


def initial_room(data, prepared, output, inputs):
    output.mkdir();shutil.copyfile(inputs.touch(prepared/'cloth_supported_seeds.npz'),output/'cloth_supported_seeds.npz')
    params,_=initialize(data,output,'cuda')
    for p in params.values():p.requires_grad_(False)
    mask=params['part'][:,0].long()==0
    return GaussianState(params['means'][mask].detach(),params['quats'][mask].detach(),
        params['scales'][mask].detach().exp(),params['opacities'][mask].detach().sigmoid(),
        params['sh'][mask].detach(),params['part'][mask,0].detach().long())


def pool_support_input(anchors, pool):
    first={}
    for point in pool['points']:first.setdefault(point['surfaceId'],point)
    points=list(first.values())
    # An in-memory adapter for S only; these representatives are NEVER initialized
    # as a third Gaussian asset. All legal sample locations are saved separately.
    return {'xyz':np.concatenate([anchors['xyz'],np.array([p['xyz'] for p in points],np.float32).reshape(-1,3)]),
        'source_id':np.concatenate([anchors['source_id'],np.arange(len(points),dtype=np.int64)]),
        'source_kind':np.concatenate([anchors['source_kind'],np.ones(len(points),np.uint8)]),
        'triangle_sources':np.concatenate([anchors['triangle_sources'],np.array([p['triangleSources'] for p in points],np.int64).reshape(-1,3)])}


def legal_pixel_support(xyz, C, K, width, height, near):
    counts=np.zeros((height,width),np.int32)
    camera=xyz@C[:3,:3].T+C[:3,3];q=camera@K.T
    uv=np.floor(q[:,:2]/np.maximum(q[:,2:],1e-8)).astype(np.int64)
    u,v=uv.T;good=(camera[:,2]>near)&(u>=0)&(v>=0)&(u<width)&(v<height)
    np.add.at(counts,(v[good],u[good]),1)
    return counts


def render_comparison(data, old, pool_seed, new, pool_xyz, states, person, output, names):
    results=[];all_hashes={k:state_hash(v) for k,v in states.items()}
    for name in names:
        folder=output/Path(name).stem;folder.mkdir()
        frame=make_frame(data,name,crop=False,half=True,device='cuda' if states else 'cpu');target=cpu(frame['rgb']);h,w=target.shape[:2]
        K,C=cpu(frame['K']),cpu(frame['C']);masks={k:cpu(v) for k,v in frame['masks'].items()}
        mask=masks['room_visible'];known_person=masks['face_core']|masks['face_boundary']|masks['hair_visible']|masks['glasses_visible']|masks['neck_cloth_visible']
        layers={};metrics={}
        for key,seed in [('old',old),('pool',pool_seed),('selected',new)]:
            s,sm=support_surface(seed,C,K,w,h,.01*data['scale'])
            layers['S_'+key+'_raw']=s['S_raw'];layers['S_'+key]=s['S_raw']&mask&~masks['unknown_or_occluded']
            layers['depth_'+key]=s['depth'];layers['triangle_'+key]=s['triangle']
            sm['visibleFraction']=float(layers['S_'+key][mask].mean())
            sm['rawPersonOverlapPixels']=int((s['S_raw']&known_person).sum())
            sm['rawUnknownOverlapPixels']=int((s['S_raw']&masks['unknown_or_occluded']).sum())
            metrics[key]=sm
        layers['L_pool_count']=legal_pixel_support(pool_xyz,C,K,w,h,.01*data['scale'])
        layers['L_selected_count']=legal_pixel_support(new['xyz'][new['source_kind']==1],C,K,w,h,.01*data['scale'])
        S0,SP,SB=[layers['S_'+n] for n in ['old','pool','selected']]
        masks_more={'poolNew':SP&~S0,'poolLost':S0&~SP,'selectedNew':SB&~S0,
                    'selectedLost':S0&~SB,'budgetLost':SP&~SB,'selectedOutsidePool':SB&~SP}
        changes={k:{'pixels':int(v.sum()),'maskFraction':float(v[mask].mean())} for k,v in masks_more.items()}
        png(folder/'source.png',target)
        overlay=target*.4;overlay[masks_more['selectedNew']]+=np.array([.03,.5,.25]);overlay[masks_more['selectedLost']]+=np.array([.5,.1,.02])
        png(folder/'support-change.png',overlay)
        np.savez_compressed(folder/'support.npz',rgb=target,C=C,K=K,F=cpu(frame['F']),**masks,**layers,**masks_more)
        row={'imageName':name,'width':w,'height':h,'reference':data.get('reference'),'surfaceHypotheses':metrics,
             'supportChanges':changes,'roomMaskPixels':int(mask.sum()),'states':{},
             'legalSamples':{'poolVisiblePixelFraction':float(((layers['L_pool_count']>0)&mask)[mask].mean()),
                 'selectedVisiblePixelFraction':float(((layers['L_selected_count']>0)&mask)[mask].mean()),
                 'meaning':'projected legal sample centre pixels, not a filled continuous surface'},
             'overlapMeaning':'room behind a person can overlap in 2D; these are risk locations, not proof of wrong depth'}
        if not states:
            panel=np.concatenate([labeled_tile(target,'Source'),labeled_tile(S0,'S old upper bound'),
                labeled_tile(SP,'S pool upper bound'),labeled_tile(SB,'S selected upper bound'),
                labeled_tile(overlay,'Green=new Orange=lost'),
                labeled_tile((layers['L_pool_count']>0)&mask,'Legal point pixels')],1)
            png(folder/'support-comparison.png',panel)
            row['gaussianReplay']='pending CUDA; S/L only, not a substitute renderer'
            json_write(folder/'metrics.json',row);results.append(row)
            print('SUPPORT',name,{k:metrics[k]['visibleFraction'] for k in metrics},flush=True)
            continue
        images={}
        for key,state in states.items():
            before=state_hash(state)
            r=draw(state,frame['C'],frame['K'],w,h,unit_scale=data['scale'],antialiased=False)
            foot=effective_footprints(r['info'],w,h)
            termination=termination_check(r['info'],r['alpha'],foot['all_eligible_alpha'])
            surf=S0 if key=='A' else SB
            stats,regions,error=analyze(surf,foot['U'],r['alpha'],r['q'][:,:,0],r['rgb'],frame['rgb'],mask)
            full=draw(joined_state(person,state),frame['C'],frame['K'],w,h,unit_scale=data['scale'],antialiased=False)
            stats['fixedPersonComposite']=analyze(surf,foot['U'],full['alpha'],full['q'][:,:,0],full['rgb'],frame['rgb'],mask)[0]
            stats['exclusiveTerminationCheck']=termination
            stats['surfaceWithoutFootprintPixels']=int((surf&~cpu(foot['U'])).sum())
            stats['parametersUnchanged']=state_hash(state)==before
            info=r['info']
            np.savez_compressed(folder/(key+'.npz'),rgb=cpu(r['rgb']),A=cpu(r['alpha']),q_room=cpu(r['q'][:,:,0]),
                U=cpu(foot['U']),overlap=cpu(foot['overlap']),error=error,full_rgb=cpu(full['rgb']),full_A=cpu(full['alpha']),
                full_q_room=cpu(full['q'][:,:,0]),means2d=cpu(info['means2d']),conics=cpu(info['conics']),radii=cpu(info['radii']))
            images[key]={'rgb':cpu(r['rgb']),'U':cpu(foot['U']),'A':cpu(r['alpha'])}
            png(folder/(key+'-composite.png'),full['rgb']);row['states'][key]=stats
        panel1=np.concatenate([labeled_tile(target,'Source'),labeled_tile(S0,'S old upper bound'),labeled_tile(SP,'S pool upper bound'),
            labeled_tile(SB,'S selected upper bound'),labeled_tile(images['A']['U'],'A U'),labeled_tile(images['B']['U'],'B U')],1)
        panel2=np.concatenate([labeled_tile(images['A']['rgb'],'A initial RGB'),labeled_tile(images['B']['rgb'],'B initial RGB'),
            labeled_tile(images['A']['A'],'A alpha'),labeled_tile(images['B']['A'],'B alpha'),
            labeled_tile(overlay,'Green=new Orange=lost'),labeled_tile((layers['L_pool_count']>0)&mask,'Legal point pixels')],1)
        png(folder/'comparison.png',np.concatenate([panel1,panel2],0))
        json_write(folder/'metrics.json',row);results.append(row)
        print('REPLAY',name,{k:metrics[k]['visibleFraction'] for k in metrics},flush=True)
    if any(state_hash(v)!=all_hashes[k] for k,v in states.items()):raise ValueError('state_mutation')
    return results


def run(args):
    root=Path(__file__).resolve().parent;out=args.output
    if out.exists():raise ValueError('never_overwrite_prepare_run')
    out.mkdir(parents=True);started=time.perf_counter();inputs=Inputs()
    head,diff=git_info(root.parent)
    budget={'candidateWallSeconds':1200,'candidatePeakRssBytes':10*1024**3,'allocationWallSeconds':600,
        'mapPointCountExpected':3532,'trainingViewsExpected':59,'nativeDimensions':[1080,1920],
        'estimatedRgbAndBlurBytes':59*1080*1920*3*4*2,'maxTotalPoints':22020,
        'coarseGridPixels':32,'fineGridPixels':4,'gaussianMode':'classic','zeroTraining':True,
        'noDevelopmentDataForSelection':True,'oneEnumerationOnePreparedOneAB':True}
    json_write(out/'execution-budget.json',budget)
    (out/'code-before-run.diff').write_text(diff)
    snapshot=out/'algorithm-source';snapshot.mkdir()
    source_files={}
    for n in ['reconstruction_scene.py','prepare_surface_candidate_audit.py','test_surface_candidate_budget.py',
              'audit_reconstruction_stage_coverage.py','reconstruction_shared_v2.py']:
        source_files[n]=sha(inputs.touch(root/n));shutil.copyfile(root/n,snapshot/n)
    with zero_training():
        freeze_contract(root,args.run,args.prepared,inputs)
        data=load_data(args.prepared,inputs);old=data['room']
        stage0=inputs.js(args.stage0/'summary.json')
        if sha(args.prepared/'static_surface_seeds.npz')!='22296697a46475e5099a5fe2430852422876150cfc9aaccc3e0b6f124b11ad35':
            raise ValueError('frozen_prepared_hash_mismatch')
        if sha(args.prepared/'local_geometry.npz')!='fae308b496a50dad7c67c58ee2767d20ea9c9957f2c8dcbd811bb337d44f07e0':
            raise ValueError('frozen_geometry_hash_mismatch')
        original_backend=args.prepared.parent.parent;map_path=original_backend/data['staticMap']
        map_files={p.name:sha(inputs.touch(p)) for p in sorted(map_path.glob('*.bin'))}
        namespace=hashlib.sha256(json.dumps({'map':map_files,'prepared':sha(args.prepared/'preparation.json')},sort_keys=True).encode()).hexdigest()
        model=pycolmap.Reconstruction(map_path);by_name={im.name:im for im in model.images.values() if im.has_pose}
        if len(data['train'])!=59 or set(data['train'])&set(data['development']):raise ValueError('frozen_frame_split_mismatch')
        views={n:(data['worlds'][n],data['K']) for n in data['train']}
        for n,(C,K) in views.items():
            if not np.allclose(C[:3],by_name[n].cam_from_world().matrix(),atol=1e-12,rtol=0):raise ValueError('map_camera_mismatch:'+n)
        anchors={k:v[old['source_kind']==0].copy() for k,v in old.items()}
        if len(anchors['xyz'])!=2000:raise ValueError('historical_anchor_count_changed')
        rgb={};masks={};unknown={}
        for n in data['train']:
            rgb[n]=data['rgb'][n];labels=data['labels'][n]
            masks[n]=labels['room_visible'];unknown[n]=labels['unknown_or_occluded']
        config={'head':head,'sourceSha256':data['sourceHash'],'sourceFiles':source_files,'mapFiles':map_files,
            'namespace':namespace,'preparedParent':str(args.prepared),'oldPreparedSha256':sha(args.prepared/'static_surface_seeds.npz'),
            'oldGeometrySha256':sha(args.prepared/'local_geometry.npz'),'trainingViews':sorted(views),
            'developmentFramesForEvaluationOnly':data['development'],'budget':budget,
            'pycolmap':pycolmap.__version__,'gsplat':importlib.metadata.version('gsplat'),
            'sourceRectifiedPixels':'legacy remap returns uint8/255; persisted round-trip PNG preserves exact values',
            'status':'prepare_only_research_not_release'}
        json_write(out/'config.json',config)
        pool=collect_supported_surface_pool(model,views,masks,rgb,anchors,out/'candidate-pool',namespace=namespace,
            wall_seconds=budget['candidateWallSeconds'],rss_limit_bytes=budget['candidatePeakRssBytes'],unknown_masks=unknown,
            progress=lambda stage,name,stats:print(stage,name,json.dumps(stats),flush=True))
        old_surfaces={_surface_token(namespace,1,*sorted(t.tolist())) for t in old['triangle_sources'][old['source_kind']==1]}
        new,allocation=allocate_surface_pool(pool,anchors,views,masks,namespace=namespace,max_points=22020,retained_surfaces=old_surfaces,
            coarse_pixels=32,fine_pixels=4,wall_seconds=600)
        # Assert no development image/mask was accessed while selecting candidates.
        dev_read=[p for p in inputs.records if any('/rectified_observations/'+n in p for n in data['development'])]
        if dev_read:raise ValueError('development_pixels_read_before_prepared_freeze')
        new_dir=out/'prepared';new_dir.mkdir();np.savez_compressed(new_dir/'static_surface_seeds.npz',**new)
        json_write(new_dir/'allocation.json',allocation)
        json_write(new_dir/'preparation.json',{'schema':'self.surface.prepare-only.1','namespace':namespace,
            'parent':str(args.prepared),'sourceSha256':data['sourceHash'],'surfaceAssetSha256':sha(new_dir/'static_surface_seeds.npz'),
            'candidatePoolSummarySha256':sha(out/'candidate-pool/summary.json'),'readOnlyObservationParent':str(args.prepared/'rectified_observations'),
            'pointEvidenceFile':'../candidate-pool/sample-evidence.jsonl','evidenceBitOrder':pool['report']['trainingViews'],
            'evidenceScopes':{'0':'anchor original SfM track observations; negative tests not newly inferred',
                              '1':'all frozen training projections under original sample rules'},
            'noTrainingNoPLYNoPublisher':True,'developmentPixelsAccessBeforeFreeze':dev_read})
        frozen_new_hash=sha(new_dir/'static_surface_seeds.npz')
        del rgb,masks,unknown,model;gc.collect()
        # Freeze before any development pixels are read. Resume never allocates again.
        inputs.verify()
        files={str(p.relative_to(out)):{'bytes':p.stat().st_size,'sha256':sha(p)}
               for p in sorted(out.rglob('*')) if p.is_file()}
        frozen={'status':'prepared_replay_pending','inputs':inputs.records,'outputs':files,
            'headBeforeRun':head,'sourceFiles':source_files,'preparedSha256':frozen_new_hash,
            'candidatePool':pool['report'],'allocation':allocation,'sourceSha256':data['sourceHash'],
            'seconds':time.perf_counter()-started,
            'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'newTrainingSteps':0,'qualityPassed':False,'published':False}
        json_write(out/'preparation-summary.json',frozen)
        print('PREPARED_FROZEN',out,frozen['seconds'],flush=True)
    if torch.cuda.is_available():
        replay(args)
    else:
        with zero_training():
            support_out=out/'cpu-support';support_out.mkdir()
            support_seed=pool_support_input(anchors,pool)
            pool_xyz=np.array([p['xyz'] for p in pool['points']],np.float32).reshape(-1,3)
            rows=render_comparison(data,old,support_seed,new,pool_xyz,{},None,support_out,data['development'])
            inputs.verify()
            json_write(support_out/'summary.json',{'status':'S_L_only_Gaussian_replay_pending',
                'frames':rows,'inputs':inputs.records,'preparedSha256':frozen_new_hash,'newTrainingSteps':0})
        print('CUDA_REPLAY_PENDING; use --resume-replay with the same frozen output',flush=True)


def verify_frozen_prepare(output, inputs):
    frozen=inputs.js(output/'preparation-summary.json')
    for rel,record in frozen['outputs'].items():
        if sha(inputs.touch(output/rel))!=record['sha256']:raise ValueError('frozen_output_changed:'+rel)
    for path,record in frozen['inputs'].items():
        current=Path(path)
        if current.resolve()==Path(__file__).resolve():
            # Only this reporting/resume adapter may change after the preparation
            # freeze. Verify its executed snapshot and separately record current
            # source. Collector, initializer and all observations remain exact.
            executed=output/'algorithm-source'/current.name
            if sha(inputs.touch(executed))!=record['sha256']:raise ValueError('executed_adapter_snapshot_changed')
            inputs.touch(current)
        elif sha(inputs.touch(current))!=record['sha256']:raise ValueError('frozen_input_changed:'+path)
    return frozen


def resume_support(args):
    inputs=Inputs()
    with zero_training():
        frozen=verify_frozen_prepare(args.output,inputs)
        freeze_contract(Path(__file__).resolve().parent,args.run,args.prepared,inputs)
        out=args.output/'cpu-support-resumed'
        if out.exists():raise ValueError('never_overwrite_support_replay')
        out.mkdir();shutil.copyfile(__file__,out/'replay-adapter.py')
        data=load_data(args.prepared,inputs);old=data['room']
        new=inputs.npz(args.output/'prepared/static_surface_seeds.npz')
        anchors={k:v[old['source_kind']==0].copy() for k,v in old.items()}
        points=[json.loads(line) for line in (args.output/'candidate-pool/legal-samples.jsonl').read_text().splitlines()]
        pool={'points':points};xyz=np.array([p['xyz'] for p in points],np.float32).reshape(-1,3)
        rows=render_comparison(data,old,pool_support_input(anchors,pool),new,xyz,{},None,out,data['development'])
        inputs.verify()
        json_write(out/'summary.json',{'status':'S_L_only_Gaussian_replay_pending','frames':rows,
            'inputs':inputs.records,'preparedSha256':frozen['preparedSha256'],'newTrainingSteps':0,
            'referenceMeaning':'world-static room; no person initialized or composited in CPU support projection'})


def replay(args):
    root=Path(__file__).resolve().parent;inputs=Inputs();started=time.perf_counter()
    with zero_training():
        frozen=verify_frozen_prepare(args.output,inputs)
        freeze_contract(root,args.run,args.prepared,inputs)
        if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; frozen preparation preserved')
        torch.zeros(1,device='cuda')
        out=args.output/'gaussian-replay'
        if out.exists():raise ValueError('never_overwrite_replay')
        out.mkdir();shutil.copyfile(__file__,out/'replay-adapter.py')
        data=load_data(args.prepared,inputs);old=data['room']
        new=inputs.npz(args.output/'prepared/static_surface_seeds.npz')
        anchors={k:v[old['source_kind']==0].copy() for k,v in old.items()}
        points=[json.loads(line) for line in (args.output/'candidate-pool/legal-samples.jsonl').read_text().splitlines()]
        pool={'points':points};stage0=inputs.js(args.stage0/'summary.json')
        states={'A':initial_room(data,args.prepared,out/'A-initial',inputs)}
        if state_hash(states['A'])!=stage0['states']['v3_initial']['hash']:raise ValueError('old_untrained_baseline_drift')
        states['B']=initial_room({**data,'room':new},args.prepared,out/'B-initial',inputs)
        for k,state in states.items():np.savez_compressed(out/(k+'-initial-state.npz'),**{n:cpu(getattr(state,n)) for n in FIELDS},covariance=cpu(state.covariance()))
        v3,_=read_asset(args.run/'portrait.gaussian.ply',args.run/'portrait.components.npz',inputs)
        person=subset(v3,v3.parts!=0)
        support_seed=pool_support_input(anchors,pool);pool_xyz=np.array([p['xyz'] for p in points],np.float32).reshape(-1,3)
        torch.cuda.reset_peak_memory_stats()
        rows=render_comparison(data,old,support_seed,new,pool_xyz,states,person,out,data['development'])
        inputs.verify()
        if sha(args.output/'prepared/static_surface_seeds.npz')!=frozen['preparedSha256']:raise ValueError('prepared_changed_after_evaluation')
        outputs={str(p.relative_to(out)):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file()}
        summary={'status':'completed_prepare_only_research','newTrainingSteps':0,
            'preparationSummarySha256':sha(args.output/'preparation-summary.json'),'frames':rows,
            'sourceSha256':data['sourceHash'],'inputs':inputs.records,'outputs':outputs,
            'preparedSha256':frozen['preparedSha256'],
            'initialStates':{k:state_stats(v,v.scales) for k,v in states.items()},'fixedPersonStateHash':state_hash(person),
            'seconds':time.perf_counter()-started,'peakRssBytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'replayPeakCudaAllocatedBytes':torch.cuda.max_memory_allocated(),'replayPeakCudaReservedBytes':torch.cuda.max_memory_reserved(),
            'qualityPassed':False,'published':False,'productionEntryChanged':False}
        json_write(out/'summary.json',summary);print('REPLAY_COMPLETED',out,summary['seconds'],flush=True)



if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['prepared','run','stage0','output']:p.add_argument('--'+key,type=Path,required=True)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--resume-replay',action='store_true')
    mode.add_argument('--resume-support',action='store_true')
    args=p.parse_args()
    try:
        if args.resume_support:resume_support(args)
        elif args.resume_replay:replay(args)
        else:run(args)
    except Exception:
        if args.output.exists() and not (args.output/'summary.json').exists():
            error_file=args.output/('failure-'+str(time.time_ns())+'.txt')
            with error_file.open('x') as stream:stream.write(traceback.format_exc())
        raise
