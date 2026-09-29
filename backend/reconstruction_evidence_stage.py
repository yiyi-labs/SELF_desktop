"""Reusable strict R0 loading for isolated surface experiments."""
from pathlib import Path
import json,shutil
import torch
from reconstruction_components_v3 import load_v3_prepared,save_json,sha
from reconstruction_portrait_pipeline import initialize_scene
from reconstruction_shared_surface import SharedSurfaceModel
from audit_portrait_priority_handoff import restore_tensors

class MeasuredSurfaceModel(SharedSurfaceModel):
    def attach_field(self,field):
        self.register_buffer('surface_base',self.portrait.surface_residual.detach().clone())
        self.register_buffer('measured_surface_field',field)
    def displacement(self):return self.measured_surface_field


def load_stage(manifest,out):
    spec=json.loads(Path(manifest).read_text(encoding='utf-8-sig'));out=Path(out).resolve();private=Path(__file__).resolve().parent/'.sources'
    if not out.is_relative_to(private):raise ValueError('research output must stay in .sources')
    out.mkdir(parents=True,exist_ok=False);save_json(out/'spec.json',spec);src=out/'algorithm-source';src.mkdir()
    base=Path(__file__).parent
    for p in base.glob('*.py'):
        if p.name.startswith(('reconstruction_','run_surface','flame_open','appearance_direction','audit_portrait_priority')):shutil.copyfile(p,src/p.name)
    prep=Path(spec['prepared']);data=load_v3_prepared(prep);plan=json.loads(Path(spec['observations']).read_text());plan.pop('new_audit',None)
    loading=out/'loading';loading.mkdir();shutil.copyfile(prep/'cloth_supported_seeds.npz',loading/'cloth_supported_seeds.npz')
    scene=initialize_scene(data,loading);model=MeasuredSurfaceModel(scene,data,plan['train']);del scene;model.enable_components(data,plan['train'])
    ck=torch.load(spec['checkpoint'],map_location='cuda',weights_only=False);restore_tensors(model,ck['model']);model.room.metadata=ck['extra']['roomMetadata'];model.body_sources=ck['extra']['bodySources']
    model.attach_field(torch.zeros_like(model.portrait.surface_residual))
    for p in model.parameters():p.requires_grad_(False)
    contract={'sourceHash':data['sourceHash'],'checkpointHash':sha(spec['checkpoint']),'preparedHash':sha(prep/'preparation.json'),'spec':spec,'sources':{p.name:sha(p) for p in src.glob('*.py')},'published':False}
    save_json(out/'contract.json',contract)
    return data,plan,model,contract
