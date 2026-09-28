"""Fit real room/clothing splats with the portrait's verified camera poses.

The face keeps its full-resolution, higher-weight training. This lower-density
scene stage uses the same world coordinates and merges into one standard PLY,
so the PlayCanvas renderer sorts face and room splats together at every view.
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

from reconstruction_scene import environment_view_support, foreground_clearance
from reconstruction_train import load_scene, update_progress


def train(path: Path, steps: int = 2400) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    from scipy.spatial import cKDTree
    from gsplat import export_splats
    from gsplat.rendering import rasterization
    from gsplat.strategy import DefaultStrategy

    if steps < 1500:
        raise ValueError("environment_training_too_short")
    torch.manual_seed(73)
    random.seed(73)
    cameras, _, _ = load_scene(path, path / "environment_aligned" / "0")
    cameras.sort(key=lambda entry: entry[0].name)
    seeds = np.load(path / "environment_seeds.npz")
    xyz = seeds["xyz"]
    rgb = seeds["rgb"].astype(np.float32) / 255
    if len(xyz) < 200:
        raise ValueError("environment_seed_count_too_low")
    centers = np.stack([np.linalg.inv(pose)[:3, 3] for _, pose, _, _, _ in cameras])
    scene_scale = float(np.linalg.norm(centers - centers.mean(axis=0), axis=1).max())
    distances, _ = cKDTree(xyz).query(xyz, k=4)
    spacing = np.sqrt(np.maximum((distances[:, 1:] ** 2).mean(axis=1), 1e-8))
    spacing = np.clip(spacing, .001 * scene_scale, .08 * scene_scale)
    params = torch.nn.ParameterDict({
        "means": torch.nn.Parameter(torch.from_numpy(xyz.copy())),
        "scales": torch.nn.Parameter(torch.from_numpy(np.log(spacing).astype(np.float32)[:, None].repeat(3, axis=1))),
        "quats": torch.nn.Parameter(torch.tensor([[1., 0., 0., 0.]]).repeat(len(xyz), 1)),
        "opacities": torch.nn.Parameter(torch.full((len(xyz),), -2.1972246)),
        "sh0": torch.nn.Parameter((torch.from_numpy(rgb) - .5)[:, None, :] / .28209479177387814),
        "shN": torch.nn.Parameter(torch.zeros(len(xyz), 15, 3)),
    }).to("cuda")
    rates = {"means": 1.2e-4 * scene_scale, "scales": 3e-3,
             "quats": 1e-3, "opacities": 4e-2, "sh0": 2e-3, "shN": 1e-4}
    optimizers = {key: torch.optim.Adam([{"params": params[key], "lr": rate}], eps=1e-15)
                  for key, rate in rates.items()}
    schedule = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], gamma=.01 ** (1 / steps))
    strategy = DefaultStrategy(refine_start_iter=250, refine_stop_iter=1300,
                               refine_every=100)
    strategy.check_sanity(params, optimizers)
    state = strategy.initialize_state(scene_scale=scene_scale)
    holdouts = cameras[::max(5, len(cameras) // 8)]
    holdout_names = {entry[0].name for entry in holdouts}
    training = [entry for entry in cameras if entry[0].name not in holdout_names]
    random.shuffle(training)
    cache = {}

    def render(entry, degree):
        name, pose, intrinsic, width, height = entry
        if name not in cache:
            with Image.open(name) as source:
                image = np.asarray(source.convert("RGB").resize((width // 2, height // 2),
                                                                   Image.Resampling.BILINEAR), dtype=np.uint8)
            with Image.open(path / "environment_masks" / (name.name + ".png")) as source:
                mask = np.asarray(source.convert("L").resize((width // 2, height // 2),
                                                                Image.Resampling.NEAREST), dtype=np.uint8)
            cache[name] = (image.copy(), mask.copy())
        image, mask = cache[name]
        target = torch.from_numpy(image).to("cuda").float()[None] / 255
        keep = torch.from_numpy(mask).to("cuda").float()[None, :, :, None] / 255
        intrinsic = intrinsic.copy()
        intrinsic[:2, :] *= .5
        colors = torch.cat([params["sh0"], params["shN"]], dim=1)
        output, alpha, info = rasterization(params["means"], params["quats"],
                                            torch.exp(params["scales"]),
                                            torch.sigmoid(params["opacities"]), colors,
                                            torch.from_numpy(pose).to("cuda")[None],
                                            torch.from_numpy(intrinsic).to("cuda")[None],
                                            width // 2, height // 2, packed=True,
                                            sh_degree=degree, near_plane=.01)
        return output, target, keep, alpha, info

    losses = []
    for step in range(steps):
        degree = min(step // 900, 2)
        output, target, keep, alpha, info = render(training[step % len(training)], degree)
        strategy.step_pre_backward(params, optimizers, state, step, info)
        # The room must reconstruct recorded pixels yet remain transparent
        # through the entire protected head/skin area.
        loss = (((output - target).abs() * keep).sum() / keep.sum().clamp_min(1) / 3 +
                .35 * (alpha * (1 - keep)).mean())
        if not torch.isfinite(loss):
            raise RuntimeError("environment_loss_nonfinite")
        loss.backward()
        for optimizer in optimizers.values():
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        schedule.step()
        strategy.step_post_backward(params, optimizers, state, step, info, packed=True)
        if step % 200 == 0:
            losses.append(round(float(loss.detach().cpu()), 5))
            update_progress(path, step, steps, base=76, span=8)
        del output, target, keep, alpha, info, loss
        if len(params["means"]) > 100000 or torch.cuda.max_memory_allocated() > 7.4 * 1024**3:
            raise RuntimeError("environment_gpu_capacity_exceeded")
        if step % 100 == 0 and torch.cuda.memory_reserved() - torch.cuda.memory_allocated() > 512 * 1024**2:
            torch.cuda.empty_cache()

    errors, leaks = [], []
    with torch.no_grad():
        for entry in holdouts:
            output, target, keep, alpha, _ = render(entry, 2)
            error = (((output - target) ** 2 * keep).sum() / keep.sum().clamp_min(1) / 3)
            errors.append(float(error.cpu()))
            leaks.append(float((alpha * (1 - keep)).mean().cpu()))
    psnr = -10 * math.log10(max(sum(errors) / len(errors), 1e-10))
    leak = sum(leaks) / len(leaks)
    means = params["means"].detach().cpu().numpy()
    scales = params["scales"].detach().cpu().numpy()
    radii = 2 * np.exp(scales).max(axis=1)
    safe = foreground_clearance(means, seeds["target"], seeds["front"],
                                seeds["up"], seeds["headRadii"], splat_radius=radii)
    stable, compact, screen_radii = environment_view_support(path, cameras, means, scales)
    opaque = (1 / (1 + np.exp(-params["opacities"].detach().cpu().numpy()))) > .035
    selected = np.flatnonzero(safe & stable & compact & opaque)
    if len(selected) > 60000:
        opacity = params["opacities"].detach().cpu().numpy()
        selected = selected[np.argsort(opacity[selected])[-60000:]]
    metrics = {"steps": steps, "sourceResolution": "room_half_only", "seedPoints": len(xyz),
               "trainedSplats": len(means), "exportSplats": len(selected),
               "unsafeOrTransparentRemoved": int(len(means) - len(selected)),
               "multiViewSupported": int(stable.sum()),
               "orbitClearanceSplats": int(safe.sum()),
               "boundedFootprint": int(compact.sum()),
               "maximumExportRadiusAtHalfResolution": round(float(screen_radii[selected].max()), 2)
               if len(selected) else None,
               "heldOutRoomPsnrDb": round(psnr, 2), "alphaOverProtectedPerson": round(leak, 4),
               "peakCudaMemoryMiB": round(torch.cuda.max_memory_allocated() / 1024**2),
               "lossSamples": losses, "protectedOrbitDegrees": 65,
               "roomGeometryFromVideo": True}
    (path / "environment_training_metrics.json").write_text(json.dumps(metrics, separators=(",", ":")),
                                                              encoding="utf-8")
    if psnr < 12 or leak > .08 or len(selected) < 300:
        raise RuntimeError("environment_reconstruction_quality_low")

    with np.load(path / "portrait_face_splats.npz") as face:
        face_count = len(face["means"])
        all_splats = {}
        for key in ("means", "scales", "quats", "opacities", "sh0", "shN"):
            room = params[key].detach().cpu().numpy()[selected].copy()
            if key == "opacities":
                alpha = np.clip(1 / (1 + np.exp(-room)), .001, .8)
                room = np.log(alpha / (1 - alpha))
            elif key == "sh0":
                rgb = np.clip(.5 + room * .28209479177387814, 0, 1)
                room = (rgb * .95 - .5) / .28209479177387814
            elif key == "shN":
                room *= .95
            all_splats[key] = torch.from_numpy(np.concatenate((face[key], room), axis=0))
    output = path / "portrait.gaussian.combined.ply"
    export_splats(**all_splats, format="ply", save_to=str(output))
    if not output.is_file() or output.stat().st_size < 4096:
        raise RuntimeError("combined_gaussian_missing")
    output.replace(path / "portrait.gaussian.ply")
    view_path = path / "portrait.view.json"
    view = json.loads(view_path.read_text(encoding="utf-8"))
    view["editableSplats"] = face_count
    view["recordedEnvironmentSplats"] = len(selected)
    view_path.write_text(json.dumps(view, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return metrics


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: reconstruction_train_environment.py JOB_DIR")
    train(Path(sys.argv[1]))
