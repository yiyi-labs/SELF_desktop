import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import recon_transfer
from app import app


class ReconstructionTransportTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(recon_transfer, "ROOT", Path(self.root.name)),
            patch.dict(os.environ, {"SELF_BACKEND_TOKEN": "test-token", "SELF_DEV_LOOPBACK": "0"}),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(app)
        self.headers = {"Authorization": "Bearer test-token"}

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.root.cleanup()

    def test_binary_echo_and_resumable_capture_are_exact(self):
        payload = bytes(range(256)) * 4096 + b"SELF-face"
        response = self.client.post("/v1/reconstruction/echo", content=payload[:1024], headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, payload[:1024])
        self.assertEqual(response.headers["x-content-sha256"], hashlib.sha256(payload[:1024]).hexdigest())

        created = self.client.post("/v1/reconstruction/jobs", json={
            "totalBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "format": "mp4",
        }, headers=self.headers)
        self.assertEqual(created.status_code, 200)
        job_id = created.json()["jobId"]
        chunks = [payload[:recon_transfer.CHUNK_BYTES], payload[recon_transfer.CHUNK_BYTES:]]
        for index, chunk in enumerate(chunks):
            url = f"/v1/reconstruction/jobs/{job_id}/chunks/{index}"
            headers = {**self.headers, "X-Content-SHA256": hashlib.sha256(chunk).hexdigest()}
            result = self.client.put(url, content=chunk, headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(self.client.put(url, content=chunk, headers=headers).status_code, 200)
        sealed = self.client.post(f"/v1/reconstruction/jobs/{job_id}/seal", headers=self.headers)
        self.assertEqual(sealed.status_code, 200)
        self.assertEqual((Path(self.root.name) / job_id / "capture.mp4").read_bytes(), payload)
        self.assertEqual(self.client.get(f"/v1/reconstruction/jobs/{job_id}/assets/mesh", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.delete(f"/v1/reconstruction/jobs/{job_id}", headers=self.headers).status_code, 200)

    def test_rejects_bad_digest_and_missing_authorization(self):
        payload = b"a" * 1024
        self.assertEqual(self.client.post("/v1/reconstruction/echo", content=payload).status_code, 401)
        job_id = self.client.post("/v1/reconstruction/jobs", json={
            "totalBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "format": "mp4",
        }, headers=self.headers).json()["jobId"]
        bad = self.client.put(f"/v1/reconstruction/jobs/{job_id}/chunks/0", content=payload,
                              headers={**self.headers, "X-Content-SHA256": "0" * 64})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.client.post(f"/v1/reconstruction/jobs/{job_id}/seal", headers=self.headers).status_code, 409)

    def test_completed_asset_requires_matching_size_and_digest(self):
        payload = b"a" * 1024
        job_id = self.client.post("/v1/reconstruction/jobs", json={
            "totalBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "format": "mp4",
        }, headers=self.headers).json()["jobId"]
        job_dir = Path(self.root.name) / job_id
        model = b"glTF" + (2).to_bytes(4, "little") + (1024).to_bytes(4, "little") + bytes(1012)
        (job_dir / "fixture.glb").write_bytes(model)
        job = recon_transfer._read_job(job_dir)
        job["state"] = "complete"
        job["assets"] = {"mesh": {"file": "fixture.glb", "bytes": len(model),
                                 "sha256": hashlib.sha256(model).hexdigest()}}
        recon_transfer._save_job(job_dir, job)
        url = f"/v1/reconstruction/jobs/{job_id}/assets/mesh"
        response = self.client.get(url, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, model)
        (job_dir / "fixture.glb").write_bytes(model[:-1] + b"x")
        self.assertEqual(self.client.get(url, headers=self.headers).status_code, 409)


if __name__ == "__main__":
    unittest.main()
