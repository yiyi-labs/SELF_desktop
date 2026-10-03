"""Re-pin engine-profile.json's implementationSha256 after the reformat.

Byte-preserving edit: only the 64-hex value after "implementationSha256" changes.
Evidence copies go to docs/evidence/backend-reformat-20261003/.
"""
import json
import pathlib
import re
import sys

REPO = pathlib.Path(r"d:/STUDY/College/mine/olay")
DATA = REPO / "backend/.data/reconstruction"
EV = REPO / "docs/evidence/backend-reformat-20261003"
EV.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO / "backend"))
import code_identity as ci  # noqa: E402

profile = DATA / "engine-profile.json"
raw = profile.read_text(encoding="utf-8")
m = re.search(r'("implementationSha256"\s*:\s*")([0-9a-f]{64})(")', raw)
assert m, "implementationSha256 key not found"
old = m.group(2)

ident = ci.source_identity(REPO / "backend")
new = ident["implementationSha256"]
assert new != old, "source identity unchanged despite reformat"

(EV / "engine-profile-before.json").write_text(raw, encoding="utf-8")
updated = raw[:m.start(2)] + new + raw[m.end(2):]
profile.write_text(updated, encoding="utf-8")
(EV / "engine-profile-after.json").write_text(updated, encoding="utf-8")

# sanity: parses, only the pin changed, pins agreeing
before_obj = json.loads(raw)
after_obj = json.loads(updated)
for key in before_obj:
    if key != "implementationSha256":
        assert before_obj[key] == after_obj[key], key
assert after_obj["implementationSha256"] == new

again = ci.source_identity(REPO / "backend")["implementationSha256"]
assert again == new, "source identity not deterministic"
(EV / "identity-after.json").write_text(
    json.dumps(ci.source_identity(REPO / "backend"), indent=1, sort_keys=True) + "\n",
    encoding="utf-8")

print("profile sha", old, "->", new)
print("deterministic:", again == new)
print("keys:", ", ".join(sorted(after_obj)))
