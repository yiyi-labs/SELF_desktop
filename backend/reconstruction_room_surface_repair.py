"""Local replacement by actual multi-view surface samples, not old covariance.
Surface evidence is conditional on recorded static cameras. All proposal
colours are sampled from original valid room observations, never generated.
"""
from pathlib import Path
import hashlib,json
import cv2,numpy as np,torch
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from reconstruction_mvs_contract import read_mvs_cloud
from reconstruction_dense_contract import project
from reconstruction_portrait_model import GaussianState,joined_state,quaternion_matrix
from reconstruction_components_v3 import FreeComponent,pick,sha
from reconstruction_portrait_pipeline import draw
from reconstruction_surface_patch import weights


def surface_domain(points,parent_means,parent_quats,parent_scales,maximum_mahalanobis=3.):
    """Old footprint proposes a finite search domain; it is not surface truth."""
    R=Rotation.from_quat(np.asarray(parent_quats)[:,[1,2,3,0]]).as_matrix()
    d=np.asarray(points)[:,None]-np.asarray(parent_means)[None]
    local=np.einsum('nki,kij->nkj',d,R)/np.asarray(parent_scales)[None]
    distance=np.linalg.norm(local,axis=-1)
    return distance.min(1)<=maximum_mahalanobis,distance.argmin(1)


def projected_surface_domain(points,views,names,cameras,K,parents):
    """Finite observed footprint proposal; never a depth/visibility proof.
    A wrong parent centre must not bound the real replacement surface in 3D.
    This linear projection proxy only selects MVS evidence, not final culling.
    """
    means,quats,scales=parents;R=Rotation.from_quat(np.asarray(quats)[:,[1,2,3,0]]).as_matrix()
    covariance=(R*np.asarray(scales)[:,None,:])@(R*np.asarray(scales)[:,None,:]).transpose(0,2,1)
    distances=[];supported=[]
    for vi,n in enumerate(names):
        C=cameras[n];uv,z=project(points,K,C);cam=np.asarray(means)@C[:3,:3].T+C[:3,3];center,_=project(means,K,C)
        J=np.zeros((len(means),2,3));safe=np.maximum(cam[:,2],1e-8)
        J[:,0,0]=K[0,0]/safe;J[:,1,1]=K[1,1]/safe;J[:,0,2]=-K[0,0]*cam[:,0]/safe**2;J[:,1,2]=-K[1,1]*cam[:,1]/safe**2
        covcam=C[:3,:3]@covariance@C[:3,:3].T;conic=np.linalg.inv(J@covcam@J.transpose(0,2,1)+np.eye(2)[None]*.3)
        d=uv[:,None]-center[None];mahal=np.einsum('nki,kij,nkj->nk',d,conic,d)
        provenance=np.array([vi in v for v in views]);valid=provenance&(z>0)&np.isfinite(uv).all(1)
        distances.append(np.where(valid[:,None],mahal,1e12));supported.append(valid[:,None]&(mahal<=9)&(cam[:,2]>0)[None])
    count=np.stack(supported).sum(0);stack=np.stack(distances);valid=stack<1e11;distance=np.where(valid,stack,0).sum(0)/np.maximum(valid.sum(0),1);distance[count<3]=1e12
    lineage=distance.argmin(1);domain=count.max(1)>=3
    return domain,lineage


def validate_mvs_roles(data,plan,names):
    forbidden=set(plan['development']+plan['audit']);allowed=set(data['train'])|set(plan['train'])
    if any(n not in allowed or n in forbidden or n not in data['worlds'] or data['local'][n]['role']!='train' for n in names):raise ValueError('MVS_training_camera_missing')


def validate_imported_native_intrinsics(folder,contract,expectedK):
    """Verify the actual pinned PINHOLE file, not just a legacy JSON label.
    OpenMVS 2.4.0 removes COLMAP's half pixel principal point on import.
    A legacy integer-centred export must not silently enter new experiments.
    """
    rows=[r.split() for r in (Path(folder)/'colmap/sparse/cameras.txt').read_text().splitlines() if r.strip() and not r.startswith('#')]
    if len(rows)!=1 or len(rows[0])!=8 or rows[0][1]!='PINHOLE':raise ValueError('pinned_single_pinhole_contract_required')
    row=rows[0];fx,fy,cx,cy=map(float,row[4:]);K=np.array([[fx,0,cx-.5],[0,fy,cy-.5],[0,0,1.]])
    if not np.allclose(K,expectedK,rtol=0,atol=1e-6):raise ValueError('actual_OpenMVS_native_K_mismatch')
    meta=contract['contract']
    if meta.get('pixelCenter')!='COLMAP_half_export_OpenMVS_integer_import':raise ValueError('explicit_MVS_pixel_center_required')
    np.testing.assert_allclose(meta['nativeK'],expectedK,rtol=0,atol=1e-6)
    if int(row[2])!=meta['width'] or int(row[3])!=meta['height']:raise ValueError('actual_MVS_canvas_mismatch')
    return K


def verified_surface_samples(folder,data,plan,parents,budget=8000,proposal_domain='world-ellipsoid'):
    folder=Path(folder);contract=json.loads((folder/'contract.json').read_text());names=contract['names']
    if contract['sourceHash']!=data['sourceHash']:raise ValueError('MVS_source_changed')
    validate_mvs_roles(data,plan,names)
    validate_imported_native_intrinsics(folder,contract,data['K'])
    for n in names:np.testing.assert_allclose(contract['contract']['cameras'][n],data['worlds'][n],rtol=0,atol=1e-6)
    cloud=read_mvs_cloud(folder/'dense.ply');xyz=cloud['xyz'];normal=cloud['normal'];norm=np.linalg.norm(normal,axis=1)
    if proposal_domain=='world-ellipsoid':domain,lineage=surface_domain(xyz,*parents)
    elif proposal_domain=='projected-surface':domain,lineage=projected_surface_domain(xyz,cloud['views'],names,data['worlds'],data['K'],parents)
    else:raise ValueError('unknown_surface_proposal_domain')
    finite=np.isfinite(xyz).all(1)&np.isfinite(normal).all(1)&(norm>.8)&domain
    colour_sum=np.zeros((len(xyz),3));colour_sq=np.zeros_like(colour_sum);support=np.zeros(len(xyz),int);source=np.full(len(xyz),'',dtype='U64');source_uv=np.zeros((len(xyz),2))
    visible=np.zeros((len(names),len(xyz)),bool)
    for vi,n in enumerate(names):
        provenance=np.array([vi in views for views in cloud['views']])
        uv,z=project(xyz,data['K'],data['worlds'][n]);xy=np.rint(np.nan_to_num(uv)).astype(int);h,w=data['rgb'][n].shape[:2]
        inside=finite&provenance&(z>0)&(xy[:,0]>1)&(xy[:,0]<w-2)&(xy[:,1]>1)&(xy[:,1]<h-2)
        lab=data['labels'][n];room=lab['room_visible']&~lab['unknown_or_occluded']
        safe=cv2.erode(room.astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)
        clipped=xy.clip([0,0],[w-1,h-1]);inside&=safe[clipped[:,1],clipped[:,0]]
        ids=np.flatnonzero(inside);colours=np.array([np.median(data['rgb'][n][y-1:y+2,x-1:x+2],axis=(0,1)) for x,y in xy[ids]])
        if not len(ids):continue
        first=support[ids]==0;source[ids[first]]=n;source_uv[ids[first]]=uv[ids[first]]
        support[ids]+=1;colour_sum[ids]+=colours;colour_sq[ids]+=colours*colours;visible[vi,ids]=True
    accepted=np.flatnonzero(support>=3)
    if len(accepted)<32:raise ValueError('insufficient_actual_multiview_surface:'+str(dict(raw=len(xyz),domain=int(domain.sum()),finite=int(finite.sum()),accepted=len(accepted),maxSupport=int(support.max()))))
    # Preserve the measured surface's neighbourhood spacing before any budget
    # thinning. Colour variation is recorded, never used to discard highlights.
    points=xyz[accepted];nn=cKDTree(points).query(points,k=min(5,len(points)))[0][:,1:]
    spacing=np.median(nn,1);normal=normal[accepted]/norm[accepted,None]
    axis=np.tile([1.,0,0],(len(points),1));axis[abs(normal[:,0])>.8]=[0,1,0]
    u=np.cross(axis,normal);u/=np.linalg.norm(u,axis=1,keepdims=True);v=np.cross(normal,u)
    reference=names[len(names)//2];_,z=project(points,data['K'],data['worlds'][reference]);pixel=np.maximum(z/data['K'][0,0],1e-8)
    tangent=np.clip(spacing*.7,pixel*1.25,pixel*6.)
    # Independent components follow the real MVS normal. This normal is not
    # inferred from the suspect old kernel or SH colour.
    q=Rotation.from_matrix(np.stack((u,v,normal),-1)).as_quat()[:,[3,0,1,2]]
    scales=np.c_[tangent,tangent,np.minimum(tangent*.25,pixel*.75)]
    mean=colour_sum[accepted]/support[accepted,None];variance=np.maximum(colour_sq[accepted]/support[accepted,None]-mean*mean,0)
    code=sha(folder/'dense.ply');uid=np.array([int.from_bytes(hashlib.sha256(f'MVS:{code}:{i}'.encode()).digest()[:8],'little')&((1<<63)-1) for i in accepted],np.int64)
    if len(accepted)>budget:
        order=np.argsort(uid);chosen=order[np.rint(np.linspace(0,len(order)-1,budget)).astype(int)]
        # Local covariance is recomputed after thinning; cannot assume original
        # spacing still gives equal coverage. Normals/identities stay unchanged.
        points=points[chosen];q=q[chosen];normal=normal[chosen];pixel=pixel[chosen]
        spacing=np.median(cKDTree(points).query(points,k=min(5,len(points)))[0][:,1:],1)
        tangent=np.clip(spacing*.7,pixel*1.25,pixel*6.);scales=np.c_[tangent,tangent,np.minimum(tangent*.25,pixel*.75)]
        accepted=accepted[chosen];mean=mean[chosen];variance=variance[chosen];uid=uid[chosen]
    sh=np.zeros((len(accepted),4,3),np.float32);sh[:,0]=(mean-.5)/.28209479177387814
    return dict(means=xyz[accepted],quats=q,scales=scales,opacity=np.full(len(accepted),.6),sh=sh,
        parts=np.zeros(len(accepted),np.int64),uid=uid,support=support[accepted],source_index=accepted,
        source_image=source[accepted],source_uv=source_uv[accepted],normal=normal,lineage=lineage[accepted],colour_variance=variance,
        source_hash=np.array(data['sourceHash'])),dict(names=names,cloudHash=code,rawPoints=len(xyz),finiteDomainPoints=int(finite.sum()),
        acceptedBeforeBudget=int((support>=3).sum()),selected=len(accepted),minViews=3,
        proposalDomain=proposal_domain,proposalIsNotVisibilityTruth=True,conditionalGeometry='actual OpenMVS fused surface under existing static cameras; not independent sensor truth',
        sourceColours='original native valid-room 3x3 median, mean across actual fused supporting views',
        budget=budget,sourceIndicesUnique=True,trainingRoleContract='prepared training identities plus stage training, excluding unchanged dev/audit',scalePixels=np.quantile(scales[:,:2]/pixel[:,None],[.1,.5,.9]).tolist())


class RoomSurfaceStage(torch.nn.Module):
    def __init__(self,base,parent_ids,state,uids,support):
        super().__init__();self.baseline=base;self.scale=base.scale
        self.register_buffer('parent_ids',torch.as_tensor(parent_ids,device='cuda',dtype=torch.long))
        kept=torch.where(base.keep_room)[0];head=int(base.keep_head.sum());rows=head+torch.where(torch.isin(kept,self.parent_ids))[0]
        self.register_buffer('full_ids',rows)
        self.patch=FreeComponent(state,torch.as_tensor(uids,device='cuda'),torch.as_tensor(support,device='cuda',dtype=torch.float32),'world',float(state.scales.min(-1).values.median())*.5)
    def state(self,f):
        s=self.baseline.state(f);keep=torch.ones(len(s.means),device='cuda',dtype=torch.bool);keep[self.full_ids]=False
        return joined_state(pick(s,keep),self.patch.state())
    def render(self,f):
        f=self.baseline.baseline.adjusted_frame(f);h,w=f['rgb'].shape[:2]
        return draw(self.state(f),f['C'],f['K'],w,h,unit_scale=self.scale)

