import hashlib
import json
import math
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import recon_transfer
from app import app
from portrait_preview import create_scene_lod, _read_splats


def fixture(path: Path) -> tuple[bytes, bytes]:
    header = ("ply\nformat binary_little_endian 1.0\nelement vertex 32000\n"
              "property float x\nproperty float y\nproperty float z\n"
              "property float f_dc_0\nproperty float f_dc_1\nproperty float f_dc_2\n"
              "property float opacity\nproperty float scale_0\n"
              "property float scale_1\nproperty float scale_2\nend_header\n").encode()
    points = bytearray()
    for i in range(32000):
        distant = i >= 16000
        x = (5 if distant else 0) + (i % 100) * .01
        size = 1.0 if i % 5 == 0 else .04
        points.extend(struct.pack("<ffffffffff", x, (i // 100 % 100) * .01, 0,
                                  .2, .1, .3, 3.0, math.log(size), math.log(size), math.log(size)))
    gaussian = header + points
    view = json.dumps({"schemaVersion": 1, "sourceFrame": "frame_0001.png", "sourceFaceFraction": .32,
                       "targetFaceFraction": .5, "target": [0, 0, 0],
                       "camera": [0, 0, 3], "up": [0, 1, 0],
                       "fovDegrees": 50, "faceTrackCount": 80}).encode()
    (path / "portrait.gaussian.ply").write_bytes(gaussian)
    (path / "portrait.view.json").write_bytes(view)
    return gaussian, view


class ScenePreviewTest(unittest.TestCase):
    def test_spatial_sampling_keeps_surroundings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            fixture(path)
            output = create_scene_lod(path, limit=8000)
            splats = _read_splats(output)
            self.assertEqual(len(splats), 8000)
            self.assertGreater(sum(splats["x"] > 4), 1500)
            self.assertGreater(sum(splats["x"] < 2), 1500)
            self.assertTrue(all(splats["scale_0"] < 0))
            self.assertLess(output.stat().st_size, 12 * 1024 * 1024)

    def test_authenticated_backfill_without_source_video(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(recon_transfer, "ROOT", Path(directory)), \
             patch.dict(os.environ, {"SELF_BACKEND_TOKEN": "test-token"}):
            client = TestClient(app)
            created = client.post("/v1/reconstruction/jobs", json={
                "totalBytes": 1024, "sha256": "0" * 64, "format": "mp4"},
                headers={"Authorization": "Bearer test-token"}).json()
            job_id = created["jobId"]
            path = Path(directory) / job_id
            gaussian, view = fixture(path)
            job = recon_transfer._read_job(path)
            job.update(state="gaussian_ready", assets={
                name: {"file": filename, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, filename, data in (("gaussian", "portrait.gaussian.ply", gaussian),
                                             ("view", "portrait.view.json", view))})
            recon_transfer._save_job(path, job)
            url = f"/v1/reconstruction/jobs/{job_id}/scene-preview"
            self.assertEqual(client.post(url).status_code, 401)
            first = client.post(url, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(first.status_code, 200)
            second = client.post(url, headers={"Authorization": "Bearer test-token"})
            self.assertEqual(second.json(), first.json())
            asset = client.get(f"/v1/reconstruction/jobs/{job_id}/assets/scene3d",
                               headers={"Authorization": "Bearer test-token"})
            self.assertEqual(asset.status_code, 200)
            self.assertEqual(hashlib.sha256(asset.content).hexdigest(), first.json()["sha256"])
            self.assertFalse((path / "capture.mp4").exists())
            client.close()


if __name__ == "__main__":
    unittest.main()
