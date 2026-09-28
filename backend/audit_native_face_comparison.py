"""Compare frozen full-scene assets at native decoded pixels in one view.

This is a private development diagnostic. The source frame is never altered,
and the tested PLYs are rendered together with their recorded room splats.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw

from reconstruction_joint_visibility import load_recorded_ply, render_shared, sha256_file
from reconstruction_train import load_scene


def edge_l1(image: np.ndarray, source: np.ndarray, mask: np.ndarray) -> float:
    dx_valid = mask[:, 1:] & mask[:, :-1]
    dy_valid = mask[1:] & mask[:-1]
    dx = np.abs((image[:, 1:] - image[:, :-1]) -
                (source[:, 1:] - source[:, :-1])).mean(axis=2)
    dy = np.abs((image[1:] - image[:-1]) -
                (source[1:] - source[:-1])).mean(axis=2)
    return .5 * (float(dx[dx_valid].mean()) + float(dy[dy_valid].mean()))


def audit(job: Path, names: list[str], assets: list[tuple[str, Path]],
          output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    if not torch.cuda.is_available():
        raise RuntimeError("native_face_comparison_requires_cuda")
    if len({label for label, _ in assets}) != len(assets):
        raise ValueError("duplicate_asset_label")
    output.mkdir(parents=True)
    cameras = {entry[0].name: entry for entry in load_scene(job)[0]}
    with np.load(job / "face_camera_poses.npz") as record:
        faces = dict(zip(map(str, record["names"]), record["w2c"]))
    regions = json.loads((job / "face_regions.json").read_text())
    bundle = []
    for label, ply in assets:
        view = json.loads((ply.parent / "portrait.view.json").read_text())
        bundle.append((label, load_recorded_ply(ply, int(view["editableSplats"]))))
    report = {"status": "private_native_pixel_development_comparison",
              "sourceCaptureSha256": sha256_file(job / "capture.mp4"),
              "assets": {label: asset["ply_sha256"] for label, asset in bundle},
              "frames": [], "notFinalAudit": True}
    for name in names:
        if name not in cameras or name not in faces or name not in regions:
            raise ValueError(f"unpaired_recorded_view:{name}")
        source_file, C, K, width, height = cameras[name]
        x, y, w, h = regions[name]
        x0, y0 = max(0, x-round(w*.38)), max(0, y-round(h*.38))
        x1, y1 = min(width, x+w+round(w*.38)), min(height, y+h+round(h*.38))
        with Image.open(source_file) as image:
            source = np.asarray(image.convert("RGB"))[y0:y1, x0:x1].astype(np.float32)/255
        with Image.open(job / "face_masks" / (name + ".png")) as image:
            observed = np.asarray(image.convert("L"))[y0:y1, x0:x1] > 127
        observed = cv2.erode(observed.astype(np.uint8),
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))) > 0
        if observed.sum() < 100 or x1-x0 < 64 or y1-y0 < 64:
            raise ValueError(f"invalid_native_face_crop:{name}")
        crop_K = K.copy()
        crop_K[0, 2] -= x0
        crop_K[1, 2] -= y0
        hcrop, wcrop = source.shape[:2]
        tiles = [Image.fromarray(np.uint8(source*255))]
        measurements = {}
        for label, asset in bundle:
            with torch.no_grad():
                result = render_shared(asset, C, faces[name], crop_K,
                                       wcrop, hcrop)
            rgb = result["rgb"].cpu().numpy()
            alpha = result["alpha"].cpu().numpy()
            display = np.clip(rgb + (1-alpha[..., None])*.08, 0, 1)
            qroom = result["q_environment"].cpu().numpy()
            qperson = result["q_person"].cpu().numpy()
            tiles.append(Image.fromarray(np.uint8(display*255)))
            measurements[label] = {
                "faceRgbL1IncludingMissing": float(np.abs(display[observed]-source[observed]).mean()),
                "faceSignedEdgeL1": edge_l1(display, source, observed),
                "faceAlphaMean": float(alpha[observed].mean()),
                "facePersonContributionMean": float(qperson[observed].mean()),
                "faceEnvironmentContributionMean": float(qroom[observed].mean()),
            }
        canvas = Image.new("RGB", (wcrop*len(tiles), hcrop+28), (19, 19, 29))
        draw = ImageDraw.Draw(canvas)
        for i, tile in enumerate(tiles):
            canvas.paste(tile, (i*wcrop, 28))
            draw.text((i*wcrop+8, 8), "SOURCE" if i == 0 else bundle[i-1][0],
                      fill=(232, 230, 240))
        canvas.save(output / f"{Path(name).stem}-native-face-comparison.png")
        report["frames"].append({"name": name, "sourcePngSha256": sha256_file(source_file),
                                  "nativeCrop": [x0, y0, x1, y1],
                                  "sourceMaskPixels": int(observed.sum()),
                                  "measurements": measurements})
    (output / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("names", nargs="+")
    parser.add_argument("--asset", action="append", required=True,
                        help="Unique label=path/to/portrait.gaussian.ply")
    args = parser.parse_args()
    assets = []
    for spec in args.asset:
        label, separator, path = spec.partition("=")
        if not separator or not label or not path:
            parser.error("--asset must be label=PLY_PATH")
        assets.append((label, Path(path)))
    result = audit(args.job, args.names, assets, args.output)
    print(json.dumps({"status": result["status"], "frames": len(result["frames"]),
                      "assets": result["assets"]}))
