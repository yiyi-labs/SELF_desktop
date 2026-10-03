# Fresh capture preparation and bounded short-window localization

This run follows the live worker's actual `extract_frames → prepare_faces → prepare_capture` functions. It does not queue a production job, invoke appearance training, export a PLY, deploy or publish.

## Identity and untouched baseline

- Recording SHA-256: `7ac189eb49e05c83220addf16c1fabe325ef35e32d8ffd7e4c5af4824777e4cf`.
- Original recording was not changed. The first probe made a verified private research copy.
- No previous 900-step appearance state, previous world camera or prepared cache was loaded.
- First run: `backend/.sources/live-complete-repair-20261003-fresh-capture`.
- Bounded rescue: `backend/.sources/live-complete-repair-20261003-registration`.
- Actual implementation snapshots and private parameter/checkpoint hashes remain inside each run. No source image or personal checkpoint is added to Git.

## Actual preparation

The first run decoded and selected 160 native-resolution frames with actual source indices and verified FFprobe timestamps. All 160 had face observations. Extraction took 65.21 s; face preparation took 71.81 s; new mapping/local preparation took 111.70 s. Measured process wall time was 252.57 s, excluding no hidden appearance-training stage: none was run.

The resulting preparation had 40 local observations (32 train / 8 development) and 22 actual registered world cameras (18 train / 4 development). The shared shape and per-view expression/pose/translation were actually fitted for 260 preparation steps. Initial, middle and final checkpoints now preserve those tensors, optimizer state, RNG, K, observation identities, roles and source/model hashes. CPU reconstruction from the final checkpoint matched all 40 saved local meshes within `2.981e-8`, and F matrices within `3.141e-8`. Four optimizer parameter states each recorded step 260.

This does not constitute appearance optimization or quality approval. The initial appearance had 6,947 points: 6,339 surface, 552 detail-class surface and 56 independently supported hair seeds. Dense surface initialization is a later stage.

## Concrete live-path blocker

`choose_capture_reference` rejected the first preparation with `capture_reference_no_supported_body_window`. The widest detected-face region did not have reliable world cameras. Other registered views were generally about two seconds apart; the only nearby pair had two observations, below the unchanged minimum of three. The old cached preparation had hidden this limitation.

No C matrix was interpolated or copied from the old reconstruction. The first failed preparation and reference receipt were preserved.

## Bounded correction

`reconstruction_capture_registration.py` now supplies a generic conditional correction used by fresh preparation:

1. Choose at most two sufficiently sharp registered training anchors, ranked by measured frontal width and separated in time. Development observations do not choose anchors.
2. Consider only their existing captured neighbors, at most ±4 names and within 1.75 real seconds.
3. Copy the current static database, extract masked SIFT for those queries with the installed PyCOLMAP 4.2.0, and match only to up to six nearby registered training anchors.
4. Join query keypoint indices to actual map POINT3D_IDs; reject ambiguous associations and repeated physical tracks. No feature-index substitution or new map triangulation occurs.
5. Split physical 3D track IDs deterministically into fit and withheld sets. Run fixed-intrinsics absolute-pose RANSAC/refinement using only the fit set.
6. Require withheld positive depth, median/P90 reprojection, 4×4 image-grid distribution and hull area, in addition to fit support. Failed queries supply no world matrix.
7. Preserve every existing C, K and map XYZ exactly. The map hash before and after was `6c4f410b2af7ebb0d4ec440a4acb27e43506daac9e0208b22dfab41d81ff25fe`.

The actual two proposed anchors were frame 0053 and frame 0001. Nine queries were examined. Six passed: 0003, 0004, 0005, 0049, 0050 and 0051. Their withheld P90 errors ranged from 1.20 to 2.62 pixels; all had positive depths and at least four occupied validation grid cells. Frame 0002 was still rejected despite low reprojection because its validation distribution covered only three cells. Frame 0054 had insufficient unique tracks; 0056 had no qualifying tracks. Thresholds were not relaxed after these results.

Static localization itself took 6.46 s. Re-preparation on the genuinely expanded observation set, including another 260-step shared local fit, took 122.22 s total. This second fit uses additional measured observations and retains the original eight development identities. It is not an exact resume or a repetition claimed as extra evidence.

## Prepared handoff

- Prepared directory: `backend/.sources/live-complete-repair-20261003-registration/portrait-preparation`.
- 46 local observations, 28 actual world cameras, 24 world/local training observations.
- Shared reference: `frame_0053.png`.
- Body window: frames 0049–0053, actual timestamps 19.781567, 20.047978, 20.447611, 20.980444 and 21.280167 s.
- Camera baseline / median head distance: 0.182354.
- Shared scene scale: 23.2444780902; no per-frame scale.
- New appearance hash: `9d2c6c575d2e78884f4ce7d99a03862d1c04dbbb3e909527c978de3458f093ba`.

These establish a numerically eligible common reference, not proven rigid torso motion or final geometric fidelity. Body motion remains explicitly a short-window approximation until separately validated.

## Resources and recovery

First preparation parent CUDA allocated/reserved peaks were 52.30/62.00 MiB; device-level sampled peak was 238 MiB. The rescue preparation parent peaks were 55.62/62.00 MiB. These are preparation-only measurements, not end-to-end training or device FPS.

After completion, unreferenced cached CUDA memory is released before the training child starts. Retained live allocations are not forcibly removed. Runtime records preparation-parent statistics separately from the child. It also retains byte-exact local-fit checkpoints and metadata under `portrait-state/local-fit`; original image cleanup is unchanged, so full image-supervised retraining still needs the original images.

Tests cover unique physical-track fit/holdout separation, independent validation rejection despite high match count, full-camera projection/depth, bounded time/name-based window selection, common reference selection and runtime recovery. The real run preserves per-query fit/held IDs and residual/distribution metrics in private audit files.

## Status

Fresh preparation and the bounded localization correction are implemented and actually exercised. The new prepared result may proceed to downstream research training. Appearance quality, complete scene continuity, PlayCanvas/HarmonyOS rendering and publishing are not approved by this preparation result. Existing works, production queue, transport, UI and worker status were not changed by this subtask.
