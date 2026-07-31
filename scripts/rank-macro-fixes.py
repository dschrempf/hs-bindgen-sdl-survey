#!/usr/bin/env python3
"""Rank root causes by how many SDL3 macros each fix would actually unlock.

A per-cause tally overstates leverage: most failing bodies are blocked by more
than one construct, so fixing one cause moves the macro from "fails at parse" to
"fails slightly later" rather than to "bound". This script instead models each
macro's *blocker set* and reports

  alone       macros unlocked by fixing this cause and nothing else
  cumulative  marginal unlock when the cause is added to a greedy fix set
  required-by macros for which this cause is necessary but not sufficient

A macro is unlocked by a fix set S iff every blocker is in S *and* every broken
macro it depends on is itself unlocked by S — so cascades are credited to the
fix that clears the root.

Usage: rank-macro-fixes.py OUTDIR [--funclike]
"""

import csv
import json
import sys
from collections import Counter


def load(out_dir):
    # classified-all.csv covers non-SDL macros too, so a cascade chain that
    # leaves the SDL set (SDL_SINT64_C -> INT64_C) can still be credited.
    rows = list(csv.DictReader(open(f"{out_dir}/classified-all.csv")))
    verdicts = {
        r["name"]: r for r in csv.DictReader(open(f"{out_dir}/verdicts.csv"))
    }
    return rows, verdicts


def blockers_of(r, functions):
    """The set of causes that must all be fixed before this macro can bind."""
    if r["usable"] == "yes":
        return set()
    stage, cause = r["stage"], r["cause"]
    bs = set()
    if stage == "parse":
        bs.add(r["root_cause"])
        bs |= {c for c in r["also_contains"].split(";") if c}
        # If the body is a call to a declared C function, a grammar fix only
        # moves the failure to the typechecker, which cannot apply a C function
        # type. Count that as a further blocker.
        head = r["body"].strip().split("(")[0].strip()
        if head in functions:
            bs.add("calls-c-function")
    elif cause != "cascade":
        bs.add(cause)
    return bs


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sdl3-survey"
    only_fl = "--funclike" in sys.argv
    rows, verdicts = load(out_dir)

    functions = {
        n for n, v in verdicts.items() if v["kind"] == "NameKindOrdinary"
    }
    by_name = {r["name"]: r for r in rows}
    sdl = [r for r in rows if r["in_sdl"] == "yes"]
    scope = [r for r in sdl if r["funclike"] == "yes"] if only_fl else sdl
    failing = [r for r in scope if r["usable"] == "no"]

    blockers = {r["name"]: blockers_of(r, functions) for r in rows}
    # Only a cascade row's `depends_on` names a broken macro that must itself be
    # unlocked. For resolve/typecheck rows it names the unresolvable entity,
    # which is the cause rather than a dependency.
    dep = {
        r["name"]: (r["depends_on"] if r["cause"] == "cascade" else "")
        for r in rows
    }

    def unlocked(name, S, seen=()):
        r = by_name.get(name)
        if r is None:
            return False  # referenced entity is not a macro we classified
        if r["usable"] == "yes":
            return True
        if name in seen:
            return False  # cyclic; treat as unresolvable
        bs = blockers[name]
        d = dep[name]
        if not bs and not d:
            return False  # cause unknown, so no fix set can be shown to help
        if not bs <= S:
            return False
        if d and d in by_name and by_name[d]["usable"] == "no":
            return unlocked(d, S, seen + (name,))
        if d and d not in by_name:
            return False
        return True

    def count(S):
        return sum(1 for r in failing if unlocked(r["name"], S))

    all_causes = sorted({c for r in scope for c in blockers[r["name"]]})

    alone = {c: count({c}) for c in all_causes}
    required = Counter()
    for r in failing:
        bs = blockers[r["name"]]
        if len(bs) > 1:
            for c in bs:
                required[c] += 1

    label = "function-like" if only_fl else "all"
    print(f"# {label} SDL macros: {len(scope)} total, {len(failing)} unusable\n")
    print(f"{'root cause':28}{'alone':>7}{'req-by':>8}")
    for c in sorted(all_causes, key=lambda c: (-alone[c], -required[c], c)):
        if alone[c] == 0 and required[c] == 0:
            continue
        print(f"{c:28}{alone[c]:7}{required[c]:8}")

    # Greedy cumulative: which fix set buys the most, in order.
    print(f"\n{'greedy cumulative fix set':46}{'bound':>7}{'delta':>7}")
    S, base = set(), count(set())
    prev = base
    print(f"{'(none)':46}{base:7}{'-':>7}")
    while True:
        best, gain = None, 0
        for c in all_causes:
            if c in S:
                continue
            g = count(S | {c}) - prev
            if g > gain:
                best, gain = c, g
        if best is None:
            break
        S.add(best)
        prev += gain
        print(f"{'+ ' + best:46}{prev:7}{gain:+7}")
    print(f"\nunreachable without further work: {len(failing) - prev}")


if __name__ == "__main__":
    main()
