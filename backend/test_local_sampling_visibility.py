import ast
import tempfile
import unittest
from pathlib import Path
import numpy as np
import audit_local_sampling_visibility as audit


class LocalSamplingContract(unittest.TestCase):
    def test_d2_only_one_research_centroid(self):
        self.assertEqual(len(audit.original_grid(2)),0)
        np.testing.assert_array_equal(audit.research_grid(2,True),[[1/3]*3])

    def test_d3_and_larger_are_exactly_unchanged(self):
        for d in range(3,11):
            np.testing.assert_array_equal(audit.original_grid(d),audit.research_grid(d,True))

    def test_failed_triangle_never_rescued(self):
        for d in range(2,11): self.assertEqual(len(audit.research_grid(d,False)),0)
        C=np.eye(4);K=np.eye(3)
        reason,d=audit.triangle_check(np.array([[0,0,10],[1,0,10],[0,1,10.]]),C,K)
        self.assertEqual(reason,'edge')
        self.assertEqual(len(audit.research_grid(d,reason in ('noInteriorSamples','geometryAccepted'))),0)

    def test_true_3d_centroid_not_screen_mean(self):
        vertices=np.array([[0,0,1],[2,0,2],[0,3,3.]])
        uv,_=audit.project(vertices,np.eye(4),np.eye(3))
        projected,_=audit.project(vertices.mean(0)[None],np.eye(4),np.eye(3))
        np.testing.assert_allclose(projected,[[1/3,1/2]])
        self.assertFalse(np.allclose(projected[0],uv.mean(0)))

    def test_centroid_dedup_cross_winding_d3_d6(self):
        a=audit.point_identity('map',[100,7,90],[1,1,1])
        self.assertEqual(a,audit.point_identity('map',[7,90,100],[2,2,2]))
        self.assertNotEqual(a[1],audit.point_identity('other',[7,90,100],[1,1,1])[1])

    def test_original_all_59_rule_and_rejection(self):
        rgb=np.zeros((59,1,3),np.float32);valid=np.ones((59,1),bool)
        self.assertTrue(audit.original_decision(rgb,valid,0)[0][0])
        rgb[57:]=1
        keep,votes,bad,_,_=audit.original_decision(rgb,valid,0)
        self.assertFalse(keep[0]);self.assertEqual(int(votes[0]),57);self.assertEqual(int(bad[0]),2)
        with self.assertRaises(ValueError):audit.original_decision(rgb[:9],valid[:9],0)

    def test_original_reference_is_not_silently_replaced(self):
        rgb=np.zeros((59,1,3),np.float32);valid=np.ones((59,1),bool)
        rgb[0]=1;valid[0]=False
        keep,votes,bad,_,_=audit.original_decision(rgb,valid,0)
        self.assertFalse(keep[0]);self.assertEqual(int(votes[0]),0);self.assertEqual(int(bad[0]),58)

    def test_audit_labels_cannot_change_decisions(self):
        rgb=np.zeros((59,1,3),np.float32);valid=np.ones((59,1),bool);rgb[4:7]=1
        before=audit.original_decision(rgb,valid,0)
        self.assertEqual(audit.interpretation(False,True,0),'5_original_rule_excluded')
        self.assertEqual(audit.interpretation(True,True,8),'4_boundary_mixing_or_projection_unresolved')
        self.assertEqual(audit.interpretation(True,False,8),'3_room_pixel_candidate_visibility_unknown')
        after=audit.original_decision(rgb,valid,0)
        for a,b in zip(before,after):np.testing.assert_array_equal(a,b)

    def test_frozen_input_mutation_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'frozen';p.write_bytes(b'original');manifest={str(p):audit.sha(p)}
            audit.verify_frozen(manifest);p.write_bytes(b'changed')
            with self.assertRaises(ValueError):audit.verify_frozen(manifest)

    def test_existing_run_is_never_tainted_by_failure_log(self):
        import subprocess,sys,os
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'completed';out.mkdir();(out/'evidence').write_bytes(b'keep')
            args=[sys.executable,'-B',audit.__file__]
            for key in ['stage2','prepared','original-backend','windows']:
                args+=['--'+key,str(Path(d)/'unread')]
            args+=['--output',str(out)]
            result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                  env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(sorted(p.name for p in out.iterdir()),['evidence'])
            self.assertEqual((out/'evidence').read_bytes(),b'keep')
    def test_no_training_render_or_global_prepare_calls(self):
        tree=ast.parse(Path(audit.__file__).read_text())
        forbidden={'Adam','AdamW','backward','DefaultStrategy','rasterization','collect_supported_surface_pool',
                   'allocate_surface_pool','supported_static_surfaces','Delaunay','initialize','export_ply'}
        calls={n.func.id if isinstance(n.func,ast.Name) else n.func.attr if isinstance(n.func,ast.Attribute) else ''
               for n in ast.walk(tree) if isinstance(n,ast.Call)}
        self.assertFalse(calls&forbidden)


if __name__=='__main__':unittest.main()