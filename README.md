# hs-bindgen SDL3 macro-support survey

A measurement-only survey of how many of SDL3's macros [`hs-bindgen`][hs-bindgen]
binds, and why the rest are dropped. Nothing is fixed here and no `hs-bindgen`,
`c-expr` or SDL source is modified: the survey only reads headers, runs the
`hs-bindgen` frontend over them, and classifies the verdict it gives each macro.

- [`report/2026-07-31-sdl3-macro-support-summary.md`](report/2026-07-31-sdl3-macro-support-summary.md)
  — start here (2 pages)
- [`report/2026-07-31-sdl3-macro-support.md`](report/2026-07-31-sdl3-macro-support.md)
  — full report: grammar audit, attribution method, ranking, usability, diagnostics
- [`report/2026-07-31-sdl3-macro-support-appendix.csv`](report/2026-07-31-sdl3-macro-support-appendix.csv)
  — all 1980 SDL macros with stage, root cause, dependency, error token and body
- [`plan/2026-07-31-sdl3-macro-support-survey.md`](plan/2026-07-31-sdl3-macro-support-survey.md)
  — the plan the run executed (paths in it refer to the original working copies)

Headline: of 1980 macros defined under `SDL/include`, 1099 bind (31 of the 160
function-like ones); 53 are dropped as cascades of another failure and 828 fail
in their own right — 594 of those being `SDL_oldnames.h` shims that are *meant*
to be unbindable. The most consequential finding is that bound ≠ usable: all 31
bound function-like macros reject the newtypes SDL's own API produces, because
the `c-expr-runtime` operator classes are not derived for them
([hs-bindgen#2184](https://github.com/well-typed/hs-bindgen/issues/2184)).

## Reproducing

```bash
./run-survey.sh                  # artefacts land in /tmp/sdl3-survey
OUT=~/sdl3-survey ./run-survey.sh
```

Needs `clang`, `python3`, and — unless you point `BINDGEN` at an installed
`hs-bindgen-cli` — `ghc` and `cabal`. The last step diffs the run's
`classified.csv` against the report's appendix, so a matching run says so
explicitly.

The survey has two external inputs, both used read-only, both resolved
automatically. `run-survey.sh` records what it picked in `$OUT/provenance.txt`.

| Input | Resolution order | Override |
|---|---|---|
| SDL headers | `$SDL`, cached clone at `SDL_SHA` | `SDL=/path/to/SDL` |
| `hs-bindgen-cli` | `$BINDGEN`, `$HS_BINDGEN`, sibling `../hs-bindgen`, `$PATH`, cached clone at `HS_BINDGEN_SHA` | `HS_BINDGEN=/path/to/hs-bindgen` or `BINDGEN='hs-bindgen-cli'` |

Clones go to `$CACHE` (`~/.cache/hs-bindgen-sdl-survey` by default) at the
revisions pinned in [`pins.env`](pins.env), which is the single source of truth
for what the report measured. A checkout at a different revision is used as
given, with a warning — the numbers then describe that revision, not the report's.

No `c-expr` checkout is needed: `hs-bindgen` depends on the released
`c-expr-dsl` / `c-expr-runtime` from Hackage. Set `CEXPR` to have a checkout's
revision recorded in the provenance, and add a `cabal.project.local` to the
`hs-bindgen` checkout to measure against it:

```cabal
packages: /path/to/c-expr/c-expr-dsl
          /path/to/c-expr/c-expr-runtime
```

### The B6 use-site check

Off by default because it compiles the 3.6 MB of generated bindings:

```bash
SURVEY_USE_SITE=1 ./run-survey.sh
SDL=/path/to/SDL ./use-site/run-use-site.sh /tmp/sdl3-survey   # after a survey run
```

It stages a cabal package in `$OUT/use-site` (the generated modules plus the two
hand-written ones) and builds it twice, at `-O0`: the generated code `#include`s
`SDL3/SDL.h`, hence the `SDL` variable.

`use-site/UseSite.hs` must compile and `use-site/UseSiteNewtype.hs` must *not* —
that second failure is the finding.

## Layout

```
run-survey.sh   driver: runs everything, writes $OUT
pins.env        pinned SDL / hs-bindgen / c-expr revisions and reference toolchain
lib/inputs.sh   resolves (and if need be clones) SDL and hs-bindgen-cli
scripts/        collect-macro-defs.py    clang -dM/-dD -> definition site, arity, body
                parse-frontend-dump.py   frontend Show dump -> verdicts / selected / deps
                classify-macro-failures.py  root-cause assignment per macro
                rank-macro-fixes.py      blocker-set modelling: macros unlocked per fix
                compare-selection.py     macros bound per selection mode
probe/          macro-grammar-probe.h    38 probes + 14 controls; the Part A anchor
use-site/       B6 harness (see above)
report/ plan/   the deliverables
```

Each script is standalone and reads only `$OUT`, so a step can be re-run against
an existing run without redoing the frontend dumps.

[hs-bindgen]: https://github.com/well-typed/hs-bindgen
