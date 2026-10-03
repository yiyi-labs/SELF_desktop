"""Select inherited neck SH by actual frozen visibility, not point centers.

The color-channel derivative is an exact per-Gaussian compositing weight for
the selected pixels. Only an audit feature tensor receives gradients: this
module never creates an optimizer or changes model parameters. The caller
provides current full-scene states for short-window neck support, and may
provide head-only states from other observations for conservative face veto.
"""
from __future__ import annotations

import hashlib
import numpy as np
import torch


def _masks(frame):
    w,h=map(int,frame['fullSize'])
    if tuple(frame['rectangle'])!=(0,0,w,h) or frame.get('nativeScale')!=1:
        raise ValueError('neck_selection_requires_native_full_canvas')
    labels=frame['masks']
    required=('face_core','face_boundary','observed_body_skin','room_visible',
              'neck_cloth_visible','hair_visible','glasses_visible','unknown_or_occluded')
    if any(k not in labels for k in required):
        raise ValueError('neck_selection_requires_attached_observation_domains')
    if any(tuple(labels[k].shape)!=(h,w) for k in required):
        raise ValueError('neck_selection_mask_canvas_mismatch')
    from live_dense import physical_masks
    cpu={k:(v.detach().cpu().numpy() if isinstance(v,torch.Tensor) else np.asarray(v)).astype(bool)
         for k,v in labels.items()}
    neck=physical_masks(cpu)['neck'] & ~cpu['unknown_or_occluded']
    protected=cpu['face_core']|cpu['face_boundary']|cpu['hair_visible']|cpu['glasses_visible']
    # Do not let semantic overlap vote both for neck recovery and face editing.
    neck &= ~protected
    return neck,protected


def point_region_contributions(state,frame,neck,protected,*,unit_scale=1.,antialiased=False,rasterizer=None):
    """Return [neck, protected, all-visible] pixel-integrated contributions.

    Occlusion/sorting/footprint are those of the actual full-canvas renderer.
    We detach covariance (including neck's full Jacobian transport) rather
    than reconstructing it from export-only eigenvectors.
    """
    if rasterizer is None:
        from gsplat import rasterization as rasterizer
    w,h=map(int,frame['fullSize'])
    device=state.means.device
    if tuple(frame['rectangle'])!=(0,0,w,h) or frame.get('nativeScale')!=1:
        raise ValueError('neck_contribution_requires_full_canvas')
    if not np.isfinite(unit_scale) or unit_scale<=0:
        raise ValueError('neck_contribution_scale')
    if neck.shape!=(h,w) or protected.shape!=(h,w):
        raise ValueError('neck_region_shape')
    if not torch.allclose(frame['K'],frame['fullK'],atol=1e-5,rtol=0):
        raise ValueError('neck_contribution_intrinsics')
    C=frame['C']
    if C is None:
        raise ValueError('neck_contribution_camera_required')
    with torch.enable_grad():
        features=torch.zeros((len(state.means),3),device=device,dtype=state.means.dtype,requires_grad=True)
        image,_,_=rasterizer(state.means.detach(),None,None,state.opacity.detach(),features,
            C.detach()[None],frame['fullK'].detach()[None],w,h,covars=state.covariance().detach(),
            packed=True,sh_degree=None,render_mode='RGB',rasterize_mode='antialiased' if antialiased else 'classic',
            near_plane=.01*unit_scale,far_plane=1e10*unit_scale)
        masks=torch.stack((torch.as_tensor(neck,device=device),torch.as_tensor(protected,device=device),
                           torch.ones((h,w),device=device,dtype=torch.bool)),-1).to(features.dtype)
        score=(image[0]*masks).sum()
        contribution=torch.autograd.grad(score,features,only_inputs=True)[0].detach()
    if not torch.isfinite(contribution).all() or (contribution < -1e-6).any():
        raise ValueError('neck_invalid_compositing_contribution')
    return contribution.clamp_min(0)


def select_neck_sh_points(observations,portrait_count,surface_count,*,min_support=3,
                          min_neck_pixels=.25,min_neck_fraction=.95,protected_tolerance=1e-7,
                          antialiased=False,measure=point_region_contributions):
    """Consume a streaming set of explicit frozen observations.

    Each item has ``frame``, ``state``, ``unit_scale``, ``support`` and
    ``full_scene``. Support observations must be full scene and come from the
    recorded body window. Non-support observations can conservatively veto
    candidates using a head-only render. The portrait is the unchanged prefix
    of each state; only its old surface prefix is eligible, never hair/body.

    Selection is strict: at least three distinct neck views and no actual
    protected-pixel contribution in *any* supplied view. Tiny neck-only tails
    cannot qualify a point whose main footprint lies on some other surface.
    """
    if not 0<surface_count<=portrait_count or min_support<3:
        raise ValueError('neck_selection_counts_or_support')
    if min_neck_pixels<=0 or not 0<min_neck_fraction<=1 or protected_tolerance<0:
        raise ValueError('neck_selection_thresholds')
    support_count=torch.zeros(portrait_count,dtype=torch.int64)
    veto=torch.zeros(portrait_count,dtype=torch.bool)
    max_protected=torch.zeros(portrait_count,dtype=torch.float64)
    neck_evidence=torch.zeros(portrait_count,dtype=torch.float64)
    records=[]
    seen=set()
    support_names=[]
    for item in observations:
        frame,state=item['frame'],item['state']
        name=str(frame['name'])
        if name in seen:
            raise ValueError('neck_duplicate_observation:'+name)
        seen.add(name)
        support=bool(item['support'])
        if support and not item.get('full_scene',False):
            raise ValueError('neck_support_requires_full_scene')
        if len(state.means)<portrait_count:
            raise ValueError('neck_portrait_prefix_missing')
        neck,protected=_masks(frame)
        values=measure(state,frame,neck,protected,unit_scale=float(item['unit_scale']),antialiased=antialiased)
        if values.shape!=(len(state.means),3):
            raise ValueError('neck_contribution_shape')
        values=values[:portrait_count].detach().cpu().double()
        if not torch.isfinite(values).all() or (values<0).any():
            raise ValueError('neck_contribution_values')
        neck_q,protected_q,all_q=values.unbind(-1)
        if (neck_q>all_q+1e-4).any() or (protected_q>all_q+1e-4).any():
            raise ValueError('neck_contribution_not_conservative')
        veto|=protected_q>protected_tolerance
        max_protected=torch.maximum(max_protected,protected_q)
        qualifies=(neck_q>=min_neck_pixels)&(neck_q>=min_neck_fraction*all_q)
        if support:
            support_count+=qualifies.long()
            neck_evidence+=neck_q
            support_names.append(name)
        records.append({'imageName':name,'supportObservation':support,'fullScene':bool(item['full_scene']),
                        'neckPixels':int(neck.sum()),'protectedPixels':int(protected.sum()),
                        'qualifyingOldSurfacePoints':int(qualifies[:surface_count].sum()) if support else 0,
                        'protectedContributingOldSurfacePoints':int((protected_q[:surface_count]>protected_tolerance).sum())})
    if len(support_names)<min_support:
        raise ValueError('neck_insufficient_distinct_support_views')
    eligible=torch.arange(portrait_count)<surface_count
    selected=eligible&(support_count>=min_support)&~veto
    ids=torch.where(selected)[0].numpy().astype('<i8')
    receipt={'method':'frozen_full_canvas_compositing_colour_derivative','zeroParameterUpdates':True,
        'topologyChanged':False,'geometryChanged':False,'opacityChanged':False,
        'selectionParameters':dict(minSupport=min_support,minNeckPixels=min_neck_pixels,
                                  minNeckFraction=min_neck_fraction,protectedTolerance=protected_tolerance),
        'portraitCount':int(portrait_count),'oldSurfaceCount':int(surface_count),'selectedCount':int(selected.sum()),
        'selectedIdsSha256':hashlib.sha256(ids.tobytes()).hexdigest(),
        'supportImageNames':support_names,'protectionImageNames':[r['imageName'] for r in records],
        'rejectedProtectedAfterEnoughNeckSupport':int((eligible&(support_count>=min_support)&veto).sum()),
        'selectedMaxProtectedContribution':float(max_protected[selected].max()) if selected.any() else 0.,
        'selectedTotalNeckContribution':float(neck_evidence[selected].sum()),'observations':records,
        'depthEvidence':'actual current-model sorting and visibility; not independently measured neck depth',
        'scope':'only provided observations; motion and depth disagreement remain separate geometry checks'}
    return selected,receipt
