"""Re-render saved actual optimization states; never report replay as training."""
import argparse,json,shutil
from pathlib import Path
import torch
from reconstruction_components_v3 import load_v3_prepared as load_prepared
from reconstruction_shared_v2 import initialize
from reconstruction_portrait_pipeline import initialize_scene
from run_reconstruction_v3 import block_from_old
from reconstruction_components_v3 import sha,save_json,exact_state_hash
from audit_reconstruction_v3 import audit_observations,evaluate

def run(a):
    private=Path(__file__).parent.resolve()/'.sources';out=a.output.resolve()
    if not out.is_relative_to(private) or out.exists():raise ValueError('new_private_run_required')
    out.mkdir(parents=True);original=json.loads((a.run/'config.json').read_text())
    prepared=Path(original['prepared']);data=load_prepared(prepared)
    audit_observations(data,prepared,out)
    shutil.copyfile(prepared/'cloth_supported_seeds.npz',out/'cloth_supported_seeds.npz')
    scene=initialize_scene(data,out);params,sources=initialize(data,out,'cuda');face=scene.portrait
    attach={}
    for key,part,bound in [('hair',2,.006),('accessory',3,.002)]:
        block=block_from_old(params,sources,part,'head-local',bound)
        if block is not None:attach[key]=block
    room=block_from_old(params,sources,0,'world-static',.01*data['scale'])
    body=block_from_old(params,sources,4,'world-reference-unaccepted-body-motion',.003*data['scale'])
    if not a.front_only:initial=evaluate(face,attach,body,room,data,out/'initial')
    b=torch.load(a.run/'B-attachments.pt',map_location='cuda',weights_only=True)
    c=torch.load(a.run/'C-static.pt',map_location='cuda',weights_only=True)
    for key,component in attach.items():component.load_state_dict(b['components'][key])
    room.load_state_dict(c['room'])
    if a.front_only:
        from reconstruction_compose_v3 import audit_front_conflicts
        result=audit_front_conflicts(face,attach,room,data,out,body=body)
        save_json(out/'replay.json',{'trainingRun':str(a.run),'newOptimizerSteps':0,'Bhash':sha(a.run/'B-attachments.pt'),'Chash':sha(a.run/'C-static.pt'),'assetSha256':json.loads((a.run/'portrait.view.json').read_text())['assetSha256']})
        print(result);return
    final=evaluate(face,attach,body,room,data,out/'final')
    image_index=[]
    for stage in ['initial','final']:
        for image in sorted((out/stage).glob('*.png')):
            name=image.name.split('.png-')[0]+'.png'
            image_index.append({'file':str(image.relative_to(out)),'sha256':sha(image),'sourceHash':data['sourceHash'],
                'assetHash':json.loads((a.run/'portrait.view.json').read_text())['assetSha256'],
                'stage':stage,'poseFrame':name,'camera':final[name].get('F'),'K':final[name]['K'],
                'kind':'per-observation-deformed-trainer-diagnostic_not_fixed_asset_orbit'})
    save_json(out/'image-index.json',image_index)
    save_json(out/'replay.json',{'trainingRun':str(a.run),'newOptimizerSteps':0,'reason':'correct overview filename collision and append exact map-ID checks',
        'Bhash':sha(a.run/'B-attachments.pt'),'Chash':sha(a.run/'C-static.pt'),'sourceHash':data['sourceHash']})
    print('Saved-state replay completed; no extra optimization.')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('output',type=Path);p.add_argument('--front-only',action='store_true');run(p.parse_args())
