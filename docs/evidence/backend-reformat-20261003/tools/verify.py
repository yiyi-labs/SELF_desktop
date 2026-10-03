"""Prove a reformatted file differs from its original only by layout.

  1. Token streams must be equal once layout tokens are removed from both sides and
     top-level ';' separators are dropped from the original (each was replaced by a
     newline). Comments are compared by exact string.
  2. ast.dump (no attributes) must be identical.
  3. The new text must compile.

compare(orig, new) returns None when all checks pass, else a description.
"""
import ast
import io
import tokenize

LAYOUT = (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
          tokenize.ENCODING)


def _tokens(src):
    out = []
    for t in tokenize.generate_tokens(io.StringIO(src, newline="").readline):
        if t.type in LAYOUT:
            continue
        if t.type == tokenize.OP and t.string == ";":
            continue
        out.append((t.type, t.string))
    return out


def compare(orig, new):
    try:
        to, tn = _tokens(orig), _tokens(new)
    except Exception as error:
        return f"tokenize failed: {type(error).__name__}: {error}"
    if to != tn:
        if len(to) != len(tn):
            return f"token count {len(to)} -> {len(tn)}"
        for i, (a, b) in enumerate(zip(to, tn)):
            if a != b:
                return f"token #{i} changed: {a!r} -> {b!r}"
    try:
        ao = ast.dump(ast.parse(orig))
        an = ast.dump(ast.parse(new))
    except SyntaxError as error:
        return f"parse failed: {error}"
    if ao != an:
        return "AST differs"
    try:
        compile(new, "<reformatted>", "exec")
    except SyntaxError as error:
        return f"compile failed: {error}"
    return None
