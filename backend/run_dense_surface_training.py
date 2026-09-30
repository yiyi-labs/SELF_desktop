"""Finite offline dense-hair/static-room comparison on the existing R0 stage.
Does not import the worker, transport, publisher or production viewer.
Face binding/identity remain existing SELF fields; dense skin depth is not
substituted for FLAME or declared skin truth. Body/eyeglasses remain explicit
unrepaired context. All context components participate in T2 visibility.
"""
import argparse,json,time,shutil
from pathlib import Path
import cv2,numpy as np,torch
from reconstruction_evidence_stage import load_stage
from reconstruction_components_v3 import FreeComponent,pick,exact_state_hash,save_json,sha
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_portrait_pipeline import make_frame,draw,metrics,masked_mean
from reconstruction_detail_controlled import pixel_structure
from reconstruction_reference_static import valid_window_structure,static_loss
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint
from reconstruction_portrait_priority import face_optimizer,face_regularizer
from run_haze_shared_surface import export_state
from reconstruction_dense_contract import digest,validate_surface_source

class DenseSurfaceStage(torch.nn.Module):
    def __init__(self,baseline,surfaces,*,source_hash):
        super().__init__();self.baseline=baseline;self.scale=baseline.scale
        self.parts=torch.nn.ModuleDict();self.sources={}
        arrays={file:dict(np.load(Path(surfaces)/file)) for file in ('head-local.npz','world.npz')}
        validate_surface_source(json.loads((Path(surfaces)/'result.json').read_text()),arrays,source_hash)
        for label,file,part,coords in [('hair','head-local.npz',2,'head-local'),('room','world.npz',0,'world')]:
            arr=arrays[file];keep=arr['parts']==part
            if int(keep.sum())<20:raise ValueError('insufficient_supported_surface:'+label)
            self.sources[label]={k:v[keep] for k,v in arr.items() if v.ndim and len(v)==len(keep)}
            t=lambda value,dtype=torch.float32:torch.as_tensor(value,device='cuda',dtype=dtype)
            s=GaussianState(t(arr['means'][keep]),t(arr['quats'][keep]),t(arr['scales'][keep]),t(arr['opacity'][keep]),t(arr['sh'][keep]),t(arr['parts'][keep],torch.long))
            limit=torch.median(s.scales[:,:2])*1.5
            self.parts[label]=FreeComponent(s,t(arr['uid'][keep],torch.long),t(arr['support'][keep]),coords,limit)
    def head_state(self,frame):
        s=self.baseline.head_state(frame)
        return joined_state(pick(s,s.parts!=2),self.parts['hair'].state())
    def render(self,frame,stage='T0'):
        f=self.baseline.adjusted_frame(frame);head=self.head_state(f);h,w=f['rgb'].shape[:2]
        if stage=='T0':return draw(head,f['F'],f['K'],w,h)
        if f['C'] is None:raise ValueError('no_world_C')
        state=joined_state(head.to_world(f['C'],f['F'],self.scale),self.parts['room'].state(),self.baseline.body_state(f['name']))
        return draw(state,f['C'],f['K'],w,h,unit_scale=self.scale)
    def reference_state(self,frame):
        f=self.baseline.adjusted_frame(frame)
        return joined_state(self.head_state(f).to_world(f['C'],f['F'],self.scale),self.parts['room'].state(),self.baseline.body_state(f['name']))

@torch.no_grad()
def evaluation(model,data,plan,out):
    out.mkdir(exist_ok=False);rows={}
    for n in plan['development']+plan['audit']+[plan['train'][0]]:
        f=make_frame(data,n,crop=False);r=model.render(f,'T0');value=metrics(r,f)
        value['role']='development' if n in plan['development'] else 'fixed-regression' if n in plan['audit'] else 'train'
        mask=f['masks']['face_core']|f['masks']['face_boundary']|f['masks']['glasses_visible']
        value['face']['edge']=float(pixel_structure(r['rgb'],f['rgb'],mask));value['F']=model.baseline.adjusted_frame(f)['F'].cpu().tolist() if isinstance(model,DenseSurfaceStage) else model.adjusted_frame(f)['F'].cpu().tolist()
        yy,xx=np.where((mask|f['masks']['hair_visible']).cpu().numpy());x0,x1=max(0,xx.min()-16),min(f['rgb'].shape[1],xx.max()+17);y0,y1=max(0,yy.min()-16),min(f['rgb'].shape[0],yy.max()+17)
        target=f['rgb'][y0:y1,x0:x1].cpu().numpy();head=r['rgb'][y0:y1,x0:x1].cpu().numpy()
        cv2.imwrite(str(out/(n+'-head.png')),cv2.cvtColor((np.concatenate([target,np.clip(head,0,1)],1)*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        if f['C'] is not None:
            scene=model.render(f,'T2');value['T2']=metrics(scene,f)
            value['T2']['faceRoomContribution']=float(masked_mean(scene['q'][...,0],mask))
            image=np.concatenate([f['rgb'].cpu().numpy(),scene['rgb'].clamp(0,1).cpu().numpy()],1)
            cv2.imwrite(str(out/(n+'-scene.jpg')),cv2.cvtColor((image*255).round().astype(np.uint8),cv2.COLOR_RGB2BGR))
        rows[n]=value
    save_json(out/'metrics.json',rows);return rows

def train(manifest,surfaces,out,face_steps=240,room_steps=240):
    start=time.perf_counter();torch.manual_seed(93031);np.random.seed(93031)
    data,plan,base,contract=load_stage(manifest,out);out=Path(out)
    for p in [Path(__file__),Path(__file__).with_name('reconstruction_dense_contract.py'),Path(__file__).with_name('reconstruction_dense_surfaces.py')]:shutil.copyfile(p,out/'algorithm-source'/p.name)
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')}
    contract['surfaces']={n:digest(Path(surfaces)/n) for n in ['result.json','head-local.npz','world.npz']}
    dense=DenseSurfaceStage(base,surfaces,source_hash=data['sourceHash'])
    config={'faceSteps':face_steps,'roomSteps':room_steps,'seed':93031,'nativeFullFrame':True,'topology':'fixed_new_dense_hair_room; existing_face_bindings',
        'headGeometry':'fixedF/K/identity; bounded_normal_and_embedding_only_after_80_before_recovery','body':'old_context_not_rebuilt',
        'denseSkin':'proposal_only_not_replaced_or_supervised_as_truth','density':'disabled_for_representation_comparison',
        'roomTraining':'all_components_render; face_frozen','newT3T4FaceUpdate':False,'releaseQualityPassed':False}
    save_json(out/'config.json',config);save_json(out/'contract.json',contract)
    raw=evaluation(base,data,plan,out/'R0-images');initial=evaluation(dense,data,plan,out/'initial-images')
    faceopt=face_optimizer(base);hair=dense.parts['hair'];room=dense.parts['room']
    rates={'offset':.002,'sh':.003,'opacity':.008,'log_scales':.002,'quats':.0005}
    hair_opt=torch.optim.Adam([{'params':[p],'lr':rates[n],'name':n} for n,p in hair.named_parameters()])
    room_opt=torch.optim.Adam([{'params':[p],'lr':rates[n],'name':n} for n,p in room.named_parameters()])
    sampler=FrameSampler(plan['train'],93031);room_names=[n for n in plan['train'] if n in data['worlds']];rs=FrameSampler(room_names,93032)
    ops={'face':faceopt,'hair':hair_opt,'room':room_opt};samplers={'face':sampler,'room':rs}
    extra={'config':config,'plan':plan,'roomMetadata':base.room.metadata,'bodySources':base.body_sources,'denseSources':dense.sources}
    def save(label,step):save_checkpoint(out/(label+'.pt'),dense,ops,samplers,stage='dense_surface_research',step=step,contract=contract,strategy={'topology':'fixed','events':[]},extra=extra)
    for p in dense.parameters():p.requires_grad_(False)
    before={n:p.detach().clone() for n,p in dense.named_parameters()};save('initial',0)
    curve=[];torch.cuda.reset_peak_memory_stats();p=base.portrait
    for step in range(1,face_steps+room_steps+1):
        phase='face' if step<=face_steps else 'room';geometry=80<=step<=face_steps-60 and step%4==0
        for value in dense.parameters():value.requires_grad_(False)
        if phase=='face':
            for n,value in p.named_parameters():value.requires_grad_(n in ('sh','opacity_logits','log_scales','quats') or geometry and n in ('normal_offset','embedding'))
            for n,value in hair.named_parameters():value.requires_grad_(n!='offset' or geometry)
            for op in ops.values():op.zero_grad(set_to_none=True)
            f=make_frame(data,sampler.next(),crop=False);r=dense.render(f,'T0');m=f['masks'];valid=(m['face_core']|m['face_boundary']|m['glasses_visible'])&~m['unknown_or_occluded'];hm=m['hair_visible']&~m['unknown_or_occluded']
            error=(r['rgb']-f['rgb']).abs().mean(-1)
            loss=1.5*masked_mean(error,valid)+masked_mean(error,hm)+.25*valid_window_structure(r['rgb'],f['rgb'],valid)+.25*pixel_structure(r['rgb'],f['rgb'],valid)
            loss+=.04*masked_mean((1-r['alpha']).square(),valid|hm)+.03*masked_mean(r['alpha'].square(),m['room_visible']&~m['unknown_or_occluded'])+face_regularizer(p,f)+hair.regularizer()
        else:
            for value in room.parameters():value.requires_grad_(True)
            for op in ops.values():op.zero_grad(set_to_none=True)
            f=make_frame(data,rs.next(),crop=False);r=dense.render(f,'T2');loss,stats=static_loss(r,f);loss+=room.regularizer()
        if not torch.isfinite(loss):raise RuntimeError('nonfinite_dense_stage_loss')
        loss.backward()
        for name,value in dense.named_parameters():
            if value.grad is not None and not torch.isfinite(value.grad).all():raise RuntimeError('nonfinite_gradient:'+name)
        torch.nn.utils.clip_grad_norm_([v for v in dense.parameters() if v.requires_grad],10.)
        if phase=='face':
            faceopt.step();hair_opt.step()
            if geometry:p.walk(faceopt)
            with torch.no_grad():
                p.log_scales.clamp_(p.initial_log_scales-np.log(1.3),p.initial_log_scales+np.log(1.3))
        else:room_opt.step()
        if step==1 or step%40==0:
            row={'step':step,'phase':phase,'name':f['name'],'loss':float(loss.detach()),'geometryUpdate':geometry,'allocatedMiB':torch.cuda.memory_allocated()/1048576};curve.append(row);print(json.dumps(row),flush=True)
        if step in (face_steps//2,face_steps,face_steps+room_steps//2):save('step-'+str(step),step)
        if time.perf_counter()-start>1500 or torch.cuda.memory_allocated()/1048576>7100:raise RuntimeError('finite_resource_budget')
    final=evaluation(dense,data,plan,out/'final-images');save('candidate-final',step)
    changes={n:float((value.detach()-before[n]).abs().mean()) for n,value in dense.named_parameters()}
    failures=[]
    for n in plan['audit']:
        if final[n]['face']['fixedRgbL1']>raw[n]['face']['fixedRgbL1']+.001:failures.append('face_regression:'+n)
        if final[n]['hair']['fixedRgbL1']>raw[n]['hair']['fixedRgbL1']+.003:failures.append('hair_regression:'+n)
    for n in plan['development']+plan['audit']:
        if 'T2' in final[n] and 'T2' in raw[n]:
            if final[n]['T2']['room']['fixedRgbL1']>raw[n]['T2']['room']['fixedRgbL1']+.005:failures.append('room_regression:'+n)
            if final[n]['T2']['faceRoomContribution']>raw[n]['T2']['faceRoomContribution']+.01:failures.append('occlusion_regression:'+n)
    f=make_frame(data,data['reference'],crop=False);state=dense.reference_state(f);export_state(state,out/'candidate-research-only.ply')
    original_head=base.head_state(f);kept=original_head.parts!=2
    # Final vertex identity is exact concatenation order, with separate source
    # namespaces. Legacy omitted hair UID is not falsely counted as editable.
    uids=torch.cat([base.portrait.stable_uid[kept],hair.source_ids,room.source_ids,torch.arange(len(base.body['means']),device='cuda')])
    namespaces=torch.cat([torch.zeros(int(kept.sum()),device='cuda',dtype=torch.long),torch.ones(len(hair.source_ids),device='cuda',dtype=torch.long),torch.full((len(room.source_ids),),2,device='cuda',dtype=torch.long),torch.full((len(base.body['means']),),3,device='cuda',dtype=torch.long)])
    if len(uids)!=len(state.means):raise ValueError('asset_identity_length')
    np.savez_compressed(out/'candidate-identities.npz',point_id=np.arange(len(uids)),source_uid=uids.cpu().numpy(),source_namespace=namespaces.cpu().numpy(),component=state.parts.cpu().numpy(),reference=np.array(f['name']),asset_sha256=np.array(digest(out/'candidate-research-only.ply')))
    result={'sourceHash':data['sourceHash'],'config':config,'curve':curve,'parameterChanges':changes,'seconds':time.perf_counter()-start,'allocatedMiB':torch.cuda.max_memory_allocated()/1048576,'reservedMiB':torch.cuda.max_memory_reserved()/1048576,
        'failures':failures,'localNumericScreen':not failures,'releaseQualityPassed':False,'published':False,'deployed':False,'assetHash':digest(out/'candidate-research-only.ply'),'bodyRebuilt':False,'glassesRebuilt':False,'reference':f['name']}
    save_json(out/'result.json',result)
    if failures:
        restore_checkpoint(out/'initial.pt',dense,ops,samplers,contract=contract,device='cuda');save('restored',0)
    print(json.dumps({k:result[k] for k in ('seconds','allocatedMiB','reservedMiB','failures','assetHash')}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('stage','surfaces','out'):parser.add_argument('--'+name,required=True)
    a=parser.parse_args()
    # Never append a failure receipt to a pre-existing independent run.
    existed=Path(a.out).exists()
    try:train(a.stage,a.surfaces,a.out)
    except Exception as error:
        if not existed and Path(a.out).is_dir() and not (Path(a.out)/'failure.json').exists():
            import traceback
            save_json(Path(a.out)/'failure.json',{'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc(),'published':False})
        raise