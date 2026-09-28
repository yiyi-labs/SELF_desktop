"""Bounded, static-only ALIKED+LightGlue pair probe for E1.

Features are in a new namespace and are never inserted into the SIFT/COLMAP
database. Pairwise geometry alone cannot authorize a world camera pose.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch


THIRD_PARTY = Path(__file__).resolve().parent / ".sources/third_party"
LIGHTGLUE_SOURCE = THIRD_PARTY / "lightglue-eb42fee2"
WEIGHTS = THIRD_PARTY / "weights"
WEIGHT_SHA = {
    "aliked-n16.pth": "5be8704840ed662d9d8c561bf7279c222092674e7eb05fd0feab94899e9d82f2",
    "aliked_lightglue_v0-1_arxiv.pth": "d975e965b105311a6143194852297dff4f02aea5cc2e10cecfed966ca0e22503",
}
SOURCE_SHA256 = "7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf"


def check_weights() -> None:
    for name, digest in WEIGHT_SHA.items():
        source = WEIGHTS / name
        cached = THIRD_PARTY / "torch-cache/hub/checkpoints" / name
        if (hashlib.sha256(source.read_bytes()).hexdigest() != digest
                or hashlib.sha256(cached.read_bytes()).hexdigest() != digest):
            raise ValueError(f"match_weight_hash_changed:{name}")


def grid_occupancy(points: np.ndarray, width: int, height: int) -> int:
    return len({(min(3, int(x * 4 / width)), min(3, int(y * 4 / height)))
                for x, y in points})


def run(job: Path, pair: tuple[int, int], margin_px: int = 32) -> dict:
    check_weights()
    os.environ["TORCH_HOME"] = str(THIRD_PARTY / "torch-cache")
    sys.path.insert(0, str(LIGHTGLUE_SOURCE))
    from lightglue import ALIKED, LightGlue

    root = job / "static_sfm_probe_stride1"
    out = root / "aliked_lightglue_local_20260927"
    cache = out / "features"
    cache.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    extractor = ALIKED(max_num_keypoints=2048).eval().to(device)
    matcher = LightGlue(features="aliked").eval().to(device)

    def features(index: int) -> tuple[dict, dict]:
        name = f"frame_{index:04d}.png"
        frame = job / "frames" / name
        mask_file = root / "masks" / (name + ".png")
        mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
        image = cv2.imread(str(frame), cv2.IMREAD_COLOR)
        if mask is None or image is None or mask.shape != image.shape[:2]:
            raise ValueError(f"image_or_mask_missing:{name}")
        image_hash = hashlib.sha256(frame.read_bytes()).hexdigest()
        mask_hash = hashlib.sha256(mask_file.read_bytes()).hexdigest()
        bridge_manifest = job / "bridge.manifest.json"
        if bridge_manifest.is_file():
            bridge = json.loads(bridge_manifest.read_text(encoding="utf-8"))
            if bridge["sourceSha256"] != SOURCE_SHA256:
                raise ValueError("source_bridge_capture_changed")
            recorded = next((row for row in bridge["records"]
                             if row["sourceIndexZeroBased"] == index), None)
            if (recorded is None or recorded["imageSha256"] != image_hash
                    or recorded["staticMaskSha256"] != mask_hash):
                raise ValueError(f"source_bridge_frame_or_mask_changed:{name}")
        # Keep the descriptor footprint well away from the dynamic-person mask.
        valid = cv2.erode(mask, cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (margin_px * 2 + 1,) * 2))
        cache_identity = {"imageSha256": image_hash, "maskSha256": mask_hash,
                          "extractorWeightSha256": WEIGHT_SHA["aliked-n16.pth"],
                          "codeCommit": "eb42fee2d71449efb0aa5c10549752b5d75384d8",
                          "resizeLongSide": 1024, "maxKeypoints": 2048,
                          "maskExtraErosionPx": margin_px}
        cache_key = hashlib.sha256(json.dumps(cache_identity, sort_keys=True).encode()).hexdigest()[:24]
        feature_file = cache / f"{name}.{cache_key}.npz"
        if feature_file.is_file():
            with np.load(feature_file) as stored:
                points = stored["keypoints"]
                descriptors = stored["descriptors"].astype(np.float32)
                raw_count = int(stored["raw_count"])
        else:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            tensor = torch.from_numpy(rgb.copy()).permute(2, 0, 1).float().to(device) / 255.
            with torch.inference_mode():
                result = extractor.extract(tensor)
            raw = result["keypoints"][0].cpu().numpy()
            x = np.clip(np.round(raw[:, 0]).astype(int), 0, mask.shape[1] - 1)
            y = np.clip(np.round(raw[:, 1]).astype(int), 0, mask.shape[0] - 1)
            keep = valid[y, x] > 0
            points = raw[keep].astype(np.float32)
            descriptors = result["descriptors"][0].cpu().numpy()[keep].astype(np.float32)
            raw_count = len(raw)
            np.savez_compressed(feature_file, keypoints=points,
                                descriptors=descriptors.astype(np.float16),
                                raw_count=np.asarray(raw_count))
        if len(points) < 20:
            raise ValueError(f"too_few_static_features:{name}:{len(points)}")
        result = {"keypoints": torch.from_numpy(points)[None].to(device),
                  "descriptors": torch.from_numpy(descriptors)[None].to(device),
                  "image_size": torch.tensor([[image.shape[1], image.shape[0]]],
                                             dtype=torch.float32, device=device)}
        return result, {"name": name, "raw": raw_count, "static": len(points),
                        "imageSha256": image_hash, "maskSha256": mask_hash,
                        "featureCacheKey": cache_key,
                        "staticGridCells4x4": grid_occupancy(points, image.shape[1], image.shape[0])}

    features0, info0 = features(pair[0])
    features1, info1 = features(pair[1])
    with torch.inference_mode():
        output = matcher({"image0": features0, "image1": features1})
    matches = output["matches"][0].cpu().numpy()
    points0 = features0["keypoints"][0].cpu().numpy()[matches[:, 0]]
    points1 = features1["keypoints"][0].cpu().numpy()[matches[:, 1]]
    if len(matches) >= 8:
        fundamental, inliers = cv2.findFundamentalMat(
            points0, points1, cv2.USAC_MAGSAC, 1.5, .999, 10000)
        inliers = inliers.reshape(-1).astype(bool) if fundamental is not None else np.zeros(len(matches), bool)
    else:
        inliers = np.zeros(len(matches), bool)
    np.savez_compressed(out / f"pair_{pair[0]:04d}_{pair[1]:04d}.matches.npz",
                        matches=matches.astype(np.int32),
                        static_fundamental_inliers=inliers,
                        keypoints0=features0["keypoints"][0].cpu().numpy(),
                        keypoints1=features1["keypoints"][0].cpu().numpy())
    result = {"sourceSha256": SOURCE_SHA256,
              "featureModel": "ALIKED N16", "matcher": "LightGlue ALIKED v0.1_arxiv",
              "codeCommit": "eb42fee2d71449efb0aa5c10549752b5d75384d8",
              "weightsSha256": WEIGHT_SHA,
              "image0": info0, "image1": info1, "maskExtraErosionPx": margin_px,
              "matches": int(len(matches)), "pairwiseStaticFundamentalInliers": int(inliers.sum()),
              "inlierGrid0_4x4": grid_occupancy(points0[inliers], 1080, 1920),
              "inlierGrid1_4x4": grid_occupancy(points1[inliers], 1080, 1920),
              "notAWorldPose": True,
              "elapsedSeconds": round(time.perf_counter() - started, 2),
              "peakAllocatedMiB": (round(torch.cuda.max_memory_allocated() / 1024 ** 2, 1)
                                   if device.type == "cuda" else None)}
    (out / f"pair_{pair[0]:04d}_{pair[1]:04d}.audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("first", type=int)
    parser.add_argument("second", type=int)
    args = parser.parse_args()
    run(args.job, (args.first, args.second))
