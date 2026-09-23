"""Record installed commercial SDK identities and declarations without redistributing headers."""
import argparse
import hashlib
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--deveco', default='C:/Program Files/Huawei/DevEco Studio')
parser.add_argument('--out', default='docs/evidence/reconstruction-contract/sdk-audit.json')
args = parser.parse_args()
root = Path(args.deveco) / 'sdk/default'
files = [
    'hms/native/sysroot/usr/include/spatial/spatial_recon_interface.h',
    'hms/native/sysroot/usr/include/ar/ar_engine_core.h',
    'hms/native/docs/html/group___spatial_recon.html',
    'hms/ets/api/@hms.graphics.spatialRender.d.ts',
    'hms/ets/api/@hms.graphics.spatialEdit.d.ts',
    'openharmony/ets/api/graphics3d/Scene.d.ts',
]
records = []
for name in files:
    path = root / name
    data = path.read_bytes()
    records.append({'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
header = (root / files[0]).read_text(encoding='utf-8')
functions = re.findall(r'HMS_SpatialReconStatus\s+(HMS_SpatialRecon_\w+)\s*\(', header)
edit = (root / files[4]).read_text(encoding='utf-8')
scene = (root / files[5]).read_text(encoding='utf-8')
report = {
    'checkedOn': '2026-09-23', 'sdkFiles': records,
    'reconstructionFunctions': functions,
    'selectionMethods': sorted(set(re.findall(r'\b(selectBy\w+)\(', edit))),
    'selectionReadbackDeclared': bool(re.search(r'\bgetSelected\w*\(', edit)),
    'renderContextLoadPluginDeclared': 'loadPlugin(name: string): Promise<boolean>' in scene,
    'copiedSdkImplementation': False,
    'runtimeCompatibilityProvenByHeaders': False,
}
out = Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(f'Recorded {len(records)} SDK file hashes and {len(functions)} reconstruction declarations')
