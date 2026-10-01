"""Measured shared local head geometry followed by equal-budget appearance.
One physical track -> one surface anchor, with source/target/third observations.
No new pose, K, identity or per-view displacement. Fixed topology and source IDs.
"""
from pathlib import Path
import argparse,json,time,shutil
import cv2,numpy as np,torch
from scipy.optimize import least_squares
from scipy.spatial import cKDTree
from reconstruction_complete_context import load_complete
from reconstruction_components_v3 import FreeComponent,pick,sha,save_json,exact_state_hash
from reconstruction_portrait_model import GaussianState,joined_state,quaternion_matrix
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean
from reconstruction_continuity_surface import physical_masks
from reconstruction_surface_continuity import SharedDisplacementField,transport_covariance
from reconstruction_reference_static import valid_window_structure
from reconstruction_surface_evidence import project
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint,rng_state,restore_rng
from run_continuous_surface_repair import evaluate_complete,regression_screen,export_complete_candidate,write_image

class LocalMeasuredField(SharedDisplacementField):
    """Compact-support smooth field; unknown surface outside support stays exact."""
    def weights(self,points):
        d=points[:,None]-self.nodes[None];distance=torch.linalg.vector_norm(d,dim=-1)
        r=distance/self.radius;v=(1-r).clamp_min(0)
        raw=v.pow(4)*(4*r+1);total=raw.sum(-1,keepdim=True)+.05
        derivative=-20*r*v.pow(3)/self.radius
        grad=derivative[:,:,None]*d/distance[:,:,None].clamp_min(1e-10)
        w=raw/total;dw=grad/total[:,:,None]-raw[:,:,None]*grad.sum(1,keepdim=True)/total[:,:,None].square()
        return w,dw
    def forward(self,points):
        w,dw=self.weights(points);displacement=self.delta.tanh()*self.maximum
        return points+w@displacement,torch.eye(3,device=points.device)[None]+torch.einsum('nki,kj->nji',dw,displacement)


def measured_field(base,data,records,part,folder):
    reference=data['reference'];f=base.baseline.adjusted_frame(make_frame(data,reference,crop=False));head=base.baseline.head_state(f)
    eligible=torch.where(base.keep_head&(head.parts==part))[0];points=head.means[eligible].cpu().numpy();q=quaternion_matrix(head.quats[eligible]).cpu().numpy();sc=head.scales[eligible].cpu().numpy()
    frames={n:base.baseline.adjusted_frame(make_frame(data,n,crop=False)) for n in {o['name'] for t in records for o in t['observations']}}
    states={n:base.baseline.head_state(f) for n,f in frames.items()}
    anchors=[];rejected={}
    for t in records:
        obs=t['observations'];source=obs[0];ff=frames[source['name']];F=ff['F'].cpu().numpy()
        posed=states[source['name']];posed_points=posed.means[eligible].cpu().numpy();posed_q=quaternion_matrix(posed.quats[eligible]).cpu().numpy()
        measured=np.array(t['xyz']);distance,index=cKDTree(posed_points).query(measured);nearest=posed_points[index]
        ray=np.linalg.inv(data['K'])@np.r_[source['uv'],1.];ray=ray@F[:3,:3];center=-F[:3,:3].T@F[:3,3]
        normal=posed_q[index,:,int(np.argmin(sc[index]))];denom=np.dot(ray,normal)
        if abs(denom)<.05:rejected['grazing_old_surface']=rejected.get('grazing_old_surface',0)+1;continue
        depth=np.dot(nearest-center,normal)/denom;initial_source=center+ray*depth
        metric=float((measured@F[:3,:3].T+F[:3,3])[2]/data['K'][0,0])
        if depth<=0 or metric<=0 or np.linalg.norm(initial_source-measured)>20*metric:
            rejected['old_surface_too_far_for_bounded_field']=rejected.get('old_surface_too_far_for_bounded_field',0)+1;continue
        R=posed_q[index]@q[index].T;initial=points[index]+R.T@(initial_source-nearest)
        motions={}
        for o in obs:
            st=states[o['name']];rr=quaternion_matrix(st.quats[eligible[index:index+1]])[0].cpu().numpy()@q[index].T
            motions[o['name']]=(st.means[eligible[index]].cpu().tolist(),rr.tolist())
        anchors.append(dict(t,initial=initial.tolist(),metric=metric,nearestUID=int(base.baseline.portrait.stable_uid[eligible[index]]),canonicalPoint=points[index].tolist(),existingMotion=motions))
    if len(anchors)<8:raise ValueError('insufficient_measured_surface_anchors:'+str(len(anchors)))
    x=np.array([t['initial'] for t in anchors]);metric=float(np.median([t['metric'] for t in anchors]));field=LocalMeasuredField(torch.tensor(x,device='cuda',dtype=torch.float32),metric*6,min(24,len(x)))
    w=field.weights(torch.tensor(x,device='cuda',dtype=torch.float32))[0].detach().cpu().numpy();bound=float(field.maximum);N=len(field.nodes)
    cameras={n:base.baseline.adjusted_frame(make_frame(data,n,crop=False))['F'].cpu().numpy() for n in {o['name'] for t in anchors for o in t['observations']}}
    fitting=[(i,o) for i,t in enumerate(anchors) for o in t['observations'][:-1]]
    def error(v,i,o):
        positions=x+w@(v.reshape(N,3)*bound);t=anchors[i];center,R=t['existingMotion'][o['name']];posed=np.asarray(center)+np.asarray(R)@(positions[i]-t['canonicalPoint']);return (project(posed[None],cameras[o['name']],data['K'])[0][0]-o['uv'])/o['sigma']
    def residual(v):return np.r_[np.concatenate([error(v,i,o) for i,o in fitting]),v*.15]
    result=least_squares(residual,np.zeros(N*3),bounds=(-np.ones(N*3)*.95,np.ones(N*3)*.95),loss='soft_l1',f_scale=1.,max_nfev=60,x_scale='jac')
    def stats(v):
        before=[];third=[];source=[];rows=[]
        for i,t in enumerate(anchors):
            values=[float(np.linalg.norm(error(v,i,o))*o['sigma']) for o in t['observations']]
            before+=values[:-1];third.append(values[-1]);source.append(values[0]);rows.append(dict(id=t['id'],names=[o['name'] for o in t['observations']],errors=values))
        return dict(fitMedian=float(np.median(before)),fitP90=float(np.quantile(before,.9)),thirdMedian=float(np.median(third)),thirdP90=float(np.quantile(third,.9)),sourceP90=float(np.quantile(source,.9))),rows
    initial,initial_rows=stats(np.zeros(N*3));final,final_rows=stats(result.x)
    accepted=final['fitMedian']<=initial['fitMedian'] and final['thirdMedian']<=initial['thirdMedian']+.5 and final['thirdP90']<=initial['thirdP90']+1 and final['sourceP90']<=1.5
    with torch.no_grad():field.delta.copy_(torch.tensor(np.arctanh(result.x.reshape(N,3)),device='cuda',dtype=torch.float32))
    for p in field.parameters():p.requires_grad_(False)
    save_json(folder/'geometry.json',dict(initial=initial,final=final,sourceAndTargetsIncluded=True,thirdExcludedFromFit=True,nfev=result.nfev,
        anchorCount=len(anchors),rejections=rejected,maximumPixels=3,controls=N,geometryResearchGatePassed=bool(accepted),conditionalOnExistingF=True,finalGeometryValidated=False))
    save_json(folder/'geometry-tracks.json',dict(anchors=anchors,initial=initial_rows,final=final_rows));torch.save(field.state_dict(),folder/'field.pt')
    w_all=field.weights(head.means[eligible])[0].sum(-1);active=eligible[w_all>.01]
    return field,active,accepted,reference

def relative_appearance(current,patch,initial_scales,initial_opacity,initial_sh,opacity_logit):
    # Updates relative to the restored source, preserving its posed covariance.
    alpha=(torch.logit(current.opacity.clamp(1e-6,1-1e-6))+opacity_logit-torch.logit(initial_opacity.clamp(1e-6,1-1e-6))).sigmoid()
    return GaussianState(current.means,current.quats,current.scales*(patch.scales/initial_scales),alpha,current.sh+patch.sh-initial_sh,patch.parts)


class HeadMeasuredStage(torch.nn.Module):
    def __init__(self,base,data,field,ids,candidate):
        super().__init__();self.baseline=base;self.scale=base.scale;self.field=field;self.candidate=candidate
        self.register_buffer('ids',ids);f=base.baseline.adjusted_frame(make_frame(data,data['reference'],crop=False));state=pick(base.baseline.head_state(f),ids)
        self.patch=FreeComponent(state,base.baseline.portrait.stable_uid[ids],torch.ones(len(ids),device='cuda'),'head-local',0.)
        self.register_buffer('canonical_initial',state.means.detach().clone())
        self.register_buffer('initial_rotation',quaternion_matrix(state.quats).detach().clone())
        self.register_buffer('initial_scales',state.scales.detach().clone())
        self.register_buffer('initial_opacity',state.opacity.detach().clone())
        self.register_buffer('initial_sh',state.sh.detach().clone())
        self.register_buffer('head_rows',torch.searchsorted(torch.where(base.keep_head)[0],ids))
    def head_patch(self,f):
        # Preserve existing expression/embedding motion at every observation.
        current=pick(self.baseline.baseline.head_state(f),self.ids);p=self.patch.state()
        relative_R=quaternion_matrix(current.quats)@self.initial_rotation.transpose(-1,-2)
        s=relative_appearance(current,p,self.initial_scales,self.initial_opacity,self.initial_sh,self.patch.opacity)
        if not self.candidate:return s
        displacement,J=self.field(self.canonical_initial);moved=current.means+torch.einsum('nij,nj->ni',relative_R,displacement-self.canonical_initial)
        J=relative_R@J@relative_R.transpose(-1,-2)
        U,_,V=torch.linalg.svd(J.detach());fix=torch.eye(3,device='cuda')[None].repeat(len(J),1,1);fix[:,2,2]=torch.where(torch.linalg.det(U@V)<0,-1.,1.)
        return transport_covariance(s,J,moved,U@fix@V)
    def state(self,f):
        s=self.baseline.state(f);keep=torch.ones(len(s.means),device='cuda',dtype=torch.bool);keep[self.head_rows]=False
        return joined_state(pick(s,keep),self.head_patch(f).to_world(f['C'],f['F'],self.scale))
    def render(self,f):
        f=self.baseline.baseline.adjusted_frame(f);h,w=f['rgb'].shape[:2]
        return draw(self.state(f),f['C'],f['K'],w,h,unit_scale=self.scale)
    def render_local(self,f):
        f=self.baseline.baseline.adjusted_frame(f);head=self.baseline.baseline.head_state(f);keep=self.baseline.keep_head.clone();keep[self.ids]=False
        s=joined_state(pick(head,keep),self.head_patch(f));h,w=f['rgb'].shape[:2]
        return draw(s,f['F'],f['K'],w,h)


def run(complete,mvs,out,component='face',steps=240,geometry_mode='vector'):
    out=Path(out);clock=time.perf_counter();torch.manual_seed(100105);np.random.seed(100105)
    data,plan,base,contract=load_complete(complete,out);extra=contract.pop('sourceExtra')
    from reconstruction_dense_face_field import dense_face_field
    for name in ('run_dense_face_surface_repair.py','reconstruction_dense_face_field.py','build_cross_window_surface.py','reconstruction_surface_consensus.py','run_measured_head_surface_repair.py'):
        shutil.copyfile(Path(__file__).with_name(name),out/'algorithm-source'/name)
    field,ids,accepted,reference=dense_face_field(base,data,plan,mvs,out,geometry_mode)
    if not accepted:save_json(out/'result.json',dict(geometryRejected=True,appearanceExecuted=False,published=False,sourceHash=data['sourceHash']));return
    records=[dict(observations=[dict(name=n) for n in plan['train'] if n in data['local']])]
    part=1
    contract['sources']={p.name:sha(p) for p in (out/'algorithm-source').glob('*.py')}
    contract['geometryHash']=sha(out/'geometry-depth-support.npz');save_json(out/'contract.json',contract)
    train=sorted({o['name'] for t in records for o in t['observations']});world_evaluation=list(dict.fromkeys([n for n in train if n in data['worlds']]+[contract['reference']]+[n for n in plan['development']+plan['audit'] if n in data['worlds']]))
    masks=physical_masks(contract['spec']['prepared'],data,list(dict.fromkeys(train+world_evaluation)));old,before=evaluate_complete(base,data,world_evaluation,masks,out/'baseline-full')
    side=dict(np.load(Path(complete)/'candidate-identities.npz'));source_hash=exact_state_hash(base);random=rng_state();summary={}
    config=dict(component=component,steps=steps,train=train,evaluate=world_evaluation,activePoints=len(ids),pointCountFixed=True,poseFixed=True,
        sharedCanonicalField=True,maximumPixels=3,appearanceBudgetSame=True,training='full-native head-local with all head parts visible',evaluation='complete scene joint compositing',
        expressionMotion='existing per-point bound geometry and local basis; no new per-frame freedom',geometryData='actual multi-window fused depth with consistent normals and bounded common surface; conditional on fixed F',published=False)
    save_json(out/'config.json',config)
    for label,candidate in [('appearance-control',False),('measured-candidate',True)]:
        folder=out/label;folder.mkdir();shutil.copyfile(out/'spec.json',folder/'spec.json');model=HeadMeasuredStage(base,data,field,ids,candidate)
        for p in model.parameters():p.requires_grad_(False)
        initial={k:v.detach().clone() for k,v in model.state_dict().items()}
        rates={'sh':.002,'opacity':.005,'log_scales':.001};ops={k:torch.optim.Adam([getattr(model.patch,k)],lr=lr) for k,lr in rates.items()}
        for k in rates:getattr(model.patch,k).requires_grad_(True)
        sampler=FrameSampler(train,100105);restore_rng(random);curve=[]
        def ck(name,step):save_checkpoint(folder/(name+'.pt'),model,ops,{'views':sampler},stage='measured-'+component,step=step,contract=contract,
            strategy={'events':[],'topology':'fixed UID surface field'},extra=dict(sourceContinuity=extra,config=config,ids=ids,candidate=candidate,fieldState=field.state_dict()))
        ck('initial',0);_,initial_metrics=evaluate_complete(model,data,world_evaluation,masks,folder/'initial-full',old)
        start=time.perf_counter();torch.cuda.reset_peak_memory_stats()
        for step in range(1,steps+1):
            for op in ops.values():op.zero_grad(set_to_none=True)
            n=sampler.next();f=make_frame(data,n,crop=False);r=model.render_local(f);mask=torch.tensor(masks[n][component],device='cuda');err=(r['rgb']-f['rgb']).abs().mean(-1)
            loss=masked_mean(err,mask)+.12*valid_window_structure(r['rgb'],f['rgb'],mask)+.025*masked_mean((1-r['q'][...,part]).square(),mask)+model.patch.regularizer()
            # Other observed head parts protect real occlusion relationships.
            other='face' if component=='hair' else 'hair';guard=torch.tensor(masks[n][other],device='cuda')
            loss+=.05*masked_mean(r['q'][...,part].square(),guard)
            if not torch.isfinite(loss):raise ValueError('nonfinite_loss')
            loss.backward()
            for k,p in model.patch.named_parameters():
                if p.grad is not None and not torch.isfinite(p.grad).all():raise ValueError('nonfinite_gradient:'+k)
            for op in ops.values():op.step()
            with torch.no_grad():model.patch.log_scales.clamp_(initial['patch.log_scales']+np.log(.8),initial['patch.log_scales']+np.log(1.2))
            if step==steps//2:ck('mid',step)
            if step==1 or step%60==0:
                row=dict(step=step,name=n,loss=float(loss.detach()));curve.append(row);print(component,label,json.dumps(row),flush=True)
            if time.perf_counter()-start>600 or torch.cuda.memory_allocated()/1048576>7100:raise ValueError('finite_resource_budget')
        ck('candidate-final',steps);_,after=evaluate_complete(model,data,world_evaluation,masks,folder/'final-full',old);failures=regression_screen(before,after)
        result=dict(baseline=before,initial=initial_metrics,final=after,failures=failures,curve=curve,steps=steps,
            parameterChanges={k:float((v-initial[k]).abs().mean()) for k,v in model.state_dict().items() if k.startswith('patch.') and v.is_floating_point()},
            trainEvalSeconds=time.perf_counter()-start,allocatedMiB=torch.cuda.max_memory_allocated()/1048576,reservedMiB=torch.cuda.max_memory_reserved()/1048576,
            frozenBaselineExact=exact_state_hash(base)==source_hash,transactionAccepted=False,releaseQualityPassed=False,published=False)
        keep=np.ones(len(side['point_id']),bool);keep[model.head_rows.cpu().numpy()]=False
        export_complete_candidate(model,base,data,contract['reference'],folder,side,keep,side['source_uid'][model.head_rows.cpu().numpy()],0,result)
        save_json(folder/'result.json',result);summary[label]={k:result[k] for k in ('assetHash','pointCount','failures','trainEvalSeconds','allocatedMiB','reservedMiB')}
        restore_checkpoint(folder/'initial.pt',model,ops,{'views':sampler},contract=contract,device='cuda');ck('restored',0)
        if any(not torch.equal(v,model.state_dict()[k]) for k,v in initial.items()):raise ValueError('head_restore_failed')
        if exact_state_hash(base)!=source_hash:raise ValueError('other_component_changed')
        del model,ops;torch.cuda.empty_cache();print(component,label,'FINISHED',json.dumps(summary[label]),flush=True)
    save_json(out/'result.json',dict(branches=summary,sourceHash=data['sourceHash'],seconds=time.perf_counter()-clock,published=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',required=True);p.add_argument('--mvs',required=True,nargs='+');p.add_argument('--out',required=True);p.add_argument('--component',choices=['face'],default='face');p.add_argument('--steps',type=int,default=240);p.add_argument('--geometry-mode',choices=['vector','normal'],default='vector');a=p.parse_args()
    try:run(a.complete,a.mvs,a.out,a.component,a.steps,a.geometry_mode)
    except Exception as e:
        if Path(a.out).exists():
            import traceback
            save_json(Path(a.out)/'failure.json',dict(type=type(e).__name__,message=str(e),traceback=traceback.format_exc(),published=False))
        raise
