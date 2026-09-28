"""Audit one private full-scene PLY against recorded views without editing it.

This uses the original source frames and their registered world cameras. It
does not turn absent/occluded pixels into negative evidence, and never writes
a candidate PLY or touches the tablet. Output remains under an ignored private
research directory chosen by the caller.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw

from reconstruction_joint_visibility import (conservation_error, load_recorded_ply,
                                             posed_points, render_shared, sha256_file,
                                             visible_point_scores)
from reconstruction_train import load_scene


def load_upright_rgb(path: Path, size: tuple[int, int]) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB").resize(size, Image.Resampling.BILINEAR),
                          dtype=np.float32) / 255


def load_mask(path: Path, size: tuple[int, int], erode: int = 0) -> np.ndarray:
    with Image.open(path) as image:
        mask = np.asarray(image.convert("L").resize(size, Image.Resampling.NEAREST)) > 127
    if erode:
        mask = cv2.erode(mask.astype(np.uint8),
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                   (erode * 2 + 1,) * 2)) > 0
    return mask


def image_u8(array: np.ndarray) -> Image.Image:
    return Image.fromarray(np.uint8(np.clip(array, 0, 1) * 255), "RGB")


def projected_center_candidates(asset: dict, world_pose: np.ndarray,
                                face_pose: np.ndarray, K: np.ndarray,
                                inside: np.ndarray) -> tuple[dict, np.ndarray]:
    """CPU shortlist only: centers/axis scales cannot prove sorted visibility."""
    means, _, _ = posed_points(asset, world_pose, face_pose)
    xyz = means.detach().cpu().numpy() @ world_pose[:3, :3].T + world_pose[:3, 3]
    z = xyz[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = np.rint(xyz[:, 0] * K[0, 0] / z + K[0, 2]).astype(np.int64)
        v = np.rint(xyz[:, 1] * K[1, 1] / z + K[1, 2]).astype(np.int64)
    height, width = inside.shape
    on_image = ((z > .01) & np.isfinite(z) & (u >= 0) & (u < width) &
                (v >= 0) & (v < height))
    hits = np.zeros(len(z), dtype=bool)
    ids = np.flatnonzero(on_image)
    hits[ids] = inside[v[ids], u[ids]]
    person = asset["person_count"]
    person_depth = z[np.flatnonzero(hits[:person])]
    room_ids = np.flatnonzero(hits[person:]) + person
    result = {"environmentCentersProjectInsideHead": int(len(room_ids)),
              "personCentersProjectInsideHead": int(len(person_depth)),
              "note": "Center projection and largest 3D axis are candidates, not opacity or true conic footprint"}
    if len(person_depth) > 10 and len(room_ids):
        lower, upper = np.quantile(person_depth, [.1, .9])
        uncertainty = max(.03, .1 * (upper - lower))
        in_front = z[room_ids] < lower - uncertainty
        axis = asset["scales"][room_ids].detach().cpu().numpy().max(axis=1)
        radius_proxy = K[0, 0] * axis / z[room_ids]
        result.update({"personDepthP10P90": [float(lower), float(upper)],
                       "depthUncertaintyWorldUnits": float(uncertainty),
                       "roomCentersStronglyBeforeHeadP10": int(in_front.sum()),
                       "projectedLargestAxisProxyP50P90Px":
                       np.quantile(radius_proxy, [.5, .9]).tolist(),
                       "wideAxisProxyOver25Px": int((radius_proxy > 25).sum())})
        return result, np.column_stack((u[room_ids[in_front]], v[room_ids[in_front]]))
    return result, np.empty((0, 2), dtype=np.int64)


def audit(job: Path, ply: Path, output: Path, names: list[str], scale: float = .5) -> dict:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    started = time.perf_counter()
    view = json.loads((job / "portrait.view.json").read_text(encoding="utf-8"))
    cuda = torch.cuda.is_available()
    asset = load_recorded_ply(ply, int(view["editableSplats"]),
                              device="cuda" if cuda else "cpu")
    cameras = {entry[0].name: entry for entry in load_scene(job)[0]}
    with np.load(job / "face_camera_poses.npz") as source:
        face_poses = dict(zip(map(str, source["names"]), source["w2c"]))
    if len(set(names)) != len(names) or not names or any(name not in cameras or
            name not in face_poses for name in names):
        raise ValueError("requested_recorded_view_missing_or_duplicated")
    if not 0 < scale <= 1:
        raise ValueError("scale_out_of_range")
    person = asset["person_count"]
    intrusion = torch.zeros(len(asset["means"]), device=asset["means"].device)
    room_support = torch.zeros_like(intrusion)
    checks = []
    if cuda:
        torch.cuda.reset_peak_memory_stats()
    for name in names:
        frame_path, world_pose, K, original_width, original_height = cameras[name]
        width, height = round(original_width * scale), round(original_height * scale)
        K = K.copy()
        K[:2, :] *= scale
        source_rgb = load_upright_rgb(frame_path, (width, height))
        inside = load_mask(job / "face_masks" / (name + ".png"),
                           (width, height), erode=max(2, round(12 * scale)))
        background = load_mask(job / "environment_masks" / (name + ".png"),
                               (width, height), erode=max(2, round(8 * scale)))
        projection, candidate_xy = projected_center_candidates(
            asset, world_pose, face_poses[name], K, inside)
        if not cuda:
            overlay = image_u8(source_rgb)
            draw = ImageDraw.Draw(overlay)
            for x, y in candidate_xy[:500]:
                draw.ellipse((int(x)-2, int(y)-2, int(x)+2, int(y)+2),
                             fill=(54, 216, 225))
            overlay.save(output / f"{Path(name).stem}-candidate-centers-not-render.png")
            checks.append({"name": name, "sourcePngSha256": sha256_file(frame_path),
                           "analysisResolution": [width, height],
                           "projectedCandidates": projection,
                           "renderStatus": "unverified_CUDA_unavailable"})
            continue
        rendered = render_shared(asset, world_pose, face_poses[name], K,
                                 width, height, point_probe=True)
        q_face = rendered["q_person"].detach().cpu().numpy()
        q_room = rendered["q_environment"].detach().cpu().numpy()
        alpha = rendered["alpha"].detach().cpu().numpy()
        rgb = rendered["rgb"].detach().cpu().numpy()
        # Source-only interior remains the coverage denominator.  The overlap
        # subset is used only to shortlist points that interrupt an existing
        # person surface; it must not hide true face holes from the report.
        overlap = inside & (q_face > .35)
        face_weights = torch.as_tensor(overlap.astype(np.float32), device="cuda")
        room_weights = torch.as_tensor(background.astype(np.float32), device="cuda")
        intrusion += visible_point_scores(rendered, face_weights, retain_graph=True)
        room_support += visible_point_scores(rendered, room_weights)
        # A composite helps inspect missing coverage while leaving alpha and
        # source contributions available separately in the report.
        display = np.clip(rgb + (1 - alpha[..., None]) * .08, 0, 1)
        tiles = [image_u8(source_rgb), image_u8(display),
                 image_u8(np.stack((q_room, np.zeros_like(q_room), q_face), axis=-1)),
                 image_u8(np.repeat(alpha[..., None], 3, axis=2))]
        canvas = Image.new("RGB", (width * 4, height + 32), (18, 19, 28))
        for index, tile in enumerate(tiles):
            canvas.paste(tile, (index * width, 32))
        ImageDraw.Draw(canvas).text((8, 8),
            "SOURCE                    SHARED RGB                 ENV red / PERSON blue          ALPHA",
            fill=(228, 226, 240))
        canvas.save(output / f"{Path(name).stem}-source-joint-contribution.png")
        face_pixels = int(inside.sum())
        room_pixels = int(background.sum())
        checks.append({"name": name, "sourcePngSha256": sha256_file(frame_path),
                       "projectedCandidates": projection,
                       "worldPoseSource": "COLMAP_registered_image_name",
                       "facePoseSource": "pose_compensated_by_same_name",
                       "analysisResolution": [width, height],
                       "conservationMaxAbs": conservation_error(rendered),
                       "sourceFaceInteriorPixels": face_pixels,
                       "personOverlapPixelsForPointShortlist": int(overlap.sum()),
                       "visibleRoomPixels": room_pixels,
                       "faceInternalEnvironmentContributionMean":
                       float(q_room[inside].mean()) if face_pixels else None,
                       "faceInternalPersonContributionMean":
                       float(q_face[inside].mean()) if face_pixels else None,
                       "visibleRoomEnvironmentContributionMean":
                       float(q_room[background].mean()) if room_pixels else None,
                       "visibleRoomRgbL1IncludingMissing":
                       float(np.abs(display[background]-source_rgb[background]).mean())
                       if room_pixels else None,
                       "faceRgbL1IncludingMissing":
                       float(np.abs(display[inside]-source_rgb[inside]).mean())
                       if inside.any() else None})
        del rendered
    bad = intrusion[person:].detach().cpu().numpy()
    good = room_support[person:].detach().cpu().numpy()
    if cuda:
        np.savez_compressed(output / "private-point-visible-weights.npz",
                            plySha256=np.asarray(asset["ply_sha256"]),
                            editableSplats=np.asarray(person, dtype=np.int64),
                            faceIntrusion=bad.astype(np.float32),
                            roomSupport=good.astype(np.float32))
    order = np.argsort(bad)[::-1][:64]
    suspects = [{"plyIndex": int(person + i),
                 "trustedFaceVisibleWeight": float(bad[i]),
                 "observedRoomVisibleWeight": float(good[i]),
                 "roomSupportToIntrusionRatio": float(good[i] / max(bad[i], 1e-9))}
                for i in order if bad[i] > 0]
    report = {"status": "shared_visibility_diagnostic" if cuda else
                        "projection_only_CUDA_unavailable_no_point_removed",
              "sourceCaptureSha256": sha256_file(job / "capture.mp4"),
              "plySha256": asset["ply_sha256"], "pointCount": len(asset["means"]),
              "partition": {"person": person, "environmentAndClothing": len(asset["means"])-person},
              "gsplat": "1.5.3", "scale": scale, "checks": checks,
              "suspects": suspects,
              "peakTorchAllocatedMiB": round(torch.cuda.max_memory_allocated()/1024**2)
              if cuda else None,
              "elapsedSeconds": round(time.perf_counter()-started, 2),
              "limits": ["The legacy two-way partition includes clothing in environment",
                         "The face mask is a 2D observation, not measured depth",
                         "Visible-point gradient measures current visibility, not delete counterfactual",
                         "These are selected development views, not a blind final audit"]}
    (output / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("ply", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("names", nargs="+")
    parser.add_argument("--scale", type=float, default=.5)
    args = parser.parse_args()
    result = audit(args.job, args.ply, args.output, args.names, args.scale)
    print(json.dumps({key: result[key] for key in
                      ("status", "plySha256", "peakTorchAllocatedMiB", "elapsedSeconds")},
                     ensure_ascii=False))
