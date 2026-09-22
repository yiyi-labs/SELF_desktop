"""Checks only files actually retrieved from the HarmonyOS emulator."""
from pathlib import Path
import json
from PIL import Image, ImageOps, ImageChops
root=Path(__file__).resolve().parents[1]
evidence=root/'docs/evidence/native-es3'
fixtures=root/'entry/src/main/resources/rawfile/native-fixtures'
checks={}
for i in range(1,9):
    expected=ImageOps.exif_transpose(Image.open(fixtures/f'orientation-{i}.jpg')).convert('RGB')
    actual=Image.open(evidence/f'orientation-{i}.png').convert('RGB')
    # Independent JPEG decoders can round color by a small amount. Direction must be exact.
    assert actual.size==expected.size
    samples=[(3,3),(actual.width-4,3),(3,actual.height-4),(actual.width-4,actual.height-4)]
    maximum=max(abs(a-b) for p in samples for a,b in zip(actual.getpixel(p),expected.getpixel(p)))
    assert maximum<=2,(i,maximum)
    checks[f'exif{i}']={'dimensions':actual.size,'cornerMaxError':maximum,'pass':True}
odd=Image.open(evidence/'odd-stride.png').convert('RGB')
assert ImageChops.difference(odd,Image.open(fixtures/'odd-stride.png').convert('RGB')).getbbox() is None
checks['oddWidthPNGExact']=True
base,edited,repeat,side=[Image.open(evidence/name).convert('RGB') for name in ['native-face.png','native-edit.png','native-repeat.png','native-side.png']]
checks['editChangedBounds']=ImageChops.difference(base,edited).getbbox()
checks['repeatAbsoluteExact']=ImageChops.difference(edited,repeat).getbbox() is None
checks['rotationChanged']=ImageChops.difference(base,side).getbbox() is not None
assert checks['editChangedBounds'] and checks['repeatAbsoluteExact'] and checks['rotationChanged']
blocked,exception,later,clean,marked=[Image.open(evidence/name).convert('RGB') for name in ['protected-blocked.png','protected-exception.png','protected-later.png','snapshot-clean.png','snapshot-marked.png']]
checks['protectedWithoutGrantExactBaseline']=ImageChops.difference(base,blocked).getbbox() is None
checks['singleGrantChangesPixels']=ImageChops.difference(base,exception).getbbox() is not None
checks['laterUngrantOperationCannotChangeProtection']=ImageChops.difference(exception,later).getbbox() is None
checks['cleanSnapshotMatchesEffectiveExport']=ImageChops.difference(edited,clean).getbbox() is None
checks['annotationSeparateFromClean']=ImageChops.difference(clean,marked).getbbox() is not None
checks['invalidGLBLeavesEffectiveImage']=ImageChops.difference(base,Image.open(evidence/'after-invalid-glb.png').convert('RGB')).getbbox() is None
checks['actualSelectionTexels']=sum(v>0 for v in (evidence/'native-selection.mask').read_bytes())
checks['actualPhotoSelectionTexels']=sum(v>0 for v in (evidence/'photo-selection.mask').read_bytes())
assert checks['invalidGLBLeavesEffectiveImage'] and checks['actualSelectionTexels']>0 and checks['actualPhotoSelectionTexels']==45
assert all(checks[key] for key in ['protectedWithoutGrantExactBaseline','singleGrantChangesPixels','laterUngrantOperationCannotChangeProtection','cleanSnapshotMatchesEffectiveExport','annotationSeparateFromClean'])
(evidence/'pixel-checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
print(json.dumps(checks,indent=2))
