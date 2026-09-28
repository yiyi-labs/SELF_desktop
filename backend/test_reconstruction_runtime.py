"""Routing cannot substitute a different person's cached reconstruction."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import reconstruction_worker as worker
from reconstruction_runtime import engine_profile,verified_preparation,PORTRAIT_TEST
from reconstruction_live_prepare import selected_names


class RuntimeTest(unittest.TestCase):
    def test_unknown_or_unauthorized_profile_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/"engine-profile.json"
            self.assertEqual(engine_profile(root)["engine"],"gsplat-colmap")
            for value in ({"engine":"unknown"},{"engine":PORTRAIT_TEST}):
                profile.write_text(json.dumps(value))
                with self.assertRaises(ValueError):engine_profile(root)

    def test_cache_requires_exact_capture_and_private_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cache=root/".sources/cache";cache.mkdir(parents=True)
            (cache/"preparation.json").write_text(json.dumps({"sourceHash":"a"}))
            profile={"preparedCache":".sources/cache"}
            self.assertIsNone(verified_preparation(profile,"b",root))
            self.assertEqual(verified_preparation(profile,"a",root),cache)
            with self.assertRaises(ValueError):verified_preparation({"preparedCache":"../elsewhere"},"a",root)

    def test_test_engine_dispatches_and_preserves_quality_and_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);job=root/("a"*32);job.mkdir()
            (root/"engine-profile.json").write_text(json.dumps({"engine":PORTRAIT_TEST,"userTestingAuthorized":True}))
            (job/"job.json").write_text(json.dumps({"state":"queued","sha256":"a"}))
            (job/"capture.mp4").write_bytes(b"private capture")
            (job/"portrait.gaussian.ply").write_bytes(b"test result")
            (job/"portrait.view.json").write_text("{}")
            assets={"gaussian":{"file":"portrait.gaussian.ply"},"view":{"file":"portrait.view.json"}}
            with patch.object(worker,"ROOT",root),patch.object(worker,"verify_capture"), \
                 patch("reconstruction_runtime.reconstruct_test",return_value=(assets,{"releaseApproved":False})), \
                 patch.object(worker,"portrait_preview",side_effect=ValueError), \
                 patch.object(worker,"extract_frames") as legacy:
                worker.run_one(job)
            result=json.loads((job/"job.json").read_text())
            self.assertEqual(result["algorithm"],PORTRAIT_TEST)
            self.assertEqual(result["state"],"gaussian_ready")
            self.assertFalse(result["reconstructionQuality"]["releaseApproved"])
            self.assertFalse((job/"capture.mp4").exists())
            legacy.assert_not_called()

    def test_selection_uses_names_not_colmap_ids_and_no_duplicates(self):
        names=[f"frame_{i:04d}.png" for i in range(1,161)]
        result=selected_names(names)
        self.assertEqual(len(result),32);self.assertEqual(len(set(result)),32)
        self.assertEqual(result[0],names[0]);self.assertEqual(result[-1],names[-1])


if __name__=="__main__":unittest.main()
