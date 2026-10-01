"""Reusable cross-window surface evidence. Research-only, standard 3DGS output.
A cloud is conditional on the recorded cameras, never independent depth truth.
No production, transport or publisher imports.
"""
import hashlib
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation


def contract_compatible(a,b):
    for k in ('sourceHash','cameraFrame','restoredCompleteCheckpointHash'):
        if not a.get(k) or a[k]!=b.get(k):raise ValueError('surface_contract_changed:'+k)
    np.testing.assert_allclose(a['fullK'],b['fullK'],atol=1e-6,rtol=0)
    for n in set(a['names'])&set(b['names']):
        np.testing.assert_allclose(a['contract']['cameras'][n],b['contract']['cameras'][n],atol=1e-6,rtol=0)
    return True


def consensus_status(x,normals,pixels,window,*,distance_pixels=2.5,normal_degrees=30):
    """Cross-window agreement, conflict, unknown. No forced cloud alignment.
    Close samples with opposing normals are compared unsigned: imported normal
    orientation is not consistently signed. Unknown never becomes empty space.
    """
    x=np.asarray(x,float);normals=np.asarray(normals,float);pixels=np.asarray(pixels,float);window=np.asarray(window,int)
    if not(len(x)==len(normals)==len(pixels)==len(window)) or np.any(pixels<=0):raise ValueError('invalid_surface_arrays')
    agreement=np.zeros(len(x),int);conflict=np.zeros(len(x),int);partners=np.full(len(x),-1,int)
    cosine=np.cos(np.radians(normal_degrees))
    for w in np.unique(window):
        ids=np.flatnonzero(window==w);other=np.flatnonzero(window!=w)
        if not len(other):continue
        distance,nearest=cKDTree(x[other]).query(x[ids]);near=other[nearest]
        spatial=distance<=distance_pixels*np.maximum(pixels[ids],pixels[near])
        normal=np.abs((normals[ids]*normals[near]).sum(-1))>=cosine
        agreement[ids]=spatial&normal;conflict[ids]=spatial&~normal;partners[ids[spatial]]=near[spatial]
    return dict(agreement=agreement,conflict=conflict,partner=partners,unknown=(agreement==0)&(conflict==0))


def representative_samples(x,normals,pixels,quality,uids,*,budget,voxel_pixels=1.2):
    """Spatial dedup with evidence-ranked representatives, no position averaging.
    The point retains its actual MVS XYZ, normal, UID and source lineage.
    """
    if budget<1 or len(np.unique(uids))!=len(uids):raise ValueError('surface_budget_or_identity')
    pitch=max(float(np.median(pixels))*voxel_pixels,1e-10)
    cells=np.floor(np.asarray(x)/pitch).astype(np.int64);bins={};kept=[]
    order=np.lexsort((uids,-np.asarray(quality)))
    for i in order:
        key=tuple(cells[i]);existing=bins.get(key,[])
        # Different normal sheets in one voxel remain different physical layers.
        if any(abs(float(normals[i]@normals[j]))>.94 for j in existing):continue
        bins.setdefault(key,[]).append(int(i));kept.append(int(i))
    selected=np.array(kept,int)
    if len(selected)>budget:
        # Fair spatial strata; no winner-takes-all highest-texture crop.
        sorted_ids=selected[np.lexsort((uids[selected],cells[selected,2],cells[selected,1],cells[selected,0]))]
        selected=sorted_ids[np.floor(np.arange(budget)*len(sorted_ids)/budget).astype(int)]
    return selected,dict(input=len(x),deduplicated=len(kept),selected=len(selected),budget=budget,pitch=pitch,positionsAveraged=False)


def surface_gaussians(x,normal,pixels,rgb,*,tangent_min=.8,tangent_max=3.):
    x=np.asarray(x);normal=np.asarray(normal);normal=normal/np.linalg.norm(normal,axis=1,keepdims=True)
    if len(x)<2:raise ValueError('surface_neighbours_required')
    spacing=np.median(cKDTree(x).query(x,k=min(5,len(x)))[0][:,1:],axis=1)
    axis=np.tile([1.,0,0],(len(x),1));axis[abs(normal[:,0])>.8]=[0,1,0]
    u=np.cross(axis,normal);u/=np.linalg.norm(u,axis=1,keepdims=True);v=np.cross(normal,u)
    quat=Rotation.from_matrix(np.stack((u,v,normal),-1)).as_quat()[:,[3,0,1,2]]
    tangent=np.clip(spacing*.7,pixels*tangent_min,pixels*tangent_max)
    scale=np.c_[tangent,tangent,np.minimum(tangent*.25,pixels*.6)]
    sh=np.zeros((len(x),4,3),np.float32);sh[:,0]=(rgb-.5)/.28209479177387814
    return dict(means=x,quats=quat,scales=scale,opacity=np.full(len(x),.6),sh=sh,parts=np.full(len(x),2,np.int64))


def covered_retirement(total,covered,*,minimum_pixels=2.,ratio=.92,minimum_views=3):
    """Actual per-splat alpha*T responsibility, not centre distance.
    Any significant observed view without replacement coverage blocks retirement.
    Coverage is conditional on the rendered proposal; never surface truth.
    """
    a=np.asarray(total,float);b=np.asarray(covered,float)
    if a.shape!=b.shape or a.ndim!=2 or np.any(b>a+1e-3) or np.any(b<0):raise ValueError('invalid_contribution_contract')
    relevant=a>=minimum_pixels
    fraction=np.divide(b,a,out=np.ones_like(a),where=a>0)
    accepted=(relevant.sum(0)>=minimum_views)&np.all(~relevant|(fraction>=ratio),axis=0)
    return accepted,fraction


def new_uid(digest,index):
    return int.from_bytes(hashlib.sha256(f'CONSENSUS:{digest}:{index}'.encode()).digest()[:8],'little')&((1<<63)-1)