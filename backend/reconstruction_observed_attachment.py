"""Observed exterior attachment, without changing labels or fabric."""
import numpy as np
from scipy.spatial import cKDTree
from reconstruction_dense_contract import project
from build_continuity_candidates import inside_mask

def rebind_hair(old,observations,surface,max_native_pixels=16.,minimum_views=3):
    if not observations or any(o['role']!='train' for o in observations):
        raise ValueError('training_observations_required')
    old=np.asarray(old); xyz=np.asarray(surface['means'])
    metric=np.nanmedian(np.stack([np.where((z:=project(old,o['K'],o['F'])[1])>0,z/o['K'][0,0],np.nan) for o in observations]),axis=0)
    distance,index=cKDTree(xyz).query(old);support=np.zeros(len(old),int);observed=support.copy()
    for o in observations:
        uv,z=project(xyz[index],o['K'],o['F']);support+=(z>0)&inside_mask(o['hair'],uv)
        uv,z=project(old,o['K'],o['F']);observed+=(z>0)&inside_mask(o['hair'],uv)
    valid=(support>=minimum_views)&(observed>=minimum_views)&(distance<=max_native_pixels*metric)
    valid&=np.isfinite(metric)&(metric>0)&(np.asarray(surface['support'])[index]>=minimum_views)
    return np.flatnonzero(valid),index[valid],dict(candidates=int(valid.sum()),minimumViews=minimum_views,
        distanceNativePixelQuantiles=np.quantile(distance[valid]/metric[valid],[.1,.5,.9]).tolist() if valid.any() else [],
        totalOld=len(old),rule='bounded predicted exterior with original training hair pixels; unknown retained',
        independentDepthTruth=False)

def contact_pairs(neck,head,metric,coordinate,max_pixels=8.):
    if metric<=0:raise ValueError('positive_contact_pixel_metric')
    if not len(head) or not len(neck):return np.empty(0,int),np.empty(0,int)
    distance,index=cKDTree(head).query(neck)
    ids=np.flatnonzero((coordinate<=np.quantile(coordinate,.25))&(distance<=max_pixels*metric))
    return ids,index[ids]

def exterior_patch(old,observations,surface,parents,nearest,maximum_points=6000,neighbors=24,max_native_pixels=16.,minimum_views=3):
    """Select existing supported exterior samples, not clones of old shells.

    The original qualified parent set remains fixed. Rank-round sampling retains
    the first supported candidate for each parent before extending a patch.
    Predicted depth remains a hypothesis even when training masks agree.
    """
    if not observations or any(o['role']!='train' for o in observations):
        raise ValueError('training_observations_required')
    if neighbors<1 or maximum_points<len(parents):raise ValueError('patch_budget')
    old=np.asarray(old);parents=np.asarray(parents,int);nearest=np.asarray(nearest,int)
    xyz=np.asarray(surface['means']);tree=cKDTree(xyz)
    if not len(parents):return np.empty(0,int),np.empty(0,int),dict(points=0)
    metric=np.nanmedian(np.stack([np.where((z:=project(old[parents],o['K'],o['F'])[1])>0,z/o['K'][0,0],np.nan) for o in observations]),axis=0)
    distance,index=tree.query(old[parents],k=min(neighbors,len(xyz)))
    if distance.ndim==1:distance=distance[:,None];index=index[:,None]
    pool=np.unique(index);visible=np.zeros(len(pool),int)
    for o in observations:
        uv,z=project(xyz[pool],o['K'],o['F']);visible+=(z>0)&inside_mask(o['hair'],uv)
    ok=(visible>=minimum_views)&(np.asarray(surface['support'])[pool]>=minimum_views)
    lookup=np.zeros(len(xyz),bool);lookup[pool]=ok
    valid=lookup[index]&(distance<=max_native_pixels*metric[:,None])&np.isfinite(metric[:,None])&(metric[:,None]>0)
    chosen=[];seen=set()
    for rank in range(index.shape[1]):
        for row in range(len(parents)):
            i=int(index[row,rank])
            if valid[row,rank] and i not in seen and len(chosen)<maximum_points:
                chosen.append(i);seen.add(i)
    chosen=np.asarray(chosen,int)
    # Lineage is a nearest qualified original parent, not independent geometry.
    _,lineage=cKDTree(old[parents]).query(xyz[chosen])
    return chosen,parents[lineage],dict(points=len(chosen),retiredParents=len(parents),neighbors=neighbors,
        maximumPoints=maximum_points,minimumViews=minimum_views,nativeDistanceLimit=max_native_pixels,
        qualifiedNearestRetained=int(sum(int(i) in seen for i in nearest)),
        sourceIndicesUnique=len(np.unique(chosen))==len(chosen),sourceColors='original observed surface colours',
        geometryEvidence='cached multi-view predicted exterior; not independent depth truth',
        independentDepthTruth=False,selection='rank-round existing samples; no duplicate copies')
