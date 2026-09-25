"""Exercise the running USB-local service with disposable, non-image bytes."""

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8787/v1/reconstruction"


def token() -> str:
    for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("SELF_BACKEND_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"\'')
    raise RuntimeError("SELF_BACKEND_TOKEN is missing")


def request(method: str, path: str, auth: str, body: bytes = b"", digest: str = "") -> dict:
    headers = {"Authorization": "Bearer " + auth}
    if digest:
        headers["X-Content-SHA256"] = digest
    if method == "POST" and path == "/jobs":
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=body if method in {"POST", "PUT"} else None,
        headers=headers, method=method), timeout=15) as response:
        return json.load(response)


def main() -> None:
    auth = token()
    payload = b"SELF disposable cancellation probe." * 64
    digest = hashlib.sha256(payload).hexdigest()
    job_id = ""
    try:
        created = request("POST", "/jobs", auth, json.dumps({
            "totalBytes": len(payload), "sha256": digest, "format": "mp4"
        }).encode("utf-8"))
        job_id = created["jobId"]
        request("PUT", f"/jobs/{job_id}/chunks/0", auth, payload, digest)
        request("POST", f"/jobs/{job_id}/seal", auth)
        request("POST", f"/jobs/{job_id}/cancel", auth)
        deadline = time.monotonic() + 35
        state = ""
        while time.monotonic() < deadline:
            state = request("GET", f"/jobs/{job_id}", auth)["state"]
            if state == "cancelled":
                break
            time.sleep(.5)
        folder = HERE / ".data" / "reconstruction" / job_id
        if state != "cancelled" or (folder / "capture.mp4").exists() or (folder / "chunks").exists():
            raise RuntimeError("live cancellation did not remove the test input")
        print(json.dumps({"liveService": "passed", "state": state,
                          "captureRemoved": True, "chunksRemoved": True}))
    finally:
        if job_id:
            try:
                request("DELETE", f"/jobs/{job_id}", auth)
            except urllib.error.HTTPError:
                pass

    # A rejected clip also must not linger on the PC. The payload is deliberately
    # not a video or an image and cannot contain a person's face.
    job_id = ""
    try:
        created = request("POST", "/jobs", auth, json.dumps({
            "totalBytes": len(payload), "sha256": digest, "format": "mp4"
        }).encode("utf-8"))
        job_id = created["jobId"]
        request("PUT", f"/jobs/{job_id}/chunks/0", auth, payload, digest)
        request("POST", f"/jobs/{job_id}/seal", auth)
        deadline = time.monotonic() + 35
        state = ""
        while time.monotonic() < deadline:
            state = request("GET", f"/jobs/{job_id}", auth)["state"]
            if state == "failed":
                break
            time.sleep(.5)
        folder = HERE / ".data" / "reconstruction" / job_id
        if state != "failed" or (folder / "capture.mp4").exists() or (folder / "frames").exists():
            raise RuntimeError("live failed job retained test input")
        print(json.dumps({"liveFailure": "passed", "state": state,
                          "captureRemoved": True, "framesRemoved": True}))
    finally:
        if job_id:
            try:
                request("DELETE", f"/jobs/{job_id}", auth)
            except urllib.error.HTTPError:
                pass


if __name__ == "__main__":
    main()
