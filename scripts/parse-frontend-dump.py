#!/usr/bin/env python3
"""Extract per-declaration verdicts and dependency graphs from a
`hs-bindgen-cli internal frontend` dump.

The dump is Haskell `Show` output on a single line, with three top-level fields
of interest: `decls` (the declarations that survived selection), `declIndex`
(the verdict per declaration) and `useDeclGraph` / `declUseGraph` (dependencies
and their reverse).

Entry keys in `declIndex` are distinguishable from `DeclId`s nested in payloads
because only a key is immediately followed by `UsableEntry`/`UnusableEntry`.

Note on the partition this supports: `UnusableReason` has no "a dependency is
unusable" constructor, so every `UnusableEntry` is a *primary* failure. A
cascade drop is a declaration that is `UsableEntry` in `declIndex` yet absent
from `decls`, having been deselected by program slicing.

Usage:
  parse-frontend-dump.py verdicts DUMP    # CSV of per-decl verdicts
  parse-frontend-dump.py selected DUMP    # one selected decl name per line
  parse-frontend-dump.py deps DUMP        # CSV of user,used edges
"""

import ast
import csv
import re
import sys

FIELDS = ["decls", "declIndex", "useDeclGraph", "declUseGraph"]

DECL_ID_PAT = (
    r'DeclId \{name = DeclName \{text = "((?:[^"\\]|\\.)*)", '
    r"kind = (NameKind\w+(?: TagKind\w+)?)\}, isAnon = (True|False)\}"
)
DECL_ID = re.compile(DECL_ID_PAT)
ENTRY = re.compile(r"\(" + DECL_ID_PAT + r",(Usable|Unusable)Entry ")

# Shapes the parsec error takes for an unexpected token. `token` renders via
# `tokenPretty` ("spelling" (kind)); parsec's own machinery sometimes shows the
# raw `Token` record instead.
UNEXPECTED_RAW = re.compile(r"unexpected Token \{.*?getTokenSpelling = \"(.*?)\"\}", re.S)
UNEXPECTED_PRETTY = re.compile(r'unexpected "(.*?)" \(simpleEnum (CXToken_\w+)\)')
UNEXPECTED_ANY = re.compile(r"unexpected (.*)")
ERR_POS = re.compile(r"\(line (\d+), column (\d+)\)")


def sections(dump):
    """Map each top-level field name to its slice of the dump."""
    at = {}
    for f in FIELDS:
        m = re.search(r"\b" + f + r" = ", dump)
        if m:
            at[f] = m.start()
    order = sorted(at.items(), key=lambda kv: kv[1])
    out = {}
    for i, (name, start) in enumerate(order):
        end = order[i + 1][1] if i + 1 < len(order) else len(dump)
        out[name] = dump[start:end]
    return out


def balanced(s, start, open_chars="(", close_chars=")"):
    """Substring of the bracketed group starting at `s[start]`, brackets excluded.

    Skips over Haskell string literals so brackets inside them do not count.
    """
    depth = 0
    i = start
    in_str = False
    while i < len(s):
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in open_chars:
            depth += 1
        elif c in close_chars:
            depth -= 1
            if depth == 0:
                return s[start + 1 : i]
        i += 1
    raise ValueError("unbalanced brackets")


def haskell_string_at(s, start):
    """Read the Haskell string literal beginning at `s[start] == '"'`, unescaped."""
    assert s[start] == '"'
    i = start + 1
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == '"':
            break
        i += 1
    raw = s[start : i + 1]
    try:
        return ast.literal_eval(raw)
    except (SyntaxError, ValueError):
        return raw[1:-1]


def classify_reason(payload):
    """Reduce an `UnusableEntry` payload to a verdict dict."""
    out = {
        "reason_loc": "",
        "reason_ctor": "",
        "unexpected": "",
        "err_line": "",
        "err_col": "",
        "message": "",
    }
    conflict = payload.startswith("UnusableConflict")
    if conflict:
        out["reason_ctor"] = "UnusableConflict"
        return out

    m = re.match(r'UnusableReason "([^"]*)" ', payload)
    if m:
        out["reason_loc"] = m.group(1)
        rest = payload[m.end() :]
    else:
        rest = payload
    ctor = re.match(r"\(?(\w+)", rest)
    out["reason_ctor"] = ctor.group(1) if ctor else "?"

    # The parse-error text is a shown String; unescape it before matching.
    key = 'macroParseError = "'
    j = rest.find(key)
    if j >= 0:
        msg = haskell_string_at(rest, j + len(key) - 1)
        out["message"] = " ".join(msg.split())
        m = UNEXPECTED_RAW.search(msg) or UNEXPECTED_PRETTY.search(msg)
        if m:
            out["unexpected"] = m.group(1)
        else:
            m = UNEXPECTED_ANY.search(msg)
            if m:
                out["unexpected"] = m.group(1).splitlines()[0].strip()
        p = ERR_POS.search(msg)
        if p:
            out["err_line"], out["err_col"] = p.group(1), p.group(2)
    else:
        # Typecheck / resolution failures: keep a compacted head of the payload.
        out["message"] = " ".join(rest.split())[:400]
    return out


def verdicts(dump):
    idx = sections(dump)["declIndex"]
    rows = []
    for m in ENTRY.finditer(idx):
        name, kind, is_anon, usable = m.groups()
        row = {
            "name": name,
            "kind": kind,
            "is_anon": is_anon,
            "usable": "yes" if usable == "Usable" else "no",
            "reason_loc": "",
            "reason_ctor": "",
            "unexpected": "",
            "err_line": "",
            "err_col": "",
            "message": "",
        }
        if usable == "Unusable":
            open_at = idx.index("(", m.end() - 1)
            row.update(classify_reason(balanced(idx, open_at)))
        rows.append(row)
    return rows


def selected(dump):
    """Names of declarations present in the `decls` list (i.e. selected)."""
    sec = sections(dump)["decls"]
    names = []
    for chunk in sec.split("Decl {info = DeclInfo {loc = ")[1:]:
        m = DECL_ID.search(chunk)
        if m:
            names.append(m.group(1))
    return names


def deps(dump):
    """Edges (user, used) from `useDeclGraph`."""
    sec = sections(dump)["useDeclGraph"]
    edges = []
    for m in re.finditer(r"\(" + DECL_ID_PAT + r",", sec):
        src = m.group(1)
        body = balanced(sec, m.end() - 1, "([{", ")]}")
        for tgt, _kind, _anon in DECL_ID.findall(body):
            if tgt != src:
                edges.append((src, tgt))
    return edges


def main():
    mode, path = sys.argv[1], sys.argv[2]
    dump = open(path).read()
    if mode == "verdicts":
        rows = verdicts(dump)
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        print(f"# {len(rows)} entries", file=sys.stderr)
    elif mode == "selected":
        names = selected(dump)
        for n in sorted(set(names)):
            print(n)
        print(f"# {len(set(names))} selected", file=sys.stderr)
    elif mode == "deps":
        w = csv.writer(sys.stdout)
        w.writerow(["user", "used"])
        w.writerows(sorted(set(deps(dump))))
    else:
        sys.exit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
