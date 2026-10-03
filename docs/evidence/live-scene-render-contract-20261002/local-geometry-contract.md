# Live local geometry / hair evidence, 2026-10-03

Scope: current P/backend only. New adapters and tests; no modification of the
portrait main class, pipeline, viewer, assets, point set or training run.

## Concrete implementation gap

`reconstruction_portrait_model.py::surface` moves the surface and normal with
`surface_residual`. `local_state` still returns the independently normalized
`self.quats`, without transport by the changed triangle frame. In contrast,
W's `reconstruction_shared_surface.py::SharedSurfaceModel.head_state` computes
the incremental before/after triangle frame and rotates the Gaussian basis.
The current local schedule actually optimizes `surface_residual` on geometry
steps. This gap is real; it does not prove it explains all photometric error.

Read-only evidence from `.sources/live-complete-repair-20261002-local`:

- `local-init.pt`: `1b0c287f1311765d41765adfc7b9592ae0ec92a68f2f8ace6a8d11a1628e9f76`
- `local-state.pt`: `50d9b74677a08c1546345edcf2d5408080791aa4bf34aab338d5031f1b015133`
- 0 -> 900 actual optimizer steps; 8798 surface points; 701 triangle IDs changed.
- Residual increment vertex norm median 0.0000916941, P99 0.0004923263,
  max 0.0008476688 head-local units. No assertion of calibrated millimetres.
- At frame0111, residual-only frame rotation using each FINAL chart has
  median/P90/P99/max 1.296/4.283/13.985/158.346 degrees.
- Relative covariance L1 change if that rotation were applied is
  median 1.10%, P99 18.1%, maximum 78.7%. This is a numeric counterfactual,
  not an accepted visual repair and not the complete chart-walk effect.

The few extreme changes make retroactively rotating every final Gaussian
unsafe. Large relative deformations require rejection or a separately bounded
geometry transaction; the research result is not silently rewritten.
All per-observation results are in
`backend/.sources/live-complete-repair-20261002-hair-conflicts/surface-basis-audit.json`.

## Minimal reusable implementation

`reconstruction_live_local_geometry.py` provides:

1. `SurfaceFrameTransport(portrait, max_degrees=...)`: snapshots the phase-start
   shared residual and topology. `transport(portrait, observed_mesh)` returns
   the current old-model means with covariance orientation transported by the
   incremental surface rotation. Eigenvalues, opacity, source colours, SH and
   all hair fields stay untouched. No background colour sampling exists here.
   It does not reapply global head rotation or expression to an imported state.
2. `BoundedLocalPose(roles, reference, eligible_names, degrees=..., translation=...)`:
   supplies only bounded camera-local rigid increments of F for explicitly
   eligible TRAIN observations. The reference and all development/audit frames
   have no active variable. K, identity, expression, scale and world C are
   outside this interface. Geometric reliability must be established by the
   caller; the interface does not declare weak observations trustworthy.

At phase entry the adapter uses an exact zero-difference identity construction,
while retaining derivatives with respect to geometry. Checkpoints need to
include this adapter's buffers and pose delta if later integrated. It currently
rejects changed triangle IDs. A walk/split transaction must explicitly transport
or refresh its complete anchor contract; ignoring that error is not permitted.

The existing `GaussianState.to_world` converts a fixed rotation to a quaternion
through detached CPU SciPy. This is fine for the current fixed F transfer but
is not sufficient proof of covariance rotation gradients for a future world-F
optimization. The new pose interface is not claimed to complete joint training.

## Actual contract verification

Command in the locked WSL environment:

```
/opt/self-reconstruction/venv/bin/python -B -m unittest test_reconstruction_live_local_geometry -v
```

6 tests passed in 8.591 seconds. One test used the installed gsplat on CUDA,
128 x 128 synthetic scene: RGB and alpha are bitwise equal before/after adapter
attachment. Other checks cover nonzero old residual and absolute F, covariance
rotation, nonzero geometry derivative at initialization, unchanged hair/colour,
large-rotation/topology rejection, strict bounds, and excluded evaluation frames.
This is a numerical contract, not person quality, device rendering or performance
validation. No optimizer or real-asset training was run by this audit.

## Head rotation and neck are not the same missing contract

`root_neutral_contract` zeros the FLAME root rotation in the local mesh and
stores `translation + center - R*center` in F, including shaped-root correction.
`NeckBinding.relative_head` uses `H_t @ inverse(H_ref)` and exactly preserves a
nonidentity absolute reference pose. Code and existing regression coverage do
not support alleging double global rotation here.

The current generic fit uses landmarks, then local appearance training holds F
fixed. There is no independent hair correspondence refinement during this 900
step run. A consistent hair-local transform across time is therefore a remaining
measurement question, not something fixed by rotating covariance alone.

## Hair semantic counterevidence, not deletion

`audit_live_hair_conflicts.py` read the frozen 8000 point head-local hair proposal
and the accepted depth windows, checking 21 DISTINCT training observations.
It uses original high-confidence eroded face_core, original K/F and image
transforms. Depth is the conditional DA3 prediction, not independent truth.

| Projection/depth interpretation | At least 1 view | At least 2 | At least 3 |
| --- | ---: | ---: | ---: |
| Projected into clear eroded face | 2641 | 2139 | 1635 |
| Within 3% depth and at/before predicted visible layer | 4 | 3 | 3 |
| More than 3% in front of predicted layer | 2 | 1 | 0 |
| More than 3% behind predicted layer | 2636 | 2136 | 1632 |

Thus center projection into the forehead does not justify blanket removal.
Almost all these projections are behind the conditional first layer. The few
remaining candidates are only potential semantic counterevidence. Gaussian
footprint, actual alpha contribution, depth reliability and temporal alignment
must still be checked before changing any of them.

Hair source SHA-256:
`c1f05722365962d28d69af64b7b88862d8b57b6f53b658246ed80e60dff932e2`.
Audit: `backend/.sources/live-complete-repair-20261002-hair-conflicts/report.json`,
`candidate-details.json`, `point-counts.npz`, `projection-overlay.jpg`.
CPU time 5.05 seconds; zero removed points; input hash unchanged; no GPU/training.

Next useful action is a finite new geometry phase with an unchanged starting
render, surface-frame synchronization and measured reliable multi-view F
constraints, alongside actual hair contribution diagnosis. Neither this adapter
nor the 4/2 candidate counts establish complete portrait quality.
