"""Reference-relative FLAME joint-1 transport for a separate hair component.

This is a low-frequency skull-rigid approximation, not full FLAME skin LBS.
The skull pivot uses shared shape and ONE fixed reference expression. Jaw,
eyes and per-frame expression do not drag the hair. Root motion remains in
F_root and must not be multiplied into this relative transform a second time.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import numpy as np
import torch

from flame_open_model import axis_angle_matrix
from portrait_model import (GaussianState,quat_product,
    rotate_sh1,rotation_quaternion)


def joint1_root_neutral_transform(pivot,neck):
    """Exact FLAME joint-1 rigid transform with root removed: R, J - R J."""
    R=axis_angle_matrix(neck)
    result=torch.eye(4,dtype=R.dtype,device=R.device).expand(len(R),4,4).clone()
    result[:,:3,:3]=R
    result[:,:3,3]=pivot-(R@pivot[...,None])[...,0]
    return result


@dataclass
class HairMotionBinding:
    names: tuple
    reference: str
    transforms: torch.Tensor
    metadata: dict

    def matrix(self,name,like):
        try:index=self.names.index(name)
        except ValueError as error:raise ValueError('hair_motion_missing_imageName:'+name) from error
        return self.transforms[index].to(device=like.device,dtype=like.dtype)

    def camera(self,name,F_root):
        """Canonical reference hair -> this source camera; root applied once."""
        return F_root@self.matrix(name,F_root)

    def deform(self,name,state,surface_count):
        if name==self.reference or self.metadata['status']=='explicit_legacy_root_local':return state
        return transport_hair(state,self.matrix(name,state.means),surface_count)

    def arrays(self):
        return {'imageNames':np.asarray(self.names),'referenceName':np.asarray(self.reference),
                'referenceToFrameRootLocal':self.transforms.cpu().numpy()}

    def receipt(self):return dict(self.metadata)


def build_hair_motion(model,fit_state,reference,*,checkpoint_sha256):
    names=tuple(map(str,fit_state['names']))
    if not names or len(names)!=len(set(names)) or reference not in names:
        raise ValueError('hair_motion_image_identity')
    if not isinstance(checkpoint_sha256,str) or len(checkpoint_sha256)!=64:
        raise ValueError('hair_motion_checkpoint_identity_required')
    if fit_state['modelSha256']!=model.model_sha256:raise ValueError('hair_motion_model_identity')
    if tuple(model.parents)!=(-1,0,1,1,1):raise ValueError('hair_motion_parent_chain')
    shape=torch.as_tensor(fit_state['shape']).detach().cpu().double()
    expressions=torch.as_tensor(fit_state['expression']).detach().cpu().double()
    poses=torch.as_tensor(fit_state['pose']).detach().cpu().double()
    if (shape.shape!=(1,model.shape_count) or expressions.shape!=(len(names),model.expression_count)
        or poses.shape!=(len(names),5,3) or not all(torch.isfinite(v).all() for v in (shape,expressions,poses))):
        raise ValueError('hair_motion_parameter_shape_or_values')
    at=names.index(reference);reference_expression=expressions[at:at+1]
    template=model.template.detach().cpu().double();directions=model.directions.detach().cpu().double()
    shaped=template+torch.einsum('vci,bi->bvc',directions,torch.cat((shape,reference_expression),1))[0]
    pivot=torch.einsum('v,vc->c',model.joint_regressor[1].detach().cpu().double(),shaped)
    G=joint1_root_neutral_transform(pivot,poses[:,1])
    # Same fixed pivot in every view. D_ref is set exactly to identity after
    # composition, not merely close to it after a numerical matrix inverse.
    D=G@torch.linalg.inv(G[at]);D[at]=torch.eye(4,dtype=D.dtype)
    rotations=D[:,:3,:3]
    if not torch.allclose(rotations.transpose(-1,-2)@rotations,torch.eye(3,dtype=D.dtype),atol=1e-10,rtol=0):
        raise ValueError('hair_motion_non_rigid_transform')
    identity=hashlib.sha256(json.dumps({'names':names,'reference':reference,
        'checkpointSha256':checkpoint_sha256,'modelSha256':model.model_sha256},sort_keys=True).encode()+
        D.numpy().tobytes()).hexdigest()
    meta={'schemaVersion':1,'status':'reference_relative_joint1_transport',
        'sourceHash':fit_state.get('sourceHash'),'checkpointSha256':checkpoint_sha256,
        'modelSha256':model.model_sha256,'referenceName':reference,'transformSha256':identity,
        'jointIndex':1,'rootAppliedHere':False,'referenceTransformExactIdentity':True,
        'pivotPolicy':'shared_shape_plus_fixed_reference_expression_joint_regressor',
        'pivotRootLocal':pivot.tolist(),'referenceExpression':reference_expression[0].tolist(),
        'perFrameExpressionApplied':False,'jawApplied':False,'identityScaleChanged':False,
        'cameraMeaning':'F_hair = F_root @ D_reference_to_frame_root_local',
        'approximation':'low_frequency_skull_rigid_not_full_flame_skin_LBS',
        'newHairDepthInferenceRequired':True,'oldRootLocalDepthCacheCompatible':False}
    return HairMotionBinding(names,reference,D,meta)


def legacy_hair_motion(names,reference):
    """An explicit old-asset adapter, never evidence of new hair transport."""
    names=tuple(map(str,names))
    if not names or len(set(names))!=len(names) or reference not in names:raise ValueError('legacy_hair_identity')
    return HairMotionBinding(names,reference,torch.eye(4,dtype=torch.float64).repeat(len(names),1,1),
        {'schemaVersion':1,'status':'explicit_legacy_root_local','referenceName':reference,
         'newHairDepthInferenceRequired':False,'motionCorrected':False,
         'reason':'historical_preparation_without_recorded_joint_parameters'})


def load_prepared_fit(prepared,metadata,geometry,model=None):
    """Read only a recorded checkpoint; never infer identity from a loose file."""
    prepared=Path(prepared);entry=metadata.get('localFitState')
    if entry is None:
        audit=prepared/'automatic-prepare-audit.json'
        if audit.is_file():
            report=json.loads(audit.read_text())
            entry=report.get('localFit',{}).get('stateCheckpoint')
            if entry and report.get('sourceHash')!=metadata['sourceHash']:
                raise ValueError('hair_fit_audit_source_mismatch')
    if entry is None:return None
    path=(prepared/entry['file']).resolve()
    if not path.is_relative_to(prepared.resolve()):raise ValueError('hair_fit_path_escape')
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if actual!=entry['sha256']:raise ValueError('hair_fit_checkpoint_changed')
    # This hash-bound private checkpoint contains numpy RNG state from our own
    # fitter; it is not an untrusted downloaded pickle.
    state=torch.load(path,map_location='cpu',weights_only=False)
    names=list(map(str,geometry['names']))
    if (state.get('kind')!='capture-local-landmark-fit-state' or state['names']!=names
        or state['roles']!=list(map(str,geometry['roles'])) or state['sourceHash']!=metadata['sourceHash']
        or state['modelSha256']!=metadata['modelHash']):raise ValueError('hair_fit_identity_mismatch')
    np.testing.assert_allclose(np.asarray(state['K']),geometry['K'],atol=1e-4,rtol=1e-7)
    from flame_open_model import FlameOpen,MODEL
    if model is None:model=FlameOpen(state['shape'].shape[1],state['expression'].shape[1],model_path=MODEL)
    with torch.no_grad():
        for i,name in enumerate(names):
            pose=state['pose'][i:i+1].clone();pose[:,0]=0
            mesh,_=model(state['shape'],state['expression'][i:i+1],pose)
            shaped=model.template+torch.einsum('vci,bi->bvc',model.directions,
                torch.cat((state['shape'],state['expression'][i:i+1]),1))[0]
            J0=torch.einsum('v,vc->c',model.joint_regressor[0],shaped).double()
            R=axis_angle_matrix(state['pose'][i:i+1,0].double())[0]
            F=torch.eye(4,dtype=torch.float64);F[:3,:3]=R
            F[:3,3]=state['translation'][i].double()+J0-R@J0
            np.testing.assert_allclose(mesh[0].numpy(),geometry['meshes'][i],atol=2e-6,rtol=0)
            np.testing.assert_allclose(F.numpy(),geometry['F'][i],atol=2e-6,rtol=0)
    return dict(state=state,sha256=actual,path=str(path),model=model)


def prepared_hair_motion(prepared,metadata,geometry,reference,model=None,fit=None):
    fit=fit if fit is not None else load_prepared_fit(prepared,metadata,geometry,model)
    if fit is None:return legacy_hair_motion(geometry['names'],reference)
    binding=build_hair_motion(fit['model'],fit['state'],reference,checkpoint_sha256=fit['sha256'])
    binding.metadata['fitStatePath']=fit['path']
    return binding


def write_motion_contract(binding,output):
    """Hash-bound reference transforms survive source-video cleanup."""
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    arrays=output/'hair-motion.npz';receipt=output/'hair-motion.json'
    if arrays.exists() or receipt.exists():raise FileExistsError('hair_motion_receipt_exists')
    np.savez_compressed(arrays,**binding.arrays())
    value={**binding.receipt(),'arrayPath':str(arrays.resolve()),
           'arraySha256':hashlib.sha256(arrays.read_bytes()).hexdigest()}
    receipt.write_text(json.dumps(value,indent=2),encoding='utf-8')
    return dict(path=str(receipt.resolve()),sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
                **binding.receipt())


def verify_motion_receipt(receipt,binding):
    expected=binding.receipt()
    if not receipt:
        if expected['status']=='explicit_legacy_root_local':return
        raise ValueError('hair_depth_missing_motion_receipt_reinfer_required')
    path=Path(receipt['path'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=receipt['sha256']:
        raise ValueError('hair_motion_receipt_changed')
    saved=json.loads(path.read_text());array_path=Path(saved['arrayPath'])
    if hashlib.sha256(array_path.read_bytes()).hexdigest()!=saved['arraySha256']:
        raise ValueError('hair_motion_arrays_changed')
    for key in ('status','sourceHash','checkpointSha256','modelSha256','referenceName'):
        if saved.get(key)!=expected.get(key) or receipt.get(key)!=expected.get(key):
            raise ValueError('hair_motion_contract_mismatch:'+key)
    arrays=dict(np.load(array_path,allow_pickle=False))
    if list(map(str,arrays['imageNames']))!=list(binding.names) or str(arrays['referenceName'])!=binding.reference:
        raise ValueError('hair_motion_array_identity')
    stored=arrays['referenceToFrameRootLocal']
    if stored.dtype!=np.float64 or stored.shape!=tuple(binding.transforms.shape):
        raise ValueError('hair_motion_array_type_or_shape')
    if expected['status']!='explicit_legacy_root_local':
        identity=hashlib.sha256(json.dumps({'names':binding.names,'reference':binding.reference,
            'checkpointSha256':expected['checkpointSha256'],'modelSha256':expected['modelSha256']},sort_keys=True).encode()+
            stored.tobytes()).hexdigest()
        if saved['transformSha256']!=identity or receipt['transformSha256']!=identity:
            raise ValueError('hair_motion_stored_transform_digest')
    # CPU reduction order changes the joint pivot by ~1e-18 on real data.
    # Check geometry to a sub-nanometre tolerance, then use the immutable
    # inference matrices exactly. This is not permission to alter a camera.
    np.testing.assert_allclose(stored,binding.transforms.numpy(),atol=1e-12,rtol=0)
    if not np.array_equal(stored[binding.names.index(binding.reference)],np.eye(4)):
        raise ValueError('hair_motion_reference_not_exact_identity')
    binding.transforms=torch.from_numpy(stored.copy())
    if 'transformSha256' in saved:binding.metadata['transformSha256']=saved['transformSha256']


class _HairCovariantState(GaussianState):
    def __init__(self,original,transform,surface_count,means,quats,sh):
        super().__init__(means,quats,original.scales,original.opacity,sh,original.parts)
        self._original=original;self._rotation=transform[:3,:3];self._surface_count=surface_count

    def covariance(self):
        sigma=self._original.covariance();n=self._surface_count;R=self._rotation
        return torch.cat((sigma[:n],R@sigma[n:]@R.T),0)


def transport_hair(state,D,surface_count):
    """Move only the hair tail, including full covariance and SH orientation."""
    n=int(surface_count)
    if n<0 or n>len(state.means) or D.shape!=(4,4) or not torch.isfinite(D).all():
        raise ValueError('hair_transport_contract')
    if len(state.parts)!=len(state.means) or (state.parts[n:]!=2).any() or (state.parts[:n]==2).any():
        raise ValueError('hair_transport_component_prefix')
    if n==len(state.means) or torch.equal(D,torch.eye(4,device=D.device,dtype=D.dtype)):return state
    R,t=D[:3,:3],D[:3,3]
    if not torch.allclose(R.T@R,torch.eye(3,dtype=D.dtype,device=D.device),atol=2e-5,rtol=0):
        raise ValueError('hair_transport_rotation_invalid')
    means=torch.cat((state.means[:n],state.means[n:]@R.T+t))
    quats=torch.cat((state.quats[:n],quat_product(rotation_quaternion(R),state.quats[n:])))
    sh=torch.cat((state.sh[:n],rotate_sh1(state.sh[n:],R)))
    return _HairCovariantState(state,D,n,means,quats,sh)
