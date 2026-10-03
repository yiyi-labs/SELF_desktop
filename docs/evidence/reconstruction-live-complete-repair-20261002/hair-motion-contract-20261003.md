# Hair motion handoff — 2026-10-03

This record describes a backend correction and CPU verification. It does not claim that hair quality has improved before the controlled GPU result is inspected. No asset was sent to HarmonyOS by this task.

## Confirmed coupling gap

The capture fitter stores root-neutral FLAME meshes. Removing joint 0 does not remove joint 1 (neck): the mesh follows the fitted neck articulation. The separate hair tail previously stayed constant in root-local coordinates, then received only `F_root`. The same root-only convention was used to condition the hair depth inference.

On the current fresh preparation, fitted neck angles reach 3.88633 degrees. A model-defined counterfactual that fixes joint 1 at the reference state while leaving other fitted state unchanged moves the inspected upper-head landmarks by a median 2.7868 mm and a maximum 5.7678 mm, or a median 3.7823 pixels and maximum 13.5392 pixels. These are predicted changes from the fitted model, **not measured hair ground truth**.

## Corrected contract

Use a skull-rigid approximation. A single pivot `J1` comes from the fitted shared shape plus the fixed reference expression. For each image name:

`G_t = [R_neck,t, J1 - R_neck,t J1]`

`D_t = G_t inverse(G_ref)`

`F_hair,t = F_root,t D_t`

`D_ref` is explicitly set to the identity. Root rotation is applied once through `F_root`; jaw, eyes and per-frame expression do not drag the hair. This is not claimed to equal every weighted vertex in FLAME skin LBS.

Hair depth inference, multi-view support and colour collection now use `F_hair`. Training transports hair means, covariance and SH through the same `D`; skin remains unchanged. World export applies the existing root-to-world transform after that transport. Reference export therefore has no additional hair transform.

Old depth inferred using only `F_root` cannot satisfy this contract. It is explicitly rejected for a prepared capture with recorded joint state. Old preparations without such a state and sparse old hair seeds without corrected depth remain explicitly labelled `legacy_root_local`.

## Actual verification

- The real capture checkpoint hash is `e87eb2b390c7b3acf086be44e59dc4fc2b7eb941b5e841fea6861c1b4a710313`.
- 46 image names, roles, K and model/source identity were checked. Recomputed root-neutral meshes and root extrinsics matched the saved preparation at a 2e-6 absolute tolerance.
- Reference: `frame_0053.png`; relative transform is exactly the identity.
- Transform contract SHA-256: `848c864fd672a68c9c17de88032846b0d177f93863cbcea9b6e1e7b273513b6c`.
- The actual pinned DA3 Python environment loaded the contract on CPU and rejected missing old-cache motion proof. CUDA was not initialized by that check.
- Synthetic tests cover nonzero shape, reference neck pose and root; a pure joint-1 rigid marker; jaw/expression exclusion; reference identity; covariance and SH transport; source-camera equivalence; frozen skin prefix; and proof tampering.
- Surface recovery tests retain original motion JSON, transform NPZ, fitted parameter checkpoint and the separate hair depth manifest. Original room/body manifests remain unchanged. Old paths can be resolved after test inputs expire, and corrupted evidence is rejected.

Relevant CPU runs passed: 47 tests across motion, dense input, component loading, face contribution and recovery; then 21 tests across motion, recovery and the added prefix-transfer trial. Counts overlap and are not separate quality evidence.

## Controlled trial

`run_live_hair_motion_trial.py` accepts explicit parent run, corrected hair manifest and new output directory. It verifies source/preparation/scale/reference and exact room/body component identities, restores every learned face field (including chart, surface residual, bindings, SH, covariance parameters, source IDs and confidence), preserves all environment and neck state, then trains only hair. Unknown state fields fail instead of being dropped.

The bounded schedule follows the current local phase: appearance first; after step 80, every fourth step can update only hair offset. Learning rates, local image objective, SH/scale regularizers and bounded displacement/scale limits are retained. It performs 900 hair-only local steps followed by at most 180 full-scene hair appearance steps. Face and environment state are asserted bitwise unchanged. Initial/mid/final parameter and optimizer state, RNG, sampler, source snapshot and transfer receipts are saved.

The original full local phase also updated face parameters, whereas this research trial freezes the completed face. Consequently the comparison against the prior full run is not claimed to be a strict single-factor rerun of that entire 900-step optimization. The production fresh route uses corrected inference followed by its usual complete local training.

## Remaining separate issues

- Skin Gaussian centres follow observed meshes, but their covariance/SH do not currently receive a reference-to-observed same-triangle articulation transform. This was left unchanged to avoid mixing factors into the hair test.
- The environment neck transition uses root-only relative `C/F`. It likewise does not include joint-1 articulation at its top. It was left unchanged; correcting this would not itself solve a static depth mismatch or the reference-state neck seam.
- A more consistent motion contract is not a claim of true hair depth, complete hair volume or restored individual strands. Those remain image/geometry quality checks.
