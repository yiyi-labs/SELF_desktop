# Hair appearance recovery: full-scene evidence and limits

This is a read-only review of `live-complete-repair-20261003-hair-composite`,
whose parent is `live-complete-repair-20261003-shared-room-trained`.
The 180-step phase changes only existing hair SH and opacity. It renders all
components together. Non-hair parameters were checked bitwise unchanged by
the training implementation. It does not change hair volume, seed geometry,
frame poses, skin covariance, garment geometry or background geometry.

The full-frame cache contains five development observations plus reference
0111. All eight development observations have head-local T0 comparisons;
0055/0075/0095 have no supported world C and therefore no T2. These three
views must not be counted as successful complete-scene rendering. Legacy
cropped audit metrics and native full-frame metrics remain separate.

## Native full-scene hair RGB L1

| View | Before | After | Interpretation |
| --- | ---: | ---: | --- |
| 0015 dev | .089849 | .063061 | Improves |
| 0035 dev | .071514 | .046869 | Improves |
| 0115 dev | .061845 | .064476 | Slight regression |
| 0130 dev | .116951 | .079144 | Improves |
| 0145 dev | .162805 | .128306 | Improves, still visibly incomplete |
| 0111 reference | .043539 | .044779 | Slight regression |

The six-view mean is .091084 -> .071106. This is not an acceptance gate by
itself. Source/before/after panels for 0035, 0111 and 0145 show less white
background shining through the side hair, but the disjoint edge clusters,
over-thick outline and erroneous hairline remain. The reference frontal
surface remains softer and thicker than the real hair. This is useful
appearance recovery in the correct composite context, not geometric repair.

Full-frame face RGB mean .033128 -> .033087; maximum individual regression
.000116 at 0115. The six-view cloth and neck RGB metrics and contributions
are unchanged. Observed-room RGB mean .113716 -> .113793; maximum individual
regression .000338. Hair contribution affects other pixels even when their
parameter groups are frozen, so this small room change is recorded.

## Head-local T0, all development observations

| View | Before hair RGB L1 | After hair RGB L1 |
| --- | ---: | ---: |
| 0015 | .038787 | .041897 |
| 0035 | .033190 | .050155 |
| 0055 | .065944 | .067915 |
| 0075 | .045226 | .046434 |
| 0095 | .036399 | .039981 |
| 0115 | .061749 | .064283 |
| 0130 | .040884 | .051339 |
| 0145 | .058190 | .066205 |
| 0111 reference | .046805 | .047906 |

All head-only black-background metrics become worse. This phase changes the
color/opacity ambiguity under the real background and is not intended to
optimize the black-background objective. Nevertheless, no unsupported world
view is claimed as validated, and this result does not establish viewpoint
robustness or repair the independent hair geometry gap.

The computer-only review used no optimizer, CUDA, camera change or input
modification. Full per-domain data, before/after asset hashes, training
receipt, and three native comparison panels are preserved under:

`backend/.sources/live-complete-repair-20261003-hair-composite-review/`.

The subsequently preserved-budget asset is a different PLY. Its actual
PlayCanvas evidence is recorded separately in `actual-display-20261003.md`.
