"""Compare reformat test logs against the rename A/B baselines.

Hard checks (must be identical):
  * "Ran N tests" count, final FAILED(...) line
  * multiset of failing test ids
  * multiset of terminal exception lines

Block check: per failing id, the traceback text after removing `File "...", line N`
lines, their quoted source lines, `...<N lines>...` elisions and `^^^^` markers
must be identical (line numbers and quoted source text necessarily change when
statement-splitting inserts newlines).
"""
import collections
import json
import pathlib
import re
import sys

EV = pathlib.Path(r"d:/STUDY/College/mine/olay/docs/evidence")
BASE = EV / "backend-rename-20261003"
NEW = EV / "backend-reformat-20261003"
SEP = "=" * 70

EXC = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt)\b")


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def parse(raw):
    ran = re.search(r"^Ran (\d+) tests? in ", raw, re.M)
    final = re.search(r"^FAILED \(.*\)|^OK(?: \(.*\))?$", raw, re.M)
    lines = raw.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        if lines[i].startswith(("ERROR: ", "FAIL: ")):
            start = i
            j = i
            while j < len(lines) and lines[j] != SEP:
                j += 1
            chunk = lines[start:j]
            for k, l in enumerate(chunk):
                if re.match(r"^Ran \d+ tests? in ", l) or l.startswith("FAILED (") \
                        or re.match(r"^OK( \(|$)", l):
                    chunk = chunk[:k]
                    break
            header = chunk[0]
            m = re.search(r"\(([^()]+)\)\s*$", header)
            tid = m.group(1).strip() if m else header.split(": ", 1)[1].strip()
            terminal = None
            for l in reversed(chunk):
                if EXC.match(l.strip()):
                    terminal = l.strip()
                    break
            blocks.append({"id": tid, "terminal": terminal, "lines": chunk})
            i = j
        else:
            i += 1
    return {"ran": int(ran.group(1)) if ran else None,
            "final": final.group(0).strip() if final else None,
            "blocks": blocks}


FILE_LINE = re.compile(r'^\s*File ".*", line \d+')
ELISION = re.compile(r"^\s*\.\.\.<\d+ lines?\.\.\.\s*$")
CARET = re.compile(r"^\s*[\^~]+\s*$")


def normalize_block(lines):
    out = []
    skip_quote = False
    for l in lines:
        if skip_quote:
            skip_quote = False
            # quoted source line directly under a File line
            if l.strip() and not l.startswith("Traceback ") and not FILE_LINE.match(l):
                continue
        if FILE_LINE.match(l):
            out.append(FILE_LINE.sub(lambda m: m.group(0).split(", line")[0], l))
            skip_quote = True
            continue
        if ELISION.match(l) or CARET.match(l):
            continue
        out.append(l)
    while out and (not out[-1].strip() or re.fullmatch(r"-+", out[-1].strip())):
        out.pop()
    return "\n".join(out).strip()


regressions = []
for env, base_name, new_name in (("win", "win-after.txt", "win-after.txt"),
                                 ("wsl", "wsl-after.txt", "wsl-after.txt")):
    b = parse(read(BASE / base_name))
    a = parse(read(NEW / new_name))
    print(f"== {env} ==")
    checks = []
    checks.append(("ran count", b["ran"] == a["ran"], f'{b["ran"]} vs {a["ran"]}'))
    checks.append(("final line", b["final"] == a["final"], f'{b["final"]!r} vs {a["final"]!r}'))
    cb = collections.Counter(x["id"] for x in b["blocks"])
    ca = collections.Counter(x["id"] for x in a["blocks"])
    checks.append(("failing ids", cb == ca, f"{len(b['blocks'])} vs {len(a['blocks'])} blocks"))
    tb = collections.Counter(x["terminal"] for x in b["blocks"])
    ta = collections.Counter(x["terminal"] for x in a["blocks"])
    checks.append(("terminal exception lines", tb == ta, f"{len(tb)} vs {len(ta)} distinct"))
    by_id_b = collections.defaultdict(list)
    by_id_a = collections.defaultdict(list)
    for x in b["blocks"]:
        by_id_b[x["id"]].append(x)
    for x in a["blocks"]:
        by_id_a[x["id"]].append(x)
    ndiff = 0
    for tid in sorted(set(by_id_b) | set(by_id_a)):
        nb = sorted(normalize_block(x["lines"]) for x in by_id_b.get(tid, []))
        na = sorted(normalize_block(x["lines"]) for x in by_id_a.get(tid, []))
        if nb != na:
            ndiff += 1
            print(f"  block diff: {tid}")
            for x, y in zip(nb, na):
                if x != y:
                    for lx, ly in zip(x.split("\n"), y.split("\n")):
                        if lx != ly:
                            print(f"    - {lx!r}\n    + {ly!r}")
                    break
    checks.append(("normalized blocks", ndiff == 0, f"{ndiff} diffs"))
    for name, ok, detail in checks:
        print(f"  {'MATCH' if ok else 'DIFF '} {name}: {detail}")
        if not ok:
            regressions.append(f"{env}: {name}: {detail}")

print("ALL MATCH" if not regressions else "REGRESSIONS: " + "; ".join(regressions))
sys.exit(1 if regressions else 0)
