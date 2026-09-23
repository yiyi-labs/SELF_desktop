"""Verify the pinned, vendored CPU camera dependencies without network or user images."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
records = json.loads((root / 'shared/camera-dependencies.json').read_text())
count = 0
for library in records:
    assert len(library['revision']) == 40
    for item in library['files']:
        path = root / item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], str(path)
        count += 1
    source = root / 'entry/src/main/cpp/vendor' / library['name'] / 'LICENSE'
    packaged = root / 'entry/src/main/resources/rawfile/licenses' / (library['name'] + '.txt')
    assert source.read_bytes() == packaged.read_bytes()
print(f'PASS: {len(records)} pinned libraries, {count} files, packaged licenses match.')
