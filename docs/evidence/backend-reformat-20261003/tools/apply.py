"""Apply the verified reformat to backend/*.py with a per-file proof chain.

For every staged file X.py:
  1. refuse to run if the reconstruction API is listening (service must be stopped),
  2. disk bytes must equal `git show HEAD:backend/X.py` after CRLF normalisation,
  3. staged bytes must equal reformat(disk) recomputed right now,
  4. verify.py: token stream (layout removed, ';' dropped) identical, AST identical,
     compiles,
  5. overwrite disk, then assert disk bytes == staged bytes.

Writes apply-report.json (per-file splits/bytes/sha256 before+after, closure set).
"""
import hashlib
import json
import pathlib
import socket
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import reformat as R          # noqa: E402
import verify as V            # noqa: E402

REPO = pathlib.Path(r"d:/STUDY/College/mine/olay")
BACK = REPO / "backend"
STAGE = pathlib.Path(r"C:/Users/30243/AppData/Local/Temp/self-format/staged")
OUT = pathlib.Path(__file__).parent


def sha(b):
    return hashlib.sha256(b).hexdigest()


def norm(b):
    return b.replace(b"\r\n", b"\n")


def api_listening():
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", 8787)) == 0


if api_listening():
    sys.exit("refusing: reconstruction API is listening on 8787 - stop the service first")

closure = set(json.loads(
    (REPO / "docs/evidence/backend-rename-20261003/identity-after.json")
    .read_text(encoding="utf-8"))["sourceFiles"])

report, failures = [], []
for p in sorted(STAGE.glob("*.py")):
    name = p.name
    disk = (BACK / name).read_bytes()
    head = subprocess.run(["git", "-C", str(REPO), "show", f"HEAD:backend/{name}"],
                          capture_output=True, check=True).stdout
    head_ok = norm(disk) == norm(head)
    staged = p.read_bytes()
    text = disk.decode("utf-8")
    new, splits = R.reformat(text)
    entry = {"file": name, "closure": name in closure, "splits": splits,
             "bytes_before": len(disk), "bytes_after": len(staged),
             "sha256_before": sha(disk), "sha256_after": sha(staged),
             "lines_before": text.count("\n"), "lines_after": new.count("\n")}
    problem = None
    if not head_ok:
        problem = "disk != git HEAD (modulo CRLF)"
    elif new.encode("utf-8") != staged:
        problem = "staged != reformat(disk) (stale staging)"
    else:
        verdict = V.compare(text, new)
        if verdict:
            problem = f"verify: {verdict}"
    if problem:
        entry["problem"] = problem
        failures.append(f"{name}: {problem}")
    else:
        (BACK / name).write_bytes(staged)
        if (BACK / name).read_bytes() != staged:
            failures.append(f"{name}: post-write mismatch")
            entry["problem"] = "post-write mismatch"
        else:
            entry["ok"] = "applied"
    report.append(entry)

report.sort(key=lambda e: (not e["closure"], -e["splits"]))
json.dump(report, open(OUT / "apply-report.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
applied = [e for e in report if e.get("ok")]
print(f"applied: {len(applied)} | closure: {sum(e['closure'] for e in applied)} "
      f"| non-closure: {sum(not e['closure'] for e in applied)} "
      f"| splits: {sum(e['splits'] for e in applied)} | failures: {len(failures)}")
for f in failures:
    print("FAIL:", f)
sys.exit(1 if failures else 0)
