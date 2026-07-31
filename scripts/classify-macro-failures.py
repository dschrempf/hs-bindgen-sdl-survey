#!/usr/bin/env python3
"""Assign a root cause to each unusable SDL3 macro.

Usage: classify-macro-failures.py OUTDIR
Reads OUTDIR/{verdicts.csv,defs.json,selected-all.txt}, writes classified CSV to
stdout and a ranked summary to stderr.

Every macro clang saw is classified, not just SDL's, so that a cascade chain can
be followed through a libc macro (SDL_SINT64_C -> INT64_C -> token paste). Only
the SDL-defined subset is reported in the summary.

Attribution follows the survey's rule, extended by one case the data forced:
the parser's error token is informative *unless* it is `(` (the position is the
failing production's start) *or* the callee identifier of a call whose argument
list failed to parse. In both cases we fall back to body inspection, taking the
earliest unsupported construct in token order — the parser consumes greedily
left to right, so that is the construct it actually choked on.

Cascade is separated from primary here rather than read off the DeclIndex:
`UnusableReason` has no dependency constructor, so a macro that fails only
because a macro it references is broken shows up as its own typecheck failure
("Unbound variable: 'X'"). Those are cascade, not primary.
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict


# --- body markers, in no particular order; position in the body decides ------
#
# Each entry is (cause, regex). Matching is done on a body with string and
# character literals blanked out, so punctuation inside them cannot match.

TYPE_WORD = (
    r"(?:unsigned|signed|int|char|short|long|float|double|void|_Bool|bool"
    r"|[US]int(?:8|16|32|64)|size_t|\w+_t"
    r"|SDL_[A-Z]\w*)"
)

MARKERS = [
    ("stringification", r"(?<!#)#(?!#)"),
    ("token-paste", r"##"),
    ("statement-expression", r"\(\s*\{"),
    ("do-while", r"\bdo\b"),
    ("compound-statement-body", r"^\s*\{"),
    ("inline-asm", r"\b__asm__\b|\b__asm\b"),
    ("attribute", r"\b__attribute__\b"),
    ("_Generic", r"\b_Generic\b"),
    ("_Static_assert", r"\b_Static_assert\b"),
    ("sizeof", r"\bsizeof\b"),
    ("alignof", r"\b_Alignof\b|\balignof\b"),
    ("offsetof", r"\boffsetof\b|\b__builtin_offsetof\b"),
    ("conditional-?:", r"\?"),
    # A cast is `(TYPE)` or `(TYPE *)` immediately followed by an operand.
    ("cast", r"\(\s*(?:const\s+)?" + TYPE_WORD + r"(?:\s+\w+)*\s*\**\s*\)\s*[\(\w&*+\-!~]"),
    ("compound-literal", r"\)\s*\{"),
    ("designated-initialiser", r"\.\s*\w+\s*="),
    ("member-access-arrow", r"->"),
    ("member-access-dot", r"[\w\)]\s*\.\s*[A-Za-z_]"),
    ("array-subscript", r"\["),
    # Unary &/*: preceded by an operator or start, and not part of &&/*/ etc.
    ("address-of", r"(?:^|[\(,=+\-/%<>!|^~?:])\s*&(?!&)\s*[\(\w]"),
    ("dereference", r"(?:^|[\(,=+\-/%<>!|^~?:])\s*\*\s*[\(\w]"),
    ("assignment", r"(?<![=!<>+\-*/%&|^])=(?!=)"),
    ("increment-decrement", r"\+\+|--"),
    ("string-concatenation", r'@\s+@|@\s+\w|\w\s+@'),  # @ = blanked string literal
    ("comment-token", r"/\*|//"),
]
MARKERS = [(c, re.compile(p, re.M)) for c, p in MARKERS]

# Error tokens that name the construct directly.
TOKEN_CAUSE = {
    "#": "stringification",
    "##": "token-paste",
    "do": "do-while",
    "{": "compound-statement-body",
    "?": "conditional-?:",
    "sizeof": "sizeof",
    "_Alignof": "alignof",
    "_Generic": "_Generic",
    "_Static_assert": "_Static_assert",
    "__attribute__": "attribute",
    "__builtin_offsetof": "offsetof",
    "...": "variadic-parameter-list",
}
C_KEYWORDS = {
    "signed", "unsigned", "int", "char", "short", "long", "float", "double",
    "void", "const", "volatile", "static", "struct", "union", "enum", "return",
    "if", "else", "while", "for", "switch", "case", "default", "break",
    "continue", "sizeof", "typedef", "extern", "register", "auto", "inline",
    "restrict", "_Bool", "bool", "goto",
}

BUILTIN = re.compile(r"^(?:__builtin_|__atomic_|__sync_|__has_|__asm)")
# Compiler-predefined macros: no #define exists for the frontend to see.
PREDEFINED = {
    "__LINE__", "__FILE__", "__FILE_NAME__", "__DATE__", "__TIME__",
    "__func__", "__FUNCTION__", "__COUNTER__", "__BASE_FILE__",
}
KEYWORD_BODY = {"__func__", "__inline__", "__inline", "__restrict", "__volatile__"}


def blank_literals(body):
    """Replace string literals with `@` and char literals with `$`."""
    body = re.sub(r'"(?:[^"\\]|\\.)*"', "@", body)
    body = re.sub(r"'(?:[^'\\]|\\.)*'", "$", body)
    return body


def body_cause(body, params):
    """(root cause, also_contains) from body inspection; earliest match wins."""
    if "..." in params:
        return "variadic-parameter-list", []
    param_names = [p for p in re.findall(r"\w+", params)]
    for p in param_names:
        if p in C_KEYWORDS:
            return "keyword-as-parameter-name", []
    if not body.strip():
        return "empty-body", []
    b = blank_literals(body)
    hits = []
    for cause, pat in MARKERS:
        m = pat.search(b)
        if m:
            hits.append((m.start(), cause))
    # A cast whose target is a macro parameter, e.g. SDL_static_cast's
    # ((type)(expression)). No Haskell function has that type: it needs a C
    # wrapper per instantiation, so keep it distinct from a concrete cast.
    #
    # The operand must start with `(` or a word character. Allowing &, *, +, -
    # would misread `(cspace) & 0x1F` and `(S)->flags` as casts.
    for p in param_names:
        m = re.search(r"\(\s*" + re.escape(p) + r"\s*\**\s*\)\s*[\(\w]", b)
        if m:
            hits.append((m.start(), "cast-to-parameter-type"))
    # A type expression passed as a call argument, e.g.
    # SDL_reinterpret_cast(Uint16 *, x). Same "needs a C wrapper" class.
    m = re.search(r"\w+\s*\(\s*(?:const\s+)?" + TYPE_WORD + r"\s*\*+\s*,", b)
    if m:
        hits.append((m.start(), "type-as-call-argument"))
    if not hits:
        return "unclassified", []
    hits.sort()
    return hits[0][1], sorted({c for _, c in hits[1:]})


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sdl3-survey"
    rows = list(csv.DictReader(open(f"{out_dir}/verdicts.csv")))
    defs = json.load(open(f"{out_dir}/defs.json"))
    selected = set(open(f"{out_dir}/selected-all.txt").read().split())

    # Classify every macro clang saw, so cascade chains can be followed through
    # libc macros; the summary is restricted to the SDL-defined subset.
    macros = [r for r in rows if r["kind"] == "NameKindMacro" and r["name"] in defs]
    by_name = {r["name"]: r for r in macros}

    out = []
    for r in macros:
        d = defs[r["name"]]
        body, params = d.get("body", ""), d.get("params", "")
        rec = {
            "name": r["name"],
            "in_sdl": "yes" if d["in_sdl"] else "no",
            "funclike": "yes" if d["funclike"] else "no",
            "header": (d["file"] or "?").rsplit("/", 1)[-1],
            "usable": r["usable"],
            "selected": "yes" if r["name"] in selected else "no",
            "stage": "",
            "cause": "",
            "also_contains": "",
            "depends_on": "",
            "unexpected": r["unexpected"],
            "body": body,
        }
        if r["usable"] == "yes":
            # A usable declaration that selection dropped is a cascade drop:
            # program slicing removed it because a dependency is unusable.
            rec["stage"] = "bound" if rec["selected"] == "yes" else "deselected"
            rec["cause"] = "-" if rec["selected"] == "yes" else "deselected-cascade"
            out.append(rec)
            continue

        ctor = r["reason_ctor"]
        msg = r["message"]

        if ctor == "UnusableParseFailure":
            rec["stage"] = "parse"
            tok = r["unexpected"]
            # A comment between the parameter list and the body reaches the
            # parser as a CXToken_Comment with no rule to skip it. `clang -dM`
            # strips comments, so only the error token reveals this.
            if tok.startswith("/*") or tok.startswith("//"):
                rec["cause"] = "comment-token"
                _, also = body_cause(body, params)
                rec["also_contains"] = ";".join(also)
            elif tok in TOKEN_CAUSE:
                rec["cause"] = TOKEN_CAUSE[tok]
                _, also = body_cause(body, params)
                rec["also_contains"] = ";".join(also)
            elif tok in C_KEYWORDS:
                rec["cause"] = "keyword-as-parameter-name" if tok in params else "cast"
            else:
                # `(` or a callee identifier: uninformative, inspect the body.
                cause, also = body_cause(body, params)
                rec["cause"] = cause
                rec["also_contains"] = ";".join(also)

        elif ctor == "UnusableMacroResolutionFailure":
            rec["stage"] = "resolve"
            m = re.search(r'bare identifier \\"(.*?)\\" not found', msg)
            ident = m.group(1) if m else ""
            rec["depends_on"] = ident
            # SDL_oldnames.h defines each SDL2 name to a `X_renamed_Y` sentinel
            # that deliberately does not exist, so that using the old name is a
            # compile error naming its replacement. Not a binding gap.
            if re.search(r"_(?:renamed|deprecated)_", ident):
                rec["cause"] = "sdl2-compat-sentinel"
            elif not body.strip():
                rec["cause"] = "empty-body"
            elif ident in PREDEFINED:
                rec["cause"] = "predefined-macro"
            elif BUILTIN.match(ident):
                rec["cause"] = "clang-builtin"
            elif ident in KEYWORD_BODY or body.strip() in KEYWORD_BODY:
                rec["cause"] = "keyword-body"
            elif ident in by_name:
                rec["cause"] = "cascade"
            elif re.match(r"^SDL_[A-Z0-9_]+$", ident):
                rec["cause"] = "enum-constant"
            elif re.search(r"\b__attribute__\b", body) or "ANNOTATION_ATTRIBUTE" in body:
                rec["cause"] = "attribute-argument-name"
            elif ident in re.findall(r"\w+", params):
                rec["cause"] = "empty-body"
            else:
                rec["cause"] = "undeclared-identifier"

        elif ctor == "UnusableMacroTypecheckFailure":
            rec["stage"] = "typecheck"
            m = re.search(r"Unbound variable: '(\w+)'", msg)
            if m:
                rec["depends_on"] = m.group(1)
                rec["cause"] = "cascade" if m.group(1) in by_name else "undeclared-identifier"
            elif "Unsupported type-like macro expression" in msg:
                rec["cause"] = "type-macro-with-parameters"
            elif "Could not unify" in msg:
                # A call whose callee is a real C function/inline function.
                callee = re.match(r"\s*(\w+)\s*\(", body)
                if callee and callee.group(1) in by_name:
                    rec["cause"] = "cascade"
                    rec["depends_on"] = callee.group(1)
                elif callee:
                    rec["cause"] = "calls-c-function"
                    rec["depends_on"] = callee.group(1)
                else:
                    rec["cause"] = "typecheck-other"
            else:
                rec["cause"] = "typecheck-other"

        elif ctor == "UnusableConflict":
            rec["stage"] = "conflict"
            rec["cause"] = "name-conflict"
        else:
            rec["stage"] = ctor
            rec["cause"] = "other"
        out.append(rec)

    # Resolve cascade chains to the ultimate root, for the "unlocked per fix"
    # estimate. `depends_on` may itself be broken.
    cause_of = {r["name"]: r["cause"] for r in out}
    dep_of = {r["name"]: r["depends_on"] for r in out}

    def root(name, seen=()):
        if name in seen:
            return "cyclic"
        c = cause_of.get(name)
        if c == "cascade":
            d = dep_of.get(name)
            if d in cause_of:
                return root(d, seen + (name,))
            return "cascade-unknown"
        return c

    for r in out:
        r["root_cause"] = root(r["name"]) if r["cause"] == "cascade" else r["cause"]

    sdl = [r for r in out if r["in_sdl"] == "yes"]
    w = csv.DictWriter(sys.stdout, fieldnames=list(out[0].keys()))
    w.writeheader()
    w.writerows(sorted(sdl, key=lambda r: (r["funclike"] != "yes", r["name"])))

    # Every macro, SDL or not, so that rank-macro-fixes.py can follow a cascade
    # chain out through libc and back.
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", newline="") as fh:
            wa = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
            wa.writeheader()
            wa.writerows(sorted(out, key=lambda r: r["name"]))

    def report(label, subset):
        bound = [r for r in subset if r["stage"] == "bound"]
        desel = [r for r in subset if r["stage"] == "deselected"]
        bad = [r for r in subset if r["usable"] == "no"]
        casc = [r for r in bad if r["cause"] == "cascade"]
        prim = [r for r in bad if r["cause"] != "cascade"]
        p = lambda *a: print(*a, file=sys.stderr)
        p(f"\n=== {label}: {len(subset)} ===")
        p(f"  bound                    {len(bound)}")
        p(f"  dropped, cascade         {len(casc) + len(desel)}"
          f"   ({len(casc)} via broken dependency, {len(desel)} deselected)")
        p(f"  dropped, primary         {len(prim)}")
        p(f"  RECONCILE {len(subset)} - {len(bound)} - {len(casc)+len(desel)} - {len(prim)}"
          f" = {len(subset)-len(bound)-len(casc)-len(desel)-len(prim)}")
        p(f"  {'root cause':30} {'primary':>8} {'+cascade':>9} {'unlocked':>9}")
        by_root = Counter(r["root_cause"] for r in bad)
        by_prim = Counter(r["cause"] for r in bad)
        for c, n in by_root.most_common():
            if c == "cascade":
                continue
            p(f"  {c:30} {by_prim.get(c,0):8} {n-by_prim.get(c,0):9} {n:9}")

    report("function-like, SDL", [r for r in sdl if r["funclike"] == "yes"])
    report("object-like, SDL", [r for r in sdl if r["funclike"] != "yes"])
    report("all SDL macros", sdl)


if __name__ == "__main__":
    main()
