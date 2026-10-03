# Neck and clothing continuity: observed support and bounded counterfactual

This is a diagnosis of the preserved-budget candidate, not a new reconstruction
or a deletion proposal. The asset is
`e37ae36a63b3ac83ee4d1179a27d3dec4384310db13b97694c867a24577a53c4`.
All camera, appearance, body geometry, face and background parameters were
preserved. No optimizer was created, no PLY exported and nothing sent to a device.

## Actual observed body and sampling

The body is now 16,000 measured conditional-surface points, not the historic 348
seeds: 13,625 cloth, 2,368 neck/skin and 7 other body-skin points. Its source NPZ
SHA-256 is `b68ab602eedefc1dd1bb9a1e73d4ac15f432281145d246916e76b3a741a8373d`.
The four body training observations are 0110--0113, lasting 1.232178 seconds.
Their camera-centre angular envelope about the body has a maximum pairwise
angle of 9.5595 degrees. That is not a calibrated head yaw measurement.

At native resolution the right shoulder and lower chest reach the image/valid
rectification boundary. Those parts are cut off by the observations themselves;
the current short body window does not observe the complete rear/far flank.
Other original video observations may help if their body motion can be verified.
This is not a claim that the entire source video lacks those observations.

Replaying only the original four-view point predicate gives these unchanged
counts. Rejection events are not independent missing surface regions.

| Observation | Source proposals | Accepted | Insufficient support | Free-space conflicts |
| --- | ---: | ---: | ---: | ---: |
| 0110 | 9,143 | 6,849 | 2,294 | 2,067 |
| 0111 | 9,127 | 8,836 | 291 | 91 |
| 0112 | 9,086 | 8,200 | 886 | 6 |
| 0113 | 9,025 | 7,512 | 1,513 | 9 |

Source depth-gradient rejection affected only 31/19/34/19 samples; source
confidence rejection affected none in this selection. The 3% cross-view depth
predicate removes some silhouette proposals, but it is not established as the
main cause of the large cuts. At reference 0111 the trained observed-cloth
q_body is 0.98170 and alpha<0.8 occupies 0.202% of the cloth domain. The captured
front clothing is substantially represented. Small orbit reveals surfaces
outside that narrow window and the actual seam, rather than proving all front
cloth was removed by a mask.

The depth estimator input was 280 x 504, while final T3 RGB training and drawings
were native 1080 x 1920. The archived `make_frame(..., half=True)` compatibility
argument is ignored. An initial audit label misread that call; the corrected
report preserves the earlier erroneous metadata as a separate file.

## Neck geometry and motion

At reference 0111, 325 of the 330 retained head-neck points project into observed
neck skin. For 254 head/body centre pairs within 8 image pixels, median absolute
relative depth difference is 4.16% (90th percentile 6.83%). Similar medians occur
in 0110/0112/0113. These are screen-nearest-centre diagnostics against conditional
depth, not independently established correspondences or measured depth truth.
They establish two non-coincident representations, not which representation is
correct at every point.

The neck motion binding has an identity reference transform and moves the
observed neck with a smooth head/body blend. It transports covariance, but
identity transport cannot align two initially distinct surfaces. There is no
explicit contact/correspondence solve between the FLAME-derived upper neck and
the observed body-neck. SH-only recovery can correct colour but cannot create
missing connecting surface. Static-Ply camera orbit applies no second temporal
head rotation, so the seam in that orbit is not duplicate global motion.

## Hiding the 330 head-neck points: rejected

An independent GPU audit rendered all components together at the four original
cameras and the two saved small-orbit cameras. Its only counterfactual was zero
visibility of the recorded 330 head-neck points. Before modifying that in-memory
opacity, the restored reference RGB, alpha and q matched the archived result
exactly (maximum error zero).

| Observation | Neck RGB before | Neck RGB hidden | alpha<0.8 before | alpha<0.8 hidden |
| --- | ---: | ---: | ---: | ---: |
| 0110 | .033873 | .043698 | 1.044% | 2.011% |
| 0111 | .014933 | .024804 | 1.373% | 2.568% |
| 0112 | .013543 | .021803 | 3.524% | 5.129% |
| 0113 | .013260 | .022784 | 4.266% | 5.988% |

The upper neck develops a black jagged gap in the reference and orbit views.
Protected face pixels are exactly unchanged in all four native comparisons;
room pixels are also unchanged. Clothing is unchanged except a negligible few
boundary pixels at 0110. Thus the actual body-neck cannot yet take over the
retained head-neck coverage. Simply deleting those points is rejected.

Twelve forward draws over six views took 92.06 seconds including loading,
CPU metrics and compressed image archival. Peak allocated CUDA memory was
1,057.45 MiB. This is an audit cost, not reconstruction time or device FPS.

Evidence in `backend/.sources/`:

- `live-complete-repair-20261003-neck-cloth-audit/report.json`
- `live-complete-repair-20261003-neck-cloth-audit/sampling-and-envelope.json`
- `live-complete-repair-20261003-neck-counterfactual/report.json`
- `live-complete-repair-20261003-neck-counterfactual/reference-neck-local-source-before-hidden.png`

The local image is source / current / hidden, without sharpening or colour
adjustment. The audit is reproducible with `audit_live_neck_counterfactual.py`.
All failed counterfactual images are retained. The next useful geometric task is
a bounded jointly observed neck contact/coverage solve, keeping skin and collar
as separate physical surfaces and preserving face/body protection, before any
replacement transaction. This audit does not claim that such a solve has run.

## Fresh 0053 reference: no confirmed coordinate handoff bug

A separate CPU-only audit checks the fresh b39eb2 asset, not the older 0111
candidate. Its body has 16,000 points: 13,056 cloth, 2,919 neck skin and 25 other
body skin. The five original support images are 0049--0053. Projection of every
initial body point back to its own recorded source UV differs by at most
9.1e-13 native pixels, with positive depth. All 2,919 neck source samples fall
within the same original neck masks. This verifies arithmetic/source identity,
not the accuracy of the predicted depth.

The reference identity checks pass: C*H versus scale-adjusted F differs by
1.19e-7; binding C and F are bitwise equal to the actual reference; scale
conversion differs only by 1.36e-7 float rounding. Initial body means enter the
scene with maximum float difference 4.77e-7 world units. Native masks have the
correct 1920 x 1080 array shape. There are 36 face/neck semantic overlap pixels,
which the appearance selector excludes from neck permission. These observations
do not support a broad wrong-mask, unit, or repeated-global-rotation explanation.

The two upper-neck representations already differ before training. For their
screen-nearest centre pairs within eight pixels, median absolute relative depth
differences are 3.17% initially, 3.32% after local training and 2.89% at the end.
The pairs vary as centres move, and are not measured surface correspondences.
They support an initial geometric disagreement rather than a sudden corruption
during export. The anatomy prior and conditional body depth do not contain a
jointly solved physical contact constraint.

An additional actual-run gap is established: the fresh neck appearance selector
returns zero points. Forty-eight points meet three-view neck support but are all
vetoed by protected-face contribution in the supplied views. The T3 log therefore
has no neck appearance optimizer steps. The prior candidate's 330-point SH
recovery must not be attributed to this fresh run. That conservative protection
is not established as a bug and was not loosened.

Evidence: `backend/.sources/live-complete-repair-20261003-fresh-neck-transfer-cpu/report.json`.
Reproducible CPU tool: `backend/audit_live_neck_transfer.py`.
No small coordinate-only fix was justified by this check; no model, optimizer,
camera or production code was changed.
