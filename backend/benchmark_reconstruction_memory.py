"""Synthetic full-resolution gsplat step; no portrait or model asset used."""

from __future__ import annotations

import json
import sys


def main(count: int = 350_000, width: int = 1920, height: int = 1080) -> None:
    import torch
    import torch.nn.functional as F
    from gsplat.rendering import rasterization

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    if not (1 <= count <= 500_000 and 640 <= width <= 4096 and 480 <= height <= 4096):
        raise ValueError("Benchmark dimensions outside reconstruction limits")
    torch.manual_seed(7)
    device = "cuda"
    torch.cuda.reset_peak_memory_stats()
    means = torch.nn.Parameter(torch.cat((
        (torch.rand(count, 2, device=device) - .5) * 2,
        torch.rand(count, 1, device=device) + 1.5), dim=1))
    scales = torch.nn.Parameter(torch.full((count, 3), -4.5, device=device))
    quats = torch.nn.Parameter(F.pad(torch.zeros(count, 3, device=device), (1, 0), value=1))
    opacities = torch.nn.Parameter(torch.full((count,), -2.2, device=device))
    sh0 = torch.nn.Parameter(torch.rand(count, 1, 3, device=device))
    shn = torch.nn.Parameter(torch.zeros(count, 15, 3, device=device))
    parameters = [means, scales, quats, opacities, sh0, shn]
    optimizers = [torch.optim.Adam([p], lr=.001) for p in parameters]
    view = torch.eye(4, device=device)[None]
    focal = float(max(width, height))
    K = torch.tensor([[[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]]], device=device)
    output, alpha, _ = rasterization(means, quats, scales.exp(), opacities.sigmoid(),
                                      torch.cat((sh0, shn), dim=1), view, K,
                                      width, height, packed=True, sh_degree=3)
    (output.mean() + alpha.mean()).backward()
    for optimizer in optimizers:
        optimizer.step()
    torch.cuda.synchronize()
    print(json.dumps({"splats": count, "resolution": [width, height],
                      "peakAllocatedMiB": round(torch.cuda.max_memory_allocated() / 1024**2),
                      "peakReservedMiB": round(torch.cuda.max_memory_reserved() / 1024**2),
                      "totalVramMiB": round(torch.cuda.get_device_properties(0).total_memory / 1024**2)}))


if __name__ == "__main__":
    main(*(int(value) for value in sys.argv[1:]))
