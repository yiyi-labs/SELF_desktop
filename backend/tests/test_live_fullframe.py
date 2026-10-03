"""Device-test entry contracts, including real full-canvas CUDA gradients."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import torch
from portrait_model import GaussianState
from portrait_pipeline import draw
from live_fullframe import native_draw, native_frame, NativeScene
from runtime import pipeline_entry, NATIVE_VERSION


class LiveEntryContractTest(unittest.TestCase):
    def test_adapter_requires_exact_local_source_set(self):
        names=("live_fullframe.py","portrait_pipeline.py",
               "portrait_model.py","appearance_direction_contract.py")
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);hashes={}
            for name in names:
                (root/name).write_bytes(name.encode());hashes[name]=hashlib.sha256(name.encode()).hexdigest()
            profile=dict(executionAdapter="native-fullframe",algorithmVersion=NATIVE_VERSION,entrySourceHashes=hashes)
            script,joint=pipeline_entry(profile,root)
            self.assertEqual(script,root/names[0]);self.assertEqual(joint,0)
            script,joint=pipeline_entry({**profile,"jointSteps":300},root)
            self.assertEqual(joint,300)
            for bad in (True,-1,601,"300"):
                with self.assertRaisesRegex(ValueError,"joint"):pipeline_entry({**profile,"jointSteps":bad},root)
            (root/names[1]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError,"hash_changed"):pipeline_entry(profile,root)
            with self.assertRaisesRegex(ValueError,"unknown_test"):pipeline_entry(dict(executionAdapter="../outside"),root)

    def test_frame_retains_native_pixels_and_recorded_crop_k(self):
        h,w=150,110;mask=np.zeros((h,w),bool);mask[60:90,30:65]=True
        labels={k:mask.copy() for k in ("face_core","face_boundary","hair_visible","glasses_visible")}
        rgb=np.arange(h*w*3,dtype=np.float32).reshape(h,w,3)/(h*w*3)
        K=np.array([[130.,0,49.],[0,140.,73.],[0,0,1.]])
        data=dict(rgb={"one":rgb},labels={"one":labels},K=K,
                  local={"one":dict(F=np.eye(4),mesh=np.zeros((3,3)))},worlds={"one":np.eye(4)})
        f=native_frame(data,"one",half=True,device="cpu");x0,y0,x1,y1=f["rectangle"]
        self.assertEqual(f["fullSize"],(w,h));self.assertEqual(f["nativeScale"],1)
        np.testing.assert_array_equal(f["rgb"].numpy(),rgb[y0:y1,x0:x1])
        self.assertAlmostEqual(float(f["K"][0,2])+x0,K[0,2]);self.assertTrue(f["requestedHalfIgnored"])


@unittest.skipUnless(torch.cuda.is_available(),"real CUDA contract test")
class LiveCudaContractTest(unittest.TestCase):
    def test_person_colour_channel_preserves_scene_pixels_and_gradients(self):
        device='cuda';w,h=72,80
        C=torch.eye(4,device=device);K=torch.tensor([[70.,0,36.],[0,70.,40.],[0,0,1.]],device=device)
        values=[torch.tensor([[0.,0.,1.],[0.,0.,2.]],device=device),
            torch.tensor([[1.,0,0,0]]*2,device=device),
            torch.tensor([[.15,.14,.02],[.3,.3,.03]],device=device),
            torch.tensor([.55,.95],device=device),torch.zeros(2,4,3,device=device)]
        parts=torch.tensor([4,0],device=device)
        frame=dict(rgb=torch.zeros(h,w,3,device=device),K=K,fullK=K,fullSize=(w,h),
            rectangle=(0,0,w,h),nativeScale=1)
        outputs=[];gradients=[]
        for enabled in (False,True):
            p=[x.clone().requires_grad_() for x in values]
            r=native_draw(GaussianState(*p,parts),C,frame,person_channels=enabled)
            (r['rgb'].square().sum()+.1*r['alpha'].sum()).backward()
            outputs.append(r);gradients.append([x.grad for x in p])
        for key in ('rgb','alpha','q','q_depth','depth'):
            torch.testing.assert_close(outputs[0][key],outputs[1][key],rtol=2e-5,atol=2e-5)
        for a,b in zip(*gradients):torch.testing.assert_close(a,b,rtol=3e-4,atol=3e-4)
        r=outputs[1]
        torch.testing.assert_close(r['person_rgb'],.5*r['q'][...,4,None].expand(-1,-1,3),rtol=2e-5,atol=1e-6)
        self.assertGreater(float(r['alpha'][40,36]),.9)
        self.assertLess(float(r['q'][40,36,4]),.6)

    def test_full_canvas_covariance_matches_reference_pixels_and_gradients(self):
        torch.manual_seed(51);w,h=160,192;device="cuda"
        K=torch.tensor([[120.,0,69.],[0,123.,91.],[0,0,1.]],device=device);C=torch.eye(4,device=device)
        values=[torch.tensor([[-.42,0.,1.],[.02,.03,1.1],[.07,.03,1.6],[1.5,.1,2.]],device=device),
                torch.tensor([[1.,0,0,0]]*4,device=device),
                torch.tensor([[.28,.12,.05],[.015,.018,.012],[.19,.17,.08],[.8,.6,.1]],device=device),
                torch.tensor([.5,.7,.65,.5],device=device),torch.randn(4,4,3,device=device)*.1]
        parts=torch.tensor([1,1,0,0],device=device)
        for rect in ((50,60,105,130),(6,8,83,100),(87,92,152,180)):
            x0,y0,x1,y1=rect;cropK=K.clone();cropK[0,2]-=x0;cropK[1,2]-=y0
            f=dict(rgb=torch.zeros(y1-y0,x1-x0,3,device=device),K=cropK,fullK=K,fullSize=(w,h),rectangle=rect,nativeScale=1)
            def execute(adapter):
                params=[v.clone().requires_grad_() for v in values];state=GaussianState(*params,parts)
                if adapter:result=native_draw(state,C,f)
                else:
                    full=draw(state,C,K,w,h);result={k:(v[y0:y1,x0:x1] if k!="info" else v) for k,v in full.items()}
                loss=result["rgb"].square().sum()+.1*result["alpha"].square().sum()+.02*result["q"][...,0].sum();loss.backward()
                return result,[p.grad for p in params]
            ref,g=execute(False);candidate,j=execute(True)
            for key in ("rgb","alpha","q"):
                self.assertTrue(torch.allclose(ref[key],candidate[key],rtol=2e-5,atol=2e-5),key)
            for a,b in zip(g,j):self.assertTrue(torch.allclose(a,b,rtol=3e-4,atol=3e-4))
            self.assertEqual(candidate["info"]["width"],w);self.assertEqual(candidate["info"]["height"],h)
            self.assertLess(float((candidate["q"].sum(-1)-candidate["alpha"]).abs().max()),1e-6)
            with self.assertRaisesRegex(ValueError,"intrinsics"):native_draw(GaussianState(*values,parts),C,{**f,"fullK":K+1})

    def test_scene_keeps_person_and_room_in_common_composition(self):
        device="cuda";C=torch.eye(4,device=device);K=torch.tensor([[100.,0,40.],[0,100.,40.],[0,0,1.]],device=device)
        def state(z,part):
            return GaussianState(torch.tensor([[0.,0.,z]],device=device),torch.tensor([[1.,0,0,0]],device=device),torch.tensor([[.2,.2,.02]],device=device),torch.tensor([.7],device=device),torch.zeros(1,4,3,device=device),torch.tensor([part],device=device))
        person=state(1.,1);room=state(2.,0)
        shim=SimpleNamespace(portrait=SimpleNamespace(local_state=lambda mesh:person),
            portrait_state=lambda frame:person,environment_state=lambda:room,scale=1.)
        f=dict(rgb=torch.zeros(80,80,3,device=device),K=K,fullK=K,fullSize=(80,80),rectangle=(0,0,80,80),nativeScale=1,F=C,C=C,mesh=None)
        r=NativeScene.render(shim,f,"T2")
        self.assertGreater(float(r["q"][...,0].sum()),0);self.assertGreater(float(r["q"][...,1].sum()),0)
        with self.assertRaisesRegex(ValueError,"world_render"):NativeScene.render(shim,{**f,"C":None},"T2")


if __name__=="__main__":unittest.main()
