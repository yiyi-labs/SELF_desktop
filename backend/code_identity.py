"""Identify the actual local implementation, including imported stage modules.

Asset schema and transport names stay stable; Git identifies code changes.
Private checkpoints, models and captures are never included in this manifest.
"""
from pathlib import Path
import ast
import hashlib
import subprocess


ROOTS = ("worker.py", "runtime.py",
         "live_fullframe.py", "live_prepare.py")


def source_identity(backend=None):
    backend = Path(backend or Path(__file__).resolve().parent)
    pending = list(ROOTS) + [Path(__file__).name]
    found = {}
    while pending:
        name = pending.pop()
        if name in found:
            continue
        path = backend / name
        raw = path.read_bytes()
        found[name] = hashlib.sha256(raw).hexdigest()
        for node in ast.walk(ast.parse(raw)):
            imports = ([node.module] if isinstance(node, ast.ImportFrom) else
                       [n.name for n in node.names] if isinstance(node, ast.Import) else [])
            for module in imports:
                local = (module or "").split(".")[0] + ".py"
                if (backend / local).is_file() and local not in found:
                    pending.append(local)
    git = subprocess.run(["git", "-C", str(backend.parent), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=False)
    # File hashes still identify dirty edits and a copied package without Git.
    files = dict(sorted(found.items()))
    import json
    return {"gitCommit": git.stdout.strip() if git.returncode == 0 else None,
            "sourceFiles": files,
            "implementationSha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
