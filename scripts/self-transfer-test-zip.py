"""Desktop test double ONLY. Production uses HarmonyOS zlib, not this script."""
import json
import sys
import zipfile
from pathlib import Path

operation, source, destination = sys.argv[1:4]
if operation == 'pack':
    root = Path(source)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for file in sorted(root.rglob('*')):
            if file.is_file():
                archive.write(file, file.relative_to(root).as_posix())
elif operation == 'extract':
    with zipfile.ZipFile(source) as archive:
        archive.extractall(destination)
elif operation == 'compose':
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for entry in json.loads(Path(source).read_text(encoding='utf-8')):
            if 'extra' in entry:
                info = zipfile.ZipInfo(entry['path'])
                info.extra = bytes.fromhex(entry['extra'])
                archive.writestr(info, Path(entry['source']).read_bytes())
            else:
                archive.write(entry['source'], entry['path'])
else:
    raise ValueError(operation)
