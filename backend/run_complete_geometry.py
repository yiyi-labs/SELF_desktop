"""Same measured tracks: fixed-F control versus bounded shared XYZ/pose solve.
The last observation per track remains a third-view check. Data information,
not regularized rank, supplies the anisotropic surface-fusion confidence.
"""
import argparse,json,time,shutil
from pathlib import Path
import numpy as np,torch
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from scipy.sparse import lil_matrix,coo_matrix,eye,vstack,kron,block_diag
from scipy.sparse.linalg import lsqr
from reconstruction_evidence_stage import load_stage
from reconstruction_surface_evidence import project
from reconstruction_patch_correspondence import intersect
from reconstruction_shared_surface import triangle_frames
from reconstruction_portrait_pipeline import make_frame
from reconstruction_detail_controlled import evaluate_face
from reconstruction_research_state import save_checkpoint
from reconstruction_components_v3 import save_json


def collect_records(data,m,measurements,old_tracks):
    p=m.portrait;faces=p.faces.cpu().numpy();base=p.surface_residual.detach().cpu().numpy();K=data["K"];frames={}
    def frame(n):
        if n not in frames:
            f=m.adjusted_frame(make_frame(data,n,crop=False));frames[n]=(f["mesh"].cpu().numpy()+base,f["F"].detach().cpu().numpy())
        return frames[n]
    previous=json.loads(Path(old_tracks).read_text())['tracks'];raw=[{'id':t['id'],'region':'face','observations':t['observations'],'measurementSource':'cached_native_ECC'} for t in previous]
    newcount=0;duplicates=0
    for file in sorted(Path(measurements).glob('window-*/tracks.json')):
        for t in json.loads(file.read_text())['tracks']:
            if t['region']!='face':continue
            commondup=False
            for old in raw:
                a={o['name']:o['uv'] for o in old['observations']};hits=[np.linalg.norm(np.array(o['uv'])-a[o['name']])<1.5 for o in t['observations'] if o['name'] in a]
                if sum(hits)>=2:commondup=True;break
            if commondup:duplicates+=1;continue
            raw.append({**t,'measurementSource':'cotracker3_native_verified'});newcount+=1
    records=[]
    for t in raw:
        n=t['observations'][0]['name'];mesh,F=frame(n);hit=intersect(mesh,faces,F,K,t['observations'][0]['uv'])
        if hit is None:continue
        tid,bary=hit;tri=faces[tid];x0=(mesh[tri]*bary[:,None]).sum(0);B0=triangle_frames(torch.tensor(mesh[tri][None])).numpy()[0];metric=float((F[:3,:3]@x0+F[:3,3])[2]/K[0,0]);obs=[]
        for o in t['observations']:
            mt,Ft=frame(o['name']);Bt=triangle_frames(torch.tensor(mt[tri][None])).numpy()[0];R=Bt@B0.T;q=(mt[tri]*bary[:,None]).sum(0)-R@x0;obs.append({**o,'R':R,'q':q,'F':Ft})
        records.append({**t,'triangle':tid,'bary':bary,'x0':x0,'metric':metric,'B0':B0,'obs':obs})
    return records,newcount,duplicates,len(previous)


def run(manifest,measurements,old_tracks,out):
    out=Path(out);start=time.perf_counter();data,plan,m,contract=load_stage(manifest,out);p=m.portrait;faces=p.faces.cpu().numpy();base=p.surface_residual.detach().cpu().numpy();ref=p.reference_mesh.cpu().numpy()+base;K=data['K'];frames={}
    def frame(n):
        if n not in frames:
            f=m.adjusted_frame(make_frame(data,n,crop=False));frames[n]=(f['mesh'].cpu().numpy()+base,f['F'].detach().cpu().numpy())
        return frames[n]
    records,newcount,duplicates,cached_count=collect_records(data,m,measurements,old_tracks)
    names=sorted({o['name'] for t in records for o in t['obs']});reference=names[0];eligible=[];spatial={}
    for n in names:
        pixels=np.array([o['uv'] for t in records for o in t['obs'][:-1] if o['name']==n]);ys,xs=np.where(data['labels'][n]['face_core']);center=np.array([np.median(xs),np.median(ys)]);sectors=set(tuple((uv>center).astype(int)) for uv in pixels);spatial[n]={'measurements':len(pixels),'sectors':len(sectors)}
        if n!=reference and len(pixels)>=8 and len(sectors)>=3:eligible.append(n)
    save_json(out/'config.json',{'newTracks':newcount,'cachedTracks':cached_count,'crossSourceDuplicatesMerged':duplicates,'totalTracks':len(records),'poseEligible':eligible,'poseSupport':spatial,'referenceFixed':reference,'fixed':'K, world C, identity, scale, expression','poseBounds':'1 degree and .0015 local units per frame; magnitude prior; no temporal prior; no scale','controlAndCandidateMaxNfev':80,'nativeCanvas':[1080,1920],'published':False})
    checkpoint_extra={'roomMetadata':m.room.metadata,'bodySources':m.body_sources};save_checkpoint(out/'initial.pt',m,{}, {},stage='shared_pose_xyz',step=0,contract=contract,extra=checkpoint_extra);evaluate_face(m,data,plan,out/'R0-images')
    results={};solutions={};N=len(records)
    for label,pose_names in [('fixed-F',[]),('bounded-F',eligible)]:
        index={n:i for i,n in enumerate(pose_names)};P=len(index);fit=[(i,o) for i,t in enumerate(records) for o in t['obs'][:-1]];dimension=3*N+6*P
        def camera(o,v):
            F=o['F'].copy()
            if o['name'] in index:
                a=v[3*N+index[o['name']]*6:3*N+(index[o['name']]+1)*6];R=Rotation.from_rotvec(a[:3]*np.deg2rad(1)/np.sqrt(3)).as_matrix();F[:3,:3]=R@F[:3,:3];F[:3,3]+=a[3:]*.0015/np.sqrt(3)
            return F
        def error(v,i,o):
            t=records[i];x=t['x0']+v[i*3:i*3+3]*t['metric'];uv,z=project((o['R']@x+o['q'])[None],camera(o,v),K);return (uv[0]-o['uv'])/o['sigma']
        def residual(v):
            a=np.concatenate([error(v,i,o) for i,o in fit]);return np.r_[a,v[:3*N]/3,v[3*N:]*.6]
        jac=lil_matrix((2*len(fit)+dimension,dimension),dtype=int)
        for j,(i,o) in enumerate(fit):
            jac[2*j:2*j+2,3*i:3*i+3]=1
            if o['name'] in index:jac[2*j:2*j+2,3*N+6*index[o['name']]:3*N+6*index[o['name']]+6]=1
        jac[2*len(fit):,:]=eye(dimension);limits=np.r_[np.full(3*N,6.),np.ones(6*P)];sol=least_squares(residual,np.zeros(dimension),jac_sparsity=jac.tocsr(),bounds=(-limits,limits),loss='soft_l1',max_nfev=80,x_scale='jac',ftol=1e-6);rows=[];informations=[]
        for i,t in enumerate(records):
            errors=[float(np.linalg.norm(error(sol.x,i,o))*o['sigma']) for o in t['obs']];J=np.stack([(np.concatenate([error(sol.x+np.eye(1,dimension,i*3+k)[0]*.001,i,o) for o in t['obs'][:-1]])-np.concatenate([error(sol.x-np.eye(1,dimension,i*3+k)[0]*.001,i,o) for o in t['obs'][:-1]]))/.002 for k in range(3)],1);eig,U=np.linalg.eigh(J.T@J);sqrt=U@np.diag(np.sqrt(np.maximum(eig,0))/max(np.sqrt(eig[-1]),1e-9))@U.T;informations.append(sqrt);rows.append({'id':t['id'],'source':t['measurementSource'],'names':[o['name'] for o in t['obs']],'errors':errors,'dataEigenvalues':eig.tolist(),'normalizedXYZ':sol.x[3*i:3*i+3].tolist()})
        # Fuse XYZ using anisotropic data information in a shared canonical field.
        rr=[];cc=[];vv=[];rhs=[];blocks=[]
        for i,t in enumerate(records):
            Bref=triangle_frames(torch.tensor(ref[faces[t['triangle']]][None])).numpy()[0];T=Bref@t['B0'].T;delta=T@(sol.x[i*3:i*3+3]*t['metric']);info=T@informations[i]@T.T;blocks.append(info);rhs.append(delta)
            for vertex,b in zip(faces[t['triangle']],t['bary']):rr.append(i);cc.append(vertex);vv.append(b)
        A=coo_matrix((vv,(rr,cc)),shape=(N,len(ref))).tocsr();edges=p.edges.cpu().numpy();allowed=set(cc)
        for _ in range(2):allowed.update(edges[np.isin(edges,list(allowed)).any(1)].reshape(-1).tolist())
        allowed=np.array(sorted(allowed));L=coo_matrix((np.tile([1.,-1.],len(edges)),(np.repeat(np.arange(len(edges)),2),edges.reshape(-1))),shape=(len(edges),len(ref))).tocsr();W=block_diag(blocks);M=vstack([W@kron(A[:,allowed],eye(3)),kron(L[:,allowed],eye(3))*.15,eye(3*len(allowed))*.08]).tocsr();target=np.r_[W@np.array(rhs).reshape(-1),np.zeros(3*(len(edges)+len(allowed)))];disp=np.zeros_like(ref);disp[allowed]=lsqr(M,target,atol=1e-9,btol=1e-9,iter_lim=200)[0].reshape(-1,3)
        pose_delta={n:sol.x[3*N+i*6:3*N+(i+1)*6].tolist() for n,i in index.items()};np.savez_compressed(out/(label+'-geometry.npz'),displacement=disp,xyz=sol.x[:3*N].reshape(-1,3),poseNames=np.array(pose_names),poseDelta=sol.x[3*N:].reshape(-1,6));save_json(out/(label+'-tracks.json'),rows)
        fiterr=[e for r in rows for e in r['errors'][:-1]];third=[r['errors'][-1] for r in rows];result={'fitMedian':float(np.median(fiterr)),'fitP90':float(np.quantile(fiterr,.9)),'thirdMedian':float(np.median(third)),'thirdP90':float(np.quantile(third,.9)),'nfev':sol.nfev,'poseFrames':len(index),'surfaceUpdatedVertices':int((np.linalg.norm(disp,axis=1)>1e-9).sum())};results[label]=result;solutions[label]=(disp,pose_delta);print(label,json.dumps(result),flush=True)
    # A weak spatial/third-view gate cannot be bypassed by a lower RGB average.
    a,b=results['fixed-F'],results['bounded-F'];accepted=bool(eligible and b['fitMedian']<=2 and b['fitP90']<=4 and b['thirdMedian']<=a['thirdMedian']+.5 and b['thirdP90']<=a['thirdP90']+1)
    save_json(out/'result.json',{'comparisons':results,'freeXYZTolerancePassed':accepted,'surfaceFusionStillNeedsReprojectionCheck':True,'appearanceExecuted':False,'seconds':time.perf_counter()-start,'published':False,'reason':'continuous field and fixed regressions remain required before appearance'});save_checkpoint(out/'restored.pt',m,{}, {},stage='shared_pose_xyz_restored',step=0,contract=contract,extra=checkpoint_extra)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--measurements',required=True);p.add_argument('--old-tracks',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.manifest,a.measurements,a.old_tracks,a.out)
