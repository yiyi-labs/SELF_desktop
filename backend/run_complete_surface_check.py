"""Validate the actually transported continuous field, before image recovery.
Consumes frozen shared XYZ solutions; never repeats matching or the solver.
"""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch
from scipy.spatial.transform import Rotation
from run_complete_geometry import collect_records
from reconstruction_evidence_stage import load_stage
from reconstruction_surface_evidence import project
from reconstruction_components_v3 import save_json
from reconstruction_detail_controlled import evaluate_face
from reconstruction_research_state import save_checkpoint

def stats(x):
    return {'count':len(x),'median':float(np.median(x)) if x else None,'p90':float(np.quantile(x,.9)) if x else None}

def run(manifest,measurements,old_tracks,geometry,out):
    out=Path(out);geometry=Path(geometry);start=time.perf_counter();data,plan,m,contract=load_stage(manifest,out)
    shutil.copyfile(__file__,out/'algorithm-source'/Path(__file__).name)
    shutil.copyfile(Path(__file__).with_name('run_complete_geometry.py'),out/'algorithm-source/run_complete_geometry.py')
    tracks,*_=collect_records(data,m,measurements,old_tracks);faces=m.portrait.faces.cpu().numpy()
    original=m.adjusted_frame;pose_map={}
    def adjusted(frame):
        f=original(frame)
        if frame['name'] in pose_map:
            a=pose_map[frame['name']];T=f['F'].clone();R=torch.as_tensor(Rotation.from_rotvec(a[:3]*np.deg2rad(1)/np.sqrt(3)).as_matrix(),device=T.device,dtype=T.dtype)
            T[:3,:3]=R@T[:3,:3];T[:3,3]+=torch.as_tensor(a[3:]*.0015/np.sqrt(3),device=T.device,dtype=T.dtype);f={**f,'F':T}
        return f
    m.adjusted_frame=adjusted
    extra_names=['frame_0028.png','frame_0042.png','frame_0021.png','frame_0036.png'];plan={**plan,'new_audit':[n for n in extra_names if n in data['local']]}
    results={};frozen={k:v.detach().clone() for k,v in m.state_dict().items()}
    for label in ['R0','fixed-F','bounded-F']:
        pose_map.clear();m.measured_surface_field.zero_()
        if label!='R0':
            z=np.load(geometry/(label+'-geometry.npz'));m.measured_surface_field.copy_(torch.as_tensor(z['displacement'],device='cuda'));pose_map.update({str(n):v for n,v in zip(z['poseNames'],z['poseDelta'])})
        disp=m.measured_surface_field.cpu().numpy();per_view={};groups={'source':[],'target':[],'third':[]};rows=[]
        for t in tracks:
            tri=faces[t['triangle']];local=(disp[tri]*t['bary'][:,None]).sum(0);errors=[]
            for j,o in enumerate(t['obs']):
                # This is the additive field ACTUALLY used by SharedSurfaceModel,
                # not the free XYZ transport used in the nonlinear measurement fit.
                x=o['R']@t['x0']+o['q']+local;F=o['F'].copy()
                if o['name'] in pose_map:
                    a=pose_map[o['name']];F[:3,:3]=Rotation.from_rotvec(a[:3]*np.deg2rad(1)/np.sqrt(3)).as_matrix()@F[:3,:3];F[:3,3]+=a[3:]*.0015/np.sqrt(3)
                uv,depth=project(x[None],F,data['K']);e=float(np.linalg.norm(uv[0]-o['uv']));kind='source' if j==0 else 'third' if j==len(t['obs'])-1 else 'target';groups[kind].append(e);per_view.setdefault(o['name'],[]).append(e);errors.append(e)
            rows.append({'track':t['id'],'errors':errors,'names':[o['name'] for o in t['obs']]})
        image=evaluate_face(m,data,plan,out/(label+'-images'))
        result={'reprojection':{k:stats(v) for k,v in groups.items()},'views':{k:stats(v) for k,v in per_view.items()},'images':image};results[label]=result;save_json(out/(label+'-tracks.json'),rows)
        save_checkpoint(out/(label+'.pt'),m,{}, {},stage='actual_continuous_surface_replay',step=0,contract=contract,extra={'poseDeltas':{k:v.tolist() for k,v in pose_map.items()},'poseFormula':'left rotation F; additive camera translation; fixed K/C/scale','roomMetadata':m.room.metadata,'bodySources':m.body_sources})
        print(label,json.dumps(result['reprojection']),flush=True)
    failures=[]
    for label in ['fixed-F','bounded-F']:
        for kind in ['source','target','third']:
            a=results['R0']['reprojection'][kind];b=results[label]['reprojection'][kind]
            if b['median']>2 or b['p90']>4:failures.append(label+':'+kind+':native_measurement_tolerance')
            if kind!='source' and (b['median']>a['median']+.5 or b['p90']>a['p90']+1):failures.append(label+':'+kind+':fusion_regression')
        for n,b in results[label]['images'].items():
            a=results['R0']['images'][n]
            if b['face']['fixedRgbL1']>a['face']['fixedRgbL1']+.002:failures.append(label+':image_regression:'+n)
    m.load_state_dict(frozen);pose_map.clear()
    save_checkpoint(out/'restored.pt',m,{}, {},stage='surface_replay_restored',step=0,contract=contract,extra={'roomMetadata':m.room.metadata,'bodySources':m.body_sources})
    save_json(out/'result.json',{'branches':results,'failures':failures,'geometryAccepted':not failures,'appearanceExecuted':False,'restoredExact':all(torch.equal(v,m.state_dict()[k]) for k,v in frozen.items()),'seconds':time.perf_counter()-start,'allocatedMiB':torch.cuda.max_memory_allocated()/1048576,'reservedMiB':torch.cuda.max_memory_reserved()/1048576,'published':False,'note':'Geometry replay; old pose config incorrectly said temporal prior; solver actually used magnitude prior only. No temporal claim. 21/36 reserved only if local observation exists.'})
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ['manifest','measurements','old-tracks','geometry','out']:p.add_argument('--'+k,required=True)
    a=p.parse_args();run(a.manifest,a.measurements,a.old_tracks,a.geometry,a.out)
