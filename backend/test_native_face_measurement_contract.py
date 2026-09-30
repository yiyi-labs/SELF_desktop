"""Actual ECC/native correspondence contract, no mock optimizer or renderer."""
import unittest
import numpy as np
import cv2
from reconstruction_native_measurements import native_measurement


class NativeMeasurementTests(unittest.TestCase):
    def test_real_native_translation(self):
        rng=np.random.default_rng(631)
        rgb=rng.integers(0,256,(160,160,3),dtype=np.uint8)
        rgb=cv2.GaussianBlur(rgb,(5,5),1.2)
        source=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        shift=np.array([2.,-1.]);warp=np.array([[1,0,shift[0]],[0,1,shift[1]]],np.float32)
        target=cv2.warpAffine(source,warp,(160,160),flags=cv2.INTER_LINEAR)
        point=np.array([80.,80.],np.float32)
        uv,quality=native_measurement(source,target,point,point)
        np.testing.assert_allclose(uv,point+shift,atol=.3,rtol=0)
        self.assertLess(quality['fb'],1.)
    def test_unreliable_interpolated_patch_is_not_silently_accepted(self):
        rng=np.random.default_rng(631)
        source=cv2.cvtColor(cv2.GaussianBlur(rng.integers(0,256,(160,160,3),dtype=np.uint8),(5,5),1.2),cv2.COLOR_RGB2GRAY)
        target=cv2.warpAffine(source,np.array([[1,0,.7],[0,1,-.4]],np.float32),(160,160))
        with self.assertRaises(ValueError):
            native_measurement(source,target,np.array([80.,80.],np.float32),np.array([80.,80.],np.float32))
    def test_low_texture_is_not_a_geometry_measurement(self):
        image=np.full((160,160),120,np.uint8)
        with self.assertRaisesRegex(ValueError,'low_texture'):
            native_measurement(image,image,np.array([80.,80.]),np.array([80.,80.]))

if __name__=='__main__':unittest.main()
