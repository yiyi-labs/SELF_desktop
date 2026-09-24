"""Train a Gaussian PLY from verified COLMAP poses using gsplat.

This is a small adapter around gsplat's public rasterization, densification
strategy, and PLY exporter, not a copy of its example application. Images are
rendered at source resolution; low-memory hardware fails explicitly instead
of silently shrinking the face. The PLY is not an editable mesh.
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
from pathlib import Path


def smoke() -> None:
    import torch
    from gsplat.rendering import rasterization

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    device = "cuda"
    means = torch.tensor([[0., 0., 2.]], device=device, requires_grad=True)
    quats = torch.tensor([[1., 0., 0., 0.]], device=device)
    scales = torch.tensor([[.2, .2, .2]], device=device)
    opacities = torch.tensor([.8], device=device)
    colors = torch.tensor([[.9, .3, .2]], device=device)
    view = torch.eye(4, device=device)[None]
    K = torch.tensor([[[60., 0., 32.], [0., 60., 32.], [0., 0., 1.]]], device=device)
    image, _, _ = rasterization(means, quats, scales, opacities, colors,
                                view, K, 64, 64, packed=True)
    image.sum().backward()
    if not torch.isfinite(image).all() or image.max() <= 0 or means.grad is None:
        raise RuntimeError("gsplat CUDA forward/backward smoke failed")
    print(json.dumps({"cuda": torch.version.cuda, "device": torch.cuda.get_device_name(),
                      "capability": torch.cuda.get_device_capability(), "gsplatRasterization": True}))


def update_progress(path: Path, step: int, total: int) -> None:
    job_file = path / "job.json"
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job["progress"] = 62 + round(18 * step / total)
    temporary = job_file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, job_file)


def load_scene(path: Path):
    import numpy as np
    import pycolmap

    model = pycolmap.Reconstruction(path / "sparse" / "0")
    cameras = []
    for image in model.images.values():
        if not image.has_pose:
            continue
        matrix = np.eye(4, dtype=np.float32)
        matrix[:3, :] = np.asarray(image.cam_from_world().matrix(), dtype=np.float32)
        camera = model.cameras[image.camera_id]
        cameras.append((path / "frames" / image.name, matrix,
                        np.asarray(camera.calibration_matrix(), dtype=np.float32),
                        camera.width, camera.height))
    if len(cameras) < 16:
        raise RuntimeError("Too few registered cameras")
    points = np.asarray([point.xyz for point in model.points3D.values()], dtype=np.float32)
    colors = np.asarray([point.color for point in model.points3D.values()], dtype=np.float32) / 255
    if len(points) < 1200 or len(points) > 250000:
        raise RuntimeError("Sparse point count outside verified memory range")
    return cameras, points, colors


def train(path: Path, steps: int = 6000) -> None:
    import numpy as np
    import torch
    import torch.nn.functional as F
    from PIL import Image
    from scipy.spatial import cKDTree
    from gsplat import export_splats
    from gsplat.rendering import rasterization
    from gsplat.strategy import DefaultStrategy

    if steps < 3000:
        raise RuntimeError("Training steps below fidelity floor")
    torch.manual_seed(42)
    random.seed(42)
    cameras, points, rgbs = load_scene(path)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    device = "cuda"
    distances, _ = cKDTree(points).query(points, k=4)
    nearest = np.sqrt(np.maximum((distances[:, 1:] ** 2).mean(axis=1), 1e-8))
    centers = np.stack([np.linalg.inv(pose)[:3, 3] for _, pose, _, _, _ in cameras])
    scene_scale = float(np.linalg.norm(centers - centers.mean(axis=0), axis=1).max())
    if not math.isfinite(scene_scale) or scene_scale < 1e-4:
        raise RuntimeError("Camera baseline degenerate")
    sh0 = (torch.from_numpy(rgbs).float() - .5) / .28209479177387814
    params = torch.nn.ParameterDict({
        "means": torch.nn.Parameter(torch.from_numpy(points)),
        "scales": torch.nn.Parameter(torch.from_numpy(np.log(nearest).astype(np.float32)[:, None].repeat(3, axis=1))),
        "quats": torch.nn.Parameter(torch.tensor([[1., 0., 0., 0.]]).repeat(len(points), 1)),
        "opacities": torch.nn.Parameter(torch.full((len(points),), -2.1972246)),
        "sh0": torch.nn.Parameter(sh0[:, None, :]),
        "shN": torch.nn.Parameter(torch.zeros(len(points), 15, 3)),
    }).to(device)
    rates = {"means": 1.6e-4 * scene_scale, "scales": 5e-3,
             "quats": 1e-3, "opacities": 5e-2, "sh0": 2.5e-3, "shN": 1.25e-4}
    optimizers = {key: torch.optim.Adam([{"params": params[key], "lr": rate}], eps=1e-15)
                  for key, rate in rates.items()}
    schedule = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], gamma=.01 ** (1 / steps))
    strategy = DefaultStrategy(refine_start_iter=300, refine_stop_iter=steps - 400,
                               refine_every=100)
    strategy.check_sanity(params, optimizers)
    state = strategy.initialize_state(scene_scale=scene_scale)
    face_regions = json.loads((path / "face_regions.json").read_text(encoding="utf-8"))
    random.shuffle(cameras)
    face_entries = [entry for entry in cameras if entry[0].name in face_regions]
    if len(face_entries) < 3:
        raise RuntimeError("Registered frontal face views insufficient")
    validation = face_entries[:2]
    frontal_validation_names = {entry[0].name for entry in validation}
    validation += [entry for entry in cameras if entry[0].name not in frontal_validation_names][:max(0, len(cameras) // 8 - 2)]
    validation_names = {entry[0].name for entry in validation}
    training = [entry for entry in cameras if entry[0].name not in validation_names]
    if len(training) < 14:
        raise RuntimeError("Too few training cameras")

    # Keep lossless decoded source pixels in host RAM when the whole scene
    # fits. Repeated PNG decoding from the Windows/WSL shared volume would
    # otherwise dominate thousands of GPU steps, without improving detail.
    image_cache = {}
    if sum(width * height * 3 for _, _, _, width, height in cameras) <= 2 * 1024**3:
        for name, _, _, _, _ in cameras:
            with Image.open(name) as source:
                image_cache[name] = np.asarray(source.convert("RGB"), dtype=np.uint8)

    def render(entry, degree):
        name, pose, intrinsic, width, height = entry
        image = image_cache.get(name)
        if image is None:
            with Image.open(name) as source:
                image = np.asarray(source.convert("RGB"), dtype=np.uint8)
        if image.shape[:2] != (height, width):
            raise RuntimeError("COLMAP intrinsics disagree with source frame")
        target = torch.from_numpy(image).to(device).float()[None] / 255
        view = torch.from_numpy(pose).to(device)[None]
        K = torch.from_numpy(intrinsic).to(device)[None]
        colors = torch.cat([params["sh0"], params["shN"]], dim=1)
        output, _, info = rasterization(params["means"], params["quats"],
                                        torch.exp(params["scales"]),
                                        torch.sigmoid(params["opacities"]), colors,
                                        view, K, width, height, packed=True,
                                        sh_degree=degree, near_plane=.01)
        return output, target, info

    losses = []
    for step in range(steps):
        entry = training[step % len(training)]
        degree = min(step // 1000, 3)
        output, target, info = render(entry, degree)
        strategy.step_pre_backward(params, optimizers, state, step, info)
        loss = F.l1_loss(output, target)
        if not torch.isfinite(loss):
            raise RuntimeError("Non-finite reconstruction loss")
        loss.backward()
        for optimizer in optimizers.values():
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        schedule.step()
        strategy.step_post_backward(params, optimizers, state, step, info, packed=True)
        if step % 200 == 0:
            losses.append(float(loss.detach().cpu()))
            update_progress(path, step, steps)
            if torch.cuda.max_memory_allocated() > 7.4 * 1024**3:
                raise RuntimeError("GPU memory safety limit exceeded; source quality unchanged")

    errors = []
    face_errors = []
    with torch.no_grad():
        for entry in validation:
            output, target, _ = render(entry, 3)
            errors.append(float(F.mse_loss(output, target).cpu()))
            if entry[0].name in face_regions:
                x, y, w, h = face_regions[entry[0].name]
                face_errors.append(float(F.mse_loss(output[:, y:y+h, x:x+w],
                                                   target[:, y:y+h, x:x+w]).cpu()))
    psnr = -10 * math.log10(max(sum(errors) / len(errors), 1e-10))
    face_psnr = -10 * math.log10(max(sum(face_errors) / len(face_errors), 1e-10))
    metrics = {"steps": steps, "sourceResolution": True, "gaussians": len(params["means"]),
               "validationViews": len(validation), "validationPsnrDb": round(psnr, 2),
               "frontalFacePsnrDb": round(face_psnr, 2),
               "lossSamples": losses, "humanFaceReviewRequired": True}
    (path / "training_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    if psnr < 16 or face_psnr < 18 or len(params["means"]) < 1200:
        raise RuntimeError("Held-out reconstruction quality below minimum")
    export_splats(means=params["means"].detach(), scales=params["scales"].detach(),
                  quats=params["quats"].detach(), opacities=params["opacities"].detach(),
                  sh0=params["sh0"].detach(), shN=params["shN"].detach(),
                  format="ply", save_to=str(path / "portrait.gaussian.ply"))


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--smoke":
        smoke()
    elif len(sys.argv) == 2:
        train(Path(sys.argv[1]))
    else:
        raise SystemExit("Usage: reconstruction_train.py JOB_DIR | --smoke")
