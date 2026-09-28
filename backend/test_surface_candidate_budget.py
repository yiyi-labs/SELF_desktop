"""Synthetic contracts for opt-in preparation; no fitting or reconstruction."""
from pathlib import Path
from types import SimpleNamespace as NS
import ast
import json
import subprocess
import tempfile
import unittest
import numpy as np
from reconstruction_scene import (supported_static_surfaces, collect_supported_surface_pool,
    allocate_surface_pool, surface_source_key, _surface_point_votes)


def fixture():
    names=['a0','a1','a2','z0','z1','z2'];images={i:NS(name=n,has_pose=True) for i,n in enumerate(names)}
    views={n:(np.eye(4),np.array([[100.,0,128],[0,100.,128],[0,0,1]])) for n in names}
    masks={n:np.ones((512,512),bool) for n in names}
    rgb={n:np.full((512,512,3),np.float32(128/255),np.float32) for n in names}
    points={};positions=[];ids=[];supports=[]
    for group in [0,1]:
        for y in range(6):
            for x in range(7):
                key=10007+len(points)*13;xyz=np.array([x*.56+group*4.,y*.56,2.])
                elements=[NS(image_id=i) for i in range(group*3,group*3+3)]
                points[key]=NS(xyz=xyz,error=.2,track=NS(length=lambda:3,elements=elements))
                positions.append(xyz);ids.append(key);supports.append(3)
    anchors={'xyz':np.array(positions,np.float32),'rgb':np.full((len(ids),3),np.float32(128/255),np.float32),
             'support':np.array(supports,np.int16),'source_id':np.array(ids,np.int64),'source_kind':np.zeros(len(ids),np.uint8),
             'triangle_sources':np.repeat(np.array(ids,np.int64)[:,None],3,axis=1)}
    return NS(points3D=points,images=images),views,masks,rgb,anchors


class SurfaceBudgetContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='self-stage2a-contract-')
        cls.root=Path(cls.temp.name);cls.args=fixture()
        cls.pool=collect_supported_surface_pool(*cls.args,cls.root/'pool',namespace='synthetic')

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_late_views_collected_after_early_budget(self):
        p=self.pool;self.assertEqual(len(p['report']['completedViews']),6)
        late=[x for x in p['points'] if any(n.startswith('z') for n in x['acceptedOrigins'])]
        early=[x for x in p['points'] if any(n.startswith('a') for n in x['acceptedOrigins'])]
        self.assertGreater(len(early),6);self.assertGreater(len(late),6)
        data,_=allocate_surface_pool(p,self.args[4],self.args[1],self.args[2],namespace='synthetic',max_points=len(self.args[4]['xyz'])+6)
        self.assertEqual(len(data['xyz']),len(self.args[4]['xyz'])+6)

    def test_duplicate_surfaces_keep_evidence_without_duplicate_instances(self):
        self.assertGreater(self.pool['report']['proposalCount'],self.pool['report']['geometryUniqueSurfaces'])
        self.assertEqual(len({p['pointId'] for p in self.pool['points']}),len(self.pool['points']))
        self.assertTrue(any(len(p['acceptedOrigins'])==3 for p in self.pool['points']))
        self.assertTrue(all(len(s['proposals'])==3 for s in self.pool['surfaces']))

    def test_cross_kind_ids_do_not_collide(self):
        self.assertNotEqual(surface_source_key('map',0,5),surface_source_key('map',1,5))
        self.assertNotEqual(surface_source_key('map',0,5),surface_source_key('other-map',0,5))

    def test_point_failures_survive_triangle_acceptance(self):
        sampled=np.ones((6,2,3),np.float32)*.4;sampled[0,1]=.9
        keep,votes,bad,*_= _surface_point_votes(sampled,np.ones((6,2),bool),0)
        self.assertTrue(keep[0]);self.assertFalse(keep[1]);self.assertEqual(votes[1],1);self.assertEqual(bad[1],5)

    def test_reversed_views_are_deterministic(self):
        model,views,masks,rgb,anchors=self.args
        reverse=collect_supported_surface_pool(model,dict(reversed(list(views.items()))),masks,rgb,anchors,
            self.root/'reverse',namespace='synthetic')
        self.assertEqual(reverse['points'],self.pool['points']);self.assertEqual(reverse['surfaces'],self.pool['surfaces'])
        a,_=allocate_surface_pool(self.pool,anchors,views,masks,namespace='synthetic',max_points=100)
        b,_=allocate_surface_pool(reverse,anchors,views,masks,namespace='synthetic',max_points=100)
        for k in a:self.assertTrue(np.array_equal(a[k],b[k]),k)

    def test_budget_includes_anchors_without_duplicate_fill(self):
        model,views,masks,rgb,anchors=self.args
        a,stats=allocate_surface_pool(self.pool,anchors,views,masks,namespace='synthetic',max_points=10000)
        self.assertLessEqual(len(a['xyz']),len(anchors['xyz'])+len(self.pool['points']))
        self.assertGreater(stats['unusedBudget'],0)
        self.assertEqual(len(set(a['point_id'])),len(a['point_id']))
        for k in anchors:self.assertTrue(np.array_equal(a[k][:len(anchors['xyz'])],anchors[k]),k)
        for key in ['point_id','source_id','source_kind','triangle_sources','surface_id','sample_origin','support_bits','evidence_scope']:
            self.assertEqual(len(a[key]),len(a['xyz']))
        with self.assertRaisesRegex(ValueError,'budget_cannot_drop'):
            allocate_surface_pool(self.pool,anchors,views,masks,namespace='synthetic',max_points=1)

    def test_legacy_function_unchanged_and_same_output(self):
        root=Path(__file__).resolve().parent.parent
        pointer=(root/'.git').read_text().removeprefix('gitdir: ').strip()
        if ':' in pointer:pointer='/mnt/'+pointer[0].lower()+pointer[2:].replace('\\','/')
        old=subprocess.check_output(['git','--git-dir='+pointer,'show','27c9810bf0746d8e4382eb218e89276954767d7d:backend/reconstruction_scene.py'],text=True)
        current=(root/'backend/reconstruction_scene.py').read_text()
        fn=lambda s:next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name=='supported_static_surfaces')
        self.assertEqual(ast.dump(fn(old),include_attributes=False),ast.dump(fn(current),include_attributes=False))
        ns={};exec(compile(ast.Module(body=[fn(old)],type_ignores=[]),'legacy','exec'),ns)
        args=self.args[:4]
        a,_=supported_static_surfaces(*args,self.root/'legacy-current.npz',max_points=100)
        b,_=ns['supported_static_surfaces'](*args,self.root/'legacy-anchor.npz',max_points=100)
        for k in a:self.assertTrue(np.array_equal(a[k],b[k]),k)

    def test_incomplete_pool_is_not_completed(self):
        with self.assertRaisesRegex(RuntimeError,'candidate_enumeration_incomplete'):
            collect_supported_surface_pool(*self.args,self.root/'incomplete',namespace='synthetic',wall_seconds=-1)
        self.assertFalse(json.loads((self.root/'incomplete/incomplete.json').read_text())['complete'])
        self.assertFalse((self.root/'incomplete/summary.json').exists())
        pool={**self.pool,'report':{**self.pool['report'],'complete':False}}
        with self.assertRaisesRegex(ValueError,'incomplete_pool'):
            allocate_surface_pool(pool,self.args[4],self.args[1],self.args[2],namespace='synthetic',max_points=100)


if __name__=='__main__':unittest.main(verbosity=2)
