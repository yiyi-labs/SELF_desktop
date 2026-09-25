"""Private, resumable capture transport for SELF reconstruction jobs.

The route does not claim that an uploaded clip is a reconstructed portrait.
Only a separately validated reconstruction worker may publish assets.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response


router = APIRouter(prefix="/v1/reconstruction")
def _default_jobs_root() -> Path:
    """Stable private data location, independent of source checkout and rebuilds."""
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "SELF" / "Reconstruction"
    return Path(os.getenv("XDG_DATA_HOME") or (Path.home() / ".local" / "share")) / "SELF" / "reconstruction"


ROOT = Path(os.getenv("SELF_RECON_JOBS_DIR") or _default_jobs_root()).resolve()
JOB_RE = re.compile(r"^[a-f0-9]{32}$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
CHUNK_BYTES = 1024 * 1024
MAX_CAPTURE_BYTES = 1024 * 1024 * 1024
MAX_CHUNKS = (MAX_CAPTURE_BYTES + CHUNK_BYTES - 1) // CHUNK_BYTES
_JOB_LOCKS: dict[str, threading.RLock] = {}
_JOB_LOCKS_GUARD = threading.Lock()


def _job_lock(job_id: str) -> threading.RLock:
    with _JOB_LOCKS_GUARD:
        return _JOB_LOCKS.setdefault(job_id, threading.RLock())


def _authorize(request: Request) -> None:
    token = os.getenv("SELF_BACKEND_TOKEN", "")
    if token:
        if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            raise HTTPException(401, "unauthorized")
    elif not (
        os.getenv("SELF_DEV_LOOPBACK") == "1"
        and request.client
        and request.client.host in {"127.0.0.1", "::1", "testclient"}
    ):
        raise HTTPException(503, "backend_auth_not_configured")


def _job_dir(job_id: str) -> Path:
    if not JOB_RE.fullmatch(job_id):
        raise HTTPException(404, "job_not_found")
    path = ROOT / job_id
    if not path.is_dir():
        raise HTTPException(404, "job_not_found")
    return path


def _read_job(path: Path) -> dict:
    return json.loads((path / "job.json").read_text(encoding="utf-8"))


def _save_job(path: Path, job: dict) -> None:
    temporary = path / f"job.{secrets.token_hex(4)}.tmp"
    temporary.write_text(json.dumps(job, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path / "job.json")


def _discard_job_payload(path: Path) -> None:
    """Keep a status tombstone, but discard personal footage and intermediates."""
    for item in path.iterdir():
        if item.name in {"job.json", "cancel.requested"}:
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink(missing_ok=True)


@router.get("/health")
def health(request: Request):
    _authorize(request)
    engine = "not-verified"
    heartbeat = ROOT / "worker_status.json"
    try:
        state = json.loads(heartbeat.read_text(encoding="utf-8"))
        if state.get("ready") is True and time.time() - state.get("updatedAt", 0) < 30:
            engine = "ready"
    except (OSError, ValueError, TypeError):
        pass
    return {"status": "ready", "protocol": 1, "chunkBytes": CHUNK_BYTES,
            "maxCaptureBytes": MAX_CAPTURE_BYTES, "engine": engine}


@router.post("/echo")
async def echo(request: Request):
    """One-megabyte binary round trip used by device acceptance tests."""
    _authorize(request)
    data = await request.body()
    if not 1 <= len(data) <= CHUNK_BYTES:
        raise HTTPException(413, "echo_size")
    return Response(data, media_type="application/octet-stream",
                    headers={"X-Content-SHA256": hashlib.sha256(data).hexdigest()})


@router.post("/jobs")
async def create_job(request: Request):
    _authorize(request)
    body = await request.body()
    if len(body) > 2048:
        raise HTTPException(413, "manifest_size")
    try:
        payload = json.loads(body)
        if set(payload) != {"totalBytes", "sha256", "format"}:
            raise ValueError()
        total = payload["totalBytes"]
        digest = payload["sha256"]
        if type(total) is not int or not 1024 <= total <= MAX_CAPTURE_BYTES:
            raise ValueError()
        if not isinstance(digest, str) or not SHA_RE.fullmatch(digest):
            raise ValueError()
        if payload["format"] != "mp4":
            raise ValueError()
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(422, "invalid_manifest") from None
    ROOT.mkdir(parents=True, exist_ok=True)
    job_id = secrets.token_hex(16)
    path = ROOT / job_id
    path.mkdir(mode=0o700)
    job = {"schemaVersion": 1, "jobId": job_id, "state": "receiving",
           "totalBytes": total, "sha256": digest, "format": "mp4",
           "createdAt": int(time.time()), "receivedChunks": [], "progress": 0,
           "message": "", "assets": {}}
    _save_job(path, job)
    return {"jobId": job_id, "chunkBytes": CHUNK_BYTES, "state": "receiving"}


@router.put("/jobs/{job_id}/chunks/{index}")
async def put_chunk(job_id: str, index: int, request: Request):
    _authorize(request)
    path = _job_dir(job_id)
    job = _read_job(path)
    if job["state"] != "receiving" or (path / "cancel.requested").exists():
        raise HTTPException(409, "job_not_receiving")
    count = (job["totalBytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES
    if not 0 <= index < count or count > MAX_CHUNKS:
        raise HTTPException(422, "chunk_index")
    expected_size = min(CHUNK_BYTES, job["totalBytes"] - index * CHUNK_BYTES)
    expected_sha = request.headers.get("x-content-sha256", "")
    if not SHA_RE.fullmatch(expected_sha):
        raise HTTPException(422, "chunk_digest")
    data = bytearray()
    async for piece in request.stream():
        data.extend(piece)
        if len(data) > expected_size:
            raise HTTPException(413, "chunk_size")
    if len(data) != expected_size:
        raise HTTPException(422, "chunk_size")
    actual_sha = hashlib.sha256(data).hexdigest()
    if not hmac.compare_digest(actual_sha, expected_sha):
        raise HTTPException(422, "chunk_digest")
    with _job_lock(job_id):
        job = _read_job(path)
        if job["state"] != "receiving" or (path / "cancel.requested").exists():
            raise HTTPException(409, "job_not_receiving")
        chunks = path / "chunks"
        chunks.mkdir(exist_ok=True)
        target = chunks / f"{index:04d}.bin"
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != actual_sha:
                raise HTTPException(409, "chunk_conflict")
        else:
            temporary = chunks / f"{index:04d}.tmp"
            temporary.write_bytes(data)
            os.replace(temporary, target)
        received = set(job["receivedChunks"])
        received.add(index)
        job["receivedChunks"] = sorted(received)
        job["progress"] = min(25, round(25 * len(received) / count))
        _save_job(path, job)
    return {"index": index, "sha256": actual_sha, "received": len(received), "total": count}


@router.post("/jobs/{job_id}/seal")
def seal_job(job_id: str, request: Request):
    _authorize(request)
    path = _job_dir(job_id)
    with _job_lock(job_id):
        job = _read_job(path)
        if job["state"] == "queued":
            return {"jobId": job_id, "state": "queued"}
        if job["state"] != "receiving" or (path / "cancel.requested").exists():
            raise HTTPException(409, "job_not_receiving")
        count = (job["totalBytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES
        if job["receivedChunks"] != list(range(count)):
            raise HTTPException(409, "missing_chunks")
        digest = hashlib.sha256()
        temporary = path / "capture.mp4.tmp"
        with temporary.open("wb") as output:
            for index in range(count):
                data = (path / "chunks" / f"{index:04d}.bin").read_bytes()
                output.write(data)
                digest.update(data)
        if temporary.stat().st_size != job["totalBytes"] or not hmac.compare_digest(digest.hexdigest(), job["sha256"]):
            temporary.unlink(missing_ok=True)
            raise HTTPException(422, "capture_digest")
        os.replace(temporary, path / "capture.mp4")
        job["state"] = "queued"
        job["progress"] = 25
        _save_job(path, job)
        shutil.rmtree(path / "chunks")
        return {"jobId": job_id, "state": "queued", "sha256": job["sha256"]}


@router.get("/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    _authorize(request)
    job = _read_job(_job_dir(job_id))
    result = {key: job[key] for key in ("jobId", "state", "progress", "message", "assets")}
    if "viewpointQuality" in job:
        result["viewpointQuality"] = job["viewpointQuality"]
    return result


@router.post("/jobs/{job_id}/scene-preview")
def ensure_scene_preview(job_id: str, request: Request):
    """Backfill a full-scene LOD from a retained model, without source footage."""
    _authorize(request)
    path = _job_dir(job_id)
    with _job_lock(job_id):
        job = _read_job(path)
        if job["state"] not in {"gaussian_ready", "complete"}:
            raise HTTPException(409, "model_not_ready")
        gaussian, _ = _verified_asset(job_id, "gaussian")
        view, _ = _verified_asset(job_id, "view")
        if not gaussian.is_file() or not view.is_file():
            raise HTTPException(409, "model_not_ready")
        existing = job["assets"].get("scene3d")
        if existing and existing.get("file") == "portrait.scene-v3.gaussian.ply":
            _verified_asset(job_id, "scene3d")
            return existing
        from portrait_preview import create_scene_lod
        try:
            output = create_scene_lod(path)
        except (ValueError, OSError, ImportError):
            raise HTTPException(422, "scene_preview_unavailable") from None
        manifest = {"file": output.name, "bytes": output.stat().st_size,
                    "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
        previous = job["assets"].get("scene3d")
        job["assets"]["scene3d"] = manifest
        _save_job(path, job)
        if previous and previous.get("file") in {"portrait.scene.gaussian.ply", "portrait.scene-v2.gaussian.ply"}:
            (path / previous["file"]).unlink(missing_ok=True)
        return manifest


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request):
    _authorize(request)
    path = _job_dir(job_id)
    with _job_lock(job_id):
        job = _read_job(path)
        if job["state"] in {"complete", "gaussian_ready"}:
            raise HTTPException(409, "job_already_finished")
        if job["state"] == "cancelled":
            return {"jobId": job_id, "state": "cancelled"}
        (path / "cancel.requested").touch(exist_ok=True)
        if job["state"] in {"receiving", "failed"}:
            _discard_job_payload(path)
            job.update(state="cancelled", progress=0, message="", assets={})
            _save_job(path, job)
            return {"jobId": job_id, "state": "cancelled"}
        # A worker may start a queued job while this request is in flight. Let its
        # supervisor reap the process before any input or working file is removed.
        job.update(state="cancel_requested", message="")
        _save_job(path, job)
        return {"jobId": job_id, "state": "cancel_requested"}


@router.get("/jobs/{job_id}/assets/{kind}")
def asset(job_id: str, kind: str, request: Request):
    _authorize(request)
    path, manifest = _verified_asset(job_id, kind)
    return FileResponse(path, media_type="image/png" if kind == "preview" else "model/gltf-binary" if kind == "mesh" else "application/octet-stream",
                        headers={"X-Content-SHA256": manifest["sha256"]})


def _verified_asset(job_id: str, kind: str, verify_digest: bool = True) -> tuple[Path, dict]:
    job = _read_job(_job_dir(job_id))
    if kind not in {"mesh", "gaussian", "view", "preview", "preview3d", "scene3d"} or (job["state"] != "complete" and not (job["state"] == "gaussian_ready" and kind in {"gaussian", "view", "preview", "preview3d", "scene3d"})):
        raise HTTPException(404, "asset_not_ready")
    manifest = job["assets"].get(kind)
    if not manifest:
        raise HTTPException(404, "asset_not_ready")
    if (not isinstance(manifest.get("file"), str)
            or Path(manifest["file"]).name != manifest["file"]
            or not isinstance(manifest.get("sha256"), str)
            or not SHA_RE.fullmatch(manifest["sha256"])
            or type(manifest.get("bytes")) is not int
            or not (128 if kind == "view" else 256 if kind == "preview" else 1024) <= manifest["bytes"] <=
            (4096 if kind == "view" else 512 * 1024 if kind == "preview" else 12 * 1024 * 1024 if kind in {"preview3d", "scene3d"} else 32 * 1024 * 1024 if kind == "mesh" else 256 * 1024 * 1024)):
        raise HTTPException(409, "asset_manifest_invalid")
    path = _job_dir(job_id) / manifest["file"]
    if not path.is_file() or path.stat().st_size != manifest["bytes"]:
        raise HTTPException(409, "asset_changed")
    if verify_digest:
        with path.open("rb") as source:
            if not hmac.compare_digest(hashlib.file_digest(source, "sha256").hexdigest(), manifest["sha256"]):
                raise HTTPException(409, "asset_changed")
    return path, manifest


@router.get("/jobs/{job_id}/assets/{kind}/chunks/{index}")
def asset_chunk(job_id: str, kind: str, index: int, request: Request):
    _authorize(request)
    # The device verifies the entire file digest after all bounded chunks.
    path, manifest = _verified_asset(job_id, kind, verify_digest=False)
    count = (manifest["bytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES
    if not 0 <= index < count:
        raise HTTPException(422, "chunk_index")
    with path.open("rb") as source:
        source.seek(index * CHUNK_BYTES)
        data = source.read(CHUNK_BYTES)
    return Response(data, media_type="application/octet-stream",
                    headers={"X-Content-SHA256": hashlib.sha256(data).hexdigest()})


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, request: Request):
    _authorize(request)
    path = _job_dir(job_id)
    with _job_lock(job_id):
        if _read_job(path)["state"] in {"receiving", "running", "cancel_requested"}:
            raise HTTPException(409, "job_running")
        shutil.rmtree(path)
        return {"deleted": True}
