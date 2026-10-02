"""Synthetic gsplat -> standard PLY -> gsplat contract probe.

No portrait input is read.  PlayCanvas parsing is checked separately by
viewer-gs/tests/ply-contract.test.mjs against the PLY made here.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from gsplat import export_splats
from gsplat.rendering import rasterization


def read_float_ply(path: Path) -> dict[str, np.ndarray]:
    with path.open("rb") as stream:
        lines = []
        while True:
            line = stream.readline().decode("ascii")
            lines.append(line.strip())
            if line == "end_header\n":
                break
        assert lines[:2] == ["ply", "format binary_little_endian 1.0"]
        count = int(next(line.split()[2] for line in lines if line.startswith("element vertex ")))
        fields = [line.split()[2] for line in lines if line.startswith("property float ")]
        table = np.frombuffer(stream.read(), dtype=np.dtype([(name, "<f4") for name in fields]))
    assert len(table) == count
    return {name: table[name].copy() for name in fields}


def render(parameters: dict[str, torch.Tensor], pose: torch.Tensor, K: torch.Tensor) -> torch.Tensor:
    image, _, _ = rasterization(
        parameters["means"], parameters["quats"], torch.exp(parameters["scales"]),
        torch.sigmoid(parameters["opacities"]),
        torch.cat((parameters["sh0"], parameters["shN"]), dim=1),
        pose[None], K[None], 96, 96, sh_degree=3, packed=True,
    )
    return image


def main() -> None:
    root = Path(__file__).resolve().parent / ".sources" / "gs-contract-probe"
    root.mkdir(parents=True, exist_ok=True)
    output = root / "anisotropic-occlusion.ply"
    device = "cuda"
    # A red foreground ellipse, blue rear ellipse, oblique green ellipse,
    # and offset yellow splat exercise depth order, rotation and scale axes.
    axis = torch.tensor([.8660254, 0., 0., .5], device=device)
    params = {
        "means": torch.tensor([[0., 0., 1.7], [0., 0., 2.2],
                               [.27, -.08, 1.85], [-.3, .25, 2.0]], device=device),
        "quats": torch.stack((axis, torch.tensor([1., 0., 0., 0.], device=device),
                              axis, axis)),
        "scales": torch.log(torch.tensor([[.26, .07, .035], [.33, .22, .04],
                                           [.05, .21, .04], [.08, .12, .06]], device=device)),
        "opacities": torch.logit(torch.tensor([.82, .88, .76, .70], device=device)),
        "sh0": (torch.tensor([[[.9, .1, .12]], [[.08, .18, .95]],
                               [[.1, .88, .25]], [[.95, .79, .08]]], device=device) - .5) / .28209479177387814,
        "shN": torch.zeros(4, 15, 3, device=device),
    }
    params["shN"][:, 0, :] = torch.tensor([.08, -.05, .11], device=device)
    params["shN"][:, 4, :] = torch.tensor([-.03, .06, -.02], device=device)
    export_splats(**params, format="ply", save_to=str(output))
    parsed = read_float_ply(output)
    restored = {
        "means": torch.from_numpy(np.stack([parsed[key] for key in ("x", "y", "z")], axis=1)).to(device),
        "quats": torch.from_numpy(np.stack([parsed[f"rot_{i}"] for i in range(4)], axis=1)).to(device),
        "scales": torch.from_numpy(np.stack([parsed[f"scale_{i}"] for i in range(3)], axis=1)).to(device),
        "opacities": torch.from_numpy(parsed["opacity"]).to(device),
        "sh0": torch.from_numpy(np.stack([parsed[f"f_dc_{i}"] for i in range(3)], axis=1)[:, None, :]).to(device),
        # Standard 3DGS PLY stores higher SH channel-major, while gsplat's
        # in-memory tensor is coefficient-major.
        "shN": torch.from_numpy(np.stack([parsed[f"f_rest_{i}"] for i in range(45)], axis=1)
                                .reshape(4, 3, 15).transpose(0, 2, 1).copy()).to(device),
    }
    K = torch.tensor([[92., 0., 48.], [0., 92., 48.], [0., 0., 1.]], device=device)
    errors = []
    for horizontal in (0., .18, -.22):
        pose = torch.eye(4, device=device)
        pose[0, 3] = horizontal
        before, after = render(params, pose, K), render(restored, pose, K)
        errors.append(float((before - after).abs().max()))
    scale_error = float((params["scales"] - restored["scales"]).abs().max())
    opacity_error = float((params["opacities"] - restored["opacities"]).abs().max())
    sh_error = float((params["shN"] - restored["shN"]).abs().max())
    report = {"asset": str(output), "splats": 4, "maxPixelError": max(errors),
              "maxLogScaleError": scale_error, "maxLogitOpacityError": opacity_error,
              "maxHigherShError": sh_error,
              "views": 3, "gsplatVersion": "1.5.3"}
    (root / "roundtrip.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if max(errors) > 1e-5 or scale_error > 1e-6 or opacity_error > 1e-6 or sh_error > 1e-6:
        raise AssertionError(report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
