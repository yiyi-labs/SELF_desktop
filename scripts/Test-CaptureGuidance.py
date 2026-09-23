"""API26 tablet smoke test. Reads UI metadata; never captures camera pixels."""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--device', default='127.0.0.1:5555')
parser.add_argument('--evidence', default='docs/evidence/capture-automatic-guidance')
parser.add_argument('--hdc', default=r'C:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe')
args = parser.parse_args()
evidence = ROOT / args.evidence
evidence.mkdir(parents=True, exist_ok=True)
remote_layout = '/data/local/tmp/self-guidance-ui.json'
local_layout = ROOT / 'artifacts/self-guidance-ui.json'


def hdc(*arguments):
    result = subprocess.run([args.hdc, '-t', args.device, *arguments], capture_output=True, timeout=30)
    output = result.stdout.decode('utf-8', errors='replace') + result.stderr.decode('utf-8', errors='replace')
    if result.returncode or '[Fail]' in output:
        raise RuntimeError('Device command failed: ' + output)
    return output


def nodes():
    hdc('shell', 'uitest', 'dumpLayout', '-b', 'com.self.mirror', '-p', remote_layout)
    hdc('file', 'recv', remote_layout, str(local_layout))
    stack = [json.loads(local_layout.read_text(encoding='utf-8'))]
    result = {}
    while stack:
        node = stack.pop()
        a = node.get('attributes', {})
        if a.get('id'):
            result[a['id']] = a
        stack.extend(node.get('children', []))
    return result


def wait_for(key):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        current = nodes()
        if key in current:
            return current
        time.sleep(.25)
    raise RuntimeError('UI did not become ready: ' + key)


def bounds(a):
    return tuple(map(int, re.findall(r'-?\d+', a['bounds'])))


def click(a):
    x1, y1, x2, y2 = bounds(a)
    hdc('shell', 'uitest', 'uiInput', 'click', str((x1+x2)//2), str((y1+y2)//2))


def clips():
    # Only compare filenames in memory; no private video is read or exported.
    output = hdc('shell', 'find', '/data/app/el2/100/base/com.self.mirror/haps/entry/files/captures', '-type', 'f')
    return {line.strip() for line in output.splitlines() if line.strip().endswith('.mp4')}


assert hdc('shell', 'param', 'get', 'const.product.devicetype').strip() == 'tablet'
# Collect the actual ArkUI-rendered fixture created by SELFNativeCameraPipeline.
for name in ('camera-guide-transparent-a.png', 'camera-guide-transparent-b.png',
             'camera-guide-public-scene.png', 'camera-guide-artwork.json'):
    hdc('file', 'recv', '/data/app/el2/100/base/com.self.mirror/haps/entry_test/files/'+name, str(evidence/name))
a = Image.open(evidence/'camera-guide-transparent-a.png').convert('RGBA')
b = Image.open(evidence/'camera-guide-transparent-b.png').convert('RGBA')
transparent = a.getchannel('A').histogram()[0] / (a.width*a.height)
assert transparent > .85, 'The guide must not have a filled/blurred panel'
assert a.getchannel('A').getextrema() == (0, 255), 'Expected transparent space and visible line art'
for corner in ((0,0),(a.width-1,0),(0,a.height-1),(a.width-1,a.height-1)):
    assert a.getpixel(corner)[3] == 0
assert ImageChops.difference(a,b).getbbox(), 'Movement artwork is static'
checks = {'device':args.device, 'cameraPixelsCaptured':False, 'personalTrackingValidated':False,
          'personalReconstructionValidated':False, 'transparentFraction':transparent,
          'lineAnimationChangesFrames':True, 'transparentCorners':True}
(evidence/'artwork-pixel-checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')

hdc('shell','aa','start','-a','EntryAbility','-b','com.self.mirror')
current = wait_for('begin-capture')
before = clips()
try:
    click(current['begin-capture'])
    current = wait_for('camera-preview-active')
    time.sleep(3)
    current = nodes()
    assert 'camera-record' not in current, 'Unexpected shutter/stop control'
    assert 'camera-preview-active' in current
    assert 'camera-capture-outcome' in current
    full = bounds(current['camera-fullscreen'])
    preview = bounds(current['self-camera-preview'])
    assert preview[0] <= full[0]+2 and preview[1] <= full[1]+2
    assert preview[2] >= full[2]-2 and preview[3] >= full[3]-2
    assert clips() == before, 'Preview unexpectedly created a recording'
    # An actual face can dismiss the hint; do not fake its presence to satisfy a test.
    hint = current.get('camera-motion-hint')
    if hint:
        box = bounds(hint)
        assert abs((box[0]+box[2])-(full[0]+full[2])) <= 12
        assert abs((box[1]+box[3])-(full[1]+full[3])) <= 12
        assert not hint.get('blur')
    safe_ids = ('camera-fullscreen','camera-preview-active','camera-motion-hint',
                'camera-anchor','camera-capture-outcome','camera-guide','self-camera-preview')
    checks.update({'previewStarted':True,'shutterAbsent':True,'newRecordings':0,
                   'hintPresent':bool(hint),'fullScreen':True,
                   'nodes':{key:{k:current[key].get(k) for k in ('bounds','text','blur','backgroundColor')}
                            for key in safe_ids if key in current}})
    (evidence/'device-ui-checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in checks.items() if k!='nodes'},indent=2))
finally:
    current = nodes()
    if 'camera-back' in current:
        click(current['camera-back'])
