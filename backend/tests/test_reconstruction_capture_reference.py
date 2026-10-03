import copy,json,tempfile,unittest
from pathlib import Path
import numpy as np
from reconstruction_capture_reference import choose_capture_reference,capture_timestamps,CaptureReferenceUnavailable


def data_at(times,scores=None):
    names=list(times);local={};worlds={}
    for i,n in enumerate(names):
        marks=np.zeros((478,2));marks[10]=[0,0];marks[152]=[0,100]
        marks[234]=[0,50];marks[454]=[100*(scores or {}).get(n,1),50]
        F=np.eye(4);F[2,3]=.6;C=np.eye(4);C[0,3]=-.02*i
        local[n]={'marks':marks,'F':F,'role':'train'};worlds[n]=C
    return dict(train=names,local=local,worlds=worlds,scale=1.,sourceHash='capture')


class CaptureReferenceTest(unittest.TestCase):
    def test_preserve_existing_valid_reference(self):
        t={'a':0.,'b':.4,'c':.8,'d':1.2};d=data_at(t,{'c':2.})
        n,r=choose_capture_reference(d,timestamps=t)
        self.assertEqual(n,'c');self.assertTrue(r['keptOldMaxWidthReference'])
        n,r=choose_capture_reference(d,timestamps=t,preferred='b');self.assertEqual(n,'b')

    def test_sparse_frontal_peak_falls_back_to_real_window(self):
        t={'a':0.,'b':.4,'c':.8,'frontal':20.};d=data_at(t,{'frontal':2.,'b':1.4})
        n,r=choose_capture_reference(d,timestamps=t)
        self.assertEqual(n,'b');self.assertEqual(r['oldMaxWidthReference'],'frontal')
        self.assertEqual(set(r['bodyWindow']['imageNames']),{'a','b','c'})

    def test_no_development_or_absent_world_borrowing(self):
        t={'a':0.,'b':.4,'c':.8,'dev':1.,'missing':1.2};d=data_at(t,{'dev':9,'missing':10})
        d['local']['dev']['role']='development';del d['worlds']['missing']
        n,r=choose_capture_reference(d,timestamps=t)
        self.assertNotIn('dev',r['bodyWindow']['imageNames']);self.assertNotIn('missing',r['bodyWindow']['imageNames'])

    def test_index_adjacency_never_invents_time(self):
        t={'frame_01':0.,'frame_02':10.,'frame_03':20.};d=data_at(t)
        with self.assertRaisesRegex(CaptureReferenceUnavailable,'no_supported_body_window'):
            choose_capture_reference(d,timestamps=t)

    def test_pure_rotation_has_no_camera_baseline(self):
        t={'a':0.,'b':.4,'c':.8};d=data_at(t)
        for C in d['worlds'].values():C[:3,3]=0
        with self.assertRaises(CaptureReferenceUnavailable) as caught:choose_capture_reference(d,timestamps=t)
        self.assertTrue(all(v=='insufficient_actual_camera_baseline' for v in caught.exception.receipt['rejectedWindows'].values()))

    def test_world_scale_invariant(self):
        t={'a':0.,'b':.4,'c':.8};d=data_at(t);scaled=copy.deepcopy(d)
        scaled['scale']=17.
        for C in scaled['worlds'].values():C[:3,3]*=17
        a,ra=choose_capture_reference(d,timestamps=t);b,rb=choose_capture_reference(scaled,timestamps=t)
        self.assertEqual(a,b);self.assertAlmostEqual(ra['bodyWindow']['baselineToHeadDistance'],rb['bodyWindow']['baselineToHeadDistance'])

    def test_duplicate_time_does_not_count_as_three_views(self):
        d=data_at({'a':0.,'b':.4,'c':.8})
        with self.assertRaises(CaptureReferenceUnavailable):choose_capture_reference(d,timestamps={'a':0.,'b':0.,'c':0.})

    def test_manifest_hash_and_duplicate_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'frame_manifest.audit.json';d={'source':tmp,'sourceHash':'capture'}
            p.write_text(json.dumps({'captureSha256':'capture','frames':[{'name':'a','timestampSeconds':.2}]}))
            times,receipt=capture_timestamps(d);self.assertEqual(times,{'a':.2});self.assertEqual(len(receipt['sha256']),64)
            p.write_text(json.dumps({'captureSha256':'other','frames':[]}))
            with self.assertRaisesRegex(ValueError,'source_mismatch'):capture_timestamps(d)


if __name__=='__main__':unittest.main()
