"""Bounded CPU diagnostics from shared, measured native-image tracks.

No preparation or appearance parameter is mutated.  A track has one 3D offset
in a transported triangle basis, not one 3D variable per image pair.  Third
observations and reserved physical tracks never enter the respective solves.
"""
from dataclasses import dataclass, asdict
import numpy as np
from scipy.optimize import least_squares
from reconstruction_face_pose_reliability import project, pose_delta


@dataclass(frozen=True)
class TrackConstraintConfig:
    minimum_pose_tracks: int = 10
    rotation_bound_degrees: float = .75
    translation_bound_native_pixels: float = 1.5
    pose_regularization: float = .3
    robust_native_pixels: float = 2.
    surface_bound_relative_face_extent: float = .008
    surface_regularization: float = .3
    minimum_data_singular: float = .15
    maximum_evaluations: int = 60


def unique_physical_tracks(rows,tolerance_native_pixels=.25):
    """SIFT orientations at the same three pixels are one measurement.

    Selection uses coordinates/source IDs only, never geometry residuals or
    development RGB. Distinct observations farther than tolerance are kept.
    """
    result=[];duplicates=[]
    for row in sorted(rows,key=lambda r:int(r['sourceKeypoint'])):
        xy=np.asarray(row['measured'],float)
        found=next((prior for prior in result if np.max(np.linalg.norm(
            xy-np.asarray(prior['measured'],float),axis=1))<=tolerance_native_pixels),None)
        if found is None:result.append(row)
        else:duplicates.append({'sourceKeypoint':int(row['sourceKeypoint']),
            'representativeSourceKeypoint':int(found['sourceKeypoint'])})
    return result,duplicates


def triangle_basis(vertices):
    v=np.asarray(vertices,dtype=np.float64)
    x=v[1]-v[0];x/=np.linalg.norm(x)
    z=np.cross(x,v[2]-v[0]);z/=np.linalg.norm(z)
    y=np.cross(z,x)
    return np.stack([x,y,z],axis=1)


def finite_jacobian(function,x,epsilon=1e-5):
    x=np.asarray(x,dtype=np.float64)
    return np.stack([(function(x+np.eye(len(x))[i]*epsilon)-
        function(x-np.eye(len(x))[i]*epsilon))/(2*epsilon) for i in range(len(x))],axis=1)


def texture_pose_candidate(points,measured,F,K,fit_mask,*,fixed=False,config=TrackConstraintConfig()):
    points=np.asarray(points);measured=np.asarray(measured);fit=np.asarray(fit_mask,bool)
    old,_=project(points,F,K)
    if fixed:return np.asarray(F).copy(),{'status':'fixed_reference'}
    if fit.sum()<config.minimum_pose_tracks:
        return np.asarray(F).copy(),{'status':'insufficient_fitting_tracks','fittingTracks':int(fit.sum())}
    centered=measured[fit]-measured[fit].mean(0)
    eigen=np.linalg.eigvalsh(centered.T@centered/len(centered))
    if eigen[0]<25 or eigen[0]/eigen[-1]<.025:
        return np.asarray(F).copy(),{'status':'insufficient_image_distribution','eigen':eigen.tolist()}
    center=points[fit].mean(0)
    _,depth=project(points,F,K)
    ru=np.radians(config.rotation_bound_degrees)/np.sqrt(3.)
    tu=np.median(depth[fit])/np.mean([K[0,0],K[1,1]])*config.translation_bound_native_pixels/np.sqrt(3.)
    def data(delta):
        uv,_=project(points,pose_delta(F,center,delta,ru,tu),K)
        return (uv[fit]-measured[fit]).ravel()
    def residual(delta):return np.r_[data(delta),config.pose_regularization*delta]
    solved=least_squares(residual,np.zeros(6),bounds=(-1,1),loss='huber',
        f_scale=config.robust_native_pixels,max_nfev=config.maximum_evaluations)
    result=pose_delta(F,center,solved.x,ru,tu)
    new,_=project(points,result,K)
    return result,{'status':'bounded_texture_pose_candidate','config':asdict(config),
        'fittingTracks':int(fit.sum()),'reservedTracks':int((~fit).sum()),
        'deltaNormalized':solved.x.tolist(),'dataJacobianSingular':np.linalg.svd(finite_jacobian(data,solved.x),compute_uv=False).tolist(),
        'oldErrors':np.linalg.norm(old-measured,axis=1).tolist(),'newErrors':np.linalg.norm(new-measured,axis=1).tolist(),
        'rotationDeltaDegrees':float(np.linalg.norm(solved.x[:3])*ru*180/np.pi),
        'translationDeltaModelUnits':float(np.linalg.norm(solved.x[3:])*tu),
        'appearanceUsed':False,'acceptedForTraining':False}


def shared_surface_candidate(points,bases,measured,Fs,K,face_extent,*,config=TrackConstraintConfig()):
    """Fit source+target, reserve third; data-only SVD excludes regularization."""
    points=np.asarray(points);bases=np.asarray(bases);measured=np.asarray(measured)
    if points.shape!=(3,3) or bases.shape!=(3,3,3) or measured.shape!=(3,2):
        raise ValueError('shared_surface_requires_three_observations')
    bound=float(face_extent)*config.surface_bound_relative_face_extent
    if not np.isfinite(bound) or bound<=0:raise ValueError('shared_surface_invalid_extent')
    def positions(delta):return points+np.einsum('vij,j->vi',bases,delta*bound)
    def projections(delta):return np.stack([project(p[None],F,K)[0][0] for p,F in zip(positions(delta),Fs)])
    def data(delta):return (projections(delta)[:2]-measured[:2]).ravel()
    # The identifiable subspace is computed from image measurements alone.
    _,s,vt=np.linalg.svd(finite_jacobian(data,np.zeros(3)),full_matrices=False)
    strong=s>=config.minimum_data_singular
    active=vt[strong].T
    def residual(z):
        delta=active@z
        return np.r_[data(delta),config.surface_regularization*delta]
    if not strong.any():
        delta=np.zeros(3);status='all_depth_modes_unobservable'
    else:
        # sqrt(rank) gives an Euclidean offset bound, independent of mode basis.
        zbound=1/np.sqrt(int(strong.sum()))
        solved=least_squares(residual,np.zeros(int(strong.sum())),bounds=(-zbound,zbound),
            loss='huber',f_scale=config.robust_native_pixels,max_nfev=config.maximum_evaluations)
        delta=active@solved.x;status='shared_surface_candidate_requires_third_view'
    before=np.linalg.norm(projections(np.zeros(3))-measured,axis=1)
    after=np.linalg.norm(projections(delta)-measured,axis=1)
    return positions(delta),{'status':status,'config':asdict(config),'offsetBasisNormalized':delta.tolist(),
        'offsetModelUnits':(delta*bound).tolist(),'boundModelUnits':bound,
        'dataJacobianSingular':s.tolist(),'observableModes':int(strong.sum()),
        'oldErrors':before.tolist(),'newErrors':after.tolist(),
        'thirdObservationUsedInSolve':False,'oneVariablePerPhysicalTrack':True,
        'priorWeakModesRetained':True,'acceptedForTraining':False}
