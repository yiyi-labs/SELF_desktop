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
import signal
import subprocess
import sys
import threading
import time
import queue
from pathlib import Path


JOB_ID = re.compile(r"^[0-9a-f]{32}$")
ROOT = Path(os.environ.get("SELF_RECON_JOBS_DIR", "")).resolve()
HERE = Path(__file__).resolve().parent
_SMOKE_OK = False
# Capture before lazy imports. A running worker never silently adopts edits.
from code_identity import source_identity
_LOADED_IMPLEMENTATION = source_identity(HERE)


class ReconstructionFailure(Exception):
    pass


class ReconstructionCancelled(Exception):
    pass


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
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
    if (path / "cancel.requested").exists():
        raise ReconstructionCancelled()
    job_file = path / "job.json"
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job.update(state=state, progress=progress, message=message, **extra)
    if (path / "cancel.requested").exists():
        raise ReconstructionCancelled()
    atomic_json(job_file, job)
    if (path / "cancel.requested").exists():
        raise ReconstructionCancelled()


def command(argv: list[str], timeout: int, *, cwd: Path | None = None,
            diagnostic_file: Path | None = None, progress=None) -> str:
    if progress is not None:
        process=subprocess.Popen(argv,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                 text=True,bufsize=1)
        lines=queue.Queue()
        started=time.monotonic()
        tail=[]
        def reader():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)
        threading.Thread(target=reader,daemon=True).start()
        try:
            while True:
                if time.monotonic()-started>timeout:
                    raise subprocess.TimeoutExpired(argv,timeout)
                try:
                    line=lines.get(timeout=1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                tail.append(line)
                tail=tail[-80:]
                if diagnostic_file is not None:
                    with diagnostic_file.open("a",encoding="utf-8") as stream:
                        stream.write(line)
                try:
                    row=json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row,dict):
                    progress(row)
            if process.wait()!=0:
                raise ReconstructionFailure(f"tool_failed:{Path(argv[0]).name}:{process.returncode}")
            return "".join(tail)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()
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
    import cv2

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
            8 <= duration <= 600 and math.isfinite(duration)):
        raise ReconstructionFailure("capture_length_or_resolution_insufficient")
    # Preserve angular coverage without asking COLMAP to match thousands of
    # near-duplicate video pairs. The 65 s capture needed 240 frames under the
    # previous rule, which spent minutes recovering almost identical poses.
    max_frames = min(160, max(72, math.ceil(duration * 3)))
    interval = duration / max_frames
    frames_dir = path / "frames"
    frames_dir.mkdir(exist_ok=True)
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()
    capture = cv2.VideoCapture(str(clip))
    if not capture.isOpened():
        raise ReconstructionFailure("capture_decode_failed")
    decoded_fps = capture.get(cv2.CAP_PROP_FPS)
    if not math.isfinite(decoded_fps) or decoded_fps < 8:
        capture.release()
        raise ReconstructionFailure("capture_frame_rate_unreliable")
    chosen = 0
    selected = []
    current_bucket = -1
    best = None
    decoded = 0

    def save(candidate) -> None:
        nonlocal chosen
        if candidate is None:
            return
        chosen += 1
        output = frames_dir / f"frame_{chosen:04d}.png"
        if not cv2.imwrite(str(output), candidate[1], [cv2.IMWRITE_PNG_COMPRESSION, 1]):
            raise ReconstructionFailure("capture_frame_write_failed")
        selected.append({"name": output.name, "sourceIndexZeroBased": candidate[2],
                         "pngSha256": file_sha256(output)})

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if not (480 <= frame.shape[0] <= 4096 and 480 <= frame.shape[1] <= 4096):
                raise ReconstructionFailure("capture_orientation_or_size_invalid")
            second = decoded / decoded_fps
            bucket = min(max_frames - 1, int(second / interval))
            if bucket != current_bucket:
                save(best)
                best = None
                current_bucket = bucket
            small = cv2.resize(frame, (480, 270), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            # A sharp wardrobe must never win over a blurred face. Capture
            # guidance keeps the head near the centre, so favour that region.
            central = gray[round(gray.shape[0] * .16):round(gray.shape[0] * .88),
                           round(gray.shape[1] * .20):round(gray.shape[1] * .80)]
            sharpness = (.8 * float(cv2.Laplacian(central, cv2.CV_32F).var()) +
                         .2 * float(cv2.Laplacian(gray, cv2.CV_32F).var()))
            center_bonus = 1.0 - .04 * abs((second / interval) % 1 - .5)
            score = sharpness * center_bonus
            if best is None or score > best[0]:
                best = (score, frame.copy(), decoded)
            decoded += 1
        save(best)
    finally:
        capture.release()
    frames = sorted(frames_dir.glob("frame_*.png"))
    if len(frames) < 18:
        raise ReconstructionFailure("too_few_distinct_views")
    # Record the actual selected source-frame index before private video and
    # decoded pixels are removed.  FFprobe PTS is used only when its frame
    # count exactly matches the decoder; nominal FPS is never passed off as a
    # measured timestamp on variable-frame-rate capture.
    try:
        pts_output = command(["ffprobe", "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "frame=best_effort_timestamp_time",
                              "-of", "csv=p=0", str(clip)], 90)
        pts_status = "unverified_pts_decoder_mismatch"
    except (ReconstructionFailure, subprocess.TimeoutExpired):
        # Exact PTS enriches the audit but must not turn an otherwise valid
        # video into a failed reconstruction. Never substitute nominal FPS.
        pts_output = ""
        pts_status = "unavailable_ffprobe_pts"
    try:
        pts = [float(line.split(",", 1)[0]) for line in pts_output.splitlines()
               if line.strip()]
    except ValueError:
        pts = []
    verified_pts = (len(pts) == decoded and all(math.isfinite(value) for value in pts)
                    and all(right > left for left, right in zip(pts, pts[1:])))
    for item in selected:
        item["timestampSeconds"] = (pts[item["sourceIndexZeroBased"]]
                                     if verified_pts else None)
    atomic_json(path / "frame_selection.json", {
        "schemaVersion": 1, "captureSha256": file_sha256(clip),
        "sourceDecodedFrames": decoded, "selectedFrames": selected,
        "selectionMethod": "face-centred-sharpest-per-time-bin",
        "timestampStatus": "verified_ffprobe_pts" if verified_pts else pts_status,
        "joinKey": "relative_image_name_not_colmap_id"})
    atomic_json(path / "capture_quality.json", {"sourceWidth": width,
                "sourceHeight": height, "durationSeconds": duration,
                "sampledFrames": len(frames), "decodedFrames": decoded,
                "spatialDownsample": False, "sampling": "face-centred-sharpest-per-time-bin"})
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
    # One camera solution must explain the face, clothing, and recorded room.
    # Solving two masked camera trajectories and merging their splats left a
    # measurable head/room drift and a hollow seam in the real capture.
    extraction = pycolmap.FeatureExtractionOptions(num_threads=8, max_image_size=-1)
    pycolmap.extract_features(database, frames_dir, image_names=sorted(faces),
                               camera_mode=pycolmap.CameraMode.SINGLE,
                               extraction_options=extraction,
                               device=pycolmap.Device.cpu)
    # Time-ordered captures have strong local overlap. Sequential geometric
    # matching avoids the O(N^2) exhaustive pairs that dominated long clips.
    pycolmap.match_sequential(database,
        pairing_options=pycolmap.SequentialPairingOptions(
            overlap=18, quadratic_overlap=True, num_threads=8),
        device=pycolmap.Device.cpu)
    models = pycolmap.incremental_mapping(database, frames_dir, output)
    if not models:
        raise ReconstructionFailure("camera_pose_recovery_failed")
    model = max(models.values(), key=lambda value: (value.num_reg_images(), value.num_points3D()))
    registered = model.num_reg_images()
    points = model.num_points3D()
    if registered < max(16, math.ceil(len(faces) * 0.65)) or points < 300:
        raise ReconstructionFailure("camera_coverage_insufficient")
    # A room-only SfM result is not a face model, and a face-only result leaves
    # the viewer empty behind the person. Require real observations of both.
    face_tracks = 0
    room_tracks = 0
    confirmed_views = 0
    for image in model.images.values():
        if not image.has_pose or image.name not in faces:
            continue
        x, y, w, h = faces[image.name]
        local = sum(1 for point in image.points2D
                    if point.has_point3D() and x <= point.xy[0] <= x + w
                    and y <= point.xy[1] <= y + h)
        room_tracks += sum(1 for point in image.points2D
                           if point.has_point3D() and not
                           (x <= point.xy[0] <= x + w and y <= point.xy[1] <= y + h))
        if local >= 30:
            confirmed_views += 1
            face_tracks += local
    if confirmed_views < 3 or face_tracks < 150 or room_tracks < 150:
        raise ReconstructionFailure("person_and_room_geometry_not_recovered")
    destination = output / "0"
    destination.mkdir(exist_ok=True)
    model.write(destination)
    report = {"sampledFrames": len(frames), "trackedFrames": len(faces),
              "registeredFrames": registered, "featureRegion": "unified_person_and_room",
              "sparsePoints": points, "faceConfirmedViews": confirmed_views,
              "faceTrackObservations": face_tracks, "roomTrackObservations": room_tracks,
              "meshValidated": False, "humanReviewRequired": True}
    atomic_json(path / "geometry_quality.json", report)
    return report


def train_gaussians(path: Path) -> dict:
    (path / "training_error.log").unlink(missing_ok=True)
    # A completed reconstruction is viewable even when a subjective fidelity
    # target is missed.  The trainer still rejects malformed/empty geometry.
    command([sys.executable, str(HERE / "train_joint.py"), str(path),
             "--best-effort"], 7200,
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


def opening_view(path: Path) -> dict:
    from view import coverage, derive

    view = derive(path)
    report = coverage(path, view)
    # A reconstruction can only promise free viewing inside observed camera
    # coverage. Leave a small angular reserve for disoccluded room pixels;
    # never silently expose missing background at an unrecorded side view.
    view["safeYawDegrees"] = [round(min(0., max(-60., report["minYawDegrees"] + 14)), 1),
                              round(max(0., min(60., report["maxYawDegrees"] - 10)), 1)]
    view["safePitchDegrees"] = [round(min(0., max(-20., report["minPitchDegrees"] + 3)), 1),
                                round(max(0., min(20., report["maxPitchDegrees"] - 3)), 1)]
    atomic_json(path / "viewpoint_quality.json", report)
    # Coverage guides the next capture; it must not discard a usable front
    # portrait or force someone through repeated, exact camera movements.
    output = path / "portrait.view.json"
    atomic_json(output, view)
    return {"file": output.name, "bytes": output.stat().st_size,
            "sha256": file_sha256(output)}


def portrait_preview(path: Path) -> tuple[dict, dict]:
    from portrait_preview import create, create_3d_lod, create_scene_lod

    # Each preview asset is independent: a failing thumbnail must never drop
    # the working 3D LODs (or vice versa). Failures are reported per asset.
    assets: dict = {}
    errors: dict = {}
    for kind, producer in (("preview", create),
                           ("preview3d", create_3d_lod),
                           ("scene3d", create_scene_lod)):
        try:
            output = producer(path)
        except (OSError, ValueError, KeyError, ImportError) as error:
            errors[kind] = f"{type(error).__name__}: {str(error)[:120]}"
            continue
        assets[kind] = {"file": output.name, "bytes": output.stat().st_size,
                        "sha256": file_sha256(output)}
    return assets, errors


def discard_training_inputs(path: Path, assets: dict) -> None:
    """Keep published result assets and job status, never the source video."""
    keep = {"job.json", "cancel.requested", "frame_selection.json", "failure.log",
            "preview_error.log",
            "observation_bundle.json", "portrait.provenance.npz", "portrait.algorithm.json", "portrait-state"} | {
                item["file"] for item in assets.values()}
    for item in path.iterdir():
        if item.name in keep:
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink(missing_ok=True)


def run_one(path: Path) -> None:
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    if job.get("state") != "queued" or (path / "cancel.requested").exists():
        return
    started = time.perf_counter()
    last_stage = started
    stage_times: dict[str, float] = {}

    def finished_stage(name: str) -> None:
        nonlocal last_stage
        now = time.perf_counter()
        stage_times[name] = round(now - last_stage, 2)
        last_stage = now

    try:
        update(path, "running", 27, "正在核对拍摄片段")
        verify_capture(path, job)
        from runtime import engine_profile, reconstruct_test, PORTRAIT_TEST
        profile=engine_profile(ROOT)
        if profile["engine"]==PORTRAIT_TEST:
            from face import prepare as prepare_test_faces
            assets,quality=reconstruct_test(path,job,profile,update,extract_frames,
                prepare_test_faces,command,file_sha256)
            try:
                assets.update(portrait_preview(path))
            except (OSError,ValueError,KeyError,ImportError):
                pass
            quality["pipelineTimingSeconds"]={"total":round(time.perf_counter()-started,2)}
            discard_training_inputs(path,assets)
            update(path,"gaussian_ready",85,"这颗星辰已为你留好",assets=assets,
                algorithm=PORTRAIT_TEST,reconstructionQuality=quality)
            return
        frames = extract_frames(path)
        finished_stage("decodeAndSelect")
        update(path, "running", 36, "正在核对面容与视角")
        from face import prepare

        try:
            faces = prepare(path, frames)
        except RuntimeError as error:
            raise ReconstructionFailure(str(error)) from error
        atomic_json(path / "face_regions.json", {key: list(value) for key, value in faces.items()})
        finished_stage("faceTracking")
        update(path, "running", 43, "正在恢复视角")
        recover_cameras(path, frames, faces)
        finished_stage("cameraRecovery")
        from pose import prepare_face_views
        face_pose_quality = prepare_face_views(path)
        finished_stage("facePoseAlignment")
        from observations import build_observation_bundle
        build_observation_bundle(path)
        finished_stage("observationAssociation")
        view = opening_view(path)
        from scene import seed_recorded_scene

        # Coarse environment seeds and fine face observations are trained in
        # the same scene; no independently trained room model is merged later.
        environment_quality = seed_recorded_scene(path)
        finished_stage("environmentSeeding")
        update(path, "running", 62, "正在生成立体细节")
        gaussian = train_gaussians(path)
        finished_stage("gaussianTraining")
        view_file = path / "portrait.view.json"
        view = {"file": view_file.name, "bytes": view_file.stat().st_size,
                "sha256": file_sha256(view_file)}
        try:
            preview, preview_errors = portrait_preview(path)
        except (OSError, ValueError, KeyError, ImportError) as error:
            # A navigation thumbnail must never invalidate a usable 3D model.
            preview, preview_errors = {}, {"all": f"{type(error).__name__}: {str(error)[:120]}"}
        if preview_errors:
            (path / "preview_error.log").write_text(json.dumps(preview_errors, ensure_ascii=False),
                                                    encoding="utf-8")
        finished_stage("previews")
        # Face splats have a stable editable range; the result is still a GS
        # asset rather than a textured mesh.
        viewpoint = json.loads((path / "viewpoint_quality.json").read_text(encoding="utf-8"))
        quality = {
            "faceMask": json.loads((path / "face_mask_quality.json").read_text(encoding="utf-8")),
            "geometry": json.loads((path / "geometry_quality.json").read_text(encoding="utf-8")),
            "facePose": face_pose_quality,
            "training": json.loads((path / "training_metrics.json").read_text(encoding="utf-8")),
            "environment": environment_quality,
            "pipelineTimingSeconds": {**stage_times, "total": round(time.perf_counter() - started, 2)},
        }
        training_quality = quality["training"]
        message = ("立体面容已生成；这次的细节还可以在下次拍摄时补充"
                   if training_quality.get("fidelityGatePassed") is False else
                   "立体面容已生成；侧面细节可在下次拍摄时补充"
                   if not viewpoint["broadSideCoverage"] else
                   "立体面容已生成")
        assets = {"gaussian": gaussian, "view": view}
        if preview:
            assets.update(preview)
        if preview_errors:
            # Visible in the transport status, not only in a local file.
            quality["previews"] = {"generated": sorted(preview),
                                   "errors": preview_errors}
        discard_training_inputs(path, assets)
        update(path, "gaussian_ready", 85, message,
               assets=assets, viewpointQuality=viewpoint, reconstructionQuality=quality)
    except ReconstructionCancelled:
        return
    except Exception as error:
        if (path / "cancel.requested").exists():
            return
        reason = str(error) if isinstance(error, ReconstructionFailure) else type(error).__name__
        # Keep the actual traceback for diagnosis; the generic reason above is
        # all the transport ever shows. failure.log survives input cleanup.
        try:
            import traceback
            details = traceback.format_exc()
            training_log = path / "portrait-test-training.log"
            if training_log.is_file():
                tail = "\n".join(training_log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:])
                details += "\n--- portrait-test-training.log (tail) ---\n" + tail
            (path / "failure.log").write_text(details[-65536:], encoding="utf-8")
        except OSError:
            pass
        diagnostics = {}
        for label, filename in (("faceMask", "face_mask_quality.json"),
                                ("geometry", "geometry_quality.json"),
                                ("training", "training_metrics.json")):
            source = path / filename
            if source.is_file():
                try:
                    diagnostics[label] = json.loads(source.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
        update(path, "failed", 0, reason[:120], assets={},
               reconstructionQuality=diagnostics)
        discard_training_inputs(path, {})


def finish_cancel(path: Path) -> None:
    """Only called after the job process has exited; never delete live inputs."""
    # WSL/NTFS may briefly report a non-empty directory while a terminated
    # FFmpeg child releases its final file handle. Never publish "cancelled"
    # until every private input is gone, or an API client could delete the job
    # while this supervisor is still removing its frames.
    for attempt in range(10):
        pending = [item for item in path.iterdir()
                   if item.name not in {"job.json", "cancel.requested"}]
        if not pending:
            break
        for item in pending:
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
            except OSError:
                if attempt == 9:
                    raise
        time.sleep(.15)
    job = json.loads((path / "job.json").read_text(encoding="utf-8"))
    job.update(state="cancelled", progress=0, message="", assets={})
    atomic_json(path / "job.json", job)


def supervise_job(path: Path) -> None:
    """Isolate heavy reconstruction so a mistaken submission can be stopped."""
    child = subprocess.Popen([sys.executable, str(HERE / "worker.py"),
                              "--job", path.name], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    while child.poll() is None:
        if (path / "cancel.requested").exists():
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)
            break
        time.sleep(.3)
    if (path / "cancel.requested").exists():
        finish_cancel(path)
    elif child.returncode and (path / "job.json").is_file():
        job = json.loads((path / "job.json").read_text(encoding="utf-8"))
        if job.get("state") == "running":
            update(path, "failed", 0, "worker_process_exited", assets={})


def refresh_worker_capability(capability: dict) -> dict:
    from runtime import worker_identity_status
    identity=worker_identity_status(ROOT,_LOADED_IMPLEMENTATION,HERE)
    result={**capability,**identity,"updatedAt":int(time.time())}
    if not identity["sourceIdentityVerified"]:
        result["ready"]=False
    elif any(capability.get(key)!=identity.get(key)
             for key in ("engine","algorithmVersion","executionAdapter","executionProfileSha256")):
        result.update(ready=False,reason="worker_profile_changed_preflight_required")
    return result


def dense_tool_preflight(profile: dict) -> dict:
    """Validate pinned files/environment without importing the inference model."""
    if profile.get('denseSurfaces') is not True:
        return {'denseToolVerified':False}
    from live_dense import fixed_tool
    try:
        _,_,lock=fixed_tool()
    except (OSError,ValueError,KeyError) as error:
        label=str(error) if isinstance(error,ValueError) else type(error).__name__
        if not label.startswith(('dense_','pinned_')):
            label=type(error).__name__
        raise ReconstructionFailure('Dense reconstruction tool unavailable: '+label[:90]) from error
    return {'denseToolVerified':True,'denseToolCodeCommit':lock['codeCommit'],
            'denseToolModelCommit':lock['modelCommit']}


def preflight() -> dict:
    global _SMOKE_OK
    from runtime import engine_profile,worker_identity_status
    result = {"updatedAt":int(time.time()),"ready":False}
    try:
        identity=worker_identity_status(ROOT,_LOADED_IMPLEMENTATION,HERE)
        result.update(identity)
        if not identity["sourceIdentityVerified"]:
            return result
        profile=engine_profile(ROOT)
        result.update(dense_tool_preflight(profile))
        import cv2
        import mediapipe as mp
        import pycolmap
        import torch
        import gsplat
        from face import check_models
        from pose import canonical_vertices

        if not torch.cuda.is_available() or torch.cuda.get_device_capability(0) < (12, 0):
            raise ReconstructionFailure("RTX 5070 CUDA unavailable")
        if torch.cuda.get_device_properties(0).total_memory < 7.5 * 1024**3:
            raise ReconstructionFailure("Eight-gigabyte GPU memory profile unavailable")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise ReconstructionFailure("FFmpeg unavailable")
        check_models()
        canonical_vertices()
        if profile["engine"]!="gsplat-colmap":
            from flame_open_model import FlameOpen
            FlameOpen(24,12)
        if not _SMOKE_OK:
            from train import smoke
            smoke()
            _SMOKE_OK = True
        result.update(ready=True, torch=torch.__version__, cuda=torch.version.cuda,
                      gsplat=gsplat.__version__, pycolmap=pycolmap.__version__,
                      opencv=cv2.__version__, mediapipe=mp.__version__,
                      vramMiB=round(torch.cuda.get_device_properties(0).total_memory / 1024**2))
    except Exception as error:
        result["reason"] = (str(error) if isinstance(error, ReconstructionFailure) else type(error).__name__)[:120]
    return result


def main() -> None:
    import fcntl

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--job", default="")
    args = parser.parse_args()
    if not os.environ.get("SELF_RECON_JOBS_DIR"):
        raise SystemExit("SELF_RECON_JOBS_DIR must be an explicit shared path")
    if args.job:
        if not JOB_ID.fullmatch(args.job):
            raise SystemExit("invalid job ID")
        run_one(ROOT / args.job)
        return
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
            atomic_json(ROOT / "worker_status.json", refresh_worker_capability(capability))
            time.sleep(5)
    threading.Thread(target=heartbeat, daemon=True).start()
    while True:
        capability=refresh_worker_capability(capability)
        if not capability["ready"]:
            capability = preflight()
        for path in sorted(ROOT.iterdir()):
            if path.is_dir() and JOB_ID.fullmatch(path.name) and (path / "job.json").is_file():
                job = json.loads((path / "job.json").read_text(encoding="utf-8"))
                try:
                    if job.get("state") == "cancel_requested" and (path / "cancel.requested").exists():
                        finish_cancel(path)
                    elif capability["ready"] and job.get("state") == "queued":
                        capability=refresh_worker_capability(capability)
                        if capability["ready"]:
                            supervise_job(path)
                except OSError as error:
                    # Keep the worker alive and retry terminal cleanup next
                    # pass; expose no capture paths through public status.
                    print(f"SELF_WORKER_RETRY {type(error).__name__}", file=sys.stderr)
                if args.once and job.get("state") in {"queued", "cancel_requested"}:
                    return
        if args.once:
            return
        time.sleep(5 if capability["ready"] else 30)


if __name__ == "__main__":
    main()
