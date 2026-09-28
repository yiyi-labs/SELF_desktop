"""One full-scene rasterization and evidence-based conservative front conflicts."""
import cv2
import numpy as np
import torch
from reconstruction_components_v3 import save_json,authorize_joint_training
from reconstruction_portrait_local_v3 import head_state
from reconstruction_portrait_model import joined_state
from reconstruction_portrait_pipeline import make_frame,draw

def compose_state(face,attachments,body,room,data,frame):
    if frame['C'] is None:raise ValueError('no_world_camera_no_composition')
    head=head_state(face,attachments,frame['mesh']).to_world(frame['C'],frame['F'],data['scale'])
    states=[head]
    if body is not None:states.append(body.state())
    states.append(room.state())
    return joined_state(*states)

def draw_composed(face,attachments,body,room,data,frame):
    state=compose_state(face,attachments,body,room,data,frame)
    h,w=frame['rgb'].shape[:2]
    return draw(state,frame['C'],frame['K'],w,h,unit_scale=data['scale'])

def classify_front_conflicts(front_votes,support,buffer_votes,verified_votes):
    # Query views are not allowed to contradict three independent static
    # supports. Unknown/real accessory boundary votes preserve the point.
    return ((np.asarray(front_votes)>=3)&(np.asarray(support)<3)&
            (np.asarray(buffer_votes)==0)&(np.asarray(verified_votes)>=3))


def footprint_scores(state,C,K,width,height,safe,head_depth,buffer):
    """Actual jointly sorted footprint contribution, including off-ROI centres."""
    from reconstruction_joint_visibility import render_components,visible_point_scores
    with torch.enable_grad():
        rendered=render_components(state.means.detach(),state.quats.detach(),state.scales.detach(),
            state.opacity.detach(),state.sh.detach(),state.parts,C,K,width,height,point_probe=True)
        contribution=visible_point_scores(rendered,safe.float(),retain_graph=True)
        depth_sum=visible_point_scores(rendered,safe.float()*head_depth,retain_graph=True)
        uncertain=visible_point_scores(rendered,buffer.float())
    return contribution,depth_sum/contribution.clamp_min(1e-8),uncertain


@torch.no_grad()
def audit_front_conflicts(face,attachments,room,data,out,verified_world_names=(),body=None):
    state=room.state();xyz=state.means.cpu().numpy();scales=state.scales.cpu().numpy()
    count=len(xyz);front=np.zeros(count,np.int32);buffer=np.zeros(count,np.int32);trusted=np.zeros(count,np.int32)
    overlap=np.zeros(count,np.int32);off_center=np.zeros(count,np.int32)
    for name in data['train']:
        if name not in data['worlds']:continue
        f=make_frame(data,name,crop=False,half=True);h,w=f['rgb'].shape[:2]
        head=head_state(face,attachments,f['mesh']).to_world(f['C'],f['F'],data['scale'])
        rendered=draw(head,f['C'],f['K'],w,h,unit_scale=data['scale'])
        alpha=rendered['alpha']
        expected=rendered['depth']/alpha.clamp_min(1e-8)
        C=f['C'].cpu().numpy();K=f['K'].cpu().numpy()
        cam=xyz@C[:3,:3].T+C[:3,3];z=cam[:,2];uv=cam@K.T
        uv=uv[:,:2]/np.maximum(z[:,None],1e-8);u,v=np.rint(uv).astype(int).T
        inside=(z>0)&(u>=0)&(v>=0)&(u<w)&(v<h);u=u.clip(0,w-1);v=v.clip(0,h-1)
        m=f['masks'];uncertain=m['unknown_or_occluded']|m['hair_visible']|m['glasses_visible']|m['face_boundary']
        uncertain=cv2.dilate(uncertain.cpu().numpy().astype('uint8'),np.ones((5,5),np.uint8))>0
        uncertain=torch.from_numpy(uncertain).to(alpha.device)
        safe=m['face_core'] & ~uncertain & (alpha>.95)
        combined=compose_state(face,attachments,body,room,data,f)
        score,face_depth,uncertain_score=footprint_scores(combined,f['C'],f['K'],w,h,safe,expected,uncertain)
        # Static room is the last block by the explicit component contract.
        score=score[-count:].cpu().numpy();face_depth=face_depth[-count:].cpu().numpy()
        uncertain_score=uncertain_score[-count:].cpu().numpy()
        overlaps=score>1.0  # at least one full-opacity-equivalent pixel
        centered=inside & safe.cpu().numpy()[v,u]
        overlap+=overlaps;off_center+=overlaps & ~centered
        far=(z+3*np.max(scales,1))/data['scale']
        isfront=overlaps & (z>0) & (far+.003<face_depth)
        front+=isfront;buffer+=uncertain_score>.1
        if name in verified_world_names:trusted+=isfront
    eligible=classify_front_conflicts(front,room.support.cpu().numpy(),buffer,trusted)
    np.savez_compressed(out/'D-front-evidence.npz',point_id=np.arange(count),front_votes=front,
        buffer_votes=buffer,verified_votes=trusted,static_support=room.support.cpu().numpy(),eligible=eligible,
        footprint_overlap_votes=overlap,overlap_without_center_votes=off_center)
    report={'scenePoints':count,'frontInThreeResearchViews':int((front>=3).sum()),
        'actualFootprintOverlapPoints':int((overlap>0).sum()),'overlapMissedByCenterTest':int((off_center>0).sum()),
        'supportedStaticPoints':int((room.support>=3).sum()),'bufferProtectedPoints':int((buffer>0).sum()),
        'verifiedCameraCount':len(verified_world_names),'eligibleForConservativeSuppression':int(eligible.sum()),
        'actualPruned':0,'actualOpacityChanged':0,'status':'diagnostic_only_no_E1_accepted_cameras',
        'method':'shared_sorted_per_point_adjoint_weights_and_contribution_weighted_head_depth',
        'limits':'head expected depth is a prior, not a measured z-buffer; conservative radius rejects uncertain crossings; no deletion without E1'}
    save_json(out/'D-front-evidence.json',report);return report


def require_joint(stages,source_hash):
    return authorize_joint_training(stages,source_hash)
