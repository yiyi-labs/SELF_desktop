"""Independent post-hoc proof: disk == git original modulo inserted newlines.

PRE = the commit right before the reformat (886f84e). For every backend/*.py:
  * if git-original bytes equal disk bytes (modulo CRLF) -> "unchanged"
  * else token/AST equality must hold, disk must equal reformat(git-original),
    and the split count must match apply-report.json.
Plus a whole-tree diff check: only the 44 .py files and backend/README.md may
differ from PRE under backend/.
"""
import hashlib
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import reformat as R          # noqa: E402
import verify as V            # noqa: E402

REPO = pathlib.Path(r"d:/STUDY/College/mine/olay")
BACK = REPO / "backend"
PRE = "886f84e"
EV = REPO / "docs/evidence/backend-reformat-20261003"


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, check=True).stdout


def norm(b):
    return b.replace(b"\r\n", b"\n")


head = git("rev-parse", "--short", "HEAD").decode().strip()
source_files = json.loads((EV / "identity-after.json").read_text(encoding="utf-8"))["sourceFiles"]
apply_report = {e["file"]: e for e in json.loads(
    (EV / "apply-report.json").read_text(encoding="utf-8"))}

diff = git("diff", "--name-status", PRE, "--", "backend").decode().strip().splitlines()
changed = {line.split("\t")[1] for line in diff if line}
expected = {f"backend/{name}" for name in apply_report} | {"backend/README.md"}
print(f"HEAD={head} PRE={PRE}")
print(f"changed under backend/: {len(changed)} | expected: {len(expected)} | "
      f"{'MATCH' if changed == expected else 'MISMATCH'}")
if changed != expected:
    print("  only-in-diff:", sorted(changed - expected))
    print("  only-in-expected:", sorted(expected - changed))

bad, unchanged, reformatted = [], 0, 0
lines = []
for p in sorted(BACK.glob("*.py")):
    rel = f"backend/{p.name}"
    disk = p.read_bytes()
    orig = git("show", f"{PRE}:{rel}")
    if norm(disk) == norm(orig):
        unchanged += 1
        continue
    text_o = orig.decode("utf-8")
    text_d = disk.decode("utf-8")
    verdict = V.compare(text_o, text_d)
    new, splits = R.reformat(text_o)
    nb = new.encode("utf-8")
    exact = nb == disk
    eol_only = nb.replace(b"\r", b"") == disk.replace(b"\r", b"")
    note = "exact" if exact else ("eol-only(git blob LF / worktree CRLF)" if eol_only else "")
    if verdict:
        bad.append(f"{p.name}: {verdict}")
    elif not (exact or eol_only):
        bad.append(f"{p.name}: disk != reformat(git original) beyond CR")
    elif splits != apply_report[p.name]["splits"]:
        bad.append(f"{p.name}: splits {splits} != reported {apply_report[p.name]['splits']}")
    else:
        reformatted += 1
        lines.append(f"{p.name:40s} closure={str(p.name in source_files):5s} "
                     f"splits={splits:4d} {note:38s} sha256 "
                     f"{apply_report[p.name]['sha256_before'][:12]} -> "
                     f"{apply_report[p.name]['sha256_after'][:12]}")

print(f"unchanged: {unchanged} | reformatted+proven: {reformatted} | problems: {len(bad)}")
for b in bad:
    print("PROBLEM:", b)
out = "\n".join([f"HEAD={head} PRE={PRE}",
                 f"changed={len(changed)} expected={len(expected)} match={changed == expected}",
                 f"unchanged={unchanged} reformatted={reformatted} problems={len(bad)}",
                 *bad, *lines]) + "\n"
(EV / "git-equivalence.txt").write_text(out, encoding="utf-8")
print("written:", EV / "git-equivalence.txt")
sys.exit(1 if bad or changed != expected else 0)
