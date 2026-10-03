"""Build an exact old-row -> new-row map for every reformatted file.

Every reformat() split inserts exactly one newline at a known source position
(a ';' or a header ':'). So the new row of any old position is
  old_row + (#insertions strictly above it) + (#insertions earlier on its own row).
This is verified token by token against the real output (exit 1 on mismatch),
and summarised as [start_row, end_row, delta] segments for citation numbers.
"""
import io
import json
import pathlib
import subprocess
import sys
import tokenize

REPO = pathlib.Path(r"d:/STUDY/College/mine/olay")
PRE = "886f84e"
EV = REPO / "docs/evidence/backend-reformat-20261003"
BLOCK = {"if", "elif", "else", "for", "while", "try", "except", "finally",
         "with", "def", "class", "async", "match", "case"}
LAYOUT = (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
          tokenize.COMMENT, tokenize.ENCODING)
apply_report = json.loads((EV / "apply-report.json").read_text(encoding="utf-8"))


def toks(src):
    return list(tokenize.generate_tokens(io.StringIO(src, newline="").readline))


def insertion_points(src):
    """(row, col) after each token whose following newline reformat() inserts."""
    ts = toks(src)
    points, depth = [], 0
    first = None
    header = header_done = False
    for i, t in enumerate(ts):
        if t.type == tokenize.NEWLINE:
            first, header, header_done = None, False, False
        if t.type == tokenize.OP:
            if t.string in "([{":
                depth += 1
            elif t.string in ")]}":
                depth -= 1
        if t.type not in LAYOUT and first is None:
            first = t.string
            header = first in BLOCK
        if t.type == tokenize.OP and t.string == ";" and depth == 0:
            nxt = next((u for u in ts[i + 1:] if u.type not in LAYOUT), None)
            if nxt is not None and nxt.type != tokenize.NEWLINE:
                points.append((t.start[0], t.end[1]))
            continue
        if (t.type == tokenize.OP and t.string == ":" and depth == 0
                and header and not header_done):
            header_done = True
            nxt = next((u for u in ts[i + 1:] if u.type not in LAYOUT), None)
            if nxt is not None and nxt.type != tokenize.NEWLINE and nxt.start[0] == t.end[0]:
                points.append((t.start[0], t.end[1]))
    return sorted(set(points))


def significant(src, drop_semicolon):
    out = []
    for t in toks(src):
        if t.type in LAYOUT:
            continue
        if drop_semicolon and t.type == tokenize.OP and t.string == ";":
            continue
        out.append(t)
    return out


def shift(points, row, col):
    return sum(1 for (r, c) in points if r < row or (r == row and c <= col))


out, problems, checked = {}, [], 0
for entry in sorted(apply_report, key=lambda e: e["file"]):
    if not entry["splits"]:
        continue
    name = entry["file"]
    orig = subprocess.run(["git", "-C", str(REPO), "show", f"{PRE}:backend/{name}"],
                          capture_output=True, check=True).stdout.decode("utf-8")
    new = (REPO / "backend" / name).read_bytes().decode("utf-8")
    points = insertion_points(orig)
    n_old, n_new = orig.count("\n"), new.count("\n")
    if n_new - n_old != len(points):
        problems.append(f"{name}: line delta {n_new - n_old} != insertions {len(points)}")

    a = significant(orig, True)
    b = significant(new, False)
    if len(a) != len(b):
        problems.append(f"{name}: token count {len(a)} != {len(b)}")
        continue
    for t_o, t_n in zip(a, b):
        expect = t_o.start[0] + shift(points, t_o.start[0], t_o.start[1])
        if t_n.start[0] != expect:
            problems.append(f"{name}: token {t_o.string!r} old {t_o.start} -> "
                            f"new {t_n.start}, expected row {expect}")
        checked += 1

    # segments: rows sharing one delta; row r -> r + count(insertions at rows < r)
    unique_rows = sorted({r for (r, _) in points})
    segments, start = [], 1
    cumulative = 0
    for u in unique_rows:
        if u >= start:
            segments.append([start, u, cumulative])
        cumulative += sum(1 for (r, _) in points if r == u)
        start = u + 1
    if start <= n_old + 1:
        segments.append([start, n_old + 1, cumulative])
    out[name] = {"insertions": [[r, c] for (r, c) in points],
                 "segments": segments, "old_lines": n_old + 1, "new_lines": n_new + 1}

(EV / "line-map.json").write_text(
    json.dumps({"rule": "新行号 = 旧行号 + 该行之前的插入数（行内插入不计入本行行首）；"
                        "segments = [旧行起, 旧行止, 增量]",
                "pre": PRE, "files": out}, ensure_ascii=False, indent=1) + "\n",
    encoding="utf-8")
print(f"files: {len(out)} | tokens checked: {checked} | problems: {len(problems)}")
for p in problems[:10]:
    print("PROBLEM:", p)
sys.exit(1 if problems else 0)
