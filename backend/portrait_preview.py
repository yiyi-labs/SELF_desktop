"""Make a small, static constellation preview from a verified gsplat PLY.

This projects Gaussian centers and DC colors from the actual reconstruction.
It is deliberately a low-cost navigation thumbnail, not a quality assessment
or a substitute for the full alpha-composited 3DGS viewer.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def _read_splats(path: Path) -> np.ndarray:
    with path.open("rb") as stream:
        header = bytearray()
        while not header.endswith(b"end_header\n"):
            line = stream.readline()
            if not line or len(header) + len(line) > 8192:
                raise ValueError("unsupported PLY header")
            header.extend(line)
        lines = header.decode("ascii").splitlines()
        if lines[:2] != ["ply", "format binary_little_endian 1.0"]:
            raise ValueError("preview expects the exported binary gsplat PLY")
        count = next(int(line.split()[2]) for line in lines if line.startswith("element vertex "))
        fields = [line.split()[2] for line in lines if line.startswith("property float ")]
        required = {"x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity"}
        if not required.issubset(fields) or not 100 <= count <= 2_000_000:
            raise ValueError("unsupported Gaussian fields or count")
        data = np.frombuffer(stream.read(), dtype=np.dtype([(field, "<f4") for field in fields]))
    if len(data) != count:
        raise ValueError("truncated Gaussian data")
    return data


def create(job_dir: Path) -> Path:
    splats = _read_splats(job_dir / "portrait.gaussian.ply")
    view = json.loads((job_dir / "portrait.view.json").read_text(encoding="utf-8"))
    eye = np.asarray(view["camera"], dtype=np.float64)
    target = np.asarray(view["target"], dtype=np.float64)
    up = np.asarray(view["up"], dtype=np.float64)
    forward = target - eye
    distance = np.linalg.norm(forward)
    if not np.isfinite(distance) or distance < .01:
        raise ValueError("invalid preview view")
    forward /= distance
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    up /= np.linalg.norm(up)
    fov = float(view["fovDegrees"])
    if not 10 <= fov <= 90:
        raise ValueError("invalid preview field of view")

    xyz = np.column_stack((splats["x"], splats["y"], splats["z"]))
    direction = xyz - eye
    depth = direction @ forward
    # Keep a generous head-centered volume so room splats do not dominate the
    # tiny preview. The full PLY stays untouched and opens on selection.
    in_head_volume = np.linalg.norm(xyz - target, axis=1) <= distance * .32
    opacity = 1 / (1 + np.exp(-np.clip(splats["opacity"], -30, 30)))
    mask = (depth > .02) & in_head_volume & (opacity > .08) & np.isfinite(xyz).all(axis=1)
    indices = np.flatnonzero(mask)
    side = 256
    focal = side / (2 * math.tan(math.radians(fov) / 2))
    x = side / 2 + focal * (direction[indices] @ right) / depth[indices]
    y = side / 2 - focal * (direction[indices] @ up) / depth[indices]
    visible = (x >= -4) & (x < side + 4) & (y >= -4) & (y < side + 4)
    indices, x, y = indices[visible], x[visible], y[visible]
    if len(indices) < 100:
        raise ValueError("too few projected splats for a recognizable preview")
    order = np.argsort(-depth[indices])
    indices, x, y = indices[order], x[order], y[order]
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    colors = np.clip(.5 + .28209479177387814 * np.column_stack(
        (splats["f_dc_0"][indices], splats["f_dc_1"][indices], splats["f_dc_2"][indices])), 0, 1)
    for index, (px, py) in enumerate(zip(x, y)):
        source = int(indices[index])
        radius = 1.0 if index % 7 else 1.55
        rgb = tuple(int(v * 255) for v in colors[index])
        draw.ellipse((px-radius, py-radius, px+radius, py+radius),
                     fill=(*rgb, int(min(205, 50 + opacity[source] * 175))))
    image = image.filter(ImageFilter.GaussianBlur(.35))
    output = job_dir / "portrait.preview.png"
    image.save(output, optimize=True)
    if output.stat().st_size > 512 * 1024:
        output.unlink()
        raise ValueError("preview exceeds size limit")
    return output


def create_3d_lod(job_dir: Path, limit: int = 24000) -> Path:
    """Keep complete gsplat records for a face-centered, bounded 3D preview."""
    source = job_dir / "portrait.gaussian.ply"
    with source.open("rb") as stream:
        header = bytearray()
        while not header.endswith(b"end_header\n"):
            line = stream.readline()
            if not line or len(header) + len(line) > 8192:
                raise ValueError("unsupported PLY header")
            header.extend(line)
        text = header.decode("ascii")
        count_line = next(line for line in text.splitlines() if line.startswith("element vertex "))
        count = int(count_line.split()[2])
        fields = [line.split()[2] for line in text.splitlines() if line.startswith("property float ")]
        if not {"x", "y", "z", "opacity"}.issubset(fields):
            raise ValueError("unsupported Gaussian fields")
        records = np.frombuffer(stream.read(), dtype=np.dtype([(field, "<f4") for field in fields]))
    if len(records) != count or count < 1000:
        raise ValueError("truncated or tiny Gaussian asset")
    view = json.loads((job_dir / "portrait.view.json").read_text(encoding="utf-8"))
    eye = np.asarray(view["camera"], dtype=np.float64)
    target = np.asarray(view["target"], dtype=np.float64)
    radius = np.linalg.norm(target - eye) * .34
    xyz = np.column_stack((records["x"], records["y"], records["z"]))
    opacity = 1 / (1 + np.exp(-np.clip(records["opacity"], -30, 30)))
    candidates = np.flatnonzero((np.linalg.norm(xyz - target, axis=1) <= radius) &
                                (opacity > .055) & np.isfinite(xyz).all(axis=1))
    if len(candidates) < 1500:
        raise ValueError("preview lacks enough face-centered splats")
    if len(candidates) > limit:
        rng = np.random.default_rng(20260924)
        # Favor the opaque detail splats while retaining a spatially diverse sample.
        weights = np.maximum(.03, opacity[candidates])
        weights /= weights.sum()
        candidates = rng.choice(candidates, size=limit, replace=False, p=weights)
    candidates = np.sort(candidates)
    output = job_dir / "portrait.preview.gaussian.ply"
    new_header = text.replace(count_line, f"element vertex {len(candidates)}", 1).encode("ascii")
    with output.open("wb") as stream:
        stream.write(new_header)
        stream.write(records[candidates].tobytes())
    if not 4096 <= output.stat().st_size <= 12 * 1024 * 1024:
        output.unlink()
        raise ValueError("3D preview outside bounded transfer size")
    return output


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: portrait_preview.py JOB_DIR")
    print(create(Path(sys.argv[1])))
    print(create_3d_lod(Path(sys.argv[1])))
