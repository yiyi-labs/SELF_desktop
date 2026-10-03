# Limited viewer interaction repair — 2026-10-03

Only two production source behaviours changed:

1. Camera interpolation now uses elapsed seconds: `1 - 0.8 ** (60 * dt)`, with finite elapsed time bounded to `[0, 0.05]`. At 60 Hz the step remains 0.2. A missing/nonfinite dt uses 1/60 s; negative dt does not move the camera. The bound deliberately avoids a large camera jump after a stalled/resumed frame.
2. When a pointer is cancelled, the remaining touch becomes the position baseline, exactly as on pointer-up. This prevents a cancelled finger's previous coordinates from becoming the next rotation delta.

Dynamic resolution, sorting, styles, camera bounds, colour, model loading and other UI behaviour were not changed. These repairs do not establish that model holes or all tablet stutter are solved. No installation or device interaction was performed.

## Preservation and selective Git handling

Before editing, the entire working source and compiled viewer were preserved privately in `backend/.sources/viewer-motion-repair-20261003/`, together with the existing source diff and index diff. No personal images were copied.

`viewer-motion-fix.patch` contains only this turn's delta against that dirty source snapshot. The repository index does not contain the existing multi-pointer implementation on which this cancellation repair depends. Therefore this patch is **not directly applicable to the current clean index**; it is applicable after the exact prerequisite dirty baseline is intentionally accounted for. Do not stage the whole source or compiled bundle merely to commit these changes. Both remain working-tree modifications. No index or commit was changed in this task.

| File | Before SHA-256 | After SHA-256 |
| --- | --- | --- |
| viewer-gs/main.js | 70c1f8fbe0ce1cbbc76370003a886cb42e2ee443b7a62370c670aedf208dff4e | 880fa43f7e0923c097e05e2c301f1d7ff2061092e5d9cf2e41ca3ed263f30bec |
| entry/src/main/resources/rawfile/gs-viewer.js | d633fb2718ef5ed5087aabbd27356058323d2c71e9dda69c95ee32f87718f5d3 | 23433afba21c9a36f54f00a8b7dddc9acee7b707bb57fff940e2dd228a8171c5 |

## Verification

`node --test viewer-gs/tests/viewer-motion.test.mjs`: six tests passed. Tests execute the actual source handlers in a VM, without a model or WebGL. They check the original 60 Hz response, equal elapsed-time response at 20/30/60/120/240 Hz, bounded resume/invalid dt handling, cancellation of either finger followed by a small remaining-finger movement, and final-pointer cancellation. Running the same tests against the preserved pre-fix source produces four failures, establishing that the regressions exercise the repaired behaviours.

The incremental patch passes `git apply --reverse --check` against the updated working source. The compiled bundle passes `node --check`.

## Build

Only the personal viewer was rebuilt, after verifying PlayCanvas 2.22.4 and MIT metadata. The broader repository build script was deliberately not used because it also rebuilds the universe and copies unrelated assets.

```js
await build({entryPoints:['viewer-gs/main.js'],bundle:true,platform:'browser',
  format:'iife',target:'es2020',minify:true,external:['node:worker_threads'],
  outfile:'entry/src/main/resources/rawfile/gs-viewer.js'});
```

No model display, actual HarmonyOS frame-time measurement or device acceptance was performed by this repair task.
