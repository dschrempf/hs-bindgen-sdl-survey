#!/usr/bin/env python3
"""How many SDL macros each selection mode binds.

Selection only filters what reaches the generated module; the `DeclIndex` verdict
that the survey measures is the same either way. This exists to show that the
reported counts do not depend on the selection mode.

Usage: compare-selection.py OUTDIR
"""

import csv
import json
import sys


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sdl3-survey"
    defs = json.load(open(f"{out}/defs.json"))
    rows = list(csv.DictReader(open(f"{out}/verdicts.csv")))
    usable = {r["name"] for r in rows if r["usable"] == "yes"}
    sdl = {n for n, v in defs.items() if v["in_sdl"]}
    funclike = {n for n in sdl if defs[n]["funclike"]}

    modes = [
        ("--select-all", "selected-all.txt"),
        ("--select-from-main-header-dirs", "selected-maindirs.txt"),
        ("--select-from-main-headers (DEFAULT)", "selected-main.txt"),
    ]
    print(f"{'selection mode':40}{'decls':>7}{'SDL macros':>12}{'func-like':>11}")
    for label, fn in modes:
        try:
            sel = set(open(f"{out}/{fn}").read().split())
        except FileNotFoundError:
            print(f"{label:40}{'(not run)':>7}")
            continue
        print(
            f"{label:40}{len(sel):7}"
            f"{len(sdl & usable & sel):12}{len(funclike & usable & sel):11}"
        )


if __name__ == "__main__":
    main()
