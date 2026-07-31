# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A **measurement-only** survey of how many SDL3 macros `hs-bindgen` binds and why
the rest are dropped. It contains no library code: a bash driver, five standalone
Python analysis scripts, a probe header, a use-site build harness, and the
reports those produce. SDL, `hs-bindgen` and `c-expr` are external inputs used
strictly read-only — nothing here fixes anything in them, by design
(`plan/…-survey.md` "Non-goal"; it explicitly warns against fixing a cheap gap
mid-survey, since that invalidates the collected numbers).

`report/` and `plan/` are the deliverables. Read
`report/2026-07-31-sdl3-macro-support-summary.md` first for the findings.

## Commands

```bash
./run-survey.sh                          # full run; artefacts in /tmp/sdl3-survey
OUT=~/sdl3-survey ./run-survey.sh        # elsewhere
SDL=/path/to/SDL HS_BINDGEN=/path/to/hs-bindgen ./run-survey.sh
BINDGEN='hs-bindgen-cli' ./run-survey.sh # use an installed CLI, skip cabal build

SURVEY_USE_SITE=1 ./run-survey.sh              # + B6 (slow: builds 3.6 MB of bindings)
SDL=/path/to/SDL ./use-site/run-use-site.sh /tmp/sdl3-survey   # B6 alone, after a run
```

Needs `clang`, `python3`, plus `ghc`/`cabal` unless `BINDGEN` points at an
installed CLI. `.envrc` uses the `ghc912-llvm21` flake from a sibling
`../hs-bindgen` checkout for the reference toolchain.

Every analysis script is standalone and reads only `$OUT`, so re-run a single
step against an existing run without redoing the expensive frontend dumps:

```bash
python3 scripts/classify-macro-failures.py /tmp/sdl3-survey /tmp/sdl3-survey/classified-all.csv
python3 scripts/rank-macro-fixes.py /tmp/sdl3-survey --funclike
```

### The test

There is no test suite. The check is the last step of `run-survey.sh`: it diffs
the run's `$OUT/classified.csv` against
`report/2026-07-31-sdl3-macro-support-appendix.csv`. They are the *same file*, so
a matching run reproduces the report byte for byte; a diff means a pin, clang or
`c-expr-dsl` version moved — consult `$OUT/provenance.txt`.

The second check is B6, where **`use-site/UseSiteNewtype.hs` failing to compile
is the expected outcome** (three `No instance for Bitwise …` errors). Its
compiling would mean the report's headline finding no longer reproduces.

## Architecture

### Data pipeline

`run-survey.sh` is the single entry point; its steps are named after the plan's
sections (A, B0–B7). Each stage writes a file in `$OUT` that the next reads:

```
clang -E -dM/-dD  ──> dM.txt, dD.txt ──collect-macro-defs.py──> defs.json
                                            (denominator: 1980 macros in SDL/include)
hs-bindgen internal frontend --pass final ──> frontend-all.txt   (Haskell Show dump)
                              │ parse-frontend-dump.py
                              ├── verdicts       ──> verdicts.csv     (per-decl usable/why)
                              ├── selected       ──> selected-*.txt   (per selection mode)
                              └── deps           ──> deps.csv
classify-macro-failures.py ──> classified.csv (SDL only) + classified-all.csv (all macros)
rank-macro-fixes.py        ──> rank-funclike.txt, rank-all.txt
hs-bindgen preprocess      ──> hs/ (bindings) + preprocess-{default,verbose}.log  (B7)
use-site/run-use-site.sh   ──> use-site-{UseSite,UseSiteNewtype}.log             (B6)
```

`--select-all` is what the survey measures; `--select-from-main-headers` and
`--select-from-main-header-dirs` are run only so `compare-selection.py` can show
the counts do not depend on the selection mode.

### Semantics the parsing and classification depend on

These are non-obvious properties of the `hs-bindgen` frontend dump; changing them
changes the numbers:

- **Primary vs cascade.** `UnusableReason` has no "dependency is unusable"
  constructor, so every `UnusableEntry` in `declIndex` is a *primary* failure. A
  cascade drop is a decl that is `UsableEntry` yet absent from `decls` (program
  slicing removed it), or one whose own typecheck failure is
  `Unbound variable: 'X'` for a broken macro `X`. `classify-macro-failures.py`
  reconstructs that split; it cannot be read off the `DeclIndex`.
- **Entry keys in `declIndex`** are told apart from `DeclId`s nested in payloads
  only by being immediately followed by `Usable`/`UnusableEntry`.
- **The error token is not always the cause.** When it is `(` or a callee
  identifier, it marks the failing production's start, so classification falls
  back to body inspection, taking the *earliest* unsupported construct in token
  order (the parser consumes greedily left to right).
- **Non-SDL macros are classified too**, so a cascade chain can be followed out
  through libc (`SDL_SINT64_C → INT64_C → token paste`) and back. Only the
  SDL-defined subset is reported.
- **Blocker sets, not per-cause tallies.** Most failing bodies are blocked by
  several constructs, so `rank-macro-fixes.py` models each macro's full blocker
  set and reports macros unlocked *alone* and under a greedy cumulative fix set.
  Over-reporting a blocker makes estimates pessimistic, never optimistic — keep
  that direction if you touch the `MARKERS` regexes.

### Inputs and pins

`pins.env` is the single source of truth for what the report measured (SDL and
`hs-bindgen` SHAs, reference clang/GHC/`c-expr-dsl` versions). Changing a pin
makes the report a different measurement: re-run and update `report/` together.

`lib/inputs.sh` resolves the two external inputs, cloning into `$CACHE` when the
machine has neither (SDL sparsely, `include/` only). A checkout at an unpinned
revision is used as given with a warning, not an error. No `c-expr` checkout is
needed — `hs-bindgen` uses the Hackage `c-expr-dsl`/`c-expr-runtime`; `CEXPR` is
recorded in provenance only.

### The Part A probe

`probe/macro-grammar-probe.h` isolates one C construct per `P_*` macro, each
paired with a `C_*` control differing only in that construct. The controls are
what make an attribution valid: a failing probe with a passing control blames the
construct rather than its surroundings. It has no `#include`s so the frontend
dump contains nothing else.
