import copy
import unittest
import torch
from test_reconstruction_portrait_model import fixture
from reconstruction_portrait_pipeline import SceneAssembly
from run_live_hair_motion_trial import transfer_face_environment,assert_frozen_nonhair


def scene_fixture():
    model,_,_=fixture()
    env={'means':torch.zeros(3,3),'scales':torch.zeros(3,3),'quats':torch.tensor([[1.,0,0,0]]*3),
         'opacities':torch.zeros(3),'sh':torch.zeros(3,4,3),'part':torch.tensor([[0],[4],[4]])}
    scene=SceneAssembly(model,env,1.)
    scene.register_buffer('hair_initial',model.hair_base.clone())
    scene.register_buffer('hair_support_scale',model.metric_per_pixel[2:].clone())
    return scene


class HairTrialTransfer(unittest.TestCase):
    def fixture(self):
        old=scene_fixture();new=scene_fixture()
        with torch.no_grad():
            old.portrait.embedding.add_(.001);old.portrait.surface_residual.add_(.0002)
            old.portrait.sh.add_(.2);old.portrait.log_scales.add_(.1);old.environment['sh'].add_(.6)
            old.portrait.triangle_ids[:]=torch.tensor([1,0])
            new.portrait.hair_base.add_(.004);new.portrait.sh[-1].add_(.9)
        old.register_buffer('neck_sh_editable',torch.tensor([True,False,False]))
        source=dict(sourceHash='source',reference='ref',scale=1.)
        before={'sourceSha256':'source','surfaceContract':{'reference':'ref','scale':1.},'model':copy.deepcopy(old.state_dict())}
        m={'sourceSha256':'source','preparedSha256':'p','localGeometrySha256':'g','K':[],'headToWorldScale':1.,
           'components':{'room':{'sha256':'r'},'body':{'sha256':'b'},'hair':{'sha256':'old'}}}
        changed=copy.deepcopy(m);changed['components']['hair']={'sha256':'new','hairMotion':{'status':'reference_relative_joint1_transport'}}
        return new,before,source,m,changed

    def test_complete_learned_face_and_environment_survive_new_hair(self):
        scene,old,data,m,new=self.fixture();hair=scene.portrait.hair_base.clone();hair_sh=scene.portrait.sh[-1].clone()
        receipt=transfer_face_environment(scene,old,data,m,new)
        self.assertTrue(receipt['faceAndEnvironmentBitwisePreserved']);self.assertFalse(receipt['exactOptimizerResume'])
        for key in ('portrait.embedding','portrait.surface_residual','portrait.triangle_ids','environment.sh'):
            self.assertTrue(torch.equal(scene.state_dict()[key],old['model'][key]))
        self.assertTrue(torch.equal(scene.portrait.sh[:2],old['model']['portrait.sh'][:2]))
        self.assertTrue(torch.equal(scene.portrait.hair_base,hair));self.assertTrue(torch.equal(scene.portrait.sh[-1],hair_sh))
        self.assertTrue(torch.equal(scene.neck_sh_editable,old['model']['neck_sh_editable']))
        frozen=copy.deepcopy(scene.state_dict())
        with torch.no_grad():scene.portrait.sh[-1].add_(.1);scene.portrait.hair_delta.add_(.001)
        assert_frozen_nonhair(scene,frozen)
        with torch.no_grad():scene.portrait.surface_residual.add_(.001)
        with self.assertRaisesRegex(AssertionError,'changed_frozen'):assert_frozen_nonhair(scene,frozen)

    def test_changed_environment_or_reference_rejected(self):
        scene,old,data,m,new=self.fixture();new['components']['body']['sha256']='other'
        with self.assertRaisesRegex(ValueError,'environment_evidence_changed'):transfer_face_environment(scene,old,data,m,new)
        scene,old,data,m,new=self.fixture();data['reference']='different'
        with self.assertRaisesRegex(ValueError,'reference_or_scale'):transfer_face_environment(scene,old,data,m,new)


if __name__=='__main__':unittest.main()
