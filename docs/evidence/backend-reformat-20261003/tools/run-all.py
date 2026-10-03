"""Reformat every root-level backend/*.py into a staging tree and verify each one.

Writes nothing into the repository. Exit code 0 only if every file passes:
identity when there is nothing to split, token/AST/compile equality otherwise.
归档修正：暂存目录改为系统临时目录下自建（原为当时的固定临时路径），逻辑未变。
"""
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import reformat as R          # noqa: E402
import verify as V            # noqa: E402

REPO = pathlib.Path(r"d:/STUDY/College/mine/olay")
BACK = REPO / "backend"
STAGE = pathlib.Path(tempfile.gettempdir()) / "self-format" / "staged"
STAGE.mkdir(parents=True, exist_ok=True)

report = []
failures = []
total_splits = 0
for p in sorted(BACK.glob("*.py")):
    src = open(p, encoding="utf-8", newline="").read()
    new, splits = R.reformat(src)
    total_splits += splits
    entry = {"file": p.name, "splits": splits,
             "bytes": len(src.encode()), "bytes_new": len(new.encode()),
             "lines": src.count("\n"), "lines_new": new.count("\n")}
    if splits == 0:
        if new != src:
            failures.append(f"{p.name}: identity violated with 0 splits")
            entry["problem"] = "identity"
        else:
            entry["ok"] = "unchanged"
    else:
        problem = V.compare(src, new)
        if problem:
            failures.append(f"{p.name}: {problem}")
            entry["problem"] = problem
        else:
            entry["ok"] = "verified"
        (STAGE / p.name).write_text(new, encoding="utf-8", newline="")
    report.append(entry)

report.sort(key=lambda e: -e["splits"])
print(f"files: {len(report)} | changed: {sum(1 for e in report if e['splits'])} "
      f"| splits: {total_splits} | failures: {len(failures)}")
print(f"{'file':40s} {'splits':>6s} {'lines':>7s} {'->':>3s}")
for e in report[:40]:
    if e["splits"]:
        print(f"{e['file']:40s} {e['splits']:6d} {e['lines']:7d} -> {e['lines_new']}")
for f in failures:
    print("FAIL:", f)
json.dump(report, open(STAGE / "report.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
sys.exit(1 if failures else 0)
