"""Numerical recovery gate for the complete content baseline, zero training."""
from pathlib import Path
import argparse,json,time
import cv2,numpy as np,torch
from gsplat import export_splats
from reconstruction_complete_model import load_complete
from reconstruction_checkpoint import file_sha256
from reconstruction_portrait_pipeline import make_frame,draw


def export_state(state,path):
    pad=torch.zeros(len(state.means),15,3,device=state.means.device);pad[:,:3]=state.sh[:,1:]
    export_splats(means=state.means,scales=state.scales.log(),quats=state.quats,
        opacities=torch.logit(state.opacity.clamp(1e-6,1-1e-6)),sh0=state.sh[:,:1],shN=pad,
        format='ply',save_to=str(path))


def run(manifest,out):
    out=Path(out).resolve();private=Path(__file__).resolve().parent/'.sources'
    if not out.is_relative_to(private) or out.exists():raise ValueError('fresh_private_output_required')
    out.mkdir(parents=True);clock=time.perf_counter();torch.cuda.reset_peak_memory_stats()
    data,plan,model,lock,checkpoint=load_complete(manifest)
    source={k:v.detach().clone() for k,v in model.state_dict().items()}
    report={'sourceHash':data['sourceHash'],'assetHash':lock['assetHash'],
        'checkpointHash':lock['files']['checkpoint']['sha256'],'pointCount':lock['pointCount'],
        'reference':lock['reference'],'baselineRecovered':False,'optimizerSteps':0,'published':False,
        'views':{},'explicitCovarianceContractPassed':True,
        'limitations':['Numerical recovery only, not quality approval or HarmonyOS testing.']}
    side=dict(np.load(Path(manifest).parent/lock['files']['identities']['path']))
    names=list(dict.fromkeys([lock['reference']]+[n for n in plan['development'] if n in data['worlds']]))
    with torch.no_grad():
        for name in names:
            frame=make_frame(data,name,crop=False);adjusted=model.baseline.adjusted_frame(frame)
            state=model.state(adjusted);h,w=frame['rgb'].shape[:2]
            old_contract=draw(state,adjusted['C'],frame['K'],w,h,unit_scale=model.scale)
            unified=model.render(frame)
            explicit=model.render(frame,explicit_covariance=True)
            row={'nativeWidth':w,'nativeHeight':h,'C':adjusted['C'].cpu().tolist(),
                'K':frame['K'].cpu().tolist(),'F':adjusted['F'].cpu().tolist(),
                'qConservationMax':float((unified['q'].sum(-1)-unified['alpha']).abs().max()),
                'originalContractDifference':{k:float((old_contract[k]-unified[k]).abs().max()) for k in ('rgb','alpha','q')},
                'explicitCovarianceDifference':{k:dict(max=float((old_contract[k]-explicit[k]).abs().max()),
                    mean=float((old_contract[k]-explicit[k]).abs().mean())) for k in ('rgb','alpha','q')}}
            if name==lock['reference']:
                historical=dict(np.load(Path(manifest).parent/lock['files']['referenceImage']['path']))
                row['historicalNativeDifference']={k:dict(max=float(np.abs(old_contract[k].cpu().numpy()-historical[k]).max()),
                    mean=float(np.abs(old_contract[k].cpu().numpy()-historical[k]).mean())) for k in ('rgb','alpha','q')}
                if any(v['max']>1e-5 for v in row['historicalNativeDifference'].values()):raise ValueError('historical_native_image_not_recovered')
                if not np.array_equal(state.parts.cpu().numpy(),side['component']):raise ValueError('component_order_changed')
                export_state(state,out/'recovered.ply');report['recoveredPlyHash']=file_sha256(out/'recovered.ply')
                if report['recoveredPlyHash']!=lock['assetHash']:raise ValueError('historical_ply_not_exact')
                report['componentCounts']={str(i):int((state.parts==i).sum()) for i in range(5)}
            if row['qConservationMax']>1e-4:raise ValueError('contribution_contract_failed')
            if any(v['max']>.003 or v['mean']>1e-5 for v in row['explicitCovarianceDifference'].values()):
                report['explicitCovarianceContractPassed']=False
                row['explicitCovarianceAccepted']=False
            else:row['explicitCovarianceAccepted']=True
            if any(v>1e-5 for v in row['originalContractDifference'].values()):raise ValueError('original_renderer_contract_changed')
            rgb=unified['rgb'].cpu().numpy();labels=data['labels'][name];target=data['rgb'][name]
            row['parts']={}
            for label,mask in [('face',labels['face_core']|labels['face_boundary']),
                               ('hair',labels['hair_visible']),('body',labels['neck_cloth_visible']),
                               ('room',labels['room_visible'])]:
                if not mask.any():continue
                err=np.abs(rgb-target).mean(-1);brightness=(rgb-target).mean(-1)
                row['parts'][label]={'rgbL1':float(err[mask].mean()),'positiveBrightnessBias':float(np.maximum(brightness,0)[mask].mean()),
                    'alphaBelow08':float((unified['alpha'].cpu().numpy()[mask]<.8).mean()),
                    'qRoom':float(unified['q'].cpu().numpy()[mask,0].mean())}
            np.savez_compressed(out/(name+'.npz'),rgb=rgb,alpha=unified['alpha'].cpu().numpy(),q=unified['q'].cpu().numpy())
            panels=np.concatenate((target,rgb.clip(0,1)),1)
            cv2.imwrite(str(out/(name+'.png')),cv2.cvtColor((panels*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
            report['views'][name]=row
    if any(not torch.equal(v,model.state_dict()[k]) for k,v in source.items()):raise ValueError('replay_changed_source_parameters')
    report.update(baselineRecovered=True,all67SourceFieldsExact=True,seconds=time.perf_counter()-clock,
        allocatedPeakMiB=torch.cuda.max_memory_allocated()/1048576,reservedPeakMiB=torch.cuda.max_memory_reserved()/1048576)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('baselineRecovered','pointCount','recoveredPlyHash','seconds','allocatedPeakMiB')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args()
    try:run(args.manifest,args.out)
    except Exception as exc:
        folder=Path(args.out)
        if folder.exists():(folder/'failure.json').write_text(json.dumps({'error':str(exc),'published':False}),encoding='utf-8')
        raise
