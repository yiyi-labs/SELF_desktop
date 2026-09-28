"""Fixed-count real-frame head/room shared-occlusion research pilot.

This deliberately cannot publish a model: torso/neck are not fitted, the
side-view camera gate fails, and generic face geometry is only an initializer.
It tests the real image, pose, mask, source-parameter and joint-raster paths.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from scipy.spatial import cKDTree
from gsplat.rendering import rasterization

from probe_static_alignment import best_model
from reconstruction_pose import canonical_vertices, pose_from_landmarks


TRAIN = (12, 25, 50, 110, 122, 136)
HELD = (40, 150)
WIDTH, HEIGHT = 270, 480


def sample_face(vertices: np.ndarray, obj: Path, count: int = 2500) -> np.ndarray:
    faces = []
    for line in obj.read_text(encoding="utf-8").splitlines():
        if line.startswith("f "):
            faces.append([int(field.split("/")[0]) - 1 for field in line.split()[1:4]])
    triangles = vertices[np.asarray(faces, dtype=np.int32)]
    area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                   triangles[:, 2] - triangles[:, 0]), axis=1)
    if area.sum() <= 0:
        raise ValueError("canonical_face_has_no_area")
    rng = np.random.default_rng(260927)
    chosen = triangles[rng.choice(len(triangles), size=count, p=area / area.sum())]
    a, b = rng.random(count), rng.random(count)
    over = a + b > 1
    a[over], b[over] = 1 - a[over], 1 - b[over]
    return (chosen[:, 0] + a[:, None] * (chosen[:, 1] - chosen[:, 0]) +
            b[:, None] * (chosen[:, 2] - chosen[:, 0]))


def run(job: Path, steps: int = 160) -> dict:
    started = time.perf_counter()
    root = job / "static_sfm_probe_stride1"
    out_dir = root / "joint_fixed_pilot" / f"held_{HELD[0]}_{HELD[1]}"
    out_dir.mkdir(exist_ok=True)
    selected = TRAIN + HELD
    trust = {row["name"]: row for row in json.loads(
        (root / "trusted_views.audit.json").read_text(encoding="utf-8"))["frames"]}
    for index in selected:
        if not trust[f"frame_{index:04d}.png"]["researchTrusted"]:
            raise ValueError(f"pilot_camera_not_trusted:{index}")
    model = best_model(root / "targeted_global" / "sparse")
    images = {image.name: image for image in model.images.values() if image.has_pose}
    canonical = canonical_vertices()
    sample = sample_face(canonical, Path(__file__).resolve().parent / "models" / "canonical_face_model.obj")
    scale = json.loads((root / "person_motion_contract.audit.json").read_text(
        encoding="utf-8"))["sharedScaleSceneUnitsPerCanonicalUnit"]
    records = {}
    with np.load(job / "face_landmarks.npz") as landmarks:
        for index in selected:
            name = f"frame_{index:04d}.png"
            image = images[name]
            intrinsic = np.asarray(model.cameras[image.camera_id].calibration_matrix(), dtype=np.float64)
            face_R, face_t, _, _ = pose_from_landmarks(canonical, landmarks[name], intrinsic)
            w2c = np.eye(4)
            w2c[:3, :] = np.asarray(image.cam_from_world().matrix())
            c2w = np.linalg.inv(w2c)
            head = np.eye(4)
            head[:3, :3] = c2w[:3, :3] @ face_R
            head[:3, 3] = c2w[:3, 3] + scale * c2w[:3, :3] @ face_t
            rgb = cv2.cvtColor(cv2.imread(str(job / "frames" / name), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
            face_mask = cv2.imread(str(job / "face_masks" / (name + ".png")), cv2.IMREAD_GRAYSCALE)
            room_mask = cv2.imread(str(root / "masks" / (name + ".png")), cv2.IMREAD_GRAYSCALE)
            if rgb is None or face_mask is None or room_mask is None:
                raise ValueError(f"pilot_frame_or_mask_missing:{name}")
            records[index] = {"name": name, "w2c": w2c, "K": intrinsic,
                              "head": head,
                              "target": cv2.resize(rgb, (WIDTH, HEIGHT), interpolation=cv2.INTER_AREA),
                              "face": cv2.resize(face_mask, (WIDTH, HEIGHT), interpolation=cv2.INTER_NEAREST),
                              "room": cv2.resize(room_mask, (WIDTH, HEIGHT), interpolation=cv2.INTER_NEAREST)}
    reference_head = records[12]["head"]
    reference_world = (reference_head[:3, :3] @ (sample * scale).T).T + reference_head[:3, 3]
    # Initial color observation uses only the reference image; missing or
    # occluded surfaces remain generic and must not be called reconstructed.
    ref = records[12]
    projected = (ref["K"] @ (ref["w2c"][:3, :3] @ reference_world.T +
                             ref["w2c"][:3, 3, None])).T
    uv = projected[:, :2] / projected[:, 2, None]
    full = cv2.cvtColor(cv2.imread(str(job / "frames" / ref["name"])), cv2.COLOR_BGR2RGB)
    x = np.clip(uv[:, 0].round().astype(int), 0, full.shape[1] - 1)
    y = np.clip(uv[:, 1].round().astype(int), 0, full.shape[0] - 1)
    seed_colors = np.asarray(full[y, x], dtype=np.float32) / 255
    visible = (uv[:, 0] >= 0) & (uv[:, 0] < full.shape[1]) & \
              (uv[:, 1] >= 0) & (uv[:, 1] < full.shape[0])
    source_mask = cv2.imread(str(job / "face_masks" / (ref["name"] + ".png")),
                             cv2.IMREAD_GRAYSCALE)
    visible &= source_mask[y, x] > 0
    if visible.sum() < len(sample) // 3:
        raise ValueError("face_reference_color_support_insufficient")
    seed_colors[~visible] = np.median(seed_colors[visible], axis=0)
    room_points = [point for point in model.points3D.values() if point.track.length() >= 3]
    room_xyz = np.asarray([point.xyz for point in room_points], dtype=np.float32)
    room_colors = np.asarray([point.color for point in room_points], dtype=np.float32) / 255
    if len(room_xyz) < 1500:
        raise ValueError("too_few_static_room_seeds")
    face_spacing = cKDTree(reference_world).query(reference_world, k=4)[0][:, 1:].mean(axis=1)
    room_spacing = cKDTree(room_xyz).query(room_xyz, k=4)[0][:, 1:].mean(axis=1)
    face_spacing = np.clip(face_spacing * 1.4, .008, .09).astype(np.float32)
    room_spacing = np.clip(room_spacing * .7, .015, .15).astype(np.float32)
    device = "cuda"
    torch.manual_seed(260927)
    torch.cuda.reset_peak_memory_stats()
    face_source = torch.nn.Parameter(torch.from_numpy(reference_world.astype(np.float32)).to(device))
    face_color = torch.nn.Parameter(torch.logit(torch.from_numpy(np.clip(seed_colors, .02, .98)).to(device)))
    face_opacity = torch.nn.Parameter(torch.full((len(sample),), .7, device=device))
    room_xyz_t = torch.from_numpy(room_xyz).to(device)
    room_color_t = torch.from_numpy(room_colors).to(device)
    room_opacity = torch.full((len(room_xyz),), .48, device=device)
    scales = torch.from_numpy(np.concatenate((face_spacing, room_spacing))[:, None].repeat(3, axis=1)).to(device)
    quats = torch.tensor([[1., 0., 0., 0.]], device=device).repeat(len(sample) + len(room_xyz), 1)
    q = torch.zeros(len(sample) + len(room_xyz), 2, device=device)
    q[:len(sample), 1] = 1
    q[len(sample):, 0] = 1
    cache = {}
    for index, record in records.items():
        transform = record["head"] @ np.linalg.inv(reference_head)
        cache[index] = {
            "R": torch.from_numpy(transform[:3, :3].astype(np.float32)).to(device),
            "t": torch.from_numpy(transform[:3, 3].astype(np.float32)).to(device),
            "W2C": torch.from_numpy(record["w2c"].astype(np.float32)).to(device)[None],
            "K": torch.from_numpy((record["K"] * .25).astype(np.float32)).to(device)[None],
            "target": torch.from_numpy(record["target"].astype(np.float32)).to(device) / 255,
            "face": torch.from_numpy(record["face"].astype(np.float32)).to(device) / 255,
            "room": torch.from_numpy(record["room"].astype(np.float32)).to(device) / 255,
        }
        cache[index]["K"][0, 2, 2] = 1

    def forward(index: int, static_head: bool = False):
        item = cache[index]
        head = face_source if static_head else face_source @ item["R"].T + item["t"]
        means = torch.cat((head, room_xyz_t), dim=0)
        opacities = torch.cat((torch.sigmoid(face_opacity), room_opacity), dim=0)
        colors = torch.cat((torch.sigmoid(face_color), room_color_t), dim=0)
        channels = torch.cat((colors, q), dim=1)
        return rasterization(means, quats, scales, opacities, channels,
                             item["W2C"], item["K"], WIDTH, HEIGHT,
                             packed=True, sh_degree=None, near_plane=.01)

    optimizer = torch.optim.Adam([
        {"params": [face_source], "lr": .0008},
        {"params": [face_color], "lr": .025},
        {"params": [face_opacity], "lr": .012},
    ])
    with torch.no_grad():
        initial_per_frame = []
        for index in TRAIN:
            rendered, _, _ = forward(index)
            image = rendered[0, ..., :3]
            target, face, room = cache[index]["target"], cache[index]["face"], cache[index]["room"]
            error = (image - target).abs().mean(dim=-1)
            initial_per_frame.append({"frame": index,
                "faceRgbL1": round(float((error * face).sum() / face.sum()), 4),
                "roomRgbL1": round(float((error * room).sum() / room.sum()), 4)})
    initial = None
    samples = []
    for step in range(steps):
        index = TRAIN[step % len(TRAIN)]
        out, alpha, _ = forward(index)
        rgb, person_q, room_q = out[0, ..., :3], out[0, ..., 4], out[0, ..., 3]
        target, face, room = cache[index]["target"], cache[index]["face"], cache[index]["room"]
        rgb_error = (rgb - target).abs().mean(dim=-1)
        loss = (1.6 * (rgb_error * face).sum() / face.sum().clamp_min(1) +
                .4 * (rgb_error * room).sum() / room.sum().clamp_min(1) +
                .08 * ((1 - person_q) * face).sum() / face.sum().clamp_min(1) +
                .08 * (room_q * face).sum() / face.sum().clamp_min(1) +
                .01 * ((face_source - torch.from_numpy(reference_world.astype(np.float32)).to(device)) ** 2).mean())
        if initial is None:
            initial = float(loss.detach())
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        if step % 40 == 0 or step == steps - 1:
            samples.append([step, round(float(loss.detach()), 5)])
    metrics = []
    with torch.no_grad():
        for index in selected:
            for fixed in (False, True):
                out, alpha, _ = forward(index, static_head=fixed)
                out, alpha = out[0], alpha[0, ..., 0]
                qsum = out[..., 3] + out[..., 4]
                face, room, target = cache[index]["face"], cache[index]["room"], cache[index]["target"]
                error = (out[..., :3] - target).abs().mean(dim=-1)
                metrics.append({"frame": index, "heldOut": index in HELD, "staticHead": fixed,
                                "faceRgbL1": round(float((error * face).sum() / face.sum()), 4),
                                "roomRgbL1": round(float((error * room).sum() / room.sum()), 4),
                                "facePersonContribution": round(float((out[..., 4] * face).sum() / face.sum()), 4),
                                "faceRoomContribution": round(float((out[..., 3] * face).sum() / face.sum()), 4),
                                "roomContribution": round(float((out[..., 3] * room).sum() / room.sum()), 4),
                                "conservationMax": round(float((qsum - alpha).abs().max()), 7)})
                if index in HELD or index in (25, 110):
                    composite = torch.cat((out[..., :3], alpha[..., None]), dim=-1).detach().cpu().numpy()
                    Image.fromarray(np.uint8(np.clip(composite * 255, 0, 255)), "RGBA").save(
                        out_dir / f"frame_{index:04d}-{'fixed' if fixed else 'dynamic'}.png")
                    Image.fromarray(cache[index]["target"].mul(255).byte().cpu().numpy(), "RGB").save(
                        out_dir / f"frame_{index:04d}-source.png")
    result = {"status": "research_pilot_only", "inputCaptureSha256": json.loads(
                  (job / "frame_manifest.audit.json").read_text(encoding="utf-8"))["captureSha256"],
              "trainingFrames": list(TRAIN), "heldFrames": list(HELD),
              "faceSplats": len(sample), "roomSplats": len(room_xyz),
              "allGroupsInEveryForward": True, "pointCountFixed": True,
              "headAndRoomShareStaticCamera": True,
              "neckShoulderAndClothing": "absent_fails_E3",
              "untrustedSideViewsExcluded": True,
              "initialLoss": round(initial, 5), "lossSamples": samples,
              "lossSamplesAreRoundRobinDifferentFrames": True,
              "initialPerTrainingFrame": initial_per_frame,
              "evaluations": metrics,
              "peakCudaMiB": round(torch.cuda.max_memory_allocated() / 1024 ** 2, 1),
              "elapsedSeconds": round(time.perf_counter() - started, 2),
              "warning": "generic face and sparse room cannot establish a publishable portrait, body continuity, or target side coverage"}
    (out_dir / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) not in (2, 3):
        raise SystemExit("probe_real_joint_pilot.py JOB_DIR [steps]")
    run(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) == 3 else 160)
