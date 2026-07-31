# Survey macro support against real SDL3 headers

> Historical: this is the plan as written inside the `hs-bindgen` working copy,
> kept verbatim as the record of what the run was asked to do. Its paths
> (`~/work/c-expr`, `~/work/misc/SDL`, `.ai/scripts/…`) are the original ones;
> the executed survey now lives in this repository — see `README.md`.

**Goal.** Replace hand-written probe results with a measured, reproducible
inventory of which SDL3 macros `hs-bindgen` binds, which it drops, and *why* —
classified by C construct, ranked by impact. Feeds the reply to the
[sdl3-bindgen-sys](https://github.com/jtnuttall/lithon/tree/main/sdl3-bindgen-sys#what-is-not-bound)
report and gives us a prioritised `c-expr-dsl` feature list.

**Non-goal.** Fixing anything. This step only measures.

## Scope

**In scope** — collecting facts, and only the code needed to collect them:

- reading the `c-expr` grammar to produce the accepted/rejected table (Part A)
- running `hs-bindgen` over SDL3 and tabulating outcomes (Part B)
- the survey driver script, the minimal probe header, and a throwaway use-site
  module for the usability check (B6)
- *optionally*, a per-macro JSON dump subcommand if the `Show` output proves too
  awkward to parse (B2) — instrumentation, not a fix

**Out of scope** — every grammar gap, ergonomic wart, and correctness bug the
survey turns up, including the comma-operator bug. Write them down, rank them, stop.
Each becomes its own piece of work afterwards. The "Where fixes land" section below
is guidance for *those* follow-ups, not a licence to start them here.

Resist in particular the temptation to fix a cheap-looking gap (`?:` is the likely
bait) mid-survey: it would invalidate the numbers already collected and force a
re-run.

## Local checkouts (verified 2026-07-31)

| What | Path | State |
|---|---|---|
| `c-expr` (we develop this) | `~/work/c-expr` | branch `main` @ `5bbc29d`, clean; packages `c-expr-dsl`, `c-expr-runtime` |
| SDL3 | `~/work/misc/SDL` | branch `main` @ `09552d5be` = `release-3.4.0-1231-g09552d5be`; headers in `include/SDL3` |
| `hs-bindgen` | `~/work/hs-bindgen` | this repo |

Nothing to clone. Two verified facts that save time:

- `clang -E -I include -x c include/SDL3/SDL.h` **succeeds (exit 0)** straight from
  the SDL source checkout — `include/SDL3/SDL_revision.h` is present, so no cmake
  configure step is needed to generate headers.
- Scale calibration: `clang -E -dM` yields **2956** defines total, of which
  **1642** are `SDL_`-prefixed and **160** are `SDL_`-prefixed *function-like*. So
  the headline claim concerns ~160 macros — small enough that the per-macro
  appendix can be audited by hand, and any automation can be checked against a
  manual spot-sample.

  The `SDL_` prefix is a *heuristic* filter, not the real one: some SDL macros are
  not so prefixed (`SDLCALL`, `SDLK_*`) and `-dM` also reports libc and clang
  builtins. Use **definition site inside `~/work/misc/SDL/include`** as the actual
  filter — B2's frontend dump gives definition sites, so cross-check the two counts
  and treat a large gap as its own finding (macros the frontend never attempted).

- **Decided:** measure against SDL `main` as checked out, `09552d5be`
  (`release-3.4.0-1231-g09552d5be`). Record that SHA in the report — it is not a
  tag, so the report is only reproducible against the SHA. Treat the SDL checkout
  as read-only.

## Where fixes land

**Macro parsing and typechecking is `c-expr`'s job. Fixes go into `~/work/c-expr`,
never as a workaround in `hs-bindgen`.**

Worked example — the comma-operator bug (issue #2182): the wrong Haskell tuple is
emitted by `hs-bindgen/src/HsBindgen/Internal/Macro/CExpr/Translation/Value.hs`
(lines 260, 125), but only because `c-expr-dsl` hands it a `CExpr.MTuple` /
`CExpr.TupleTyCon` node in the first place. The fix is in `c-expr`; `hs-bindgen`'s
translation then simply loses a case. Special-casing it downstream would leave the
wrong node in the typechecked AST for every other consumer. Do not do that — and
do not fix it in this step at all (see "Note on the comma operator").

Regression fixtures for anything found here belong in `c-expr`'s own test suite:
extract the failing SDL macro **bodies as text fixtures**, so the tests need
neither SDL nor libclang AST traversal.

## Workspace setup

`c-expr-dsl` / `c-expr-runtime` / `libclang-bindings` / `doxygen-parser` are plain
**Hackage dependencies** of this repo — there are no `source-repository-package`
stanzas in any `cabal.project*`. (CLAUDE.md claims they are pinned in
`cabal.project.base`; that is stale and worth fixing separately.)

Since fixes land in `c-expr` and we want to re-measure after each one, point
`hs-bindgen` at the working copy up front — `cabal.project.local`:

```cabal
packages:
  ~/work/c-expr/c-expr-dsl
  ~/work/c-expr/c-expr-runtime
```

Confirm it took effect (`cabal build --dry-run` should show them as local, not
Hackage) before trusting any measurement, otherwise you will be surveying the
released grammar while editing a different one.

---

# Part A — grammar audit (in `~/work/c-expr`)

Two different questions, two different repos. **A is cheap, exhaustive, needs
neither SDL nor the pipeline, and produces the taxonomy B classifies against — do
it first.**

Read the grammar in `~/work/c-expr/c-expr-dsl` (`C.Expr.Parse`,
`C.Expr.Parse.Expr`; entry point `parseMacro :: ClangCStandard -> Parser Macro`)
and produce the definitive list of accepted and rejected constructs, **citing the
source location that decides each**. This replaces probe-based inference: the
grammar is ground truth, probing is sampling.

Cover at least: conditional `?:` · cast expressions · `sizeof` / `alignof` /
`offsetof` · `#` stringification · `##` token paste · function call · assignment
and compound assignment · statement expression `({ … })` · `do { … } while(0)` ·
comma operator · type in parameter position · compound literal · designated
initialiser · member access `.` / `->` · array subscript · address-of ·
dereference · `_Generic` · `__VA_ARGS__` · string literal concatenation ·
`__attribute__` / `__builtin_*`.

For each: accepted / rejected, and if rejected whether it is *cheap*, *expensive*,
or *impossible* in the current type-level scheme. The boundary cases that matter:

- **cheap** — `?:` (result type is the usual arithmetic conversions, same shape as
  `Add`/`AddRes`); a cast to a *concrete* type (known target).
- **impossible** — a macro parameter used in type position
  (`SDL_static_cast(type, expr)`); no Haskell function has that type, so it needs a
  C wrapper per instantiation. This is the honest boundary between "grammar gap"
  and "genuinely needs `capi`", and the reply depends on stating it precisely.

Also check `c-expr`'s existing test suite for which of these already have negative
tests — gaps there indicate where a fix could regress silently.

---

# Part B — SDL3 sweep (in `~/work/hs-bindgen`)

Needs the whole pipeline, and most deliverables live downstream of `c-expr`:
cascade counts (Select), bound-but-unusable signatures (Backend +
`c-expr-runtime`), diagnostics visibility (trace levels). Do **not** try to run B
from `c-expr`: macro discovery from real headers — libclang traversal,
`PrepareReparse` token preprocessing, and the ordered environment `tcMacros`
accumulates as it batch-checks macros — belongs to `hs-bindgen`'s Parse /
ConstructTranslationUnit / TypecheckMacros passes. Reimplementing that in a
`c-expr` harness would risk diverging silently from what users actually get, and
measuring what users get is the entire point.

## B0. Preliminaries

Record in the report header: SDL SHA, `c-expr` SHA, `hs-bindgen` commit, clang
version, GHC version — plus whether `cabal.project.local` was in force. The
numbers are meaningless without these.

Keep the driver under `.ai/scripts/sdl3-macro-survey.sh` (or `.py`) so the run is
repeatable, not a shell-history artefact.

## B1. Establish the denominator

Needed *before* asking what hs-bindgen did, else "not bound" conflates *rejected*
with *never seen*:

```
clang -E -dM -I ~/work/misc/SDL/include -x c ~/work/misc/SDL/include/SDL3/SDL.h
```

Split into function-like (the subject of the community claim), object-like value,
and type macros. Filter by definition site, not by name prefix (see above).

## B2. Instrument: use the frontend dump, not the warning log

`internal frontend --pass typecheck-macros` emits a `DeclIndex` with a per-macro
verdict *and* the dependency graphs — everything the survey needs, structured:

```
cabal run hs-bindgen-cli -- internal frontend --pass typecheck-macros \
  -I ~/work/misc/SDL/include ~/work/misc/SDL/include/SDL3/SDL.h > /tmp/sdl3-frontend.txt
```

```haskell
-- per-macro verdict
(DeclId "P_TERN" …, UnusableEntry (UnusableReason "…3:9"
   (UnusableParseFailure (ParseMacroErrorParse (MacroParseError {…})))))
(DeclId "P_PARENS" …, UsableEntry (UsableSuccess …))
-- plus, in the same dump:
useDeclGraph = UseDeclGraph {…}   declUseGraph = DeclUseGraph {…}
```

This beats grepping `[select-parse-macro]` warnings: complete, structured
`UnusableReason`, and the graphs give the cascade computation directly instead of
re-deriving dependencies from text. It is Haskell `Show` output, so parsing is
mildly annoying — if the shape fights back, add a small `internal` subcommand
emitting per-macro outcomes as JSON. That tool is reusable and probably cheaper
than a brittle parser.

Then generate bindings for the bound-set and usability checks (B5):

```
cabal run hs-bindgen-cli -- \
  --log-enable-macro-warnings -v 3 \
  preprocess -I ~/work/misc/SDL/include --select-all --module SDL3 \
    --hs-output-dir /tmp/sdl3-out --create-output-dirs --overwrite-files \
    ~/work/misc/SDL/include/SDL3/SDL.h  2>&1 | tee /tmp/sdl3-out/diagnostics.log
```

`--log-enable-macro-warnings` is required — macro failures log at `info`, invisible
at default verbosity (see B6). `--select-all` stops the default main-header
selection quietly shrinking the denominator; also do a
`--select-from-main-headers` run to see what a normal user gets. Run with and
without `--enable-program-slicing` if counts differ.

## B3. Partition

| Set | Source |
|---|---|
| **bound** | `UsableEntry` in the `DeclIndex`, cross-checked against generated export lists |
| **dropped, primary** | `UnusableParseFailure` / typecheck failure with its own `UnusableReason` |
| **dropped, cascade** | unusable *because* a dependency is unusable — walk `UseDeclGraph` |

Keeping cascade separate from primary is the single most important methodological
point. One missing primitive inflates the count dramatically: `SDL_static_cast`
fails to parse, and everything built on it (`SDL_FOURCC`, the `SDL_PIXELFORMAT`
family, …) dies as collateral. A headline number mixing the two overstates the work
and understates the leverage of one fix.

Reconcile: `denominator − bound − dropped` must be zero. Any residue is macros
neither bound nor reported — a bug in its own right.

## B4. Classify primary failures

Assign each to exactly one *root* cause from Part A's taxonomy (the outermost
construct the grammar cannot accept).

**Attribution rule.** The parser's error token is reliable *only when it is not*
`(`. Observed:

- `P_TERN` → `unexpected "?"` — the true culprit.
- `P_SIZEOF` → `unexpected "sizeof"` — the true culprit.
- `P_TERN_P` (`((x) < (y) ? (x) : (y))`) → `unexpected "("` at the body start —
  uninformative, because the position is the failing production's start, not the
  offending token.

Use the error token when informative; fall back to body inspection when it is `(`;
confirm each *class* with a minimal probe header plus a control differing only in
the construct under test. The control matters: `((int)(x))` failing looks like a
paren problem until `((x) + 1)` is shown to succeed.

Where a body contains several unsupported constructs, record the root cause but
keep an `also_contains` column — it changes the "macros unlocked per fix" estimate.

Since Part A gives the grammar's rejection set, anything failing in B that Part A
does *not* explain is either a typecheck-level failure or an `hs-bindgen`-level
one — a useful sorting criterion, and worth calling out separately.

## B5. Rank by impact

Per cause: primary count; **cascade count** (macros unlocked if this one cause is
fixed, over `UseDeclGraph`); whether affected macros are user-facing SDL API or
internal plumbing; and Part A's cheap/expensive/impossible verdict.

The API/plumbing split matters: `SDL_min`/`SDL_max`/`SDL_clamp` and the
`SDL_PIXELFORMAT` predicates are things users reach for; `SDL_COMPILE_TIME_ASSERT`
is not. A count treating these as equal mis-prioritises.

## B6. Check that *bound* ≠ *usable*

Appearing in an export list is not evidence of working.

1. **Does the generated code compile?** Build `/tmp/sdl3-out` with GHC against
   `hs-bindgen-runtime` + `c-expr-runtime`. Report failures.
2. **Is each bound macro callable at a concrete type?** The signatures carry large
   constraint contexts:

   ```haskell
   sDL_VERSIONNUM :: forall a0 b1 c2.
     ( Add (MultRes a0 CInt) (MultRes b1 CInt)
     , Add (AddRes (MultRes a0 CInt) (MultRes b1 CInt)) c2
     , Mult b1 CInt, Mult a0 CInt )
     => a0 -> b1 -> c2 -> AddRes (AddRes (MultRes a0 CInt) (MultRes b1 CInt)) c2
   ```

   Write a use-site module calling 10–20 representative macros (arithmetic, shift,
   bitwise, relational, logical) at `CInt`, `Uint32`, `CUInt`. Record ambiguity
   errors, defaulting failures, and cases needing an annotation at every call site.

If bound-but-awkward is common, it belongs in the reply as prominently as the
unbound list — it is plausibly the *actual* reason a user concluded macros "aren't
bound". Any ergonomic fix here is also `c-expr`(-runtime) territory, not a
`hs-bindgen` patch.

## B7. Diagnostics visibility

Record as a first-class finding: by default the user gets **no indication** that N
macros were dropped or why. Quantify N for SDL3. This is the most likely root cause
of the report's incorrect rationale — the specific failures were silent, so a
blanket explanation got invented to fill the gap.

Follow-up (not this step, and this one *is* `hs-bindgen`'s): surface macro drops by
default, or emit a closing summary (`N macros not bound; use
--log-enable-macro-warnings`).

## B8. Deliverable

`.ai/2026-XX-XX-sdl3-macro-support.md`:

- environment/pin header (B0)
- headline counts: total, bound, dropped-primary, dropped-cascade; function-like
  vs object-like
- Part A grammar table, cross-referenced to `c-expr` source locations
- cause table (B4/B5) sorted by macros-unlocked-per-fix
- full per-macro CSV appendix so numbers are auditable
- the minimal probe header used for attribution, checked in
- B6 usability findings
- explicit platform scope: run on Linux, so macros gated on `_WIN32` / `__APPLE__`
  are excluded from the denominator rather than counted as failures

## Caveats to state in the report, not discover later

- One platform, one clang version, one SDL SHA.
- SDL wraps much of its API in `SDL_FORCE_INLINE` functions and
  `extern SDL_DECLSPEC` declarations. Distinguish "macro not bound" from "the
  functionality is reachable through a bound function anyway" — a dropped macro
  with a bound function equivalent is low priority regardless of cause.
- Do not extrapolate from SDL3 to "C headers in general" in the reply. SDL is
  unusually macro-heavy and unusually disciplined about it.

## Note on the comma operator

Comma-operator macros will surface as *apparently bound* (the frontend dump shows
`macroValueType = … a -> b -> Tuple2 a b`). They are mis-typed — see issue #2182
— and must not be counted as successes: put them in a separate
`bound, semantics suspect` bucket in the tally and move on. Do not investigate or
fix here; it is tracked separately, the fix is in `c-expr`, and mixing a
correctness bug into a coverage survey muddies both.

## What the final reply will need from this

1. The corrected rationale, stated without point-scoring: function-like macros are
   *translated to Haskell functions*, not imported, so linkable symbols are not the
   issue. Their observation was partly right; only the reason was wrong.
2. Real numbers for how many of SDL3's ~160 function-like macros bind today (their
   README implies zero).
3. The top three fixable grammar gaps, with cascade counts showing why they are
   worth doing.
4. The honest residue where a C wrapper genuinely is the only answer — so the
   `capi` suggestion is credited where it applies rather than dismissed.
5. The `--log-enable-macro-warnings` invocation, so they can see and report drops
   themselves in future.
