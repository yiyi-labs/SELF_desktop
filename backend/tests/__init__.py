"""Backend test package: every backend/test_*.py lives here.

Keeps two imports working no matter how discovery is started:
- sibling test helpers (`from test_contracts import snapshot`), via this directory;
- backend runtime modules (`import reconstruction_runtime`), via its parent.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for entry in (str(HERE), str(HERE.parent)):
    if entry not in sys.path:
        sys.path.insert(0, entry)
