"""Checks only files actually retrieved from the HarmonyOS emulator."""
from pathlib import Path
import json
import sys
from PIL import Image, ImageOps, ImageChops
root=Path(__file__).resolve().parents[1]
evidence=Path(sys.argv[1]) if len(sys.argv)>1 else root/'docs/evidence/native-es3'
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
assert checks['invalidGLBLeavesEffectiveImage'] and checks['actualSelectionTexels']>0
# The selection is in viewport coordinates, so its texel count changes with
# portrait/landscape aspect ratio. The centered rectangle must remain closed,
# symmetric, binary, nonempty, and a strict subset of the source photo.
photo_mask=(evidence/'photo-selection.mask').read_bytes()
pw,ph=Image.open(fixtures/'odd-stride.png').size
assert len(photo_mask)==pw*ph and set(photo_mask)<=set([0,255])
selected=[(i%pw,i//pw) for i,v in enumerate(photo_mask) if v]
assert 0<len(selected)<pw*ph
xs,ys=zip(*selected);x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
assert len(selected)==(x1-x0+1)*(y1-y0+1) and abs(x0+x1-(pw-1))<=1 and abs(y0+y1-(ph-1))<=1
checks['photoCenteredRectangle']={'bounds':[x0,y0,x1,y1],'complete':True}
assert all(checks[key] for key in ['protectedWithoutGrantExactBaseline','singleGrantChangesPixels','laterUngrantOperationCannotChangeProtection','cleanSnapshotMatchesEffectiveExport','annotationSeparateFromClean'])
if (evidence/'v2-edit.png').exists():
    v2,v2repeat,v2blocked=[Image.open(evidence/n).convert('RGB') for n in ['v2-edit.png','v2-repeat.png','v2-blocked.png']]
    checks['v2ProtectedExact']=ImageChops.difference(base,v2blocked).getbbox() is None
    checks['v2AbsoluteRepeatExact']=ImageChops.difference(v2,v2repeat).getbbox() is None
    checks['v2Changed']=ImageChops.difference(base,v2).getbbox() is not None
    checks['v2DiffersFromLegacy']=ImageChops.difference(edited,v2).getbbox() is not None
    assert all(checks[k] for k in ['v2ProtectedExact','v2AbsoluteRepeatExact','v2Changed','v2DiffersFromLegacy'])
if (evidence/'legacy-photo-base.png').exists():
    # Independent CPU calculation of the pre-migration two-layer contract:
    # every legacy layer uses the luminance before the entire layer group.
    old_base=Image.open(evidence/'legacy-photo-base.png').convert('RGB')
    old_layers=Image.open(evidence/'legacy-photo-layers.png').convert('RGB')
    def linear(v): return v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4
    def srgb(v): return v*12.92 if v<=.0031308 else 1.055*max(v,0)**(1/2.4)-.055
    errors=[]
    for dx in [-18,-6,6,18]:
        for dy in [-18,-6,6,18]:
            point=(old_base.width//2+dx,old_base.height//2+dy)
            c=[linear(v/255) for v in old_base.getpixel(point)]
            luminance=sum(a*b for a,b in zip(c,[.2126,.7152,.0722]))
            factor=min(1.5,max(0,luminance/.35))
            for tint in [( .66,.12,.30),(.65,.25,.18)]:
                c=[a*.5+linear(b)*factor*.5 for a,b in zip(c,tint)]
            expected=[round(min(1,max(0,srgb(v)))*255) for v in c]
            errors.extend(abs(a-b) for a,b in zip(expected,old_layers.getpixel(point)))
    assert max(errors)<=3,('legacy multilayer changed',max(errors))
    checks['legacyMultilayerCPUContract']={'samples':16,'maxChannelError':max(errors),'pass':True}
if (evidence/'face-after-products.png').exists():
    assert ImageChops.difference(base,Image.open(evidence/'face-after-products.png').convert('RGB')).getbbox() is None
    checks['faceUnchangedAfterProductScenes']=True
    for style in ['red-jar','black-jar','white-pump','black-tube','white-set','white-ampoule']:
        closed,moving,opened,side=[Image.open(evidence/f'product-{style}-{state}.png').convert('RGB') for state in ['closed','moving','open','side']]
        assert all(ImageChops.difference(a,b).getbbox() for a,b in [(closed,moving),(moving,opened),(opened,side)])
        if style=='red-jar':
            # Catch missing/incomplete texture bindings, not just moving geometry.
            red=sum(r>g*1.5 and r>b*1.2 and r>40 for r,g,b in closed.getdata())
            assert red>500,('Red lacquer texture missing',red)
        checks['product-'+style]={'real3DFramesDiffer':True,'openAndRotate':True}
(evidence/'pixel-checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
print(json.dumps(checks,indent=2))
