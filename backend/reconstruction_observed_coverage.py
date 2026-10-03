"""Finite train-only projected-footprint budgeting for observed room surfaces.

The sparse atlas is a selection proxy, NOT accumulated alpha, truth geometry,
or a replacement for full-frame native rasterization. Existing candidate
geometry and opacity are never enlarged to obtain coverage.
"""
import numpy as np
from scipy import sparse
from scipy.spatial.transform import Rotation


def covariance_projection(means, quats, scales, C, K, eps=.3):
    R=Rotation.from_quat(np.asarray(quats)[:,[1,2,3,0]]).as_matrix()
    cov=(R*np.asarray(scales)[:,None,:]**2)@R.transpose(0,2,1)
    p=np.asarray(means)@C[:3,:3].T+C[:3,3]
    z=p[:,2];safe=np.where(z>1e-8,z,1.)
    J=np.zeros((len(p),2,3));J[:,0,0]=K[0,0]/safe;J[:,1,1]=K[1,1]/safe
    J[:,0,2]=-K[0,0]*p[:,0]/safe**2;J[:,1,2]=-K[1,1]*p[:,1]/safe**2
    camera_cov=C[:3,:3]@cov@C[:3,:3].T
    cov2=J@camera_cov@J.transpose(0,2,1)+np.eye(2)*eps
    uv=np.c_[K[0,0]*p[:,0]/safe+K[0,2],K[1,1]*p[:,1]/safe+K[1,2]]
    return uv,z,cov2


def footprint_atlas(arrays, observations, *, cell=8, alpha_floor=.05, max_radius=96):
    """Potential kernel mass at native-lattice samples in valid observations.

    Includes off-canvas centres whose footprint enters the canvas. Optional
    point_visible is an externally supplied prediction-consistency mask; it is
    not counted as independent first-surface truth. Large/invalid footprints
    are recorded, not clamped or changed in the candidate.
    """
    count=len(arrays['means']);all_rows=[];all_cols=[];all_values=[];cell_weights=[];meta=[];offset=0
    for obs in observations:
        if obs['role']!='train':raise ValueError('coverage_requires_training_observations')
        mask=np.asarray(obs['mask'],bool);h,w=mask.shape
        yy,xx=np.mgrid[cell//2:h:cell,cell//2:w:cell];gh,gw=yy.shape
        valid=mask[yy,xx];mapping=np.full((gh,gw),-1,np.int64);mapping[valid]=np.arange(int(valid.sum()))+offset
        uv,z,cov=covariance_projection(arrays['means'],arrays['quats'],arrays['scales'],np.asarray(obs['C']),np.asarray(obs['K']))
        eig=np.linalg.eigvalsh(cov);cut=-2*np.log(alpha_floor/np.maximum(arrays['opacity'],alpha_floor))
        radius=np.sqrt(eig[:,-1].clip(0)*cut)
        visible=np.asarray(obs.get('point_visible',np.ones(count,bool)),bool)
        eligible=(z>0)&np.isfinite(uv).all(1)&np.isfinite(cov).all((1,2))&(radius<=max_radius)&(eig[:,0]>0)&visible
        eligible&=(uv[:,0]+radius>=0)&(uv[:,0]-radius<w)&(uv[:,1]+radius>=0)&(uv[:,1]-radius<h)
        ids=np.flatnonzero(eligible);iv=np.linalg.inv(cov[ids]);center=np.floor((uv[ids]-cell/2)/cell).astype(int)
        reach=int(np.ceil(radius[ids].max()/cell))+1 if len(ids) else 0
        for dy in range(-reach,reach+1):
            for dx in range(-reach,reach+1):
                x=center[:,0]+dx;y=center[:,1]+dy
                inside=(x>=0)&(x<gw)&(y>=0)&(y<gh)
                ii=np.flatnonzero(inside)
                if not len(ii):continue
                col=mapping[y[ii],x[ii]];delta=np.c_[x[ii]*cell+cell/2,y[ii]*cell+cell/2]-uv[ids[ii]]
                power=np.einsum('ni,nij,nj->n',delta,iv[ii],delta)
                value=arrays['opacity'][ids[ii]]*np.exp(-.5*power)
                good=(col>=0)&(value>=alpha_floor)
                if good.any():
                    all_rows.append(ids[ii[good]]);all_cols.append(col[good]);all_values.append(value[good].astype(np.float32))
        cells=int(valid.sum());cell_weights.extend([1/max(1,cells)]*cells)
        meta.append(dict(name=obs['name'],offset=offset,cells=cells,projectedCandidates=len(ids),unscoredTooWide=int((visible&(z>0)&(radius>max_radius)).sum())))
        offset+=cells
    if not all_rows or not offset:raise ValueError('no_supported_footprint_atlas')
    atlas=sparse.csr_matrix((np.concatenate(all_values),(np.concatenate(all_rows),np.concatenate(all_cols))),shape=(count,offset))
    atlas.sum_duplicates()
    return atlas,np.asarray(cell_weights,np.float32),meta


def balanced_select(atlas, weights, uids, budget, *, batch=64, target_mass=1.5):
    """Diminishing-return coverage, finite exact point budget, no RGB selection.

    Kernel mass is additive potential coverage. Actual compositing/occlusion
    must be checked afterwards; no alpha-equivalence claim is made.
    """
    n=atlas.shape[0]
    if budget<=0 or budget>n or len(np.unique(uids))!=n:raise ValueError('invalid_budget_or_identity')
    selected=[];used=np.zeros(n,bool);mass=np.zeros(atlas.shape[1],np.float32)
    # Stable UID tie handling, independent of pool row order.
    uid_order=np.argsort(uids);steps=[]
    while len(selected)<budget:
        marginal=weights*np.exp(-mass/target_mass)
        scores=np.asarray(atlas@marginal).ravel();scores[used]=-np.inf
        order=uid_order[np.argsort(-scores[uid_order],kind='stable')]
        take=order[:min(batch,budget-len(selected))]
        used[take]=True;selected.extend(take.tolist());mass+=np.asarray(atlas[take].sum(0)).ravel()
        if len(steps)<2 or len(selected)==budget:steps.append(dict(points=len(selected),potentialSupport=float((mass>0).mean()),meanMass=float(mass.mean())))
    return np.asarray(selected,int),steps


def atlas_summary(atlas, selected, metadata):
    mass=np.asarray(atlas[selected].sum(0)).ravel();rows={}
    for view in metadata:
        part=mass[view['offset']:view['offset']+view['cells']]
        rows[view['name']]=dict(potentialSupport=float((part>0).mean()) if len(part) else None,potentialMassMean=float(part.mean()) if len(part) else None,overlapMassAbove15=float((part>=1.5).mean()) if len(part) else None)
    return rows


def protected_exchange(atlas, weights, uids, original, proposed, *, max_swaps=5000):
    """Improve allocation without losing any original supported atlas sample.

    Preserve at least min(original potential mass, .75) at every original
    sample. This guards a sampling proxy only, not actual rendered alpha.
    Fixed point count; positive marginal utility required for every swap.
    """
    original=np.asarray(original,int);proposed=np.asarray(proposed,int)
    if len(original)!=len(proposed) or len(np.unique(original))!=len(original):raise ValueError('exchange_budget_mismatch')
    used=np.zeros(atlas.shape[0],bool);used[original]=True
    mass=np.asarray(atlas[original].sum(0)).ravel();floor=np.minimum(mass,.75)
    desired=np.zeros_like(used);desired[proposed]=True
    incoming=proposed[~used[proposed]];outgoing=original[~desired[original]]
    scores=np.asarray(atlas@(weights*np.exp(-mass/1.5))).ravel()
    outgoing=outgoing[np.lexsort((uids[outgoing],scores[outgoing]))]
    swaps=[];blocked=0
    outgoing_rows={int(i):atlas.getrow(int(i)) for i in outgoing}
    for iteration,new in enumerate(incoming):
        if len(swaps)>=max_swaps:break
        a=atlas.getrow(int(new));mass[a.indices]+=a.data
        accepted=False
        # Finite proposal search, deterministic rotation avoids repeatedly
        # testing only the first essential points. No global parameter search.
        start=(iteration*37)%max(1,len(outgoing))
        trials=outgoing[(np.arange(min(128,len(outgoing)))+start)%max(1,len(outgoing))]
        for old in trials:
            if not used[old]:continue
            b=outgoing_rows[int(old)];after=mass[b.indices]-b.data
            if np.any(after+2e-6<floor[b.indices]):continue
            inds=np.union1d(a.indices,b.indices);before=mass[inds].copy();delta=np.zeros(len(inds),np.float32)
            delta[np.searchsorted(inds,a.indices)]-=a.data
            # before means before this tentative insertion.
            before+=delta;trial=mass[inds].copy();trial[np.searchsorted(inds,b.indices)]-=b.data
            gain=float((weights[inds]*(np.exp(-before/1.5)-np.exp(-trial/1.5))).sum())
            if gain<=1e-10:continue
            mass[b.indices]-=b.data;used[old]=False;used[new]=True
            swaps.append((int(old),int(new),gain));accepted=True;break
        if not accepted:mass[a.indices]-=a.data;blocked+=1
    selected=np.flatnonzero(used);selected=selected[np.argsort(uids[selected])]
    actual=np.asarray(atlas[selected].sum(0)).ravel()
    if len(selected)!=len(original) or np.any(actual+1e-5<floor):raise ValueError('protected_footprint_floor_broken')
    return selected,dict(swaps=swaps,blocked=int(blocked),floorMass=.75,originalSupportedSamples=int((floor>0).sum()),
        lostOriginalSamples=int(((floor>0)&(actual<=0)).sum()),minimumFloorMargin=float((actual-floor).min()),
        limits='No loss of original supported atlas samples; not a guarantee of actual compositing or true geometry.')


def balanced_region_mean(error, mask, tile=96, minimum_pixels=64):
    """Every valid pixel participates; a quarter weight protects weaker tiles.

    Fixed image-space tiles, not gradient-selected features. Masks never
    multiply RGB before a neighbourhood loss.
    """
    import torch
    import torch.nn.functional as F
    m=mask.to(error.dtype);h,w=m.shape;pad=(0,(-w)%tile,0,(-h)%tile)
    count=F.avg_pool2d(F.pad(m[None,None],pad),tile,tile)*tile**2
    sums=F.avg_pool2d(F.pad((error*m)[None,None],pad),tile,tile)*tile**2
    valid=count>=minimum_pixels
    global_mean=(error*m).sum()/m.sum().clamp_min(1)
    local=(sums/count.clamp_min(1))[valid].mean() if valid.any() else global_mean
    return .75*global_mean+.25*local
