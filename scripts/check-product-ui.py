"""Check the actual emulator screenshot, not just a successful button press.

The UI suite explicitly asks about the white waterglow bottle. Its lower body
must be light and textured in the second native surface. A black texture or a
missing surface must not pass. Bounds are reported by HarmonyOS UiTest.
"""
import json,statistics,sys
from pathlib import Path
from PIL import Image

root=Path(sys.argv[1]);box=json.loads((root/'product-ui-bounds.json').read_text())
im=Image.open(root/'product-ui-closed.png').convert('RGB')
l,t,r,b=[box[k] for k in ('left','top','right','bottom')];w=r-l;h=b-t
crop=im.crop((round(l+w*.47),round(t+h*.69),round(l+w*.53),round(t+h*.77)))
pixels=list(crop.getdata());median=statistics.median(sum(p)/3 for p in pixels)
passed=125<median<235
result={'source':'HarmonyOS UiTest screenCapture + component bounds','bounds':box,'whiteBottleBodyMedian':median,'expectedRange':[125,235],'pass':passed}
(root/'product-ui-pixels.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result,indent=2))
if not passed:raise SystemExit('Product texture on screen is black, absent or inconsistent with the requested white bottle')
