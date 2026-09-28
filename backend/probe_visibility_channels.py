"""Check shared-occlusion person/background contributions in gsplat 1.5.3.

All labels are fixed source attributes. The last two color channels are
rendered in the *same* pass as RGB, so their transmittance accounts for the
other group. This is a feasibility probe, not a production training loss.
"""

from __future__ import annotations

import json
import math

import torch
from gsplat.rendering import rasterization


def render(person_front: bool, offset: float = 0.) -> tuple[torch.Tensor, float]:
    device = "cuda"
    front_z, back_z = (1.7, 2.3) if person_front else (2.3, 1.7)
    means = torch.tensor([[offset, 0., front_z], [0., 0., back_z]],
                         device=device, requires_grad=True)
    quats = torch.tensor([[1., 0., 0., 0.]] * 2, device=device)
    scales = torch.tensor([[.18, .18, .035]] * 2, device=device)
    opacities = torch.tensor([.92, .92], device=device)
    # RGB, environment contribution, person contribution.
    colors = torch.tensor([[.9, .2, .1, 0., 1.], [.1, .2, .9, 1., 0.]], device=device)
    K = torch.tensor([[100., 0., 32.], [0., 100., 32.], [0., 0., 1.]], device=device)
    out, _, _ = rasterization(means, quats, scales, opacities, colors,
                              torch.eye(4, device=device)[None], K[None],
                              64, 64, packed=True, sh_degree=None)
    middle = out[0, 32, 32]
    # Verify gradients can pass from the shared visibility channels to the
    # geometry; labels themselves remain immutable.
    out[0, 27, 32, 4].backward()
    gradient = float(means.grad.abs().sum())
    return middle.detach().cpu(), gradient


def conservation_and_update() -> dict:
    """Check channel conservation and real canonical/pose optimizer updates.

    This is deliberately a fixed two-point scene. It does not establish that
    the person's unknown shape, camera poses, or training losses are correct.
    """
    device = "cuda"
    canonical_x = torch.nn.Parameter(torch.tensor(.10, device=device))
    opacity_logit = torch.nn.Parameter(torch.tensor(1.7, device=device))
    head_yaw = torch.nn.Parameter(torch.tensor(.08, device=device))
    values = [canonical_x, opacity_logit, head_yaw]
    K = torch.tensor([[100., 0., 32.], [0., 100., 32.], [0., 0., 1.]], device=device)
    view = torch.eye(4, device=device)[None]
    colors = torch.tensor([[.9, .2, .1, 0., 1.], [.1, .2, .9, 1., 0.]], device=device)
    quats = torch.tensor([[1., 0., 0., 0.]] * 2, device=device)
    scales = torch.tensor([[.18, .18, .035]] * 2, device=device)

    def forward() -> tuple[torch.Tensor, torch.Tensor]:
        # The same canonical source parameter is transformed on every call.
        person_x = canonical_x * torch.cos(head_yaw) + .2 * torch.sin(head_yaw)
        person_z = 1.7 - canonical_x * torch.sin(head_yaw) + .2 * torch.cos(head_yaw)
        means = torch.stack((torch.stack((person_x, canonical_x * 0, person_z)),
                             torch.tensor([0., 0., 2.3], device=device)))
        opacities = torch.stack((torch.sigmoid(opacity_logit),
                                 torch.tensor(.85, device=device)))
        rgb_contribution, alpha, _ = rasterization(
            means, quats, scales, opacities, colors, view, K[None],
            64, 64, packed=True, sh_degree=None)
        return rgb_contribution, alpha

    image, alpha = forward()
    max_conservation_error = float((image[..., 3] + image[..., 4] - alpha[..., 0]).abs().max().detach())
    if max_conservation_error > 2e-5:
        raise AssertionError(f"contribution_not_conserved:{max_conservation_error}")
    # The pixel is on the near edge of the person, away from a depth-order swap.
    def scalar_loss() -> torch.Tensor:
        channels, _ = forward()
        return (channels[0, 32, 40, 4] - .35).square()

    loss = scalar_loss()
    analytic = torch.autograd.grad(loss, values)
    finite_differences = []
    for parameter in values:
        original = float(parameter.detach())
        epsilon = 1e-3
        with torch.no_grad():
            parameter.fill_(original + epsilon)
        high = float(scalar_loss().detach())
        with torch.no_grad():
            parameter.fill_(original - epsilon)
        low = float(scalar_loss().detach())
        with torch.no_grad():
            parameter.fill_(original)
        finite_differences.append((high - low) / (2 * epsilon))
    gradient_values = [float(value.detach()) for value in analytic]
    for name, auto, numeric in zip(("canonicalX", "opacityLogit", "headYaw"),
                                   gradient_values, finite_differences):
        if not math.isfinite(auto) or abs(auto) < 1e-7 or not math.isclose(
                auto, numeric, rel_tol=.06, abs_tol=3e-4):
            raise AssertionError(f"gradient_mismatch:{name}:{auto}:{numeric}")
    before = [float(parameter.detach()) for parameter in values]
    optimizer = torch.optim.SGD(values, lr=.01)
    optimizer.zero_grad(set_to_none=True)
    first_loss = scalar_loss()
    first_loss.backward()
    optimizer.step()
    after = [float(parameter.detach()) for parameter in values]
    last_loss = float(scalar_loss().detach())
    if last_loss >= float(first_loss.detach()) or any(
            abs(a - b) < 1e-8 for a, b in zip(before, after)):
        raise AssertionError("source_parameter_optimizer_step_failed")
    return {"maxContributionConservationError": round(max_conservation_error, 8),
            "canonicalAndPoseFiniteDifference": True,
            "sourceParametersActuallyUpdated": True,
            "lossBefore": round(float(first_loss.detach()), 7),
            "lossAfter": round(last_loss, 7)}


def main() -> None:
    face_first, face_gradient = render(True)
    room_first, room_gradient = render(False)
    partial, partial_gradient = render(True, .15)
    assert face_first[4] > face_first[3] * 3, face_first
    assert room_first[3] > room_first[4] * 3, room_first
    assert partial[3] > 0 and partial[4] > 0, partial
    assert min(face_gradient, room_gradient, partial_gradient) > 0
    report = {"faceFront": [round(float(v), 4) for v in face_first[3:]],
              "roomFront": [round(float(v), 4) for v in room_first[3:]],
              "partial": [round(float(v), 4) for v in partial[3:]],
              "sharedVisibilityGradients": True, "gsplatVersion": "1.5.3"}
    report.update(conservation_and_update())
    print(json.dumps(report))


if __name__ == "__main__":
    main()
