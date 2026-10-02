"""Same-canvas renderer comparison and FIXED-Ply orbit of bounded candidates."""
from pathlib import Path
import argparse,json,math,time
import cv2,numpy as np,torch
from reconstruction_checkpoint import file_sha256,load_checkpoint
from reconstruction_portrait_model import GaussianState
from reconstruction_render_contract import draw
from reconstruction_observation_domains import attach_observation_domains
from probe_gs_contract import read_float_ply


def host_asset_path(value):
    """Explicit Windows/WSL host path conversion, never relative-path guessing."""
    value=str(value).replace('\\','/')
    if value[1:3]==':/' and Path('/mnt').is_dir():
        value='/mnt/'+value[0].lower()+'/'+value[3:]
    return Path(value).resolve()


def read_state(path,parts):
    a=read_float_ply(path);n=len(a['x']);t=lambda x:torch.as_tensor(x.copy(),device='cuda',dtype=torch.float32)
    sh=np.stack([a['f_dc_'+str(i)] for i in range(3)],1)[:,None,:]
    rest=np.stack([a['f_rest_'+str(i)] for i in range(45)],1).reshape(n,3,15).transpose(0,2,1)
    if np.abs(rest[:,3:]).max()>1e-7:raise ValueError('only_locked_sh1_expected')
    return GaussianState(t(np.stack([a[k] for k in ('x','y','z')],1)),t(np.stack([a['rot_'+str(i)] for i in range(4)],1)),
        t(np.exp(np.stack([a['scale_'+str(i)] for i in range(3)],1))),t(1/(1+np.exp(-a['opacity']))),
        t(np.concatenate((sh,rest[:,:3]),1)),torch.as_tensor(parts,device='cuda',dtype=torch.long))


def parameter_updates(folder):
    init=load_checkpoint(folder/'initial.pt',expected_hash=file_sha256(folder/'initial.pt'),device='cpu')
    final=load_checkpoint(folder/'final.pt',expected_hash=file_sha256(folder/'final.pt'),device='cpu')
    rows={}
    for key,value in init['model'].items():
        if key.startswith('patch.') and value.is_floating_point():
            diff=(value-final['model'][key]).abs();rows[key]=dict(max=float(diff.max()),mean=float(diff.mean()))
        elif not torch.equal(value,final['model'][key]):raise ValueError('protected_checkpoint_field_changed:'+key)
    steps=[int(state['step']) for state in final['optimizer']['state'].values()]
    if not steps or any(s!=final['step'] for s in steps):raise ValueError('optimizer_updates_not_actual')
    return dict(parameterDelta=rows,adamSourceSteps=steps,
        initialHash=file_sha256(folder/'initial.pt'),finalHash=file_sha256(folder/'final.pt'))


def run(control,candidate,out,*,orbit_frames=61):
    clock=time.perf_counter();root=Path(__file__).parent;control=Path(control).resolve();candidate=Path(candidate).resolve();out=Path(out).resolve()
    private=root/'.sources'
    if not all(p.is_relative_to(private) for p in (control,candidate,out)) or out.exists():raise ValueError('fresh_private_paths_required')
    out.mkdir();lock=json.loads((root/'reconstruction_baseline.json').read_text());reference=lock['reference']
    old=json.loads((control/'report.json').read_text());new=json.loads((candidate/'report.json').read_text())
    pc=json.loads((candidate/'playcanvas/report.json').read_text());spec=pc['sourceContract']
    if old['baselineAssetHash']!=lock['assetHash'] or new['baselineAssetHash']!=lock['assetHash'] or spec['sourceHash']!=lock['sourceHash']:
        raise ValueError('baseline_identity_mismatch')
    prepared=root/lock['prepared'];meta=json.loads((prepared/'preparation.json').read_text());raw=dict(np.load(prepared/'local_geometry.npz'))
    resolve=lambda value:Path(value) if Path(value).is_absolute() else root/value
    data=dict(K=raw['K'],staticMap=str(resolve(meta['staticMap'])),
        labels={reference:dict(np.load(prepared/'rectified_observations'/(reference+'.npz')))})
    attach_observation_domains(data,prepared);m=data['labels'][reference]
    domains=dict(face=m['face_core']|m['face_boundary'],hair=m['hair_visible'],body=m['neck_cloth_visible'],room=m['observed_room'])
    target=cv2.cvtColor(cv2.imread(str(prepared/'rectified_observations'/reference)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
    records={};pc_images={};h,w=target.shape[:2]
    # The actual trainer and recorded display both consume float32 K.
    # Test that exact contract rather than mixing raw float64 storage with it.
    if not np.array_equal(np.asarray(spec['K'],np.float32),raw['K'].astype(np.float32)):
        raise ValueError('intrinsics_changed')
    if (w,h)!=(spec['width'],spec['height']):raise ValueError('canvas_changed')
    for row in pc['rows']:
        asset=row['asset'];path=host_asset_path(asset['ply'])
        if not path.is_relative_to(private):raise ValueError('asset_outside_private_sources')
        if file_sha256(path)!=asset['hash']:raise ValueError('asset_changed')
        rgba=np.fromfile(candidate/'playcanvas'/(asset['label']+'.rgba'),np.uint8).reshape(h,w,4)[::-1].copy().astype(np.float32)/255
        folder=control/'baseline' if asset['label']=='baseline' else control/'final' if asset['label']=='control' else candidate/'final'
        gs=dict(np.load(folder/(reference+'.npz')));records[asset['label']]={};pc_images[asset['label']]=rgba[:,:,:3]
        for part,mask in domains.items():
            records[asset['label']][part]=dict(gsRgb=float(np.abs(gs['rgb']-target).mean(-1)[mask].mean()),
                pcRgb=float(np.abs(rgba[:,:,:3]-target).mean(-1)[mask].mean()),
                enginesRgb=float(np.abs(rgba[:,:,:3]-gs['rgb']).mean(-1)[mask].mean()),
                enginesAlpha=float(np.abs(rgba[:,:,3]-gs['alpha'])[mask].mean()),
                pcLowAlpha=float((rgba[:,:,3][mask]<.8).mean()))
        records[asset['label']]['fullEnginesRgb']=float(np.abs(rgba[:,:,:3]-gs['rgb']).mean())
    labels=['baseline','control','rejected-resample'];panels=[target]+[pc_images[n].clip(0,1) for n in labels]
    cv2.imwrite(str(out/'source-pc-baseline-control-rejected.png'),cv2.cvtColor((np.concatenate(panels,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    gs_panels=[target]+[dict(np.load((control/'baseline' if name=='baseline' else control/'final' if name=='control' else candidate/'final')/(reference+'.npz')))['rgb'].clip(0,1) for name in labels]
    cv2.imwrite(str(out/'source-gs-baseline-control-rejected.png'),cv2.cvtColor((np.concatenate(gs_panels,1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
    side=dict(np.load(root/lock['files']['identities']['path']));base_parts=side['component'];videos=[]
    if orbit_frames:
        C=np.asarray(spec['C'],np.float32);K=torch.as_tensor(spec['K'],device='cuda',dtype=torch.float32)
        poses=np.linalg.inv(C);camera=poses[:3,3];up=-poses[:3,1]
        base_state=read_state(root/lock['files']['ply']['path'],base_parts)
        face=base_state.parts==1;pivot=base_state.means[face].median(0).values.cpu().numpy()
        angles=np.interp(np.linspace(0,1,orbit_frames),[0,.25,.75,1],[0,-60,60,0])
        for row in pc['rows']:
            asset=row['asset'];parts=base_parts
            if asset['label']!='baseline':
                folder=control if asset['label']=='control' else candidate
                proposal=dict(np.load(folder/'proposal.npz'));retired=set(np.unique(proposal['parent_global_index']).tolist()) if 'parent_global_index' in proposal else set(json.loads((folder/'proposal.json').read_text())['selectedParents'])
                keep=np.asarray([i not in retired for i in range(len(base_parts))]);parts=np.r_[base_parts[keep],np.zeros(len(proposal['xyz']),np.int64)]
            state=read_state(host_asset_path(asset['ply']),parts);video=out/(asset['label']+'-fixed-ply-orbit.mp4')
            writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),24,(w,h))
            if not writer.isOpened():raise ValueError('video_encoder_unavailable')
            views=[]
            try:
                with torch.no_grad():
                    for i,angle in enumerate(angles):
                        a=math.radians(float(angle));R=np.array([[math.cos(a),0,math.sin(a)],[0,1,0],[-math.sin(a),0,math.cos(a)]])
                        cam=pivot+R@(camera-pivot)
                        # Rotate the ORIGINAL orientation too, avoiding a
                        # first-frame jump caused by suddenly looking at pivot.
                        rotation=(R@poses[:3,:3]).T
                        view=np.eye(4,dtype=np.float32);view[:3,:3]=rotation;view[:3,3]=-rotation@cam
                        if i in (0,orbit_frames-1):view=C.copy()
                        rendered=draw(state,torch.as_tensor(view,device='cuda'),K,w,h,unit_scale=spec['near']/.01)
                        rgb=rendered['rgb'].cpu().numpy().clip(0,1);writer.write(cv2.cvtColor((rgb*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
                        views.append(dict(index=i,controlYaw=float(angle),C=view.tolist()))
            finally:writer.release()
            if file_sha256(host_asset_path(asset['ply']))!=asset['hash']:raise ValueError('orbit_asset_changed')
            videos.append(dict(label=asset['label'],assetHash=asset['hash'],videoHash=file_sha256(video),frames=orbit_frames,
                canvas=[w,h],renderer='gsplat1.5.3',pivot=pivot.tolist(),poses=views,
                limitation='reference-state diagnostic, control yaw is not measured observation yaw; NOT HarmonyOS'))
    summary=dict(sourceHash=lock['sourceHash'],baselineAssetHash=lock['assetHash'],reference=reference,renderers=records,
        regression=new['failures'],sourceAll67FieldsExact=old['sourceAll67FieldsExact'] and new['sourceAll67FieldsExact'],
        parameterReceipts=dict(control=parameter_updates(control),resample=parameter_updates(candidate)),
        videos=videos,seconds=time.perf_counter()-clock,published=False,
        auditSourceHash=file_sha256(Path(__file__)),
        originalKStorageConversionMax=float(np.abs(raw['K']-raw['K'].astype(np.float32)).max()))
    (out/'report.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(dict(renderers=records,seconds=summary['seconds'],regression=new['failures']),indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--control',required=True);p.add_argument('--candidate',required=True);p.add_argument('--out',required=True);p.add_argument('--orbit-frames',type=int,default=61)
    a=p.parse_args();run(a.control,a.candidate,a.out,orbit_frames=a.orbit_frames)
