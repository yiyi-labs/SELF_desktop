# Appearance recovery against the completed room: bounded result

Parent PLY: `7812b7673a65659c951f2252bb73b25c14f25b1d7b5269f1165582c23b384d83`.
Candidate: `2ced0ecc664e702a3b6d337bbb6f12f2d37619d071e8005be9ea5a13f0be147d`.

The 180-step run changes SH and alpha only for 983 selected core-face splats.
All geometry and non-selected parameters are protected. The actual training
stage is 9.66 seconds; the enclosing report's 108.96 seconds includes evaluation
and archival. Peak allocated GPU memory for the enclosing run is 1,517.59 MiB.
No claim of improved geometry, hair or glasses is made.

All previously recorded development views were retained. The eight development
views already influenced research and are not a new blind test. There are only
five development views with reliable world C, plus reference 0111; missing world
observations are not invented for 0055/0075/0095.

| View | Local T0 before | Local T0 after | Full T2 before | Full T2 after |
| --- | ---: | ---: | ---: | ---: |
| 0015 | .026286 | .025464 | .029270 | .027952 |
| 0035 | .022545 | .024303 | .024398 | .025547 |
| 0055 | .054173 | .057483 | unavailable | unavailable |
| 0075 | .023931 | .023981 | unavailable | unavailable |
| 0095 | .024901 | .025038 | unavailable | unavailable |
| 0115 | .034389 | .033201 | .036189 | .033862 |
| 0130 | .032888 | .031565 | .036833 | .035417 |
| 0145 | .026887 | .025710 | .028914 | .027234 |
| 0111 reference | .043156 | .041392 | .046820 | .045006 |

The full-scene face improves in five of six measured views, but 0035 regresses.
Four local-development views regress, including 0055. Comparing the original,
parent and candidate images at identical crop/face width reveals slightly less
cheek colour mottling; the remaining artificial-looking fine pattern, soft
glasses, hair boundary and neck seam are not resolved. A small mean change is
not evidence of new measured skin detail.

The same new PLY was loaded and rendered in PC 2.22.4 with original K/C,
1080 x 1920 and default settings. The reference face change is preserved:
.046091 -> .044523 source L1. Hair, glasses, neck/clothing and room PC metrics
are exactly unchanged. No browser errors. No HarmonyOS test was performed.

Evidence in `backend/.sources/`:

- `live-complete-repair-20261003-face-composite-review/report.json`
- `live-complete-repair-20261003-face-composite-review/frame_0035.png-source-parent-candidate.png`
- `live-complete-repair-20261003-face-composite-review/frame_0111.png-source-parent-candidate.png`
- `live-complete-repair-20261003-face-composite-review/frame_0145.png-source-parent-candidate.png`
- `live-complete-repair-20261003-face-composite-display/comparison.json`

Conclusion: a limited, real appearance recovery has survived export/display,
but cross-view regressions prevent claiming simultaneous improvement. This
does not justify removing the background, globally hardening opacity, or calling
the geometry repaired. All old candidate assets and observations remain intact.
