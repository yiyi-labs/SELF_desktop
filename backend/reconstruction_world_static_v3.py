"""Static-only parameters and supervision. Never absorb garments into the room."""
import time
import torch
from reconstruction_components_v3 import exact_state_hash,save_json
from reconstruction_portrait_pipeline import make_frame,draw,masked_mean

def train_static(room,data,out,steps,*,research_cameras=False,verified_world_names=()):
    names=[n for n in data['train'] if n in data['worlds'] and n in verified_world_names]
    if research_cameras:names=[n for n in data['train'] if n in data['worlds']]
    if not names:raise ValueError('no_verified_static_world_cameras')
    if not torch.all(room.parts==0):raise ValueError('non_static_point_in_room_optimizer')
    start=time.perf_counter();before=exact_state_hash(room);curve=[]
    optimizer=torch.optim.Adam([{'params':[p],'lr':dict(offset=.002,log_scales=.0008,quats=.0002,opacity=.004,sh=.003)[n]}
                                for n,p in room.named_parameters()])
    for step in range(steps):
        frame=make_frame(data,names[step%len(names)],crop=False,half=True)
        h,w=frame['rgb'].shape[:2];optimizer.zero_grad(set_to_none=True)
        output=draw(room.state(),frame['C'],frame['K'],w,h,unit_scale=data['scale'])
        mask=frame['masks']['room_visible'] & ~frame['masks']['unknown_or_occluded']
        error=(output['rgb']-frame['rgb']).abs().mean(-1)
        rgb=masked_mean(error,mask);coverage=masked_mean((1-output['alpha']).square(),mask)
        loss=rgb+.08*coverage+room.regularizer()
        if not torch.isfinite(loss):raise RuntimeError('nonfinite_static_loss')
        loss.backward();torch.nn.utils.clip_grad_norm_(room.parameters(),5.);optimizer.step()
        if step%60==0 or step==steps-1:
            curve.append({'step':step+1,'frame':frame['name'],'roomRgb':float(rgb.detach()),'coverage':float(coverage.detach())})
            print('v3-static',curve[-1],flush=True)
    torch.cuda.synchronize()
    report={'steps':steps,'seconds':time.perf_counter()-start,'curve':curve,'cameraCount':len(names),
        'cameraStatus':'research_not_E1_accepted' if research_cameras else 'verified',
        'changed':before!=exact_state_hash(room),'personPixelsInLoss':0,'garmentPoints':0,
        'finalJointTraining':False,'limitations':'unseen background behind person remains unknown; no pure-color completion'}
    torch.save({'room':room.state_dict(),'optimizer':optimizer.state_dict()},out/'C-static.pt')
    save_json(out/'C-training.json',report);return report
