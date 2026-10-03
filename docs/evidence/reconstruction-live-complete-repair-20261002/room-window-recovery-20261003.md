# Rejected room-window recovery: bounded CPU implementation

This is a component experiment, not a complete reconstruction or display acceptance. No GPU, new depth inference, deployment, asset return, or production-entry change was performed by this branch.

## Confirmed implementation gap

`reconstruction_live_dense.build_components` chooses whole pairwise-compatible world windows. In the current final-integrated capture, world 0 and world 2 have fixed recorded K/C and valid camera-scale gates, but conflict with world 1 at a shared image. Both are excluded before shared-surface correction. `run_shared_surface` and auxiliary selection formerly admitted only `acceptedWindows`, so independent static tracks could not rescue any surface in either excluded window.

The original rejection remains unchanged. Recovery now requires an explicit hash-bound proposal, original training membership, unchanged source image and depth files, unchanged prepared/local geometry, and K/C equality. A proposal permits a solve only. It does not certify depth or visibility. No missing world camera is invented.

## Parent and outputs

Parent bundle:

`backend/.sources/live-complete-repair-20261003-final-integrated/dense-surfaces/shared-room-surface/observed-room-completion/result.json`

Capture SHA-256: `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`.

Initial bounded recovery and failure records:

`backend/.sources/live-person-coverage-20261003-room-recovery/`

Local candidate, reusing the accepted solve without another optimization:

`backend/.sources/live-person-coverage-20261003-room-recovery-local/result.json`

Manifest SHA-256: `6d8ceb3c3cf167e7465da0307409bed4bfe0bb3ad55073c53188d1b9b084e479`.

Room asset SHA-256: `56d0e9d964098c861237304e6776bad04c4d6e17d9ea4d7139ebb12dd28ddb46`.

## Actual solve results

Selection used original train observations, real unique static track IDs and additional observed-area demand. There are no programmed frame numbers. At most two different rejected windows, 40 function evaluations each, and a shared 30,000-point addition ceiling were permitted.

| Selected reference | Actual fit / held tracks | Held depth median before → after | Held depth P90 before → after | Held reprojection P90 before → after | Decision |
|---|---:|---:|---:|---:|---|
| 0032, world 0 | 100 / 27 | 2.2496% → 0.4829% | 5.1997% → 2.6104% | 6.7858 → 3.3981 px | Independent geometry check passed, 19 evaluations, 7.11 s |
| 0160, world 2 | 61 / 15 | 1.1744% → 0.3750% | 5.2054% → 5.2830% | 4.2825 → 6.0592 px | Rejected, 15 evaluations, 5.06 s |

The 20 fit / 12 held minima, depth median 3%, depth P90 8%, and non-worsening reprojection P90 were not relaxed. The second reference was not retried or replaced with a better-looking frame.

## Local connection rather than another whole-window rejection

0032's broad bidirectional comparisons against existing corrected 0047/0119/0052 surfaces had P90 relative disagreement of approximately 9.0–16.8%. A room label does not prove two proposed surfaces are simultaneously visible. This broad diagnostic is retained, not converted into an assertion that every difference is false geometry or unknown visibility.

One local replay therefore used the already-qualified 0032 solve and the original point filters. It reconstructed the parent's native 1080×1920 covariance footprints, including off-canvas-centred kernels; it did not render a face-sized viewport. Candidate admission was restricted to both:

- Original depth support from at least three distinct source images, with original free-space count at most one.
- No effective parent room footprint on that source observation: maximum individual contribution below 1/255 and union alpha below 0.01, with a conservative one-pixel footprint guard.

Covered, conflicting and depth-insufficient candidates were withheld. This footprint calculation is an analytic proxy using the actual covariance and opacity, not PlayCanvas rendering, independent measured visibility, or permission to fill unobserved pixels.

| Local decision | Points |
|---|---:|
| Candidates surviving existing shared-surface source rules | 16,332 |
| Candidates with original strict three-view depth support | 5,366 |
| Outside parent effective footprint | 9,244 |
| Outside parent footprint but insufficient strict depth support | 8,744 |
| Covered or overlapping parent footprint, withheld | 7,088 |
| Both strict support and genuinely unrepresented source footprint | **500** |

Final room count is **54,879**, from 54,379 plus 500. Every original point and per-point field remains bitwise identical. Scales and opacity were not enlarged. Hair 8,000 and body 16,000 asset hashes remain unchanged; the common export/body/person reference remains 0053. There is no evidence yet that 500 points repair the entire missing side of the room.

Per-point UID, original source pixels, raw support/free counts, prior contribution proxies and nearest old point IDs are saved in:

`backend/.sources/live-person-coverage-20261003-room-recovery-local/local-filter/point-evidence.npz`.

## Reusable API and source changes

New module: `backend/reconstruction_live_room_window_recovery.py`.

- `recover_static_window_surfaces(parent_bundle, output, max_surfaces=2, max_evaluations=40, extra_budget=30000)` selects rejected but eligible cached windows, validates provenance, performs bounded correction and connection checks, and returns a new manifest.
- The local fallback is the same generic filtering rule used in the 0032 replay. It retains the failed broad-overlap diagnostic and permits only strict, unrepresented source observations.
- `replay_local_recovery(...)` reuses the single previously accepted solve for controlled evaluation. It never chooses a new reference or reruns a solver.

Small integration changes:

- `reconstruction_live_shared_room_surface.py`: explicit rejected-window proposal and candidate-filter handoff.
- `reconstruction_live_room_completion.py`: rejected-window-only selection mode; original mode preserved; additional receipt numbering accounts for existing surfaces.
- `reconstruction_live_surface_binding.py`: allows at most two original auxiliary receipts plus at most two explicit recovered-window receipts. Each point remains bound to its exact source asset; local eligibility UIDs, hashes, thresholds and immutable original decisions are checked.
- `test_live_room_window_recovery.py`: input, fixed camera, scope, scale, overlap, footprint and budget contracts.

The main pipeline, runtime profile, application, viewer and production defaults were not modified by this branch. The new dependency and its receipt closure must be included in implementation identity and asset preservation before production use.

## Verification and limits

42 targeted CPU tests passed across the new recovery tests, surface binding, room completion and shared-surface regressions. A real CPU `load_prepared → choose_capture_reference → prepared_hair_motion → load_surface_bundle` call passed against the new candidate; see `backend/.sources/live-person-coverage-20261003-room-recovery-local/binding-check.json`.

Both original solves have start-of-run source snapshots. The first local replay did not snapshot the entire module at startup; its executed footprint/filter function bodies were preserved afterwards, and the limitation is explicitly recorded in `code-verification.json`. These two function bodies were unchanged during that replay. Later proof validation and automatic-stage wiring were updated, and subsequent local replays now snapshot all source files before execution. This record does not claim an exact startup snapshot for the first local replay.

No rendered-quality or GPU result is claimed here. The fixed parent plus 500-point candidate is available for an equal-budget full-scene test. The important remaining limitation is substantial: 8,744 genuinely unrepresented source-room candidates still lack the original three-view depth agreement, even after the reference's static geometry improves. Increasing their opacity, widening kernels, or treating semantic room membership as visibility would not solve that evidence gap. More coherent multi-view surface evidence is needed for those regions; unknown remains unknown.

## Approved original-contract conditional control

A subsequent explicit authorization allowed a second CPU-only control using the **already existing** two-class export contract. The independent 0032 solve, cameras, source images, prior footprint calculation, free-space threshold and parent scene are identical. No new solve, depth inference or reference selection took place.

The only changed admission is `allow_typed_conditional=True`: alongside strict depth-consistent points, the original `conditional_shared_surface` class is allowed when at least three original static observations and at least three matching source-colour observations corroborate it, and the original free-space count remains at most one. Every accepted candidate must still lie outside the parent's effective native footprint. Its actual depth support remains stored unchanged, including zero or one vote. This is a conditional surface hypothesis, not independent measured depth or known visibility.

Of the same 9,244 eligible uncovered candidates, 500 are strict and 8,744 conditional. Existing spatial deduplication removes one candidate, leaving **9,243** additions. The parent 54,379 points remain bitwise unchanged, so the candidate room has **63,622** points. Hair/body hashes and reference 0053 remain unchanged. No covariance or opacity was enlarged to fill holes.

Candidate:

`backend/.sources/live-person-coverage-20261003-room-recovery-conditional/result.json`

- Manifest SHA-256: `26a9d6f6ff1715fb5730660e5643bd483b0c8251fcebfd54891d3e6c93b6d177`.
- Room SHA-256: `c0c78597c5081d896d535907646c9cf9697b4e34aaa3c23be93990b1b0f24c11`.
- Addition SHA-256: `b55d477d22e80c65dabf1a75f0d5961099939f5526d75e1731ecb05fc08469e6`.

This control has a full startup source snapshot under its `algorithm-source` directory. The generic recovery API exposes the same optional typed-conditional policy; it is not enabled in the production entry by this branch. Both the 500-point candidate and this control passed the real CPU loading and reference/hair-motion checks. The test suite now contains **43 passing tests**, including an explicit check that conditional support does not forge depth votes or relax free-space rejection.

The next decision requires actual full-scene rendering and equal-budget training: does this recovered observed area improve the missing side without producing double surfaces, haze or new face occlusion? This CPU result alone does not answer that quality question. All earlier failure and strict-only results are retained.
