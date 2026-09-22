import importlib.metadata as metadata,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
result=[]
for distribution in sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
    m=distribution.metadata
    if m['Name'].lower()=='pip':continue
    result.append({'name':m['Name'],'version':distribution.version,'license':m.get('License-Expression') or m.get('License') or [c for c in m.get_all('Classifier',[]) if c.startswith('License ::')], 'scope':'backend dependency, unmodified; not bundled into HAP','projectURLs':m.get_all('Project-URL',[])})
(root/'docs/backend-dependencies.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
cgltf=(root/'entry/src/main/cpp/vendor/cgltf.h').read_text(encoding='utf-8')
license_text=cgltf[cgltf.rfind('/* cgltf is distributed under MIT license:'):].removeprefix('/* ').removesuffix(' */\n')
(root/'licenses/cgltf-MIT.txt').write_text(license_text,encoding='utf-8')
print('Recorded installed dependency versions/licenses; cgltf retains its original embedded MIT notice.')
