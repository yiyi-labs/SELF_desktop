import asyncio
import hashlib
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import recon_transfer
from app import app


class ReconstructionTransportTest(unittest.TestCase):
    def test_cancel_after_completion_returns_terminal_state_and_preserves_result(self):
        body={"totalBytes":1024,"sha256":"a"*64,"format":"mp4"}
        job_id=self.client.post('/v1/reconstruction/jobs',json=body,headers=self.headers).json()['jobId']
        path=Path(self.root.name)/job_id
        result=path/'portrait.gaussian.ply';result.write_bytes(b'retained model')
        for state in ('gaussian_ready','complete'):
            job=recon_transfer._read_job(path);job.update(state=state)
            recon_transfer._save_job(path,job)
            receipt=self.client.post(f'/v1/reconstruction/jobs/{job_id}/cancel',headers=self.headers)
            self.assertEqual(receipt.status_code,200)
            self.assertEqual(receipt.json()['state'],state)
            self.assertEqual(recon_transfer._read_job(path)['state'],state)
            self.assertEqual(result.read_bytes(),b'retained model')
            self.assertFalse((path/'cancel.requested').exists())

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

    def test_cancel_receiving_and_queued_jobs_discards_capture(self):
        payload = b"a" * 1024
        for seal in (False, True):
            created = self.client.post("/v1/reconstruction/jobs", json={
                "totalBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                "format": "mp4"}, headers=self.headers)
            job_id = created.json()["jobId"]
            url = f"/v1/reconstruction/jobs/{job_id}"
            chunk_headers = {**self.headers, "X-Content-SHA256": hashlib.sha256(payload).hexdigest()}
            self.assertEqual(self.client.put(url + "/chunks/0", content=payload,
                                             headers=chunk_headers).status_code, 200)
            if seal:
                self.assertEqual(self.client.post(url + "/seal", headers=self.headers).status_code, 200)
            self.assertEqual(self.client.post(url + "/cancel").status_code, 401)
            cancelled = self.client.post(url + "/cancel", headers=self.headers)
            self.assertEqual(cancelled.status_code, 200)
            self.assertEqual(cancelled.json()["state"], "cancel_requested" if seal else "cancelled")
            if seal:
                from reconstruction_worker import finish_cancel
                finish_cancel(Path(self.root.name) / job_id)
            self.assertEqual(self.client.post(url + "/cancel", headers=self.headers).status_code, 200)
            self.assertEqual(self.client.get(url, headers=self.headers).json()["state"], "cancelled")
            self.assertFalse((Path(self.root.name) / job_id / "capture.mp4").exists())
            self.assertFalse((Path(self.root.name) / job_id / "chunks").exists())
            self.assertEqual(self.client.put(url + "/chunks/0", content=payload,
                                             headers=chunk_headers).status_code, 409)

    def test_running_cancel_requests_worker_stop(self):
        payload = b"a" * 1024
        created = self.client.post("/v1/reconstruction/jobs", json={
            "totalBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "format": "mp4"}, headers=self.headers)
        job_id = created.json()["jobId"]
        path = Path(self.root.name) / job_id
        job = recon_transfer._read_job(path)
        job["state"] = "running"
        recon_transfer._save_job(path, job)
        response = self.client.post(f"/v1/reconstruction/jobs/{job_id}/cancel", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "cancel_requested")
        self.assertTrue((path / "cancel.requested").exists())

    def test_cancel_while_chunk_is_streaming_cannot_restore_video(self):
        payload = b"a" * 1024
        job_id = self.client.post("/v1/reconstruction/jobs", json={
            "totalBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "format": "mp4"}, headers=self.headers).json()["jobId"]
        started, release = threading.Event(), threading.Event()
        outcome = []

        class SlowRequest:
            headers = {"authorization": "Bearer test-token",
                       "x-content-sha256": hashlib.sha256(payload).hexdigest()}

            async def stream(self):
                started.set()
                release.wait(5)
                yield payload

        def upload():
            try:
                asyncio.run(recon_transfer.put_chunk(job_id, 0, SlowRequest()))
            except Exception as error:
                outcome.append(error)

        thread = threading.Thread(target=upload)
        thread.start()
        try:
            self.assertTrue(started.wait(5))
            cancelled = self.client.post(f"/v1/reconstruction/jobs/{job_id}/cancel",
                                         headers=self.headers)
            self.assertEqual(cancelled.json()["state"], "cancelled")
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertEqual(outcome[0].status_code, 409)
        path = Path(self.root.name) / job_id
        self.assertEqual(recon_transfer._read_job(path)["state"], "cancelled")
        self.assertFalse((path / "chunks").exists())
        self.assertFalse((path / "capture.mp4").exists())

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

    def test_gaussian_is_chunked_but_not_claimed_as_editable_mesh(self):
        payload = b"a" * 1024
        job_id = self.client.post("/v1/reconstruction/jobs", json={
            "totalBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "format": "mp4",
        }, headers=self.headers).json()["jobId"]
        job_dir = Path(self.root.name) / job_id
        gaussian = b"ply\nformat binary_little_endian 1.0\nelement vertex 1\nend_header\n" + bytes(range(256)) * 5000
        (job_dir / "portrait.gaussian.ply").write_bytes(gaussian)
        view = b'{"schemaVersion":1,"sourceFrame":"frame_0001.png","target":[0,0,1],"camera":[0,0,0],"up":[0,1,0],"fovDegrees":50,"faceTrackCount":80}'
        (job_dir / "portrait.view.json").write_bytes(view)
        job = recon_transfer._read_job(job_dir)
        job.update(state="gaussian_ready", assets={"gaussian": {
            "file": "portrait.gaussian.ply", "bytes": len(gaussian),
            "sha256": hashlib.sha256(gaussian).hexdigest()}, "view": {
            "file": "portrait.view.json", "bytes": len(view),
            "sha256": hashlib.sha256(view).hexdigest()}},
            viewpointQuality={"registeredViews": 43, "minYawDegrees": -24.3,
                              "maxYawDegrees": 18.7, "broadSideCoverage": False})
        recon_transfer._save_job(job_dir, job)
        base = f"/v1/reconstruction/jobs/{job_id}/assets"
        status = self.client.get(f"/v1/reconstruction/jobs/{job_id}", headers=self.headers).json()
        self.assertEqual(status["state"], "gaussian_ready")
        self.assertFalse(status["viewpointQuality"]["broadSideCoverage"])
        self.assertEqual(self.client.get(base + "/mesh", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get(base + "/gaussian/chunks/0", headers=self.headers).content,
                         gaussian[:recon_transfer.CHUNK_BYTES])
        self.assertEqual(self.client.get(base + "/gaussian/chunks/1", headers=self.headers).content,
                         gaussian[recon_transfer.CHUNK_BYTES:])
        self.assertEqual(self.client.get(base + "/gaussian/chunks/2", headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get(base + "/view", headers=self.headers).content, view)
        (job_dir / "portrait.view.json").write_bytes(view[:-1] + b"x")
        self.assertEqual(self.client.get(base + "/view", headers=self.headers).status_code, 409)

    def test_star_preview_is_bounded_and_hash_checked(self):
        payload = b"a" * 1024
        job_id = self.client.post("/v1/reconstruction/jobs", json={
            "totalBytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "format": "mp4",
        }, headers=self.headers).json()["jobId"]
        job_dir = Path(self.root.name) / job_id
        preview = b"\x89PNG\r\n\x1a\n" + b"p" * 512
        preview3d = b"ply\nformat binary_little_endian 1.0\n" + b"p" * 8192
        (job_dir / "portrait.preview.png").write_bytes(preview)
        (job_dir / "portrait.preview.gaussian.ply").write_bytes(preview3d)
        job = recon_transfer._read_job(job_dir)
        job.update(state="gaussian_ready", assets={name: {
            "file": filename, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, filename, data in (
                ("preview", "portrait.preview.png", preview),
                ("preview3d", "portrait.preview.gaussian.ply", preview3d))})
        recon_transfer._save_job(job_dir, job)
        base = f"/v1/reconstruction/jobs/{job_id}/assets"
        self.assertEqual(self.client.get(base + "/preview", headers=self.headers).content, preview)
        self.assertEqual(self.client.get(base + "/preview3d", headers=self.headers).content, preview3d)
        (job_dir / "portrait.preview.gaussian.ply").write_bytes(preview3d[:-1] + b"x")
        self.assertEqual(self.client.get(base + "/preview3d", headers=self.headers).status_code, 409)


if __name__ == "__main__":
    unittest.main()
