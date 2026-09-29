"""D2 integration and frozen real point-level regression."""
from pathlib import Path
import json,unittest
import numpy as np
from reconstruction_scene import surface_barycentric_numerators,_surface_point_votes,_surface_bits
from audit_local_sampling_visibility import point_identity

class D2Integration(unittest.TestCase):
    def test_existing_grids_unchanged(self):
        self.assertEqual(surface_barycentric_numerators(2),[(1,1,1)])
        for d in range(3,11):
            self.assertEqual(surface_barycentric_numerators(d),[(a,b,d-a-b) for a in range(1,d) for b in range(1,d-a)])

    def test_frozen_real_point_contract(self):
        root=Path(__file__).parent/'.sources/reconstruction-local-sampling-visibility-20260929-a'
        if not root.exists():self.skipTest('private frozen observations absent')
        stage=Path(__file__).parent/'.sources/reconstruction-stage2a-20260928-b/candidate-pool'
        read=lambda p:[json.loads(x) for x in p.read_text().splitlines()]
        local=root/'point-check'
        with np.load(local/'point-observations.npz',allow_pickle=False) as z:arrays={k:z[k] for k in z.files}
        names=arrays['names'].tolist();index={p:i for i,p in enumerate(arrays['point_ids'])}
        rows=read(local/'local-point-decisions.jsonl');proposals=read(local/'local-triangle-proposals.jsonl')
        keys={(r['surfaceId'],r['view']) for r in proposals}
        cache=[r for r in read(stage/'sample-evidence.jsonl') if (r['surfaceId'],r['origin']) in keys]
        results={n:_surface_point_votes(arrays['rgb3x3'],arrays['valid'],names.index(n)) for n in {r['origin'] for r in rows+cache}}
        for r in cache:
            i=index[r['pointId']];a=results[r['origin']]
            self.assertEqual(bool(a[0][i]),r['accepted'])
            self.assertEqual(int(_surface_bits(a[4][:,i:i+1])[0]),r['supportBits'])
            self.assertEqual(int(_surface_bits(a[5][:,i:i+1])[0]),r['conflictBits'])
        self.assertEqual(len(cache),1704)
        namespace=json.loads((local/'summary.json').read_text())['namespace']
        accepted=set();existing=set();all_ids=set()
        for r in rows:
            if r['kind']!='d2_centroid':continue
            sid,pid,_=point_identity(namespace,r['originalWinding'],list(surface_barycentric_numerators(2)[0]))
            self.assertEqual((sid,pid),(r['surfaceId'],r['pointId']));all_ids.add(pid)
            if r['alreadyLegalCentroid']:existing.add(pid)
            actual=bool(results[r['origin']][0][index[pid]])
            self.assertEqual(actual,r['original_decision']['accepted'])
            if actual:accepted.add(pid)
        self.assertEqual((len(accepted-existing),len(all_ids-accepted),len(existing)),(357,50,4))

if __name__=='__main__':unittest.main()
