# Actual local900 / T3 display evidence, 2026-10-03

Both comparisons used PlayCanvas **2.22.4**, unchanged default unified COMPACT,
minPixelSize=2, radialSorting=false, AA=false, no post-effects and fog disabled.
There were no page errors. Same original 1080 x 1920 camera, full RGB/alpha
domain, raw premultiplied GL bytes, no second alpha multiplication. Actual
camera transform max discrepancy is 5.42e-8. No rendering settings were tuned.

The gsplat side reuses the matching run's archived `full-final/frame_0111.png.npz`.
It is explicitly a scene-state render, not a newly executed PLY reload. The
PlayCanvas side actually loaded and drew the exact exported PLY. Both assets
contain 62,798 points and are frozen reference frame0111 exports.

| Asset | Local900, room/body initialization | Local900 followed by T3 400 |
| --- | ---: | ---: |
| PLY SHA-256 | c455e4288881faceef17a4b988caf6fedf151f260f7c7e2a803d93d54a5066c8 | 6d750a5965f1fd6e8620a617d059b30dbe39b8821b82cc439efb506d115e7cab |
| gsplat/PC full RGB difference | .004952 | .007735 |
| gsplat/PC face RGB difference | .006392 | .006683 |
| gsplat/PC room RGB difference | .004463 | .009094 |
| gsplat/PC neck-cloth RGB difference | .004538 | .005010 |
| Source face error, gsplat / PC | .043148 / .041395 | .043148 / .041248 |
| Source hair error, gsplat / PC | .046805 / .047078 | .046673 / .046891 |
| Source neck-cloth error, gsplat / PC | .031117 / .032381 | .018079 / .018977 |
| Source room error, gsplat / PC | .427382 / .431059 | .227519 / .231804 |
| Room alpha<.8, gsplat / PC | 69.87% / 70.60% | 46.95% / 48.85% |

All errors above are fixed-domain mean RGB absolute error including missing
pixels, not only covered pixels. Alpha<.8 is a coverage proxy, not proof that
geometry does not exist. Original face and independently segmented room masks
overlap at 1,088 pixels. This conflict is recorded, not silently cut from either
metric. The first preparation attempt's masks remain preserved; the audit's
overly strict disjoint-mask requirement was corrected, with a regression test.
Six CPU display-contract tests passed in 0.039 seconds.

## Visible conclusion

The two renderers now show closely matching defects and improvements at this
camera. The huge renderer discrepancy of the old wide-kernel asset is not
reproduced by these two assets. T3 makes the collar/chest cloth clearly more
legible, and that improvement survives actual PlayCanvas drawing. It does not
repair the large right-side room absence or the holes between cupboard/curtain.
Face colouring is mottled, glasses are soft, and hair remains thick compared
with the original. The results are not complete-quality accepted assets.

The T3 file is environment/body optimization with protected face parameters,
not a newly executed T4 full joint portrait update. Nothing was deployed or
sent to the tablet in this audit, and there is no HarmonyOS rendering/FPS claim.

## Evidence paths

- `backend/.sources/live-complete-repair-20261003-local900-display-complete/comparison.json`
- `backend/.sources/live-complete-repair-20261003-local900-display-complete/source-gsplat-playcanvas.png`
- `backend/.sources/live-complete-repair-20261003-t3-display/comparison.json`
- `backend/.sources/live-complete-repair-20261003-t3-display/source-gsplat-playcanvas.png`
- Each `playcanvas/` contains original raw `.rgba`, `.png`, actual settings,
  camera matrices, PLY hash and the unchanged probe's script hash.

## Same PLY continuous orbit

Actual existing production viewer bundle under headless Chrome/SwiftShader,
720 x 1280, one immutable T3 PLY, no angle-dependent model replacement:

`backend/.sources/live-complete-repair-20261003-t3-display/fixed-asset-orbit/continuous-orbit-small/private-fixed-asset-continuous-orbit.webm`

Video SHA-256:
`4689df5fac248259d81121d4899b03a272ebe63794f0a4508cacd8cb836caf04`.
PLY before/after hash identical; no browser errors. Yaw samples are approximately
+/-11.8 degrees, with small positive/negative pitch and return. These are viewer
interaction angles, not independently validated observed face angles. The
script records actual camera snapshots and source hash in `audit.json`.
This is software-rendered graphics evidence, not tablet performance. Transparent
canvas PNGs can appear against the file viewer's own background; RGB/alpha
comparisons above use raw premultiplied data instead.

Reproducible CPU preparation:

```
python -B audit_live_scene_cached.py --run <run> --prepared <prepared> --reference frame_0111.png --out .sources/<fresh-display>
node scripts/probe-complete-baseline-display.mjs <fresh-display>/display.json <fresh-display>/playcanvas
python -B audit_live_scene_display.py compare --out .sources/<fresh-display>
```

`audit_live_scene_cached.py` verifies source/asset/reference/camera identity and
uses original rectification. It never trains or recomputes gsplat. One early
T3 receipt had a hardcoded local-only label; its original metadata is preserved
as `gsplat-receipt.initial-metadata-error.json`, and the correction explicitly
records T3 400 from the real config. Raw render data and assets were unchanged.

## Later same-session shared-room candidate: separate actual drawing

New PLY `42e2054ecd2560c9a76c411f63fe18812e68b2cd5274c5212e4f42d107cc6757`
was actually loaded and drawn, still 62,798 points, original 1080 x 1920 K/C,
same default PlayCanvas settings, no errors. This is not the preceding T3 file.

| Fixed reference domain | gsplat source RGB | PlayCanvas source RGB | Cross-render RGB | gsplat / PC alpha<.8 |
| --- | ---: | ---: | ---: | ---: |
| Full | .039675 | .042756 | .009672 | 5.65% / 6.58% |
| Face | .042752 | .041127 | .007157 | .22% / .54% |
| Hair | .043539 | .043712 | .005076 | 2.81% / 4.13% |
| Neck/clothing | .018134 | .019088 | .005045 | .41% / .86% |
| Room | .026491 | .031909 | .012117 | 8.48% / 9.55% |

Visual inspection of the new source/gsplat/PC triptych confirms that the upper
ceiling and right gray wall are now largely continuous in both renderers.
The left cupboard/curtain boundary still has conspicuous holes. Face mottling,
soft glasses and excess-looking hair volume remain. Cloth/collar clarity is
retained. This is visible scene improvement, not complete quality acceptance.

New evidence directory:
`backend/.sources/live-complete-repair-20261003-shared-room-display/`.
The new `comparison.json`, raw RGBA and triptych carry this new asset hash.
Fresh continuous orbit, same PLY before/after hash and no page errors:
`fixed-asset-orbit/continuous-orbit-small/private-fixed-asset-continuous-orbit.webm`.
New video SHA-256:
`fd9a91c871265847199ecfd07a3f90cc729c883860e612de5ac306840f99d659`.
The video uses the existing viewer bundle on SwiftShader, not HarmonyOS FPS.

## Preserved-budget plus hair-composite candidate: actual display and orbit

The later `live-complete-repair-20261003-budget-complete` PLY was separately
loaded and drawn. Hash:
`e37ae36a63b3ac83ee4d1179a27d3dec4384310db13b97694c867a24577a53c4`.
It contains 62,798 points. The headless browser reported no errors. Same
reference 0111, native 1080 x 1920 and original camera/renderer settings;
maximum camera error 5.4165e-8. No viewer tuning was applied.

| Fixed reference domain | gsplat source RGB | PlayCanvas source RGB | Cross-render RGB | gsplat / PC alpha<.8 |
| --- | ---: | ---: | ---: | ---: |
| Full | .039790 | .043169 | .010155 | 5.91% / 7.10% |
| Face | .042775 | .040818 | .006715 | .22% / .56% |
| Hair | .044808 | .045044 | .005214 | 2.59% / 3.84% |
| Neck/clothing | .018126 | .019113 | .005044 | .42% / .86% |
| Room | .026689 | .032639 | .012976 | 8.72% / 10.23% |

The native source/gsplat/PC comparison shows a largely continuous ceiling
and right wall at this reference. Left cupboard/curtain transition holes,
face mottling and soft glasses remain. The result is not final quality
acceptance. The gsplat side is the archived full scene-state draw and the PC
side is a real PLY load/draw, as explicitly recorded in the receipts.

More importantly, the same PLY at just +/-11.8 degrees of viewer yaw reveals
large missing background regions behind the human silhouette, clothing
boundaries that end abruptly, and a visible neck seam. Thus the reference
image improvement does not establish a complete surrounding scene. These
failures occur during small interaction, not only the wide exploratory orbit.
Viewer angles are not equivalent to calibrated source head-observation angles.

Evidence directory:
`backend/.sources/live-complete-repair-20261003-budget-complete-display/`.

Two new continuous videos were drawn from one immutable PLY by the existing
viewer bundle at 720 x 1280 with SwiftShader. Both retain the source hash,
actual camera samples and identical PLY hashes before/after; no browser errors:

- `fixed-asset-orbit/continuous-orbit-small/private-fixed-asset-continuous-orbit.webm`
  (+/-11.8 degrees and small pitch). Video SHA-256
  `f42a2e971ed4bea5c89cb260eacb147e95a1d9c00afc6a0dea4683419a712c92`.
- `fixed-asset-orbit/continuous-orbit/private-fixed-asset-continuous-orbit.webm`
  (approximately +/-60 viewer degrees; exploratory extrapolation, not a claim
  that these viewpoints were observed in the video). Video SHA-256
  `26c8a8faf0b4f7a7fad5bfbf662b4dbaae65cc3a0241bc21d098ee1edc5ad2e9`.

This work used no new training, no GPU inference, and no production viewer
edits. It is computer software rendering; HarmonyOS appearance and FPS are
not tested by these videos. Hair-only appearance recovery is reviewed in
`hair-composite-review-20261003.md`, separate from geometric acceptance.

## Additional observed-room surfaces: visible gains with a face regression

The following later asset was actually loaded, not substituted with any prior
draw: `7812b7673a65659c951f2252bb73b25c14f25b1d7b5269f1165582c23b384d83`.
It has 65,304 points, including the retained 30,000 room points and 2,506 new
conditional surface points. Reference 0111, 1080 x 1920, original K/C and all
production defaults were preserved. Camera error was 5.4165e-8, no browser errors.

| Domain | gsplat source RGB | PC source RGB | Cross-render RGB | gsplat / PC alpha<.8 |
| --- | ---: | ---: | ---: | ---: |
| Full | .040162 | .043687 | .010184 | 5.78% / 6.91% |
| Face | .046820 | .046091 | .006826 | .071% / .181% |
| Hair | .048355 | .050938 | .006842 | 0% / 0% |
| Neck/clothing | .018128 | .019042 | .004964 | .34% / .74% |
| Room | .026590 | .032559 | .012989 | 8.68% / 10.20% |

Compared with e37ae3 above, face and hair RGB errors increase despite improved
alpha. The room reference changes little. In the actual +/-11.8 degree orbit,
some behind-ear/background holes are smaller, especially at negative yaw, but
large missing regions, clothing boundaries and the neck seam remain. The
orbit interaction samples differ slightly due to inertia; these are qualitative
visual comparisons, not exact pixel subtraction at equal orbit cameras.
The fixed reference comparison uses the exact same camera.

The source-state parameter check confirms identical face-core geometry, SH and
opacity. Hair colour/opacity and 330 neck SH values have changed. In reference
face_core, q_skin differs by at most 1.19e-7 while mean q_room rises from .000016
to .006079. In the glasses mask, q_skin is exactly unchanged while q_room rises
from zero to .010940. This supports background transmitted through the existing
local face alpha, rather than broad new background occlusion in front of the
face. It does not exclude small ordering changes at boundaries/hair, nor establish
that all new background geometry is correct. Existing cached q has five semantic
groups and does not separate the old 30,000 and new 2,506 room points.

This experiment also reran environment optimisation: all 30,000 old room and
16,000 body point parameters change, although their initial positions and scales
match exactly. It is not a single-factor addition of 2,506 unchanged points.
`environment_uid` is local sequential identity within each initialisation;
new room points inserted before body renumber body IDs. Cross-run correspondence
was checked with identical initial component coordinates/scales, not UID alone.
The preliminary incorrect UID-only diagnostic is retained and explicitly marked.

New evidence:
`backend/.sources/live-complete-repair-20261003-observed-room-display/` contains
the actual raw PC comparison, `incremental-protection-cpu.json`,
`incremental-parameter-subgroups.json` and the fresh continuous small orbit.
Video SHA-256:
`bf5f68cf2a4f3d62c6dfb53d3a03d49b6167d62f2004c5f9ab86a800ac849414`.
It uses one immutable PLY, default viewer settings and SwiftShader, not device FPS.
This candidate is not accepted as a simultaneous face/hair/background improvement.

### Frozen source-contribution replay

A single actual GPU forward of the immutable 7812b7 PLY retained all components
and added separate additive channels for the original 30,000 room points,
2,340 points from reference 0119, and 166 from reference 0052. Their q sum agrees
with room q to 2.38e-7. This took 2.20 seconds, allocated peak 203.53 MiB, zero
optimizer steps. The exported covariance round-trip causes isolated differences
from the original state draw: max RGB .001448, q .003013 and alpha .000538. The
source replay is therefore not called bitwise identical to the checkpoint.

| Reference domain | Old room q | Added 0119 q | Added 0052 q |
| --- | ---: | ---: | ---: |
| Face core | .00001936 | .00605886 | .00000086 |
| Glasses | 0 | .01094034 | 0 |
| Hair | .00284371 | .01359067 | .01008122 |
| Observed room | .84905028 | .00017750 | .00028221 |

The incremental face transmission comes almost entirely from the 0119 surface.
Combined with unchanged skin q, this is not evidence that those points moved
in front of the skin. It exposes the frozen face's existing alpha/color ambiguity
against a now represented background. On the visible reference room domain those
new surfaces contribute little because they primarily extend behind the person.
Hair/boundary changes still need their own geometry and visibility checks.

An initial audit reader incorrectly selected the first nine fields of the
45-field, channel-major padded SH layout. Its contract check rejected that draw;
the failure is retained separately. The corrected reader reads all padded fields
before selecting degree one, and three new CPU reader tests plus six existing
display tests pass. This was an audit error, not a production exporter repair.
Evidence: `live-complete-repair-20261003-observed-room-source-q-padded/`.

## Fresh preparation: actual display, not the old controlled fit

The end-to-end fresh preparation's asset
`b39eb2aaa5de17a5bcaabd89dfd5f22ed9b77f2653d11a3e4f1dff4edced13c7`
was actually drawn separately, 60,790 points, reference 0053, 1080 x 1920.
Camera error is 1.94e-7, no browser errors. This reference differs from 0111, so
its absolute errors must not be placed in a before/after claim against 0111.

| Domain | gsplat source RGB | PC source RGB | Cross-render RGB | gsplat / PC alpha<.8 |
| --- | ---: | ---: | ---: | ---: |
| Full | .088829 | .092071 | .007220 | 11.13% / 11.86% |
| Face | .031794 | .031398 | .005812 | .389% / 1.223% |
| Hair | .043995 | .043892 | .005785 | .096% / .314% |
| Neck/clothing | .054088 | .055187 | .004598 | .266% / .525% |
| Room | .104339 | .109389 | .008491 | 17.08% / 17.96% |

Both renderers show the same principal defects: an elevated hairline with a dark
gap and bright strip, stray-looking top hair, soft glasses/face detail, a visible
upper-neck seam, right wall missing regions and rippled clothing edges. The
small +/-11.8 degree orbit makes the hair gap, neck layers and missing room more
obvious. This fresh candidate has not passed quality acceptance. There is no
evidence that a new fog/display effect explains these defects.

Evidence directory: `live-complete-repair-20261003-fresh-display/`.
Same-asset small orbit video SHA-256:
`a4177b5f8f4c1317a590c17742bbb805821917c15c60da2d844bc079dd6f06ef`.
The video is the current bundled PlayCanvas viewer on desktop SwiftShader,
720 x 1280, zero browser errors. It is not a HarmonyOS test or device FPS.

## Face-composite recovery: display preserves a limited colour improvement

The appearance-only candidate 2ced0e was separately loaded:
`2ced0ecc664e702a3b6d337bbb6f12f2d37619d071e8005be9ea5a13f0be147d`.
It keeps the 7812b7 geometry and all non-selected parameters. Reference 0111,
native 1080 x 1920 and unchanged renderer defaults, 65,304 points, no errors.

Reference face RGB L1 improves from .046820 to .045006 in gsplat and from
.046091 to .044523 in PC. Hair, glasses, neck/clothing and room PC metrics are
unchanged. Thus the local colour change survives export and actual display.
It is still worse than the earlier e37ae3 face reference, and cross-view
regressions remain; it is not complete face quality acceptance or geometric
detail restoration. See `face-composite-review-20261003.md` for all views.
Evidence: `live-complete-repair-20261003-face-composite-display/`.
