import unittest
import numpy as np
from compare_live_opaque_person_runs import region_metrics,gradient_l1


class OpaqueComparisonContract(unittest.TestCase):
    def test_missing_pixels_and_room_transmission_remain_visible(self):
        target=np.full((5,5,3),.4,np.float32);mask=np.ones((5,5),bool)
        render={'rgb':np.zeros_like(target),'alpha':np.zeros((5,5),np.float32),
                'q':np.zeros((5,5,5),np.float32)}
        row=region_metrics(render,target,mask)
        self.assertEqual(row['pixels'],25);self.assertAlmostEqual(row['premultRgbL1'],.4)
        self.assertAlmostEqual(row['whiteBackdropRgbL1'],.6)
        self.assertEqual(row['personBelow095'],1)
        render['q'][...,0]=.9;render['q'][...,1]=.1;render['alpha'][:]=1
        row=region_metrics(render,target,mask)
        self.assertAlmostEqual(row['qRoomMean'],.9);self.assertAlmostEqual(row['qPersonMean'],.1)
        self.assertEqual(row['alphaBelow08'],0);self.assertEqual(row['personBelow08'],1)

    def test_float_errors_are_not_display_clipped(self):
        source=np.ones((5,5,3),np.float32);mask=np.ones((5,5),bool)
        render={'rgb':source*1.4,'alpha':np.ones((5,5),np.float32),'q':np.zeros((5,5,5),np.float32)}
        render['q'][...,1]=1
        row=region_metrics(render,source,mask)
        self.assertAlmostEqual(row['premultRgbL1'],.4,places=6)
        self.assertAlmostEqual(row['whiteBackdropRgbL1'],.4,places=6)
        self.assertAlmostEqual(row['nightBackdropRgbL1'],.4,places=6)

    def test_mask_edge_is_not_a_measured_structure(self):
        target=np.zeros((7,7,3),np.float32);prediction=target.copy()
        mask=np.zeros((7,7),bool);mask[2:5,2:5]=True
        prediction[~mask]=5
        self.assertEqual(gradient_l1(prediction,target,mask),0)
        self.assertIsNone(gradient_l1(prediction,target,np.zeros_like(mask)))


if __name__=='__main__':unittest.main()
