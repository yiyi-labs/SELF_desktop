"""Contracts only: no production algorithm changes, optimization or private data."""
import unittest
import numpy as np
import torch
from gsplat.strategy import DefaultStrategy
from reconstruction_portrait_model import GaussianState
from reconstruction_portrait_pipeline import draw
from audit_reconstruction_stage_coverage import (zero_training, support_surface,
    effective_footprints, cohort_contribution, state_hash, analyze, termination_check)


class StageCoverageContracts(unittest.TestCase):
    def test_zero_training_guard(self):
        with zero_training():
            self.assertFalse(torch.is_grad_enabled())
            for action in [lambda: torch.optim.Adam([]), lambda: torch.tensor(1.).backward(),
                           lambda: torch.autograd.grad(None, None), lambda: DefaultStrategy()]:
                with self.assertRaisesRegex(AssertionError, 'stage0_forbids'):
                    action()

    def test_surface_zbuffer_not_a_point_bbox(self):
        # Overlapping hypotheses at two depths; the near triangle wins.
        near = np.array([[0.,0.,2.], [4.,0.,2.], [0.,4.,2.]], np.float32)
        xyz = np.concatenate((near, near*2, [[1.,1.,2.], [2.,2.,4.]]))
        seed = {'xyz':xyz, 'source_id':np.arange(8), 'source_kind':np.array([0]*6+[1]*2),
                'triangle_sources':np.array([[-1]*3]*6+[[0,1,2],[3,4,5]])}
        s, meta = support_surface(seed, np.eye(4), np.eye(3), 3, 3, .01)
        self.assertAlmostEqual(float(s['depth'][0,0]), 2.)
        self.assertFalse(s['S_raw'][1,1])
        self.assertTrue(meta['notGroundTruth'])
        self.assertEqual(int(s['triangle'][0,0]), 0)
        # Vary depth while retaining the projected triangle: depth must be
        # perspective-correct, not screen-space linear interpolation.
        seed['xyz'][:3]=np.array([[0,0,2],[8,0,4],[0,12,6]])
        seed['source_kind'][7]=0
        s,_=support_surface(seed,np.eye(4),np.eye(3),3,3,.01)
        self.assertAlmostEqual(float(s['depth'][0,0]),1/(.5/2+.25/4+.25/6),places=5)


    def test_real_kernel_footprint_and_aa(self):
        if not torch.cuda.is_available(): self.skipTest('CUDA required for forward contract')
        t = lambda v: torch.tensor(v, device='cuda', dtype=torch.float32)
        # One rotated anisotropic ellipse, one overlap, one behind the camera.
        state = GaussianState(t([[0,0,3],[.06,.03,3.1],[0,0,-2]]),
            t([[.9238795,0,0,.3826834],[1,0,0,0],[1,0,0,0]]),
            t([[.20,.03,.02],[.06,.06,.03],[.3,.3,.3]]), t([.65,.45,.8]),
            t([[[.3,.1,.2]]+[[0,0,0]]*3]*3), torch.zeros(3,device='cuda',dtype=torch.long))
        before = state_hash(state)
        C = torch.eye(4,device='cuda'); K = t([[80,0,32],[0,80,32],[0,0,1]])
        with zero_training():
            results=[]
            for aa in (False, True):
                r=draw(state,C,K,64,64,antialiased=aa)
                f=effective_footprints(r['info'],64,64)
                self.assertLess(float((f['all_eligible_alpha']-r['alpha']).abs().max()),.0008)
                self.assertEqual(int(((~f['U']) & (r['alpha']>1e-6)).sum()),0)
                self.assertNotIn(2,r['info']['gaussian_ids'].tolist())
                y,x=torch.where(f['U']); bbox=(x.max()-x.min()+1)*(y.max()-y.min()+1)
                self.assertLess(int(f['U'].sum()),int(bbox)*.8)
                q,a=cohort_contribution(r['info'],torch.ones((3,1),device='cuda'),64,64)
                self.assertTrue(torch.allclose(a,r['alpha'],atol=2e-6))
                self.assertTrue(torch.allclose(q[:,:,0],r['alpha'],atol=2e-6))
                results.append(r['alpha'])
            self.assertGreater(float((results[0]-results[1]).abs().max()),1e-5)
        self.assertEqual(state_hash(state),before)
        # An opaque second splat can trigger exclusive stop with a visible gap
        # between mathematical infinite compositing and the real kernel.
        opaque = GaussianState(t([[0,0,3],[0,0,3.1]]),t([[1,0,0,0]]*2),
            t([[.3,.3,.3]]*2),t([.985,.999]),t([[[0,0,0]]*4]*2),
            torch.zeros(2,device='cuda',dtype=torch.long))
        with zero_training():
            r=draw(opaque,C,K,64,64)
            f=effective_footprints(r['info'],64,64)
            check=termination_check(r['info'],r['alpha'],f['all_eligible_alpha'])
            self.assertLess(check['worstPixelExclusiveReplayMaxAbs'],3e-5)


    def test_exclusive_categories_and_float_rgb(self):
        shape=(3,3); S=np.ones(shape,bool); U=S.copy(); A=np.full(shape,.9,np.float32)
        S[0,0]=False; U[0,1]=False; A[0,2]=.4
        rgb=np.full((*shape,3),1.1,np.float32); target=np.ones_like(rgb)
        m,_,_=analyze(S,U,A,A,rgb,target,np.ones(shape,bool))
        self.assertAlmostEqual(sum(m['exclusiveFractions'].values()),1.)
        self.assertGreater(m['floatRgbRange'][1],1.)
        self.assertAlmostEqual(m['rgbL1'],.1,places=6)


if __name__=='__main__': unittest.main(verbosity=2)
