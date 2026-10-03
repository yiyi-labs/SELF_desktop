import unittest
import numpy as np
import torch
from reconstruction_portrait_model import GaussianState
from reconstruction_live_neck_appearance import point_region_contributions,select_neck_sh_points


def frame(name):
    mask=np.zeros((8,8),bool);mask[1:4,2:6]=True
    skin=np.zeros_like(mask);skin[4:7,2:6]=True
    labels={k:torch.zeros((8,8),dtype=torch.bool) for k in
            ('face_boundary','room_visible','neck_cloth_visible','hair_visible','glasses_visible','unknown_or_occluded')}
    labels.update(face_core=torch.tensor(mask),observed_body_skin=torch.tensor(skin))
    return dict(name=name,masks=labels,fullSize=(8,8),rectangle=(0,0,8,8),nativeScale=1,
                K=torch.eye(3),fullK=torch.eye(3),C=torch.eye(4))


def state(n=4):
    return GaussianState(torch.zeros((n,3),requires_grad=True),torch.tensor([[1.,0.,0.,0.]]*n),
        torch.full((n,3),.1,requires_grad=True),torch.full((n,),.6,requires_grad=True),
        torch.zeros((n,4,3),requires_grad=True),torch.zeros(n,dtype=torch.int64))


class NeckAppearanceTest(unittest.TestCase):
    def observations(self,count=3):
        return [dict(frame=frame(str(i)),state=state(),unit_scale=1.,support=True,full_scene=True) for i in range(count)]

    def test_actual_footprint_veto_and_hair_exclusion(self):
        # Point 1 can have its center outside the face yet its composited tail
        # touches face pixels. It must never pass simply by point-center mask.
        def measure(*a,**k):return torch.tensor([[3.,0.,3.],[3.,.01,3.1],[.1,0.,.1],[3.,0.,3.]])
        selected,receipt=select_neck_sh_points(self.observations(),4,3,measure=measure)
        self.assertEqual(selected.tolist(),[True,False,False,False])
        self.assertEqual(receipt['rejectedProtectedAfterEnoughNeckSupport'],1)
        self.assertEqual(receipt['selectedMaxProtectedContribution'],0.)

    def test_other_view_can_veto_without_voting(self):
        obs=self.observations();extra=dict(frame=frame('later'),state=state(),unit_scale=1.,support=False,full_scene=False);obs.append(extra)
        def measure(st,f,*a,**k):
            x=torch.tensor([[3.,0.,3.]]*4)
            if f['name']=='later':x[0,1]=.1
            return x
        selected,r=select_neck_sh_points(obs,4,3,measure=measure)
        self.assertEqual(selected.tolist(),[False,True,True,False])
        self.assertEqual(len(r['supportImageNames']),3)

    def test_three_distinct_support_views_required(self):
        measure=lambda *a,**k:torch.tensor([[3.,0.,3.]]*4)
        with self.assertRaisesRegex(ValueError,'insufficient_distinct'):select_neck_sh_points(self.observations(2),4,3,measure=measure)
        obs=self.observations();obs[2]['frame']['name']='0'
        with self.assertRaisesRegex(ValueError,'duplicate'):select_neck_sh_points(obs,4,3,measure=measure)

    def test_support_must_be_full_scene_and_native(self):
        measure=lambda *a,**k:torch.tensor([[3.,0.,3.]]*4)
        obs=self.observations();obs[0]['full_scene']=False
        with self.assertRaisesRegex(ValueError,'full_scene'):select_neck_sh_points(obs,4,3,measure=measure)
        obs=self.observations();obs[0]['frame']['rectangle']=(0,0,4,4)
        with self.assertRaisesRegex(ValueError,'full_canvas'):select_neck_sh_points(obs,4,3,measure=measure)

    def test_no_semantic_fallback(self):
        obs=self.observations();del obs[0]['frame']['masks']['observed_body_skin']
        with self.assertRaisesRegex(ValueError,'attached_observation'):select_neck_sh_points(obs,4,3)

    def test_exact_channel_derivative_detaches_model(self):
        st=state(2);f=frame('single')
        weights=torch.zeros((8,8,2));weights[5,3]=torch.tensor([.5,.2]);weights[2,3]=torch.tensor([.1,0.])
        def rasterizer(means,quats,scales,opacity,features,C,K,w,h,**kw):
            self.assertFalse(means.requires_grad);self.assertFalse(opacity.requires_grad)
            self.assertFalse(kw['covars'].requires_grad)
            return torch.einsum('hwn,nc->hwc',weights,features)[None],None,None
        neck=np.zeros((8,8),bool);neck[5,3]=True
        protected=np.zeros_like(neck);protected[2,3]=True
        actual=point_region_contributions(st,f,neck,protected,rasterizer=rasterizer)
        torch.testing.assert_close(actual,torch.tensor([[.5,.1,.6],[.2,0.,.2]]))
        self.assertIsNone(st.means.grad);self.assertIsNone(st.scales.grad);self.assertIsNone(st.opacity.grad);self.assertIsNone(st.sh.grad)

    def test_low_neck_fraction_does_not_expand_edit_scope(self):
        measure=lambda *a,**k:torch.tensor([[3.,0.,4.]]*4)
        selected,_=select_neck_sh_points(self.observations(),4,3,measure=measure)
        self.assertFalse(selected.any())


if __name__=='__main__':unittest.main()
