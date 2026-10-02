"""Native-canvas device-test adapter; no historical candidate is served.

Reuses the existing fresh-capture preparation, person, export and provenance.
Only verified projection/execution contracts are enabled. Failed research
motion/surface candidates are not imported, and unsafe face joint updates
remain disabled. This is an explicitly authorized research test, not release.
"""
from pathlib import Path
import argparse
import json
import torch
import torch.nn.functional as functional
from gsplat.rendering import rasterization
import reconstruction_portrait_pipeline as pipeline
from reconstruction_portrait_model import evaluate_sh1, joined_state

VERSION = "portrait-native-fullframe-20261002-research"
CAPABILITIES = ["native-full-canvas-before-roi", "explicit-covariance-no-factorization",
                "head-local-sh1-world-transport", "common-scene-alpha-composition",
                "same-capture-only-preparation", "no-rejected-research-asset"]
_make_frame = pipeline.make_frame


def native_frame(data, name, *, crop=True, half=False, device="cuda"):
    # The old call sites request half=True for room training. Keep every
    # original pixel here rather than misreporting a resized canvas as native.
    frame = _make_frame(data, name, crop=crop, half=False, device=device)
    h, w = data["rgb"][name].shape[:2]
    frame.update(fullSize=(w, h), fullK=pipeline.tensor(data["K"], device),
                 nativeScale=1, requestedHalfIgnored=bool(half))
    return frame


def native_draw(state, C, frame, *, unit_scale=1., antialiased=False):
    w, h = frame["fullSize"]; x0, y0, x1, y1 = frame["rectangle"]
    if frame["nativeScale"] != 1 or not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError("native_canvas_contract")
    K = frame["fullK"]; cropK = K.clone(); cropK[0, 2] -= x0; cropK[1, 2] -= y0
    if not torch.allclose(cropK, frame["K"], atol=1e-5, rtol=0):
        raise ValueError("native_crop_intrinsics_changed")
    if frame["rgb"].shape[:2] != (y1-y0, x1-x0):
        raise ValueError("native_crop_image_changed")
    center = torch.linalg.inv(C)[:3, 3]
    rgb = evaluate_sh1(state.sh, state.means-center)
    groups = functional.one_hot(state.parts.long(), 5).to(rgb.dtype)
    depth = (state.means @ C[:3, :3].T + C[:3, 3])[:, 2]
    features = torch.cat((rgb, groups, groups*depth[:, None]), 1)
    image, alpha, info = rasterization(state.means, None, None, state.opacity,
        features, C[None], K[None], w, h, covars=state.covariance(), packed=True,
        sh_degree=None, render_mode="RGB+D",
        rasterize_mode="antialiased" if antialiased else "classic",
        near_plane=.01*unit_scale, far_plane=1e10*unit_scale)
    info["width"] = w; info["height"] = h
    if torch.cuda.max_memory_allocated()/1048576 > 6144:
        raise RuntimeError("native_training_resource_budget")
    full = dict(rgb=image[0, :, :, :3], alpha=alpha[0, :, :, 0],
                q=image[0, :, :, 3:8], q_depth=image[0, :, :, 8:13]/unit_scale,
                depth=image[0, :, :, -1]/unit_scale)
    return {**{k:v[y0:y1, x0:x1] for k,v in full.items()}, "info":info}


class NativeScene(pipeline.SceneAssembly):
    def render(self, frame, stage, *, antialiased=False, absgrad=False):
        if absgrad:
            raise ValueError("live_density_absgrad_not_enabled")
        state = self.portrait.local_state(frame["mesh"])
        if stage == "T0":
            return native_draw(state, frame["F"], frame, antialiased=antialiased)
        if frame["C"] is None:
            raise ValueError("world_render_requires_real_world_observation")
        state = state.to_world(frame["C"], frame["F"], self.scale)
        if stage != "T1":
            state = joined_state(state, self.environment_state())
        return native_draw(state, frame["C"], frame, unit_scale=self.scale,
                           antialiased=antialiased)


def run(args):
    if args.joint_steps != 0:
        raise ValueError("rejected_T2_cannot_enable_new_face_joint_updates")
    # This entry runs as a supervised child only. Existing imports/processes
    # retain their previous class; cancellation/cleanup remains the worker's.
    pipeline.make_frame = native_frame
    pipeline.SceneAssembly = NativeScene
    pipeline.ENGINE_VERSION = VERSION
    pipeline.run(args)
    report_path = args.output/"report.json"
    report = json.loads(report_path.read_text())
    report["sourceFiles"][str(Path(__file__).resolve())] = pipeline.digest(__file__)
    report.update(executionCapabilities=CAPABILITIES, nativeCanvas=True,
                  rejectedResearchCandidatesEnabled=False, jointFaceUpdatesEnabled=False)
    pipeline.write_json(report_path, report)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("prepared", type=Path); p.add_argument("output", type=Path)
    p.add_argument("--soft", action="store_true"); p.add_argument("--antialiased", action="store_true")
    p.add_argument("--local-steps", type=int, default=900)
    p.add_argument("--room-steps", type=int, default=300)
    p.add_argument("--joint-steps", type=int, default=0)
    p.add_argument("--resume-state", type=Path)
    run(p.parse_args())
