"""Finite evidence, actual child contributions and one fixed-PLY orbit."""
import argparse,json,shutil,subprocess,time
from pathlib import Path
import cv2,numpy as np,torch
from gsplat import export_splats
from reconstruction_components_v3 import load_v3_prepared,save_json,sha,export_identity
from reconstruction_portrait_pipeline import initialize_scene,make_frame,draw,masked_mean
from reconstruction_detail_controlled import DetailModel,pixel_structure
from reconstruction_surface_patch import patch_mask,weights
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_joint_visibility import load_recorded_ply
from audit_portrait_priority_handoff import restore_tensors,camera_looking_at
from audit_detail_controlled import png


def run(a):
    out=a.output;out.mkdir(exist_ok=False);start=time.perf_counter();data=load_v3_prepared(a.prepared)
    plan=json.loads((a.run/'observations.json').read_text());capacity=json.loads((a.run/'capacity-observations.json').read_text());side=json.loads((a.run/'patch-selection.json').read_text())['side']
    shutil.copyfile(a.prepared/'cloth_supported_seeds.npz',out/'cloth_supported_seeds.npz');scene=initialize_scene(data,out);model=DetailModel(scene,data,plan['train']);model.enable_components(data,plan['train']);del scene
    names=plan['development']+plan['audit']+capacity['train'];names=list(dict.fromkeys(names));results={};states={}
    for label,cp in [('R0',a.run/'R0-frozen.pt'),('R1',a.run/'R1/candidate-final.pt'),('R2',a.run/'R2/candidate-final.pt')]:
        ck=torch.load(cp,map_location='cuda',weights_only=False);restore_tensors(model,ck['model']);model.room.metadata=ck['extra']['roomMetadata'];model.body_sources=ck['extra']['bodySources']
        for p in model.parameters():p.requires_grad_(False)
        child=torch.zeros(len(model.portrait.role),device='cuda',dtype=torch.bool)
        if label=='R2':child=torch.isin(model.portrait.stable_uid,torch.tensor(ck['extra']['mutation']['childUIDs'],device='cuda'))
        rows={};dest=out/label;dest.mkdir()
        for name in names:
            f=make_frame(data,name);full=model.adjusted_frame(make_frame(data,name,crop=False));state=model.head_state(full);mask=torch.tensor(patch_mask(data,name,side),device='cuda')
            with torch.no_grad():r=model.render(f,'T0')
            value,info=weights(state,full['F'],full['K'],full['fullSize'][0],full['fullSize'][1],mask)
            x0,y0,x1,y1=f['rectangle'];patch=mask[y0:y1,x0:x1];rgb=r['rgb'];error=(rgb-f['rgb']).abs().mean(-1)
            con=info['conics'];mat=torch.stack([con[:,0],con[:,1],con[:,1],con[:,2]],-1).reshape(-1,2,2);sigma=torch.linalg.eigvalsh(torch.linalg.inv(mat)).clamp_min(0).sqrt();idx=info['gaussian_ids'].long()
            selected=(value[idx]>.5)&(child[idx] if label=='R2' else torch.ones_like(idx,dtype=torch.bool))
            rows[name]={'pixels':int(patch.sum()),'patchL1':float(masked_mean(error,patch)),
                'patchEdge':float(pixel_structure(rgb,f['rgb'],patch)), 'patchHole':float(masked_mean((r['alpha']<.8).float(),patch)),
                'childContributionFraction':float(value[child].sum()/value.sum().clamp_min(1e-9)) if label=='R2' else None,
                'sigmaQuantiles':torch.quantile(sigma[selected],torch.tensor([.1,.5,.9],device='cuda'),dim=0).cpu().tolist() if selected.any() else [],
                'use':'development' if name in plan['development'] else 'fixed-regression' if name in plan['audit'] else 'train'}
            np.savez_compressed(dest/(name+'.npz'),rgb=rgb.cpu().numpy(),alpha=r['alpha'].cpu().numpy(),crop=f['rectangle'])
        results[label]=rows
    compare=out/'comparisons';compare.mkdir()
    for name in names:
        z=np.load(out/'R0'/(name+'.npz'));x0,y0,x1,y1=z['crop'];src=data['rgb'][name][y0:y1,x0:x1];imgs=[src]+[np.load(out/label/(name+'.npz'))['rgb'] for label in ('R0','R1','R2')]
        png(compare/(name+'-full.png'),imgs)
        m=patch_mask(data,name,side);yy,xx=np.where(m)
        if not len(xx):continue
        a0,b0,a1,b1=max(x0,int(xx.min())-12),max(y0,int(yy.min())-12),min(x1,int(xx.max())+13),min(y1,int(yy.max())+13)
        crops=[im[b0-y0:b1-y0,a0-x0:a1-x0] for im in imgs]
        if crops[0].size:png(compare/(name+'-patch.png'),crops)
    save_json(out/'patch-metrics.json',results)
    # Export the R2 candidate even when rejected, explicitly research-only.
    # O1 remains a separate frozen-person intervention and is never quietly
    # combined with R2 to imply joint success.
    ck=torch.load(a.run/'R2/candidate-final.pt',map_location='cuda',weights_only=False);restore_tensors(model,ck['model']);model.room.metadata=ck['extra']['roomMetadata'];model.body_sources=ck['extra']['bodySources']
    for p in model.parameters():p.requires_grad_(False)
    f=model.adjusted_frame(make_frame(data,data['reference'],crop=False));p=model.portrait;head=model.head_state(f).to_world(f['C'],f['F'],model.scale)
    with torch.no_grad():
        s=joined_state(head,model.room.state(),model.body_state(data['reference']));ns=p.surface_count;nh=len(p.role);nr=len(model.room.params['means']);n=len(s.means);nb=n-nh-nr
        pad=torch.zeros(n,15,3,device='cuda');pad[:,:3]=s.sh[:,1:];ply=out/'fixed-R2-T2-diagnostic.ply'
        export_splats(means=s.means,scales=s.scales.log(),quats=s.quats,opacities=torch.logit(s.opacity.clamp(1e-6,1-1e-6)),sh0=s.sh[:,:1],shN=pad,format='ply',save_to=str(ply))
        meta=model.room.metadata;arrays={'point_id':np.arange(n,dtype=np.int64),'component':np.concatenate([np.where(p.role.cpu().numpy()==2,2,1),np.zeros(nr,dtype=np.int16),np.full(nb,4)]).astype(np.int16),
            'fine_component':np.r_[model.component_origin[p.origin_index].cpu().numpy(),np.full(nr,5),np.full(nb,4)].astype(np.int16),
            'stable_uid':np.r_[p.stable_uid.cpu().numpy(),meta['point_uid'].cpu().numpy()+(1<<40),np.arange(nb)+(2<<40)],
            'parent_uid':np.r_[p.parent_uid.cpu().numpy(),np.where(meta['parent_uid'].cpu().numpy()<0,-1,meta['parent_uid'].cpu().numpy()+(1<<40)),np.full(nb,-1)],
            'source_id':np.r_[p.source_index.cpu().numpy(),meta['source_id'].cpu().numpy(),model.body_sources['id']],
            'source_kind':np.r_[np.where(p.role.cpu().numpy()==2,6,2),meta['source_kind'].cpu().numpy(),model.body_sources['kind']],
            'triangle_id':np.r_[p.triangle_ids.cpu().numpy(),np.full(n-ns,-1)],'barycentric':np.concatenate([p.embedding.cpu().numpy(),np.zeros((n-ns,3))]),
            'confidence':np.r_[p.confidence.cpu().numpy(),meta['support'].cpu().numpy(),np.load(a.prepared/'cloth_supported_seeds.npz')['support']],
            'generation':np.r_[p.generation.cpu().numpy(),meta['generation'].cpu().numpy(),np.zeros(nb,dtype=np.int64)],
            'origin_index':np.r_[p.origin_index.cpu().numpy(),np.full(n-nh,-1)],
            'normal_offset':np.r_[p.normal_offset.cpu().numpy(),np.zeros(n-ns)]}
        asset=export_identity(out/'fixed-R2-T2.components.npz',ply,arrays,source_hash=data['sourceHash'],reference=data['reference'],editable_count=ns)
        loaded=load_recorded_ply(ply,ns);same=GaussianState(loaded['means'],loaded['quats'],loaded['scales'],loaded['opacity'],loaded['sh'][:,:4],s.parts)
        h,w=f['rgb'].shape[:2];before=draw(s,f['C'],f['K'],w,h,unit_scale=model.scale);after=draw(same,f['C'],f['K'],w,h,unit_scale=model.scale)
        diff={k:{'mean':float((before[k]-after[k]).abs().mean()),'max':float((before[k]-after[k]).abs().max())} for k in ['rgb','alpha','q']}
        position=torch.linalg.inv(f['C'])[:3,3].cpu().numpy();C=f['C'].cpu().numpy();up=-C[:3,:3].T[:,1];right=C[:3,:3].T[:,0];target=same.means[:ns].mean(0).cpu().numpy()
        proc=subprocess.Popen(['ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r','24','-i','-','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(out/'fixed-ply-orbit.mp4')],stdin=subprocess.PIPE)
        cams=[]
        for i in range(72):
            phase=i/71*2*np.pi;yaw=20*np.sin(phase);pitch=8*np.sin(phase*2);R=cv2.Rodrigues(up*yaw*np.pi/180)[0]@cv2.Rodrigues(right*pitch*np.pi/180)[0]
            cam=camera_looking_at(target+R@(position-target),target,up);r=draw(same,torch.tensor(cam,device='cuda',dtype=torch.float32),f['K'],w,h,unit_scale=model.scale)
            im=(r['rgb'].clamp(0,1).cpu().numpy()*255).round().astype(np.uint8);proc.stdin.write(im.tobytes());cams.append({'C':cam.tolist(),'K':f['K'].cpu().tolist(),'yawControlNotRealObservedAngle':yaw,'pitchControl':pitch})
            if i in (0,18,36,54):cv2.imwrite(str(out/f'orbit-{i:03d}.png'),cv2.cvtColor(im,cv2.COLOR_RGB2BGR))
        proc.stdin.close();assert proc.wait()==0;assert sha(ply)==asset['assetSha256']
        save_json(out/'asset.json',{'asset':asset,'roundtrip':diff,'cameras':cams,'checkpoint':sha(a.run/'R2/candidate-final.pt'),'sourceSha256':data['sourceHash'],
            'reference':data['reference'],'renderer':'gsplat 1.5.3; not PlayCanvas or HarmonyOS','stage':'frozen T2 diagnostic, all components common raster; R2 is an unapproved local candidate','published':False,'seconds':time.perf_counter()-start})
    shutil.copyfile(Path(__file__),out/Path(__file__).name)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('prepared',type=Path);p.add_argument('run',type=Path);p.add_argument('output',type=Path);run(p.parse_args())
