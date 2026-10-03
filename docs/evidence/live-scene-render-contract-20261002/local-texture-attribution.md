# Local900 texture softness: bounded read-only attribution

The audit reused the same six existing native full-frame initial/final renders
and checkpoints; it did not train, refine cameras, run new matching or change
the accepted domains. Script: `backend/audit_live_local_texture.py`. Output:
`backend/.sources/live-complete-repair-20261003-local-texture/report.json` and
six native face crops in source / initial / final order.

## Evidence ordering

1. **Broad footprints remain a clear representational limitation.** Across
   these views, face-centred projected major covariance sigma has final median
   6.59--8.02 native pixels; minor sigma 5.41--7.02. Initial values are nearly the
   same, with no density events in this local900 run. These are actual projected
   covariance sigmas, not measured PSFs, radii or front-contribution attribution.
   Masked source Canny edges number 2678--4951; final renders only 25--143 under
   the identical fixed diagnostic threshold. Rendering has lost actual fine
   boundaries; a low RGB mean is not fine-detail recovery. Source noise and the
   threshold affect these counts, so they are not a stand-alone quality gate.

2. **Alignment is still not fine enough to assume every input colour belongs
   to the same small surface feature.** Final 105-landmark reprojection median
   is 2.20--3.98 px and P90 4.44--7.80 px across the same six images. No consistent
   geometric improvement occurred during local900. This is a detector/embedding
   diagnostic, not independent dense texture correspondence, and cannot split
   pose versus identity/expression error conclusively. The prepared data use
   neighbouring training meshes copied as expression priors with separately
   solved F. That is not a measured rigid short segment for every detail.

3. **Surface flips are a real local defect, not an explanation of the whole
   mottled face.** In five of the six views there is no flipped sampled face
   normal; in frame0111 there is one. No audited point's triangle area fell below
   20% of its phase-start area. The 158.35 degree example is row4050/source10411,
   triangle8904, native projected centre (778.95,911.32), sigma(8.52,8.78).
   Frame0111 has 50 points on 39 triangles with basis turns above20 degrees.
   Their centre list is `large-turn-point-locations.json`. No actual per-point
   alpha counterfactual was performed; coincidence with some image defects is
   not established causation or a reason to delete them.

4. **The viewer is not the major new source of these defects at the checked
   reference camera.** Actual current PLY PlayCanvas and archived gsplat render
   have face RGB difference approximately .0067--.0072, with matching softness
   and mottling. Current glasses are not a independently validated complete
   spatial frame, and local appearance cannot manufacture its missing geometry.

## Smallest useful quality experiment after geometry protection

Choose a training-supported continuous stable skin region by a generic rule,
whose independent alignment uncertainty is below the proposed new footprint.
Replace its genuinely broad contributors with a finite surface-constrained
sample set based on native projected covariance, preserving coverage and real
source colour. Do not merely reduce all scales or accumulate fine children
under old parents. Retire the replaced parents transactionally and recover
appearance with the same image budget as an unchanged-topology control.
The allocation must inspect footprints intersecting the region, not only point
centres. If source alignment is too weak, first perform bounded shared 3D/F
correction; neither an arbitrary sharpness loss nor another900steps supplies
the missing correspondence.

This experiment can improve proven stable skin without claiming glasses/hair
geometry solved. Coverage, measured edge structure and all current views must
be compared together. It is a proposed next finite experiment, not a delivered
quality improvement from this audit.

## SurfaceFrameTransport and 701 actual walks

The newly provided adapter deliberately rejects a topology/chart change. It
cannot be attached to a moving-chart phase while ignoring that rejection.
Using `frame(current_triangle) @ frame(initial_triangle).T` alone is also wrong:
different first-edge directions on coplanar neighbouring triangles can rotate
an anisotropic covariance despite there being no physical bend.

Compatible transaction design:

- Keep per-UID phase-origin chart/bary, base residual, and ordered accepted
  shared-edge crossing path (or an equivalent explicitly chart-gauge-aware
  cumulative parallel transport). Use actual hinge rotation across each edge;
  coplanar transitions must have identity physical rotation.
- Evaluate residual-induced deformation before/after on the same current chart.
  Compose it with the physical parallel transport rather than the arbitrary
  chart first-edge rotation. A shared geometry field changes covariance as well
  as centres; directional SH remains in its established head-local space.
- Preserve reference F, K, identity and world gauge. Do not conflate this
  transport with applying the global head pose again.
- Snapshot geometry, quaternions/chart anchor/path, optimizer state and bindings
  before geometry+walk. Reject flips, degenerate triangles or an out-of-contract
  turn before accepting the transaction; restore all fields and Adam together.
  Do not mask a rejected step by changing colour afterward.
- Reset/transport only the actual chart-dependent optimizer moments. Quaternion
  parameters can stay in their phase material frame if their transport is kept
  in the forward contract. Split/replace must give children complete UID/anchor
  provenance, and restore their whole state on rejection.

Required regressions are identity at entry, coplanar walk, folded hinge walk,
walk forward/back, multi-observation nonzero expression, covariance gradients,
state recovery and exact initial pixel equality. This is the safe extension
needed before integrating the fixed-topology adapter with the live701walks.
