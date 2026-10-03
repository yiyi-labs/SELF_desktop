"""One PLY, one native camera: raw gsplat/PlayCanvas display comparison.

Prepare and compare are CPU operations. Render explicitly needs CUDA and never
trains. The existing pinned Node probe does the actual PlayCanvas draw. No live
profile, viewer, source asset or previous audit directory is changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def local_path(value):
    value = str(value).replace("\\", "/")
    if value[1:3] == ":/" and Path("/mnt").is_dir():
        value = "/mnt/" + value[0].lower() + "/" + value[3:]
    return Path(value).resolve()


def windows_path(path):
    path = str(Path(path).resolve()).replace("\\", "/")
    if path.startswith("/mnt/") and len(path) > 7 and path[6] == "/":
        return path[5].upper() + ":/" + path[7:]
    return path


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_camera(spec):
    required = ("sourceHash", "reference", "width", "height", "K", "C", "near", "far")
    if any(key not in spec for key in required):
        raise ValueError("explicit_source_reference_native_camera_required")
    w, h = spec["width"], spec["height"]
    K, C = np.asarray(spec["K"], np.float32), np.asarray(spec["C"], np.float32)
    if not isinstance(w, int) or not isinstance(h, int) or min(w, h) <= 0:
        raise ValueError("invalid_native_canvas")
    if K.shape != (3, 3) or C.shape != (4, 4) or not np.isfinite(K).all() or not np.isfinite(C).all():
        raise ValueError("invalid_camera_matrix")
    if K[0, 0] <= 0 or K[1, 1] <= 0 or not np.allclose(K[2], [0, 0, 1], atol=1e-6):
        raise ValueError("invalid_intrinsics")
    if abs(K[0, 1]) > 1e-6 or abs(K[1, 0]) > 1e-6:
        raise ValueError("skew_requires_an_explicit_renderer_contract")
    R = C[:3, :3]
    if not np.allclose(C[3], [0, 0, 0, 1], atol=1e-6) or not np.allclose(R @ R.T, np.eye(3), atol=2e-5) or abs(np.linalg.det(R)-1) > 2e-5:
        raise ValueError("camera_is_not_rigid_w2c")
    if not (0 < spec["near"] < spec["far"] < math.inf):
        raise ValueError("invalid_clipping")
    if len(spec["sourceHash"]) != 64 or not all(c in "0123456789abcdef" for c in spec["sourceHash"].lower()):
        raise ValueError("source_hash_required")
    world = np.linalg.inv(C)
    return {**{key: spec[key] for key in required}, "K": K.tolist(), "C": C.tolist(),
            "camera": world[:3, 3].tolist(), "target": (world[:3, 3]+world[:3, 2]).tolist(),
            "up": (-world[:3, 1]).tolist(), "published": False}


def private_output(path, *, fresh=False):
    path = local_path(path)
    private = Path(__file__).resolve().parent / ".sources"
    if not path.is_relative_to(private) or path == private:
        raise ValueError("output_must_be_in_project_private_sources")
    if fresh:
        path.mkdir(parents=True, exist_ok=False)
    return path


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2), encoding="utf-8")


def mask_domains(values, height, width):
    """No SIFT support mask substitution and no covered-pixel-only metric."""
    def get(key):
        mask = np.asarray(values[key])
        if mask.shape != (height, width):
            raise ValueError("mask_canvas_mismatch:"+key)
        return mask.astype(bool)
    face = get("face") if "face" in values else get("face_core") | get("face_boundary")
    if "observed_room" not in values:
        raise ValueError("explicit_observed_room_mask_required")
    room = get("observed_room")
    if not face.any() or not room.any():
        raise ValueError("empty_face_or_room_domains")
    # These are independently observed semantic masks, not a disjoint label
    # partition. Keep and report conflicts; silently trimming them would alter
    # the archived evaluation domains merely to satisfy an audit adapter.
    result = {"full": np.ones((height, width), bool), "face": face, "room": room}
    for key in ("hair_visible", "glasses_visible", "neck_cloth_visible", "neck_visible", "cloth_visible"):
        if key in values:
            result[key] = get(key)
    return result


def prepare(asset, camera, masks, rgb, out):
    asset, camera, masks = map(local_path, (asset, camera, masks))
    spec = validate_camera(json.loads(camera.read_text(encoding="utf-8")))
    with np.load(masks, allow_pickle=False) as source:
        domains = mask_domains(source, spec["height"], spec["width"])
    observed = None
    if rgb:
        from PIL import Image
        rgb = local_path(rgb)
        observed = np.asarray(Image.open(rgb).convert("RGB"), np.float32)/255
        if observed.shape != (spec["height"], spec["width"], 3):
            raise ValueError("source_rgb_must_match_native_canvas")
    out = private_output(out, fresh=True)
    # The pinned browser probe intentionally accepts private .sources assets.
    # A .data export is copied byte-for-byte to this audit only; source untouched.
    import shutil
    shutil.copyfile(asset, out/"input.ply")
    asset_hash = sha(asset)
    if sha(out/"input.ply") != asset_hash:
        raise ValueError("audit_asset_copy_mismatch")
    spec["assets"] = [{"label": "asset", "hash": asset_hash, "ply": windows_path(out/"input.ply")}]
    save_json(out/"display.json", spec)
    arrays = {"mask_"+key: value for key, value in domains.items()}
    if observed is not None:
        arrays["source_rgb"] = observed
    np.savez_compressed(out/"observation.npz", **arrays)
    receipt = {"assetHash": asset_hash, "cameraHash": canonical_hash(spec),
               "sourceHash": spec["sourceHash"], "reference": spec["reference"],
               "input": {"asset": str(asset), "camera": str(camera), "masks": str(masks), "rgb": str(rgb) if rgb else None},
               "inputHashes": {"camera": sha(camera), "masks": sha(masks), "rgb": sha(rgb) if rgb else None},
               "observationHash": sha(out/"observation.npz"), "published": False,
               "scope": "fixed asset diagnostic; not HarmonyOS, training, or quality approval"}
    save_json(out/"input-receipt.json", receipt)
    return {"out": str(out), "assetHash": asset_hash,
            "playcanvasCommand": "node scripts/probe-complete-baseline-display.mjs \""+windows_path(out/"display.json")+"\" \""+windows_path(out/"playcanvas")+"\""}


def load_audit(out):
    out = private_output(out)
    spec = json.loads((out/"display.json").read_text(encoding="utf-8"))
    receipt = json.loads((out/"input-receipt.json").read_text(encoding="utf-8"))
    if canonical_hash(spec) != receipt["cameraHash"] or sha(out/"input.ply") != receipt["assetHash"] or sha(out/"observation.npz") != receipt["observationHash"]:
        raise ValueError("frozen_audit_input_changed")
    return out, spec, receipt


def render(out):
    import time
    import torch
    import gsplat
    from gsplat import rasterization
    from probe_gs_contract import read_float_ply
    out, spec, receipt = load_audit(out)
    if (out/"gsplat.npz").exists() or (out/"gsplat-receipt.json").exists():
        raise ValueError("render_output_exists")
    if not torch.cuda.is_available():
        raise RuntimeError("cuda_unavailable_no_cpu_render_substitution")
    if gsplat.__version__ != "1.5.3":
        raise RuntimeError("locked_gsplat_1_5_3_required")
    started = time.perf_counter()
    a = read_float_ply(out/"input.ply")
    n = len(a["x"])
    t = lambda x: torch.as_tensor(np.ascontiguousarray(x), dtype=torch.float32, device="cuda")
    means = t(np.stack([a[k] for k in ("x", "y", "z")], 1))
    rotations = t(np.stack([a["rot_"+str(i)] for i in range(4)], 1))
    scales = t(np.stack([a["scale_"+str(i)] for i in range(3)], 1)).exp()
    opacities = t(a["opacity"]).sigmoid()
    dc = np.stack([a["f_dc_"+str(i)] for i in range(3)], 1)[:, None]
    rest_keys = sorted((key for key in a if key.startswith("f_rest_")), key=lambda key: int(key[7:]))
    if rest_keys != ["f_rest_"+str(i) for i in range(len(rest_keys))] or len(rest_keys) not in (0, 9, 24, 45):
        raise ValueError("unsupported_standard_sh_layout")
    rest = np.stack([a[key] for key in rest_keys], 1).reshape(n, 3, -1).transpose(0, 2, 1) if rest_keys else np.empty((n, 0, 3), np.float32)
    sh = t(np.concatenate((dc, rest), 1))
    degree = round(math.sqrt(sh.shape[1])-1)
    torch.cuda.reset_peak_memory_stats()
    with torch.no_grad():
        image, alpha, _ = rasterization(means, rotations, scales, opacities, sh,
            t(spec["C"])[None], t(spec["K"])[None], spec["width"], spec["height"],
            packed=True, sh_degree=degree, rasterize_mode="classic", near_plane=spec["near"], far_plane=spec["far"])
    torch.cuda.synchronize()
    np.savez_compressed(out/"gsplat.npz", rgb=image[0].cpu().numpy(), alpha=alpha[0, :, :, 0].cpu().numpy())
    result = {"assetHash": receipt["assetHash"], "cameraHash": receipt["cameraHash"],
              "pixelsHash": sha(out/"gsplat.npz"), "points": n, "shDegree": degree,
              "renderer": "gsplat1.5.3", "seconds": time.perf_counter()-started,
              "allocatedPeakMiB": torch.cuda.max_memory_allocated()/2**20, "optimizerSteps": 0}
    save_json(out/"gsplat-receipt.json", result)
    return result


def raw_rgba(path, height, width):
    raw = np.fromfile(path, np.uint8)
    if raw.size != height*width*4:
        raise ValueError("actual_canvas_byte_count_mismatch")
    # WebGL readPixels is already premultiplied; do not multiply alpha again.
    return raw.reshape(height, width, 4)[::-1].astype(np.float32)/255


def compare(out):
    from PIL import Image
    out, spec, receipt = load_audit(out)
    if (out/"comparison.json").exists():
        raise ValueError("comparison_exists")
    pc = json.loads((out/"playcanvas/report.json").read_text(encoding="utf-8"))
    gs_receipt = json.loads((out/"gsplat-receipt.json").read_text(encoding="utf-8"))
    if pc["sourceContract"] != spec or len(pc["rows"]) != 1:
        raise ValueError("playcanvas_camera_or_asset_contract_changed")
    if gs_receipt["assetHash"] != receipt["assetHash"] or gs_receipt["cameraHash"] != receipt["cameraHash"] or gs_receipt["pixelsHash"] != sha(out/"gsplat.npz"):
        raise ValueError("gsplat_asset_camera_or_pixels_changed")
    row = pc["rows"][0]
    if row["errors"] or row["info"]["canvas"] != [spec["width"], spec["height"]] or row["asset"] != spec["assets"][0]:
        raise ValueError("playcanvas_draw_not_valid")
    info = row["info"]
    if info["version"] != "2.22.4" or info["count"] != gs_receipt["points"]:
        raise ValueError("playcanvas_version_or_point_count_mismatch")
    world = np.asarray(row["info"]["world"]).reshape(4, 4).T
    expected_world = np.linalg.inv(np.asarray(spec["C"])) @ np.diag([1, -1, -1, 1])
    camera_error = float(np.max(np.abs(world-expected_world)))
    if camera_error > 2e-5:
        raise ValueError("actual_playcanvas_camera_mismatch")
    K, w, h, n, f = np.asarray(spec["K"]), spec["width"], spec["height"], spec["near"], spec["far"]
    expected_projection = np.asarray([2*K[0, 0]/w, 0, 0, 0, 0, 2*K[1, 1]/h, 0, 0,
        1-2*K[0, 2]/w, 2*K[1, 2]/h-1, -(f+n)/(f-n), -1, 0, 0, -2*f*n/(f-n), 0])
    projection_error = float(np.max(np.abs(expected_projection-np.asarray(info["projection"]))))
    if projection_error > 2e-5:
        raise ValueError("actual_playcanvas_projection_mismatch")
    actual = raw_rgba(out/"playcanvas/asset.rgba", spec["height"], spec["width"])
    with np.load(out/"gsplat.npz", allow_pickle=False) as gs, np.load(out/"observation.npz", allow_pickle=False) as observed:
        expected, expected_alpha = gs["rgb"], gs["alpha"]
        if expected.shape != actual[:, :, :3].shape or expected_alpha.shape != actual[:, :, 3].shape:
            raise ValueError("gsplat_canvas_mismatch")
        if not np.isfinite(expected).all() or not np.isfinite(expected_alpha).all():
            raise ValueError("nonfinite_render")
        rows = {}
        overlaps = {"faceRoomPixels": int((observed["mask_face"] & observed["mask_room"]).sum())}
        for key in observed.files:
            if not key.startswith("mask_"):
                continue
            mask = observed[key].astype(bool)
            if not mask.any():
                rows[key[5:]] = {"pixels": 0}
                continue
            rgb_diff = np.abs(actual[:, :, :3]-expected).mean(-1)[mask]
            alpha_diff = np.abs(actual[:, :, 3]-expected_alpha)[mask]
            metrics = {"pixels": int(mask.sum()), "rgbMae": float(rgb_diff.mean()), "rgbP90": float(np.quantile(rgb_diff, .9)),
                       "alphaMae": float(alpha_diff.mean()), "alphaP90": float(np.quantile(alpha_diff, .9)),
                       "gsplatLowAlphaFraction": float((expected_alpha[mask] < .8).mean()),
                       "playcanvasLowAlphaFraction": float((actual[:, :, 3][mask] < .8).mean())}
            if "source_rgb" in observed:
                target = observed["source_rgb"]
                metrics.update(gsplatSourceRgb=float(np.abs(expected-target).mean(-1)[mask].mean()),
                               playcanvasSourceRgb=float(np.abs(actual[:, :, :3]-target).mean(-1)[mask].mean()))
            rows[key[5:]] = metrics
        panels = ([observed["source_rgb"]] if "source_rgb" in observed else []) + [expected, actual[:, :, :3]]
        Image.fromarray((np.concatenate(panels, 1).clip(0, 1)*255).round().astype(np.uint8)).save(out/"source-gsplat-playcanvas.png")
    result = {"assetHash": receipt["assetHash"], "sourceHash": receipt["sourceHash"], "reference": receipt["reference"],
              "cameraHash": receipt["cameraHash"], "actualCameraMaxError": camera_error,
              "actualProjectionMaxError": projection_error, "C": spec["C"], "K": spec["K"],
              "canvas": [spec["width"], spec["height"]], "rows": rows, "playcanvas": row["info"],
              "gsplat": gs_receipt, "scope": "actual desktop draw; no HarmonyOS/fps/quality approval",
              "observedDomainOverlap": overlaps,
              "alphaMeaning": "low alpha is a coverage proxy, not proof of absent geometry",
              "columns": (["source"] if len(panels) == 3 else []) + ["gsplat", "PlayCanvas"], "published": False}
    save_json(out/"comparison.json", result)
    return {"assetHash": receipt["assetHash"], "rows": rows, "actualCameraMaxError": camera_error}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    stages = parser.add_subparsers(dest="stage", required=True)
    p = stages.add_parser("prepare")
    for name in ("asset", "camera", "masks", "out"):
        p.add_argument("--"+name, required=True)
    p.add_argument("--rgb")
    for name in ("render", "compare"):
        stages.add_parser(name).add_argument("--out", required=True)
    args = parser.parse_args()
    values = vars(args).copy();stage = values.pop("stage")
    print(json.dumps(globals()[stage](**values), indent=2), flush=True)
