"""Single-process, fail-closed local reconstruction worker.

Run in WSL beside the Windows HTTP service with SELF_RECON_JOBS_DIR pointing
to the same fixed directory. An output is published only after geometry and
file integrity checks. The Gaussian result is not a textured editable mesh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


JOB_ID = re.compile(r"^[0-9a-f]{32}$")
ROOT = Path(os.environ.get("SELF_RECON_JOBS_DIR", "")).resolve()
HERE = Path(__file__).resolve().parent
_SMOKE_OK = False


class ReconstructionFailure(Exception):
    pass


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, path)


def file_sha256(path: Path) -> str:
    """Stream a digest without relying on Python 3.11's file_digest API."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update(path: Path, state: str, progress: int, message: str = "", **extra: object) -> None:
    job_file = path / "job.json"
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job.update(state=state, progress=progress, message=message, **extra)
    atomic_json(job_file, job)


def command(argv: list[str], timeout: int, *, cwd: Path | None = None,
            diagnostic_file: Path | None = None) -> str:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                            timeout=timeout, check=False)
    if result.returncode:
        # FFmpeg and ML tools can echo filenames or private frame details.
        # Keep bounded diagnostics in the private job folder, never in the
        # public status response or app logs.
        if diagnostic_file is not None:
            diagnostic_file.write_text((result.stdout + "\n" + result.stderr)[-8192:],
                                       encoding="utf-8")
        raise ReconstructionFailure(f"tool_failed:{Path(argv[0]).name}:{result.returncode}")
    return result.stdout


def verify_capture(path: Path, job: dict) -> None:
    clip = path / "capture.mp4"
    if not clip.is_file() or clip.stat().st_size != job["totalBytes"]:
        raise ReconstructionFailure("capture_missing_or_size_changed")
    actual = file_sha256(clip)
    if actual != job["sha256"]:
        raise ReconstructionFailure("capture_checksum_changed")


def extract_frames(path: Path) -> list[Path]:
    clip = path / "capture.mp4"
    probe = json.loads(command(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height,avg_frame_rate,duration:format=duration",
                                "-of", "json", str(clip)], 30))
    streams = probe.get("streams", [])
    if len(streams) != 1:
        raise ReconstructionFailure("video_stream_missing")
    stream = streams[0]
    width, height = int(stream["width"]), int(stream["height"])
    duration = float(probe.get("format", {}).get("duration") or stream.get("duration") or 0)
    if not (640 <= width <= 4096 and 480 <= height <= 4096 and
            8 <= duration <= 45 and math.isfinite(duration)):
        raise ReconstructionFailure("capture_length_or_resolution_insufficient")
    # Lossless frames preserve source detail. Fewer temporal samples avoid
    # almost-identical views; this is not spatial downsampling of the face.
    fps = min(3.0, 72.0 / duration)
    frames_dir = path / "frames"
    frames_dir.mkdir(exist_ok=True)
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()
    command(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(clip),
             "-vf", f"fps={fps:.5f}", "-frames:v", "72", "-pix_fmt", "rgb24",
             str(frames_dir / "frame_%04d.png")], 180)
    frames = sorted(frames_dir.glob("frame_*.png"))
    if len(frames) < 18:
        raise ReconstructionFailure("too_few_distinct_views")
    atomic_json(path / "capture_quality.json", {"sourceWidth": width,
                "sourceHeight": height, "durationSeconds": duration,
                "sampledFrames": len(frames), "spatialDownsample": False})
    return frames


def face_regions(frames: list[Path]) -> dict[str, tuple[int, int, int, int]]:
    import cv2

    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if detector.empty():
        raise ReconstructionFailure("face_detector_unavailable")
    regions = {}
    for frame in frames:
        image = cv2.imread(str(frame), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise ReconstructionFailure("frame_decode_failed")
        # A few frontal frames must contain a substantial face. Side views
        # are retained for reconstruction and not required to pass Haar.
        faces = detector.detectMultiScale(image, scaleFactor=1.08, minNeighbors=5,
                                          minSize=(max(80, image.shape[1] // 7),
                                                   max(80, image.shape[0] // 7)))
        if len(faces):
            x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
            regions[frame.name] = (int(x), int(y), int(w), int(h))
    if len(regions) < 3:
        raise ReconstructionFailure("face_not_confirmed_in_capture")
    return regions


def recover_cameras(path: Path, frames: list[Path], faces: dict) -> dict:
    import pycolmap

    database = path / "colmap.db"
    database.unlink(missing_ok=True)
    frames_dir = path / "frames"
    output = path / "sparse"
    output.mkdir(exist_ok=True)
    pycolmap.extract_features(database, frames_dir, camera_mode=pycolmap.CameraMode.SINGLE,
                               device=pycolmap.Device.cpu)
    pycolmap.match_exhaustive(database, device=pycolmap.Device.cpu)
    models = pycolmap.incremental_mapping(database, frames_dir, output)
    if not models:
        raise ReconstructionFailure("camera_pose_recovery_failed")
    model = max(models.values(), key=lambda value: (value.num_reg_images(), value.num_points3D()))
    registered = model.num_reg_images()
    points = model.num_points3D()
    if registered < max(16, math.ceil(len(frames) * 0.65)) or points < 1200:
        raise ReconstructionFailure("camera_coverage_insufficient")
    # A background-only SfM result is not a face model. Require triangulated
    # observations inside detected frontal face regions on multiple views.
    face_tracks = 0
    confirmed_views = 0
    for image in model.images.values():
        if not image.has_pose or image.name not in faces:
            continue
        x, y, w, h = faces[image.name]
        local = sum(1 for point in image.points2D
                    if point.has_point3D() and x <= point.xy[0] <= x + w
                    and y <= point.xy[1] <= y + h)
        if local >= 30:
            confirmed_views += 1
            face_tracks += local
    if confirmed_views < 3 or face_tracks < 150:
        raise ReconstructionFailure("face_geometry_not_recovered")
    destination = output / "0"
    destination.mkdir(exist_ok=True)
    model.write(destination)
    report = {"sampledFrames": len(frames), "registeredFrames": registered,
              "sparsePoints": points, "faceConfirmedViews": confirmed_views,
              "faceTrackObservations": face_tracks,
              "meshValidated": False, "humanReviewRequired": True}
    atomic_json(path / "geometry_quality.json", report)
    return report


def train_gaussians(path: Path) -> dict:
    (path / "training_error.log").unlink(missing_ok=True)
    command([sys.executable, str(HERE / "reconstruction_train.py"), str(path)], 7200,
            diagnostic_file=path / "training_error.log")
    output = path / "portrait.gaussian.ply"
    if not output.is_file() or output.stat().st_size < 4096:
        raise ReconstructionFailure("gaussian_output_missing")
    if output.stat().st_size > 256 * 1024 * 1024:
        raise ReconstructionFailure("gaussian_asset_exceeds_device_transfer_limit")
    with output.open("rb") as stream:
        header = stream.read(1024)
        if not header.startswith(b"ply\n") or b"element vertex " not in header:
            raise ReconstructionFailure("gaussian_output_invalid")
    digest = file_sha256(output)
    return {"file": output.name, "bytes": output.stat().st_size, "sha256": digest}


def run_one(path: Path) -> None:
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    if job.get("state") != "queued":
        return
    try:
        update(path, "running", 27, "正在核对拍摄片段")
        verify_capture(path, job)
        frames = extract_frames(path)
        update(path, "running", 36, "正在核对面容与视角")
        faces = face_regions(frames)
        atomic_json(path / "face_regions.json", {key: list(value) for key, value in faces.items()})
        update(path, "running", 43, "正在恢复视角")
        recover_cameras(path, frames, faces)
        update(path, "running", 62, "正在生成立体细节")
        gaussian = train_gaussians(path)
        # The current HarmonyOS viewer consumes GLB, not Gaussian PLY. A real
        # PLY is available, but no personal model is claimed complete here.
        update(path, "gaussian_ready", 85, "立体细节已生成；可编辑面容仍待核验",
               assets={"gaussian": gaussian})
    except Exception as error:
        reason = str(error) if isinstance(error, ReconstructionFailure) else type(error).__name__
        update(path, "failed", 0, reason[:120], assets={})


def preflight() -> dict:
    global _SMOKE_OK
    result = {"updatedAt": int(time.time()), "ready": False, "engine": "gsplat-colmap"}
    try:
        import cv2
        import pycolmap
        import torch
        import gsplat

        if not torch.cuda.is_available() or torch.cuda.get_device_capability(0) < (12, 0):
            raise ReconstructionFailure("RTX 5070 CUDA unavailable")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise ReconstructionFailure("FFmpeg unavailable")
        if not _SMOKE_OK:
            from reconstruction_train import smoke
            smoke()
            _SMOKE_OK = True
        result.update(ready=True, torch=torch.__version__, cuda=torch.version.cuda,
                      gsplat=gsplat.__version__, pycolmap=pycolmap.__version__, opencv=cv2.__version__)
    except Exception as error:
        result["reason"] = (str(error) if isinstance(error, ReconstructionFailure) else type(error).__name__)[:120]
    return result


def main() -> None:
    import fcntl

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("SELF_RECON_JOBS_DIR"):
        raise SystemExit("SELF_RECON_JOBS_DIR must be an explicit shared path")
    # gsplat's JIT loader removes its cache directory before compiling. A
    # second worker must never enter preflight or it may delete live objects.
    lock_file = open("/tmp/self-reconstruction-worker.lock", "w", encoding="utf-8")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("another SELF reconstruction worker is already active") from None
    ROOT.mkdir(parents=True, exist_ok=True)
    capability = preflight()
    def heartbeat() -> None:
        while True:
            atomic_json(ROOT / "worker_status.json", {**capability, "updatedAt": int(time.time())})
            time.sleep(5)
    threading.Thread(target=heartbeat, daemon=True).start()
    while True:
        if not capability["ready"]:
            capability = preflight()
        if capability["ready"]:
            for path in sorted(ROOT.iterdir()):
                if path.is_dir() and JOB_ID.fullmatch(path.name) and (path / "job.json").is_file():
                    run_one(path)
                    if args.once:
                        return
        if args.once:
            return
        time.sleep(5 if capability["ready"] else 30)


if __name__ == "__main__":
    main()
