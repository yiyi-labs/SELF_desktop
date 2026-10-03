import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from capture_registration import track_split,quality_accepted,projection_quality,propose_windows,existing_static_window


class RegistrationContracts(unittest.TestCase):
    def test_existing_window_requires_real_baseline_and_never_uses_development(self):
        class P:
            point3D_id=1
            def has_point3D(self):return True
        class Image:
            points2D=[P()]
            def __init__(self,x):self.x=x
            def cam_from_world(self):
                a=np.eye(4)[:3];a[0,3]=self.x;return SimpleNamespace(matrix=lambda:a)
        model=SimpleNamespace(points3D={1:SimpleNamespace(xyz=np.array([0.,0.,5.]))})
        times={'alpha':1.,'beta':1.4,'gamma':1.8};images={n:Image(0.) for n in times}
        self.assertIsNone(existing_static_window(model,images,set(),times))
        images['beta']=Image(.1);images['gamma']=Image(.2)
        self.assertIsNotNone(existing_static_window(model,images,set(),times))
        self.assertIsNone(existing_static_window(model,images,{'gamma'},times))

    def test_windows_use_real_names_times_training_anchors_and_bounded_count(self):
        names=[f'observation-{i:02d}.png' for i in range(30)]
        marks={}
        for i,n in enumerate(names):
            m=np.zeros((468,2),np.float32);m[10]=[50,10];m[152]=[50,90]
            m[234]=[10,50];m[454]=[90+i*.1,50];marks[n]=m
        times={n:i*.4 for i,n in enumerate(names)};dev={names[29],names[20]}
        with patch('cv2.imread',return_value=np.zeros((150,150),np.uint8)):
            windows=propose_windows(names,set(names),dev,marks,times,Path('unused'))
        self.assertEqual(len(windows),2)
        for w in windows:
            self.assertNotIn(w['anchor'],dev);self.assertFalse(set(w['names'])&dev)
            self.assertLessEqual(len(w['names']),9)
            self.assertTrue(all(abs(times[n]-times[w['anchor']])<=1.75 for n in w['names']))
        self.assertGreater(abs(times[windows[0]['anchor']]-times[windows[1]['anchor']]),3.5)

    def test_same_physical_track_never_leaks_across_fit_and_holdout(self):
        ids=np.arange(100,500);a,b=track_split(ids)
        self.assertFalse(np.any(a&b));self.assertTrue(np.all(a|b))
        self.assertGreater(b.sum(),20)
        c,d=track_split(ids[::-1]);np.testing.assert_array_equal(a,c[::-1]);np.testing.assert_array_equal(b,d[::-1])
        with self.assertRaises(ValueError):track_split([1,2,1])

    def test_large_match_count_cannot_bypass_held_geometry(self):
        fit={'count':200};held={'count':40,'positiveDepthFraction':1.,'medianPx':1.,'p90Px':2.,
                              'gridCells4x4':6,'imageHullFraction':.2}
        self.assertTrue(quality_accepted(fit,held,120))
        for field,value in [('positiveDepthFraction',.9),('medianPx',4.),('p90Px',10.),
                            ('gridCells4x4',1),('imageHullFraction',.001)]:
            self.assertFalse(quality_accepted(fit,{**held,field:value},120))
        self.assertFalse(quality_accepted(fit,held,30))

    def test_validation_uses_actual_full_camera_projection_and_depth(self):
        import pycolmap
        camera=pycolmap.Camera(model='PINHOLE',width=1000,height=1000,params=[500,500,500,500])
        xyz=np.array([[-1,-1,2],[1,-1,2],[-1,1,2],[1,1,2]],float)
        obs=camera.img_from_cam(xyz);row=projection_quality(xyz,obs,np.eye(4),camera)
        self.assertEqual(row['medianPx'],0);self.assertEqual(row['positiveDepthFraction'],1)
        self.assertEqual(row['gridCells4x4'],4);self.assertAlmostEqual(row['imageHullFraction'],.25)


if __name__=='__main__':unittest.main()
