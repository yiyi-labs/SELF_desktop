"""A running reconstruction child must actually stop and discard its input."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import reconstruction_worker


class ReconstructionInputRetentionTest(unittest.TestCase):
    def test_cancel_status_is_published_after_retrying_input_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            (job / "job.json").write_text(json.dumps({"state": "cancel_requested"}),
                                          encoding="utf-8")
            (job / "cancel.requested").touch()
            (job / "frames").mkdir()
            (job / "frames" / "frame.png").write_bytes(b"private frame")
            remove = reconstruction_worker.shutil.rmtree
            observed = []

            def temporarily_busy(path):
                observed.append(json.loads((job / "job.json").read_text(
                    encoding="utf-8"))["state"])
                if len(observed) == 1:
                    raise OSError(39, "directory temporarily not empty")
                remove(path)

            with patch.object(reconstruction_worker.shutil, "rmtree",
                              side_effect=temporarily_busy):
                reconstruction_worker.finish_cancel(job)
            self.assertEqual(observed, ["cancel_requested", "cancel_requested"])
            self.assertEqual(json.loads((job / "job.json").read_text(
                encoding="utf-8"))["state"], "cancelled")
            self.assertFalse((job / "frames").exists())

    def test_successful_reconstruction_discards_source_before_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            (job / "job.json").write_text(json.dumps({"state": "queued", "progress": 25}),
                                          encoding="utf-8")
            (job / "capture.mp4").write_bytes(b"private capture")
            (job / "frames").mkdir()
            (job / "frames" / "frame_0001.png").write_bytes(b"private frame")
            (job / "portrait.gaussian.ply").write_bytes(b"published model")
            (job / "portrait.view.json").write_text("{}", encoding="utf-8")
            (job / "viewpoint_quality.json").write_text(
                json.dumps({"broadSideCoverage": True}), encoding="utf-8")
            assets = {"gaussian": {"file": "portrait.gaussian.ply"},
                      "view": {"file": "portrait.view.json"}}
            with patch.object(reconstruction_worker, "verify_capture"), \
                 patch.object(reconstruction_worker, "extract_frames", return_value=[]), \
                 patch.object(reconstruction_worker, "face_regions", return_value={}), \
                 patch.object(reconstruction_worker, "recover_cameras"), \
                 patch.object(reconstruction_worker, "opening_view", return_value=assets["view"]), \
                 patch.object(reconstruction_worker, "train_gaussians", return_value=assets["gaussian"]), \
                 patch.object(reconstruction_worker, "portrait_preview", side_effect=ValueError):
                reconstruction_worker.run_one(job)
            self.assertEqual(json.loads((job / "job.json").read_text(encoding="utf-8"))["state"],
                             "gaussian_ready")
            self.assertEqual({item.name for item in job.iterdir()},
                             {"job.json", "portrait.gaussian.ply", "portrait.view.json"})

    def test_finished_job_keeps_only_published_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            (job / "job.json").write_text('{"state":"gaussian_ready"}', encoding="utf-8")
            (job / "capture.mp4").write_bytes(b"private capture")
            (job / "frames").mkdir()
            (job / "frames" / "frame_0001.png").write_bytes(b"private frame")
            (job / "colmap.db").write_bytes(b"temporary reconstruction data")
            (job / "portrait.gaussian.ply").write_bytes(b"published model")
            (job / "portrait.view.json").write_text("{}", encoding="utf-8")
            reconstruction_worker.discard_training_inputs(job, {
                "gaussian": {"file": "portrait.gaussian.ply"},
                "view": {"file": "portrait.view.json"},
            })
            self.assertEqual({item.name for item in job.iterdir()},
                             {"job.json", "portrait.gaussian.ply", "portrait.view.json"})

    def test_failed_job_removes_capture_and_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)
            (job / "job.json").write_text(json.dumps({"state": "queued", "progress": 25}),
                                          encoding="utf-8")
            (job / "capture.mp4").write_bytes(b"private capture")
            with patch.object(reconstruction_worker, "verify_capture",
                              side_effect=reconstruction_worker.ReconstructionFailure("invalid_capture")):
                reconstruction_worker.run_one(job)
            self.assertEqual({item.name for item in job.iterdir()}, {"job.json"})
            self.assertEqual(json.loads((job / "job.json").read_text())["state"], "failed")


@unittest.skipUnless(os.name == "posix", "process-group cancellation runs in WSL")
class ReconstructionCancelTest(unittest.TestCase):
    def test_running_child_is_terminated_and_capture_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "reconstruction_worker.py"
            script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
            job = root / ("a" * 32)
            job.mkdir()
            (job / "job.json").write_text(json.dumps({"state": "running", "progress": 35}),
                                           encoding="utf-8")
            (job / "capture.mp4").write_bytes(b"private test payload")

            def cancel():
                time.sleep(.7)
                (job / "cancel.requested").touch()

            trigger = threading.Thread(target=cancel)
            trigger.start()
            started = time.monotonic()
            with patch.object(reconstruction_worker, "HERE", root):
                reconstruction_worker.supervise_job(job)
            trigger.join()
            self.assertLess(time.monotonic() - started, 8)
            self.assertEqual(json.loads((job / "job.json").read_text())["state"], "cancelled")
            self.assertFalse((job / "capture.mp4").exists())


if __name__ == "__main__":
    unittest.main()
