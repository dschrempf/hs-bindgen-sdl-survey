#!/usr/bin/env python3
"""Collect every macro clang saw, with its definition site, arity and body.

`-dD` gives definition sites (via linemarkers) but keeps line continuations;
`-dM` gives each macro normalised onto one line but no site. We need both.

Usage: collect-macro-defs.py SDL_INCLUDE_DIR dM.txt dD.txt > defs.json
"""

import json
import re
import sys


def main():
    sdl_include, dm_path, dd_path = sys.argv[1], sys.argv[2], sys.argv[3]
    sdl_include = sdl_include.rstrip("/")

    # -dD: definition site, in source order, last definition wins.
    site = {}
    cur = None
    for line in open(dd_path):
        lm = re.match(r'# \d+ "([^"]*)"', line)
        if lm:
            cur = lm.group(1)
            continue
        d = re.match(r"#define (\w+)", line)
        if d:
            site[d.group(1)] = cur

    # -dM: normalised parameter list and body for macros live at end of TU.
    out = {}
    for line in open(dm_path):
        m = re.match(r"#define (\w+)(\([^)]*\))?\s*(.*)$", line.rstrip("\n"))
        if not m:
            continue
        name, params, body = m.group(1), m.group(2) or "", m.group(3)
        f = site.get(name)
        out[name] = {
            "file": f,
            "in_sdl": bool(f and f.startswith(sdl_include)),
            "funclike": params != "",
            "params": params,
            "body": body,
        }

    # Macros defined then #undef'd never reach -dM; record them so the
    # denominator reconciliation can account for them explicitly.
    for name, f in site.items():
        if name not in out:
            out[name] = {
                "file": f,
                "in_sdl": bool(f and f.startswith(sdl_include)),
                "funclike": None,
                "params": "",
                "body": "",
                "undefined_later": True,
            }

    json.dump(out, sys.stdout, indent=0, sort_keys=True)
    n_sdl = sum(1 for v in out.values() if v["in_sdl"])
    n_fl = sum(1 for v in out.values() if v["in_sdl"] and v["funclike"])
    print(f"# {len(out)} macros, {n_sdl} defined in SDL, {n_fl} function-like", file=sys.stderr)


if __name__ == "__main__":
    main()
