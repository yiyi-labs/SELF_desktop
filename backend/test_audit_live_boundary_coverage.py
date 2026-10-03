import unittest
import numpy as np
from audit_live_boundary_coverage import boundary_regions,rejection_stages


class BoundaryAttributionTest(unittest.TestCase):
    def test_rejection_reason_is_single_and_ordered(self):
        good=np.ones(5,bool);dep=good.copy();dep[0]=False;der=good.copy();der[:2]=False
        sem=good.copy();sem[2]=False;votes=np.array([0,0,0,2,3]);free=np.zeros(5,int)
        result=rejection_stages(dep,der,sem,good,votes,free)
        self.assertEqual([int(v.sum()) for v in result.values()],[1,1,1,0,1,0,1])

    def test_occluded_support_shortage_not_relabelled_empty(self):
        b=np.ones(2,bool);r=rejection_stages(b,b,b,b,np.array([2,3]),np.array([0,2]))
        self.assertEqual(r['three_view_support'].tolist(),[True,False]);self.assertEqual(r['free_space_conflict'].tolist(),[False,True])

    def test_band_changes_with_silhouette_without_frame_coordinates(self):
        c=np.zeros((160,160),np.uint8);c[30:130,45:115]=4;a=np.zeros_like(c,bool);a[30:60,60:100]=True
        regions,r=boundary_regions(c,a,np.zeros_like(a));shift=np.roll(c,10,axis=1);sa=np.roll(a,10,axis=1)
        other,r2=boundary_regions(shift,sa,np.zeros_like(a));self.assertEqual(r,r2)
        np.testing.assert_array_equal(np.roll(regions['body_edge'],10,axis=1),other['body_edge'])

    def test_invalid_canvas_border_is_not_person_contour(self):
        classes=np.zeros((160,160),np.uint8);classes[45:115,55:105]=4
        outside=np.zeros_like(classes,bool);outside[:,:5]=True;outside[:,-5:]=True
        anchor=np.zeros_like(outside);anchor[45:65,65:95]=True
        bands,_=boundary_regions(classes,anchor,outside)
        self.assertFalse(bands['room_edge'][:,5:15].any())
        self.assertFalse(bands['room_near'][:,-15:-5].any())
        self.assertTrue(bands['room_edge'][60,52])


if __name__=='__main__':unittest.main()
