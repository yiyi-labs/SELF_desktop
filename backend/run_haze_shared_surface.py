"""Bounded D/G/B research runner; frozen R0, no application/publisher import."""
import argparse,copy,json,os,random,shutil,time,threading,subprocess
from pathlib import Path
import cv2,numpy as np,torch
from gsplat import export_splats
from reconstruction_components_v3 import load_v3_prepared,save_json,sha,exact_state_hash
from reconstruction_portrait_pipeline import initialize_scene,make_frame,draw,masked_mean
from reconstruction_detail_controlled import DetailModel,evaluate_face,pixel_structure
from reconstruction_shared_surface import SharedSurfaceModel,make_basis,triangle_frames
from reconstruction_surface_patch import patch_mask,weights
from reconstruction_patch_correspondence import intersect
from reconstruction_portrait_model import GaussianState,joined_state
from reconstruction_research_state import FrameSampler,save_checkpoint,restore_checkpoint
from reconstruction_portrait_priority import face_optimizer
from audit_portrait_priority_handoff import restore_tensors
from audit_detail_controlled import png

BASE=Path(__file__).resolve().parent
OLD=BASE/'.sources/fullframe-surface-patch-20260929-b'
ROOT=Path(os.environ.get('SELF_HAZE_RUN_DIR',str(BASE/'.sources/haze-shared-surface-context-20260929-a'))).resolve()
if not ROOT.is_relative_to((BASE/'.sources').resolve()):raise ValueError('private_research_output_required')
PREP=Path('/mnt/d/STUDY/College/mine/olay/backend/.sources/integrated-components-v2-20260928-e')

def setup(phase):
    out=ROOT/phase;out.mkdir(parents=True,exist_ok=False)
    source=out/'algorithm-source';source.mkdir()
    for file in BASE.glob('*.py'):
        if file.name.startswith(('reconstruction_','run_haze','flame_open','appearance_direction','audit_portrait_priority','audit_detail_controlled')):shutil.copyfile(file,source/file.name)
    contract={'R0':sha(OLD/'R0-frozen.pt'),'prepared':str(PREP),'plan':sha(OLD/'observations.json'),
        'code':{p.name:sha(p) for p in source.glob('*.py')},'fullFrame':True,'published':False}
    save_json(out/'contract.json',contract)
    data=load_v3_prepared(PREP);plan=json.loads((OLD/'observations.json').read_text());plan.pop('new_audit',None)
    save_json(out/'observations.json',plan)
    load=out/'load';load.mkdir();shutil.copyfile(PREP/'cloth_supported_seeds.npz',load/'cloth_supported_seeds.npz')
    scene=initialize_scene(data,load);model=SharedSurfaceModel(scene,data,plan['train']);del scene;model.enable_components(data,plan['train'])
    ck=torch.load(OLD/'R0-frozen.pt',map_location='cuda',weights_only=False);restore_tensors(model,ck['model'])
    model.room.metadata=ck['extra']['roomMetadata'];model.body_sources=ck['extra']['bodySources']
    for p in model.parameters():p.requires_grad_(False)
    return out,contract,data,plan,model

def save(out,label,m,contract,optim=None,sampler=None,step=0,extra=None):
    return save_checkpoint(out/(label+'.pt'),m,optim or {},{'face':sampler} if sampler else {},stage=out.name,step=step,contract=contract,
        strategy={'density':'disabled_fixed_topology','updates':0},extra={'roomMetadata':m.room.metadata,'bodySources':m.body_sources,**(extra or {})})

def attach_zero(model):
    model.attach_surface(torch.zeros(len(model.portrait.reference_mesh),1,device='cuda'),.001)
    model.surface_control.requires_grad_(False)

@torch.no_grad()
def export_state(s,path):
    pad=torch.zeros(len(s.means),15,3,device='cuda');pad[:,:3]=s.sh[:,1:]
    export_splats(means=s.means,scales=s.scales.log(),quats=s.quats,opacities=torch.logit(s.opacity.clamp(1e-6,1-1e-6)),sh0=s.sh[:,:1],shN=pad,format='ply',save_to=str(path))

@torch.no_grad()
def display():
    out,contract,data,plan,m=setup('D');attach_zero(m);f=m.adjusted_frame(make_frame(data,data['reference'],crop=False))
    state=joined_state(m.head_state(f).to_world(f['C'],f['F'],m.scale),m.room.state(),m.body_state(data['reference']))
    export_state(state,out/'R0-frozen-T2.ply')
    from reconstruction_joint_visibility import load_recorded_ply
    rejected=BASE/'.sources/fullframe-surface-evaluation-20260929-a/fixed-R2-T2-diagnostic.ply'
    z=load_recorded_ply(rejected,9404);reject=GaussianState(z['means'],z['quats'],z['scales'],z['opacity'],z['sh'][:,:4],torch.zeros(len(z['means']),device='cuda',dtype=torch.long))
    C=f['C'];K=f['K'];h,w=f['rgb'].shape[:2];rows=[]
    for label,s,path in [('R0',state,out/'R0-frozen-T2.ply'),('R2-rejected',reject,rejected)]:
        r=draw(s,C,K,w,h,unit_scale=m.scale);np.savez_compressed(out/(label+'-gsplat.npz'),rgb=r['rgb'].cpu().numpy(),alpha=r['alpha'].cpu().numpy())
        png(out/(label+'-gsplat.png'),[r['rgb'].cpu().numpy()])
        rows.append({'label':label,'ply':str(path),'hash':sha(path),'count':len(s.means)})
    np.savez_compressed(out/'source-reference.npz',rgb=data['rgb'][data['reference']],face=data['labels'][data['reference']]['face_core'],room=data['labels'][data['reference']]['room_visible'])
    inv=torch.linalg.inv(C).cpu().numpy();eye=inv[:3,3];forward=inv[:3,2];up=-inv[:3,1]
    save_json(out/'display.json',{'assets':rows,'K':K.cpu().tolist(),'C':C.cpu().tolist(),'width':w,'height':h,'camera':eye.tolist(),'target':(eye+forward).tolist(),'up':up.tolist(),
        'near':.01*m.scale,'far':1e10*m.scale,'reference':data['reference'],'sourceHash':data['sourceHash'],'tabletCurrentAsset':'not_read_or_assumed','gsplat':'1.5.3','published':False})
    print('D_EXPORT_COMPLETE',flush=True)


def build_tracks(m,data,plan,out,side='right'):
    # Non-overlapping temporal chains, seeded once; no pair-by-pair 3D anchors.
    names=sorted(plan['train']);chains=[]
    for name in names:
        fid=int(name[6:10])
        if not chains or fid-int(chains[-1][-1][6:10])>4:chains.append([])
        chains[-1].append(name)
    chains=[c for c in chains if len(c)>=3];tracks=[];stats=[]
    for ci,chain in enumerate(chains):
        grays={n:cv2.cvtColor((data['rgb'][n]*255).round().astype(np.uint8),cv2.COLOR_RGB2GRAY) for n in chain}
        seed=cv2.goodFeaturesToTrack(grays[chain[0]],60,.01,4,mask=patch_mask(data,chain[0],side).astype(np.uint8)*255,blockSize=5)
        if seed is None:continue
        alive=np.ones(len(seed),bool);observations=[[{'name':chain[0],'uv':x.tolist(),'fb':0.}] for x in seed[:,0]];current=seed.copy()
        for a,b in zip(chain[:-1],chain[1:]):
            q,ok,_=cv2.calcOpticalFlowPyrLK(grays[a],grays[b],current,None,winSize=(21,21),maxLevel=3)
            back,ok2,_=cv2.calcOpticalFlowPyrLK(grays[b],grays[a],q,None,winSize=(21,21),maxLevel=3)
            fb=np.linalg.norm(back[:,0]-current[:,0],axis=1);xy=np.rint(q[:,0]).astype(int);h,w=grays[b].shape
            inside=(xy[:,0]>=0)&(xy[:,0]<w)&(xy[:,1]>=0)&(xy[:,1]<h);xy=xy.clip([0,0],[w-1,h-1])
            alive&=(ok[:,0]>0)&(ok2[:,0]>0)&(fb<.75)&inside&patch_mask(data,b,side)[xy[:,1],xy[:,0]]
            for i in np.where(alive)[0]:observations[i].append({'name':b,'uv':q[i,0].tolist(),'fb':float(fb[i])})
            current=q
        f=m.adjusted_frame(make_frame(data,chain[0],crop=False));mesh=(f['mesh']+m.portrait.surface_residual).detach().cpu().numpy();faces=m.portrait.faces.cpu().numpy()
        accepted=0
        for si,obs in enumerate(observations):
            if len(obs)<3:continue
            hit=intersect(mesh,faces,f['F'].detach().cpu().numpy(),data['K'],np.array(obs[0]['uv']))
            if hit is None:continue
            tid,bar=hit
            track={'id':f'chain{ci}-seed{si}','triangle':tid,'bary':bar.tolist(),'observations':obs,'use':'withheld-track' if si%5==0 else 'fit','binding':'one_source_ray_intersection_once'}
            # Last third view withheld. Features/FB confidence are fixed observations.
            for oi,o in enumerate(obs):o['role']='source' if oi==0 else 'third-withheld' if oi==len(obs)-1 else 'target';o['weight']=float(max(.2,1/(1+(o['fb']/.35)**2)))
            tracks.append(track);accepted+=1
        stats.append({'chain':chain,'seeds':len(seed),'tracksAtLeast3':accepted})
    save_json(out/'tracks.json',{'side':side,'chains':stats,'tracks':tracks,'devRgbUsed':False,'testType':'withheld_observations_on_historical_research_images_not_final_blind'})
    if len(tracks)<12:raise RuntimeError('insufficient_three_observation_tracks')
    return tracks


def residuals(m,data,tracks):
    byframe={}
    for t in tracks:
        for o in t['observations']:byframe.setdefault(o['name'],[]).append((t,o))
    errors=[];metadata=[];frozen=[]
    for name,rows in byframe.items():
        f=m.adjusted_frame(make_frame(data,name,crop=False));tri=torch.tensor([t['triangle'] for t,o in rows],device='cuda');bary=torch.tensor([t['bary'] for t,o in rows],device='cuda',dtype=torch.float32)
        uv,_=m.project_anchors(f['mesh'],f['F'],f['K'],tri,bary)
        target=torch.tensor([o['uv'] for t,o in rows],device='cuda');errors.append(uv-target)
        metadata.extend([{'track':t['id'],'name':name,'use':t['use'],'role':o['role'],'weight':o['weight']} for t,o in rows])
    return torch.cat(errors),metadata

def error_report(errors,meta):
    val=errors.detach().norm(dim=-1).cpu().numpy();groups={}
    for key,indices in [('all',list(range(len(meta))))]+[(role,[i for i,r in enumerate(meta) if r['role']==role]) for role in ('source','target','third-withheld')]+[('withheld-track',[i for i,r in enumerate(meta) if r['use']=='withheld-track'])]+[(n,[i for i,r in enumerate(meta) if r['name']==n]) for n in sorted(set(r['name'] for r in meta))]:
        if indices:groups[key]={'n':len(indices),'median':float(np.median(val[indices])),'p90':float(np.quantile(val[indices],.9)),'max':float(val[indices].max())}
    return {'groups':groups,'observations':[{**r,'error':float(v)} for r,v in zip(meta,val)]}


def geometry():
    out,contract,data,plan,m=setup('G-geometry');tracks=build_tracks(m,data,plan,out)
    fit=[t for t in tracks if t['use']=='fit'];mesh=m.portrait.reference_mesh.detach().cpu().numpy()+m.portrait.surface_residual.detach().cpu().numpy()
    basis,basis_meta=make_basis(mesh,m.portrait.faces.cpu().numpy(),[t['triangle'] for t in fit],count=12,rings=3)
    bound=3*float(m.portrait.metric_per_pixel.median());m.attach_surface(torch.tensor(basis,device='cuda'),bound)
    for p in m.parameters():p.requires_grad_(False)
    m.surface_control.requires_grad_(True)
    config={'geometrySteps':180,'controls':12,'boundHeadUnits':bound,'F':'fixed_R0','appearance':'frozen','topology':'fixed_R0','loss':'fixed_FB_weights_Huber_1px_all_source_and_targets; final_observation_and_20pct_tracks_withheld','appearanceStepsLater':120,'viewsPerStepLater':2,'seed':7299}
    save_json(out/'config.json',config);save_json(out/'basis.json',basis_meta)
    torch.manual_seed(7299);optimizer=torch.optim.Adam([m.surface_control],lr=.045);op={'surface':optimizer}
    save(out,'initial',m,contract,op,extra={'tracks':tracks,'config':config})
    before_e,meta=residuals(m,data,tracks);before=error_report(before_e,meta)
    use=torch.tensor([r['use']=='fit' and r['role']!='third-withheld' for r in meta],device='cuda');weight=torch.tensor([r['weight'] for r in meta],device='cuda')
    # Actual data Jacobian, before regularization; inspect weak/ambiguous modes.
    rows=[]
    for scalar in before_e[use].reshape(-1):rows.append(torch.autograd.grad(scalar,m.surface_control,retain_graph=True)[0].reshape(-1))
    J=torch.stack(rows);sv=torch.linalg.svdvals(J).detach().cpu().numpy();save_json(out/'jacobian.json',{'shape':list(J.shape),'singularValues':sv.tolist(),'rankRelative1e-4':int((sv>sv[0]*1e-4).sum()),'rankIsLocalNotDepthTruth':True});del J,rows,before_e
    edges=m.portrait.edges;curve=[];start=time.perf_counter();init_state=copy.deepcopy(m.state_dict())
    for step in range(1,181):
        optimizer.zero_grad(set_to_none=True);e,_=residuals(m,data,tracks)
        robust=torch.nn.functional.smooth_l1_loss(e,torch.zeros_like(e),beta=1,reduction='none').sum(-1)
        disp=m.displacement()/bound
        loss=(robust[use]*weight[use]).sum()/weight[use].sum()+.025*disp.square().mean()+.01*(disp[edges[:,0]]-disp[edges[:,1]]).square().mean()
        loss.backward();optimizer.step()
        if step==1 or step%30==0:
            row={'step':step,'loss':float(loss.detach()),'maxDisplacement':float(m.displacement().norm(dim=-1).max()),'controlGrad':float(m.surface_control.grad.norm())};curve.append(row);print(json.dumps(row),flush=True)
        if step==90:save(out,'mid',m,contract,op,step=step,extra={'tracks':tracks,'config':config})
    final_e,_=residuals(m,data,tracks);after=error_report(final_e,meta)
    current=m.current_mesh(m.portrait.reference_mesh);initial=m.portrait.reference_mesh+m.surface_base;faces=m.portrait.faces
    ta=initial[faces];tb=current[faces];na=torch.linalg.cross(ta[:,1]-ta[:,0],ta[:,2]-ta[:,0]);nb=torch.linalg.cross(tb[:,1]-tb[:,0],tb[:,2]-tb[:,0]);ratio=nb.norm(dim=-1)/na.norm(dim=-1).clamp_min(1e-10);dots=torch.nn.functional.cosine_similarity(na,nb,dim=-1)
    # Absolute source error and each view regression are checked, not just median.
    failures=[]
    for key,old in before['groups'].items():
        new=after['groups'][key]
        if key=='source':
            if new['p90']>.75 or new['max']>1.5:failures.append('source_anchor_drift')
        elif key.startswith('frame_') and (new['median']>old['median']+.25 or new['p90']>old['p90']+.5):failures.append('view_regression:'+key)
    for key in ('target','third-withheld','withheld-track'):
        if after['groups'][key]['median']>=before['groups'][key]['median']:failures.append('no_shared_improvement:'+key)
    if float(ratio.min())<.65 or float(dots.min())<.97:failures.append('surface_distortion')
    save(out,'candidate-final',m,contract,op,step=180,extra={'tracks':tracks,'config':config})
    report={'before':before,'after':after,'geometryScreen':not failures,'failures':failures,'curve':curve,'seconds':time.perf_counter()-start,'areaRatioMin':float(ratio.min()),'normalCosMin':float(dots.min()),
        'maxDisplacementPixels':float(m.displacement().norm(dim=-1).max()/m.portrait.metric_per_pixel.median()),'fixedTopology':True,'appearanceFrozen':True,'poseFrozen':True,'published':False}
    save_json(out/'result.json',report)
    # Render actual new geometry before any colour recovery, all fixed dev/reg.
    evaluate_face(m,data,plan,out/'geometry-images')
    if failures:
        restore_checkpoint(out/'initial.pt',m,op,{},contract=contract,device='cuda');save(out,'restored',m,contract,op,extra={'rejected':failures})
    print(json.dumps({'geometryScreen':not failures,'failures':failures,'tracks':len(tracks),'seconds':report['seconds']}),flush=True)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('phase',choices=['display','geometry']);args=a.parse_args()
    random.seed(7299);np.random.seed(7299);torch.manual_seed(7299);torch.cuda.reset_peak_memory_stats();started=time.perf_counter()
    try:globals()[args.phase]()
    finally:print(json.dumps({'totalSeconds':time.perf_counter()-started,'allocatedMiB':torch.cuda.max_memory_allocated()/1048576,'reservedMiB':torch.cuda.max_memory_reserved()/1048576}),flush=True)

