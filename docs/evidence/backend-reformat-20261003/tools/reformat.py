"""Statement-splitting reformatter: tokens unchanged, only line breaks inserted.

Contract (proved afterwards by verify.py):
  * the token stream (types + strings, including comments) is unchanged except that
    each top-level ';' statement separator is replaced by a newline, and
  * indentation is inserted where a one-line suite is expanded.

Rules applied to one *logical* line at a time:
  1. ';' at bracket depth 0 splits into separate statements at the current indent.
  2. A logical line that starts with a block keyword (if/elif/else/for/while/try/
     except/finally/with/def/class/async/match/case) and whose header colon at depth 0
     is followed by more tokens on the same physical line is split after the colon;
     the suite statements go to indent + 4.
  3. A ';' immediately before the line's NEWLINE (or before a trailing comment that is
     itself at end of line) is simply dropped - the real NEWLINE already ends the line.
Everything else (gaps, comments, string bytes, original indentation, line endings)
is re-emitted exactly as found.

Usage: python reformat.py <src.py> <dst.py>
"""
import io
import sys
import tokenize

BLOCK_KEYWORDS = {"if", "elif", "else", "for", "while", "try", "except", "finally",
                  "with", "def", "class", "async", "match", "case"}
SKIP_TYPES = (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
              tokenize.COMMENT, tokenize.ENCODING)


def _gap(lines, a, b):
    """Exact source text between end position a and start position b (1-based rows).

    Positions at or past EOF (the ENDMARKER sits one row past the last line) yield ''.
    """
    if a[0] == b[0]:
        row = lines[a[0] - 1] if 0 < a[0] <= len(lines) else ""
        return row[a[1]:b[1]]
    parts = []
    if 0 < a[0] <= len(lines):
        parts.append(lines[a[0] - 1][a[1]:])
    parts.extend(lines[a[0]:max(a[0], b[0] - 1)])
    if 0 < b[0] <= len(lines):
        parts.append(lines[b[0] - 1][:b[1]])
    return "".join(parts)


def _next_significant(toks, i):
    for t in toks[i + 1:]:
        if t.type in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
                      tokenize.COMMENT, tokenize.ENCODING):
            continue
        return t
    return None


def _source_lines(src):
    """Split on '\\n' only (keep '\\r'), matching how the tokenizer counts rows."""
    parts = src.split("\n")
    lines = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def reformat(src):
    toks = list(tokenize.generate_tokens(io.StringIO(src, newline="").readline))
    lines = _source_lines(src)
    out = []
    prev_end = (1, 0)
    depth = 0
    first = None          # first significant token string of the current logical line
    header = False        # that first token is a block keyword
    header_done = False   # the header colon has been consumed
    line_indent = 0       # column of the logical line's first token
    terminator = "\n"     # physical line ending of the logical line's last real line
    split_indent = None   # indent for statements after a split
    suppress_gap = False  # a split already emitted the newline+indent
    splits = 0

    for i, t in enumerate(toks):
        if t.type == tokenize.ENCODING:
            continue
        g = "" if suppress_gap else _gap(lines, prev_end, t.start)
        suppress_gap = False

        if t.type == tokenize.NEWLINE:
            terminator = t.string
            first, header, header_done, split_indent = None, False, False, None

        if t.type == tokenize.OP:
            if t.string in "([{":
                depth += 1
            elif t.string in ")]}":
                depth -= 1

        if t.type not in SKIP_TYPES and first is None:
            first = t.string
            line_indent = t.start[1]
            header = first in BLOCK_KEYWORDS
            split_indent = line_indent + 4 if header else line_indent

        if t.type == tokenize.OP and t.string == ";" and depth == 0:
            nxt = _next_significant(toks, i)
            out.append(g.rstrip())
            # A split is only needed when more tokens follow on the SAME physical
            # line (e.g. "a=1; b=2"); a trailing ';' is dropped - the NEWLINE
            # token that ends the line already provides the line break.
            if nxt is not None and nxt.start[0] == t.end[0]:
                out.append((terminator or "\n") + " " * split_indent)
                suppress_gap = True
                splits += 1
            prev_end = t.end
            continue

        if (t.type == tokenize.OP and t.string == ":" and depth == 0
                and header and not header_done):
            header_done = True
            nxt = _next_significant(toks, i)
            out.append(g)
            out.append(t.string)
            if nxt is not None and nxt.type != tokenize.NEWLINE and nxt.start[0] == t.end[0]:
                out.append((terminator or "\n") + " " * (line_indent + 4))
                suppress_gap = True
                splits += 1
            prev_end = t.end
            continue

        out.append(g)
        out.append(t.string)
        prev_end = t.end

    return "".join(out), splits


def main():
    src = open(sys.argv[1], encoding="utf-8", newline="").read()
    text, splits = reformat(src)
    with open(sys.argv[2], "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    print(f"{sys.argv[1]} -> {sys.argv[2]}: {splits} splits")


if __name__ == "__main__":
    main()
