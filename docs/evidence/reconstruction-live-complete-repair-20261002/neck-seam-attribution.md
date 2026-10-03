# Reference-neck seam attribution

This is a frozen initialization diagnostic, not trained quality acceptance or a device test. No model parameter, optimizer, density policy, asset, camera capture or production entry was changed by this audit.

## Identity and replay

- Source SHA-256: `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`.
- Initialization checkpoint SHA-256: `1b0c287f1311765d41765adfc7b9592ae0ec92a68f2f8ace6a8d11a1628e9f76`.
- Reference observation: `frame_0111.png`; original undistorted 1080 × 1920 canvas, recorded K/C/F; scene scale 13.35442008734654.
- 62,798 Gaussians: 8,798 old head surface, 8,000 observed hair, 30,000 room, 2,368 dense neck-skin, 13,625 cloth and 7 other skin.
- Head-to-world reference transform retained. Neck transport is exactly identity at this reference.
- One gsplat classic full-canvas forward composited RGB, seven component contribution channels, contribution-weighted colors and depths together. Replayed RGB versus the existing frozen full-initial tensor: mean absolute difference **6.6983e-8**, maximum **0.002054**. This is adequate attribution agreement; maximum is not reported as bit-exact equality.
- CUDA allocated peak during this diagnostic: **662.28 MiB**. This is not a training resource measurement.
- Original cached labels lacked dynamically attached physical observation domains. The first audit failed before any GPU forward; the successful audit applies the same existing `attach_observation_domains` rectification/semantic contract. That failed attempt is retained and is not treated as missing neck evidence.

## Concrete finding

The brightest positive residual band within the confidently observed neck occurs at native image row 1319. Over 3,219 band pixels:

| Quantity | Value |
|---|---:|
| RGB L1 | 0.14754 |
| Signed mean brightness residual | +0.14288 |
| Total alpha | 0.99004 |
| Room contribution | 0 |
| Old head lower-surface contribution | 0.35463 |
| New dense neck contribution | 0.63534 |

The contribution-conditioned old lower-head RGB is `[1.0505, 0.7327, 0.5667]`, while the dense neck RGB is `[0.4696, 0.3438, 0.2736]`. The actual source has no comparable horizontal bright line. Thus this seam is not a room haze contribution or an alpha hole at this reference. Old lower-head colors are too bright where they overlap the physically observed new neck. Values above one are kept in float diagnostics rather than silently clipped before comparison.

There is also geometric disagreement. Among 673 old/new center pairs within eight projected pixels in the observed neck, head-minus-neck camera depth in the local scale convention has 5/50/95 percentiles of -3.20/-0.83/+5.97 cm. This is a nearest-projection diagnostic, not proof those centers correspond to the same material surface. Contribution-conditioned band depths differ by about 1.12 cm; this is likewise not independent measured depth.

The old-head and dense-neck contributions overlap in 15,676 observed-neck pixels (both contributions greater than 0.05); those pixels have RGB L1 0.10005 and signed brightness residual +0.08750. The whole observed-neck RGB L1 is only 0.04609, which would conceal the much worse seam if reported alone.

## Why the current training stages cannot repair that old bright border

`reconstruction_portrait_pipeline.py::head_loss` supervises face, glasses and hair RGB, face/hair coverage, and known room emptiness. It has no direct observed-neck appearance target. The existing T3 then freezes the portrait parameters. Consequently, the inherited lower-head SH can remain incorrect while the newly introduced neck alone is asked to explain the remaining appearance. Training the environment longer would not give the frozen foreground boundary a corrective gradient.

## Smallest generalizable next action

1. Use reliable short-window neck observations to identify inherited head-surface points that are neck skin across multiple views and do not contribute to protected face-core/hair/glasses pixels. Use existing provenance and actual projection/contribution, not an image-coordinate crop fixed to this person.
2. In the existing full-scene forward, allow only that inherited neck group's SH to recover toward real source neck colors alongside the dense neck. Freeze head-core geometry, face/hair appearance and all other protected parameters. Preserve full state transaction and compare all short-window views, not only row 1319.
3. Keep geometry/opacity unchanged for this one-factor diagnostic. Do not lower alpha, remove the neck, feather RGB or pull cloth into skin to hide the line.
4. Treat residual depth/topology mismatch as a separate physical handoff task. Any later replacement requires genuine multi-view neck support, reference identity, covariance/SH motion transport and continuity checks; this color attribution does not prove the geometry is already correct.

The dense neck itself is still quasistatic-body plus bounded head-relative motion over a recorded short window. It is not a full independently measured torso-motion solution. Hair, detailed garments, room coverage and complete-scene release remain separate quality checks.

## Reproduce

From the backend directory, using the existing locked WSL Python:

```sh
/opt/self-reconstruction/venv/bin/python -B audit_live_neck_seam.py \
  --run .sources/live-complete-repair-20261002-training \
  --prepared .sources/integrated-components-v2-20260928-e \
  --output .sources/<new-unique-audit-directory> --gpu
```

Private, local-only evidence is in `backend/.sources/live-complete-repair-20261002-neck-seam-audit-b/`: `report.json`, float `reference-attribution.npz` and the source/full-render/head-lower-contribution/neck-contribution crop. No original or derived portrait image is added to this Git report. The audit code and report are the only new audit files; no Git commit was made by the audit agent.
