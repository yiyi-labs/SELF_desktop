"""Bounded multiview hair patch/depth search in the existing fitted head frame.

This is evidence acquisition, not a generated hairstyle. Poorly textured or
non-unique patches are rejected instead of assigned a confident depth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

from probe_flame_hair_hull import local_observations, pixels
from probe_flame_open_fit import INTRINSIC, SOURCE_SHA256, filename


def zncc(a: np.ndarray, b: np.ndarray) -> float:
    aa = a-a.mean()
    bb = b-b.mean()
    den = np.linalg.norm(aa)*np.linalg.norm(bb)
    return float(np.sum(aa*bb)/den) if den > 1e-4 else -1.


def run(job: Path, reference: int, neighbors: tuple[int, ...], run_id: str) -> dict:
    if reference not in (40, 100) or not run_id.replace("-", "").isalnum():
        raise ValueError("unsupported_bounded_hair_sweep")
    if hashlib.sha256((job / "capture.mp4").read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("capture_hash_mismatch")
    root = job / "flame_open_e2_20260927"
    out = root / f"private-hair-depth-sweep-{run_id}"
    if out.exists():
        raise FileExistsError(out)
    out.mkdir()
    Fs = local_observations(root)
    frames = (reference,)+neighbors
    photo = {}
    gray = {}
    mask = {}
    for frame in frames:
        image = cv2.imread(str(job / "frames" / filename(frame)), cv2.IMREAD_COLOR)
        hair = cv2.imread(str(job / "portrait_components_20260927" /
                              f"hair-{filename(frame)}"), cv2.IMREAD_GRAYSCALE)
        if image is None or hair is None:
            raise FileNotFoundError(frame)
        photo[frame], gray[frame], mask[frame] = image, cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), hair > 127
    with np.load(root / "private-hair-hull-20260927/private-hair-shell.npz") as data:
        shell = data["local_points"]
    sx, sy, sz = pixels(shell, Fs[reference])
    valid = sz > .03
    tree = cKDTree(np.column_stack((sx[valid], sy[valid])))
    cloud_depth = sz[valid]
    hair_uint8 = cv2.erode(mask[reference].astype(np.uint8), np.ones((7, 7), np.uint8))*255
    corners = cv2.goodFeaturesToTrack(gray[reference], 1100, .006, 3,
                                      mask=hair_uint8, blockSize=5)
    if corners is None:
        raise RuntimeError("no_hair_patch_features")
    xy = corners.reshape(-1, 2)
    nearest_distance, nearest_id = tree.query(xy)
    xy = xy[nearest_distance < 4.]
    seed_z = cloud_depth[nearest_id[nearest_distance < 4.]]
    F0 = Fs[reference]
    K = INTRINSIC
    depth_offsets = np.arange(-.025, .0251, .0025, dtype=np.float32)
    accepted = []
    scored = []
    for index, ((u, v), z0) in enumerate(zip(xy, seed_z)):
        base_patch = cv2.getRectSubPix(gray[reference], (9, 9), (float(u),float(v))).astype(np.float32)
        if base_patch.std() < 7.:
            continue
        trace = []
        for offset in depth_offsets:
            z = float(z0+offset)
            p_cam = np.asarray([(u-K[0, 2])*z/K[0, 0], (v-K[1, 2])*z/K[1, 1], z])
            p_local = F0[:3, :3].T@(p_cam-F0[:3, 3])
            matches = []
            for other in neighbors:
                cam = Fs[other][:3, :3]@p_local+Fs[other][:3, 3]
                if cam[2] < .03:
                    continue
                uu = cam[0]*K[0, 0]/cam[2]+K[0, 2]
                vv = cam[1]*K[1, 1]/cam[2]+K[1, 2]
                if (uu < 6 or vv < 6 or uu > 1074 or vv > 1914 or
                        not mask[other][int(round(vv)),int(round(uu))]):
                    continue
                target = cv2.getRectSubPix(gray[other], (9, 9), (float(uu),float(vv))).astype(np.float32)
                matches.append(zncc(base_patch,target))
            trace.append(float(np.mean(matches)) if len(matches) == len(neighbors) else -1.)
        best = int(np.argmax(trace))
        if trace[best] < .65:
            continue
        other_scores = [s for j,s in enumerate(trace) if abs(j-best)>=3]
        separation = trace[best]-max(other_scores,default=-1.)
        scored.append({"pixel": [float(u),float(v)], "bestNcc": trace[best],
                       "distinctDepthMargin": separation, "depthOffsetMeters": float(depth_offsets[best])})
        if best in (0,len(depth_offsets)-1) or separation < .05:
            continue
        z = float(z0+depth_offsets[best])
        p_cam = np.asarray([(u-K[0, 2])*z/K[0, 0], (v-K[1, 2])*z/K[1, 1], z])
        p_local = F0[:3, :3].T@(p_cam-F0[:3, 3])
        accepted.append((index,p_local.astype(np.float32), (u,v),
                         trace[best],separation,depth_offsets[best]))
    indices = np.asarray([item[0] for item in accepted], np.int32)
    points = np.asarray([item[1] for item in accepted], np.float32).reshape(-1,3)
    pixel = np.asarray([item[2] for item in accepted], np.float32).reshape(-1,2)
    rgb = cv2.cvtColor(photo[reference], cv2.COLOR_BGR2RGB)
    source_rgb = rgb[np.rint(pixel[:,1]).astype(int), np.rint(pixel[:,0]).astype(int)]/255 if len(pixel) else np.empty((0,3))
    np.savez_compressed(out / "private-observed-depth-seeds.npz",
                        local_points=points, source_rgb=source_rgb.astype(np.float32),
                        source_pixel=pixel, reference_frame=reference,
                        neighbor_frames=np.asarray(neighbors),
                        source_sha256=np.asarray(SOURCE_SHA256))
    overlay = photo[reference].copy()
    for item in accepted:
        u,v = item[2]
        cv2.circle(overlay, (round(float(u)),round(float(v))), 3, (55,230,125), -1)
    cv2.imwrite(str(out / "private-accepted-hair-depth-points.jpg"),
                cv2.resize(overlay,None,fx=.5,fy=.5), [cv2.IMWRITE_JPEG_QUALITY,94])
    report = {"status": "training_view_multiview_hair_patch_depth_probe",
              "sourceSha256": SOURCE_SHA256, "reference": reference,
              "neighbors": list(neighbors), "corners": len(corners),
              "nearExistingHull": len(xy), "textureAndPhotometricCandidates": len(scored),
              "acceptedDistinctDepth": len(accepted),
              "acceptedBestNccP50": float(np.median([i[3] for i in accepted])) if accepted else None,
              "acceptedDepthOffsetMetersP50": float(np.median([i[5] for i in accepted])) if accepted else None,
              "limits": ["Head-local F_t is estimated rather than independently calibrated",
                         "Patch NCC can fail on hair motion, lighting and specular changes",
                         "No held pixels used for geometry or color",
                         "No accepted point is a full hairstyle or approved asset"]}
    (out / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--reference", type=int, default=40)
    parser.add_argument("--neighbors", type=int, nargs="+", default=[25,50])
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run(args.job, args.reference, tuple(args.neighbors), args.run_id)
