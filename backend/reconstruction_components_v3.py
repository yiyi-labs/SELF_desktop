"""Isolated v3 component identities. No worker, publisher, or protocol imports."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib,json
import numpy as np
import torch
import torch.nn.functional as fn
from reconstruction_portrait_model import GaussianState

PARTS = ('static_scene','face_skin','hair','accessory','neck_shoulder_cloth')
VERSION = 'reconstruction-v3-isolated-0.1'

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def save_json(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

def pick(state,index):
    return GaussianState(**{k:getattr(state,k)[index] for k in GaussianState.__dataclass_fields__})

class FreeComponent(torch.nn.Module):
    """A single explicit component, with bounded displacement from measured seeds.

    Coordinates never silently switch: hair/accessory=head-local; room/cloth=
    world-reference. The latter cloth is an UNACCEPTED motion hypothesis.
    """
    def __init__(self,state,source_ids,support,coordinate_frame,max_offset):
        super().__init__()
        if not len(state.means):raise ValueError('empty_component_requires_explicit_absence_not_dummy_point')
        if state.parts.unique().numel()!=1:raise ValueError('mixed_component_forbidden')
        self.coordinate_frame=coordinate_frame
        for key,value in dict(base=state.means,parts=state.parts,source_ids=source_ids,
            support=support,initial_scales=state.scales).items():
            self.register_buffer(key,torch.as_tensor(value,device=state.means.device).detach().clone())
        self.register_buffer('max_offset',torch.as_tensor(max_offset,device=state.means.device,dtype=state.means.dtype))
        self.offset=torch.nn.Parameter(torch.zeros_like(state.means))
        self.log_scales=torch.nn.Parameter(state.scales.log().detach().clone())
        self.quats=torch.nn.Parameter(state.quats.detach().clone())
        self.opacity=torch.nn.Parameter(torch.logit(state.opacity.detach().clamp(.001,.999)))
        self.sh=torch.nn.Parameter(state.sh.detach().clone())
    def state(self):
        means=self.base+torch.tanh(self.offset)*self.max_offset
        return GaussianState(means,fn.normalize(self.quats,dim=-1),self.log_scales.exp(),self.opacity.sigmoid(),self.sh,self.parts)
    def regularizer(self):
        # Prevent an unsupported sparse component from expanding into a shell.
        excess=(self.log_scales-self.initial_scales.log()-np.log(1.6)).clamp_min(0)
        return .002*excess.square().mean()+.0001*self.offset.square().mean()+.0002*self.sh[:,1:].square().mean()

def exact_state_hash(module):
    h=hashlib.sha256()
    for name,t in sorted(module.state_dict().items()):
        h.update(name.encode());h.update(t.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()

@dataclass(frozen=True)
class StageStatus:
    evidence: str
    passed: bool
    source_hash: str

def authorize_joint_training(stages,source_hash):
    required=('face','hair','accessory','neck_cloth','static_scene','world_camera')
    missing=[key for key in required if key not in stages or not stages[key].passed or stages[key].source_hash!=source_hash]
    if missing:raise ValueError('joint_stage_blocked:'+','.join(missing))
    return True

def export_identity(path,asset,arrays,*,source_hash,reference,editable_count):
    """Full-length int provenance, no float IDs or coordinate nearest-neighbour joins."""
    n=len(arrays['point_id'])
    for key,value in arrays.items():
        if len(value)!=n:raise ValueError('point_field_length_mismatch:'+key)
    if not np.array_equal(arrays['point_id'],np.arange(n)):raise ValueError('source_order_not_identity')
    if arrays['component'].dtype.kind not in 'iu':raise ValueError('component_id_must_be_integer')
    if not np.all(arrays['component'][:editable_count]==1):raise ValueError('editable_prefix_not_face')
    np.savez_compressed(path,**arrays,asset_sha256=np.asarray(sha(asset)),source_sha256=np.asarray(source_hash))
    manifest={'schemaVersion':1,'researchOnly':True,'engine':VERSION,'assetSha256':sha(asset),
        'sourceSha256':source_hash,'reference':reference,'pointCount':n,'editableSplats':editable_count,
        'indexSemantics':'exact_PLY_vertex_index','loaderReorder':False,'sidecarSha256':sha(path),
        'componentCounts':{key:int((arrays['component']==i).sum()) for i,key in enumerate(PARTS)},
        'note':'explicit identities do not certify geometry or authorize publication'}
    save_json(Path(path).with_suffix('.json'),manifest)
    return manifest


def load_v3_prepared(prepared):
    """Resolve recorded paths relative to the input's backend, never process cwd.

    This adapter consumes the unchanged v2 preparation contract, retaining K/F/C
    and pixels exactly; it does not rerun fitting or synthesize observations.
    """
    import cv2
    from flame_open_model import FlameOpen
    prepared=Path(prepared).resolve()
    metadata=json.loads((prepared/'preparation.json').read_text())
    root=prepared.parent.parent
    def resolve(value):
        path=Path(value)
        return path if path.is_absolute() else (root/path).resolve()
    source=resolve(metadata['source']);appearance=resolve(metadata['appearance'])
    if sha(source/'capture.mp4')!=metadata['sourceHash'] or sha(appearance)!=metadata['appearanceHash']:
        raise ValueError('prepared_input_hash_changed')
    raw=dict(np.load(prepared/'local_geometry.npz'));names=[str(x) for x in raw['names']]
    if len(set(names))!=len(names):raise ValueError('duplicate_prepared_name')
    local={n:{'mesh':raw['meshes'][i],'F':raw['F'][i],'role':str(raw['roles'][i]),'marks':raw['marks'][i]} for i,n in enumerate(names)}
    worlds={str(n):raw['C'][i] for i,n in enumerate(raw['world_names'])}
    rgb={n:cv2.cvtColor(cv2.imread(str(prepared/'rectified_observations'/n)),cv2.COLOR_BGR2RGB).astype(np.float32)/255 for n in names}
    return {**metadata,'source':source,'appearance':str(appearance),'staticMap':str(resolve(metadata['staticMap'])),
        'geometry':FlameOpen(24,12),'prior':dict(np.load(appearance)),'local':local,'worlds':worlds,
        'rgb':rgb,'labels':{n:dict(np.load(prepared/'rectified_observations'/(n+'.npz'))) for n in names},
        'K':raw['K'],'scale':float(raw['scale']),'room':dict(np.load(prepared/'static_surface_seeds.npz')),
        'components':{k:dict(np.load(prepared/(k+'_multiview_seeds.npz'))) for k in ('hair','glasses')}}
