# SDL3 macro support: measured inventory

Executes `plan/2026-07-31-sdl3-macro-support-survey.md`. Measurement only —
nothing was fixed. Every number below is reproducible with
`run-survey.sh`.

## Environment (B0)

| What | Value |
|---|---|
| SDL | `09552d5beed674d6beb057481952244f652bb2c2` = `release-3.4.0-1231-g09552d5be`, clean |
| `c-expr` | `5bbc29d5a19edd38a501ca74897d6c49ab6284cd`, clean (= released `c-expr-dsl-0.1.0.1` / `c-expr-runtime-0.1.0.0` plus changelog stubs only) |
| `hs-bindgen` | `cf56afb3d922f766b924c75e0a5c0345f5e95960`, clean |
| clang | 21.1.8 |
| GHC / cabal | 9.12.3 / 3.16.1.0 |
| `cabal.project.local` | in force during the run, pointing at `~/work/c-expr/{c-expr-dsl,c-expr-runtime}`; confirmed via `plan.json` (`pkg-src type: local`). **Removed afterwards** |

The local `c-expr` checkout is byte-identical to the released library code, so
these numbers describe `c-expr-dsl-0.1.0.1` / `c-expr-runtime-0.1.0.0` as
published, and building against Hackage instead would give the same results. To
re-measure after a `c-expr` change, recreate:

```cabal
packages:
  /path/to/c-expr/c-expr-dsl
  /path/to/c-expr/c-expr-runtime
```

**Platform scope.** Linux, one clang version, one SDL SHA. Macros gated on
`_WIN32` / `__APPLE__` are never defined here, so they are absent from the
denominator rather than counted as failures. Do not extrapolate to "C headers in
general": SDL is unusually macro-heavy and unusually disciplined about it.

## Headline counts

Denominator = macros whose `#define` is inside the SDL checkout's `include/`
(definition site, not name prefix). 1980 such macros; 6 are `#undef`'d before the
end of the translation unit; 160 are function-like — and all 160 happen to be
`SDL_`-prefixed, so the prefix heuristic and the definition-site filter agree
exactly here.

| | total | bound | dropped, cascade | dropped, primary |
|---|---|---|---|---|
| **function-like** | 160 | **31** | 14 | 115 |
| object-like | 1820 | 1068 | 39 | 713 |
| all SDL macros | 1980 | 1099 | 53 | 828 |

`total − bound − cascade − primary = 0` in every row: all 1980 macros appear in
the frontend's `DeclIndex` with a verdict. No residue.

**Of the ~160 function-like macros the community report implies are unbound, 31
are bound today** — not zero. That said, see B6: none of the 31 can be applied to
the SDL types they exist to operate on, because the operator classes are not
derived for the generated newtypes (#2184).

### One number dominates the object-like column

594 of the 713 primary object-like failures are `SDL_oldnames.h` SDL2→SDL3
compatibility shims. Without `SDL_ENABLE_OLD_NAMES`, SDL defines each old name to
a sentinel that deliberately does not exist:

```c
#define AUDIO_F32  AUDIO_F32_renamed_SDL_AUDIO_F32LE
#define SDL_NumJoysticks SDL_NumJoysticks_deprecated_use_SDL_GetJoysticks
```

so that using the old name is a compile error naming its replacement. These are
*intended* to be unbindable. Excluding them, the object-like picture is 1068
bound / 119 primary failures — and the whole survey's real subject is 160
function-like + ~119 object-like macros, not 881 failures.

### How the survey was run

```
cabal run hs-bindgen-cli -- internal frontend --pass final \
  --unique-id sdl3 --select-all -I "$SDL/include" SDL3/SDL.h
```

All counts in this report come from the `--select-all` run over
`SDL3/SDL.h`. Selection only filters what reaches the generated module; it does
not affect whether a macro is *usable*, which is what the survey measures. The
`DeclIndex` verdict for all 1980 macros is therefore identical across selection
modes, and the bound counts are near-identical for the two modes that select SDL
declarations at all:

| selection | decls | SDL macros bound | function-like bound |
|---|---|---|---|
| `--select-all` | 3222 | 1099 | 31 |
| `--select-from-main-header-dirs` | 2703 | 1092 | 31 |

`--select-all` was chosen so that the denominator is not quietly reduced; it also
pulls in libc declarations, which is why the decl count is higher. Program
slicing made no difference to the macro counts: no usable SDL macro was
deselected in either mode.

---

## Part A — `c-expr-dsl` grammar audit

Read from source at `5bbc29d` and then verified empirically: every row below was
confirmed by running the frontend over `probe/macro-grammar-probe.h`, which
pairs each construct with a control differing only in that construct. All 14
controls bind; all 38 probes behave as the source says. Line references are
`c-expr-dsl/src/C/Expr/`.

The expression grammar is a `buildExpressionParser` table in `Parse/Expr.hs`,
`expr`, lines 453–498. It covers cppreference precedence levels 2–12 only. Level
1 is present but **empty** (`Parse/Expr.hs:455`), and levels 13–14 are absent
entirely. That single fact explains most rejections.

### Accepted

| Construct | Deciding location |
|---|---|
| integer / float / char / string literal (one token) | `Parse/Expr.hs:373–379` |
| identifier → `LocalParam` (macro parameter) or `Var` | `Parse/Expr.hs:363–371` |
| call `f(a,b)` where `f` is a *free* identifier | `Parse/Expr.hs:370–371`, `418–419` |
| parenthesised expression | `Parse/Expr.hs:448` |
| unary `+ - ! ~` | `Parse/Expr.hs:458–462` |
| `* / %`, `+ -`, `<< >>`, `< <= > >=`, `== !=`, `& ^ \| && \|\|` | `Parse/Expr.hs:465–497` |
| comma operator (parenthesised, body top level) | `Parse/Expr.hs:429–440` — **accepted but mis-typed**, see below |
| type: keyword bases, `const`, pointer layers, `struct`/`union`/`enum` tag, bare typedef name | `Parse/Expr.hs:161–177`, `225–230`, `239–247`, `332–339` |

### Rejected at parse

| Construct | Why | Deciding location | Cost |
|---|---|---|---|
| conditional `?:` | no level-13 entry; no `VaFun` constructor | `Parse/Expr.hs:453–498`; `Syntax/Expr.hs:119–165` | **cheap** |
| assignment, compound assignment | no level-14 entry | `Parse/Expr.hs:453–498` | n/a (statements) |
| member access `.` / `->`, subscript `[]`, postfix `++`/`--` | level-1 list is `[]` | `Parse/Expr.hs:455` | expensive (needs an lvalue/pointer story) |
| prefix `++`/`--`, unary `&`, unary `*` | absent from the `Prefix` entries | `Parse/Expr.hs:458–462` | expensive (same) |
| cast `(T)x` | no cast production | `Parse/Expr.hs:446–450` | **moderate** for concrete `T` |
| `sizeof`, `_Alignof`, `offsetof`, `_Generic`, `_Static_assert`, `__attribute__`, `__asm__`, `do`, and any other keyword in expression position | `parseIdentifier` requires `CXToken_Identifier` | `Parse/Identifier.hs:28` | expensive (`sizeof` needs layout + expression types) |
| `#` stringification, `##` token paste | no production | `Parse/Expr.hs:453–498` | expensive (symbol-level semantics) |
| statement expression `({…})`, compound literal `(T){…}`, designated initialiser, block body `{…}` | `{` has no production | `Parse/Expr.hs:446–450` | impossible as an expression |
| string literal concatenation `"a" "b"` | reads exactly one literal token | `Parse/Expr.hs:413–416`; `Parse/Literal.hs:426` | **cheap** (fold adjacent literals) |
| variadic parameter list `(...)` | `parseIdentifier \`sepBy\` comma`; `...` is punctuation | `Parse/Expr.hs:97–98` | cheap to *diagnose*, expensive to support |
| keyword as parameter name | same line | `Parse/Expr.hs:97–98` | cheap |
| comment token between parameter list and body | nothing skips `CXToken_Comment` | (no rule exists) | **cheap** — new finding, see below |
| empty function-like body | falls through to `objectLike` and reparses `(x)` as a variable reference | `Parse/Expr.hs:64` | **cheap** — new finding, see below |
| `_Pragma(…)` | explicitly rejected | `Parse/Expr.hs:88–95` | correct as-is |
| `long double` | `interpretKeywords` → `Nothing` | `Parse/Expr.hs:284–313` | moderate |

### Rejected after a successful parse

These are *not* grammar gaps, and the distinction matters for the reply:

| Construct | Stage | Message |
|---|---|---|
| call to a declared C function | typecheck | `Could not unify … Type` — the typechecker has no rule for applying a C function type |
| reference to an **enum constant** | resolve | `bare identifier "SDL_PIXELTYPE_INDEX1" not found` — enumerators are absent from the `DeclIndex` entirely; only the enum *type* is present |
| reference to a clang builtin (`__builtin_*`, `__atomic_*`, `__has_*`) | resolve | `bare identifier … not found` |
| reference to a compiler-predefined macro (`__LINE__`, `__FILE_NAME__`) | resolve | no `#define` exists for the frontend to see |
| identifier in `__attribute__((acquire_capability(x)))` argument position | resolve | the body is a declaration annotation, not an expression |
| type-like macro with parameters | typecheck | `Unsupported type-like macro expression with local parameters` |

### The honest "impossible" boundary

A macro **parameter used in type position** cannot be given a Haskell type:

```c
#define SDL_static_cast(type, expression) ((type)(expression))
#define SDL_stack_alloc(type, count)      (type*)alloca(sizeof(type)*(count))
```

and equivalently a *type expression passed as a macro argument*:

```c
#define SDL_iconv_utf8_ucs2(S) SDL_reinterpret_cast(Uint16 *, SDL_iconv_string(…))
```

No Haskell function has that type. A C wrapper per instantiation (`capi`) is the
only answer. This affects 6 + 3 = 9 function-like macros directly. Statement-shaped
bodies (`do { … } while(0)`, `({ … })`, `{ … }`, inline `__asm__`) are likewise
not expressions at all — 10 more.

### Two new findings from Part A

**Comment tokens are not skipped.** A `/* … */` between the parameter list and
the body reaches the parser as a `CXToken_Comment` with no rule to consume it:

```c
#define SDL_ISPIXELFORMAT_FOURCC(format)  /* The flag is set to 1 because … */ \
    ((format) && (SDL_PIXELFLAG(format) != 1))
```

The body uses only supported operators; it fails solely on the comment
(`unexpected Token {tokenKind = CXToken_Comment, …}` at `SDL_pixels.h 507:43`).
`clang -dM` strips comments, so only the error token reveals this — a pure lexer
filter fixes it.

**An empty function-like body is silently reparsed as object-like.** For
`#define SDL_OUT_Z_CAP(x)` with nothing after it, `functionLike` fails (no body),
`choice` (`Parse/Expr.hs:64`) falls through to `objectLike`, and the parameter
list `(x)` is then parsed as the *body* — a reference to a variable named `x`.
The reported error is `bare identifier "x" not found`, which points nowhere near
the actual problem. 9 function-like and 68 object-like SDL macros land here (77 in total).

### Negative-test coverage in `c-expr`

`c-expr-dsl/test/fixtures/macros.h` has negative cases for: cast (3 shapes),
keyword-as-parameter-name, type-macro-with-parameter, ternary, `long double`,
`_Pragma`. The golden file records only `Left <parse error>`, so it does not pin
down *which* error.

Missing entirely — a fix in any of these could regress silently:
`sizeof`/`_Alignof`/`offsetof`, `#`, `##`, statement expression, `do`-`while`,
**the comma operator** (which is not merely untested but actively mis-handled),
compound literal, designated initialiser, `.`, `->`, `[]`, unary `&`, unary `*`,
`_Generic`, variadic parameter list, `__VA_ARGS__`, string-literal
concatenation, `__attribute__`, `__builtin_*`, `++`/`--`, assignment, comment
token in body, empty body, inline asm.

---

## Part B — attribution and ranking

### Method note on attribution (B4)

The survey's rule — trust the parser's error token unless it is `(` — held up,
and needed one extension. Over the 60 function-like parse failures the error
token distributes as:

| token | n | informative? |
|---|---|---|
| `(` | 23 | no — position is the failing production's start |
| `__attribute__` | 8 | yes |
| `N1` (a macro parameter, in a string-concatenation body) | 8 | no |
| `do` | 3 | yes |
| `SDL_memset` | 3 | no — callee of a call whose arguments failed |
| `,` | 2 | yes (variadic / concatenation) |
| `SDL_reinterpret_cast` | 2 | no — callee |
| `/* … */`, `#`, `##`, `{`, `...`, `_Static_assert`, `signed`, `)` | 1 each | yes |
| `SDL_CreateThreadRuntime`, `SDL_CreateThreadWithPropertiesRuntime`, `SDL_iconv_string` | 1 each | no — callee |

So 18 of 60 are directly informative and 42 need body inspection. The extension
to the survey's rule is the callee case — the error token is also unreliable when
it is **the callee identifier of a call whose argument list failed to parse**, or
a parameter appearing mid-body:

```
SDL_zero(x)  ->  SDL_memset(&(x), 0, sizeof((x)))   unexpected "SDL_memset"
```

`actualArgs` fails on the unary `&`, `option []` swallows the failure, and the
error surfaces at the callee. Both uninformative cases fall back to body
inspection, taking the earliest unsupported construct in token order (the parser
consumes greedily left-to-right). Each class was then confirmed against the probe
header with a control.

### Ranking by macros actually unlocked (B5)

A per-cause tally overstates leverage, because most failing bodies are blocked by
more than one construct — fixing one moves the macro from "fails at parse" to
"fails slightly later". The table below models each macro's *blocker set* (root
cause + `also_contains` + `calls-c-function` where the body calls a real C
function) and credits a cascade to whatever fix clears its root.

**Function-like, 129 unusable.** `alone` = unlocked by fixing this and nothing
else; `req-by` = macros for which this is necessary but not sufficient.

| root cause | alone | req-by | audience | verdict |
|---|---|---|---|---|
| attribute-argument-name | 18 | 0 | plumbing | should be **omitted**, not fixed |
| clang-builtin | 13 | 0 | mixed (`SDL_Swap*` are API) | needs builtin knowledge |
| cast (concrete target) | 11 | 3 | **API** | **moderate** |
| enum-constant | 11 | 0 | **API** | **cheap** (resolution scope) |
| empty-body | 9 | 0 | plumbing | **cheap** (diagnostic) |
| string-concatenation | 8 | 0 | plumbing | **cheap** |
| attribute | 7 | 1 | plumbing | should be **omitted** |
| calls-c-function | 5 | 3 | API-ish | reachable via the bound function |
| cast-to-parameter-type | 5 | 1 | mixed | **impossible** — needs `capi` |
| conditional `?:` | 5 | 1 | **API** | **cheap** |
| token-paste | 4 | 0 | plumbing | expensive |
| variadic-parameter-list | 3 | 0 | plumbing | expensive |
| type-as-call-argument | 2 | 1 | plumbing | **impossible** — needs `capi` |
| name-conflict | 2 | 0 | API | separate issue |
| sizeof | 1 | 9 | API | expensive, but unblocks 9 more |
| stringification | 1 | 2 | plumbing | expensive |
| member-access `->` | 1 | 1 | **API** | expensive |
| comment-token | 1 | 0 | **API** | **cheap** |
| member-access `.` | 1 | 0 | **API** | expensive |
| inline-asm | 1 | 0 | niche | out of scope |
| keyword-as-parameter-name | 1 | 0 | API | **cheap** |
| typecheck-other | 1 | 0 | API | needs investigation |
| assignment / dereference / `do`-`while` | 0 | 3 each | plumbing | statements, not expressions |
| address-of / subscript | 0 | 2 each | API | expensive |
| `_Static_assert` / compound-literal / block body | 0 | 1 each | plumbing | statements |

Greedy cumulative: `cast` +11 → `string-concatenation` +8 → `attribute` +7 →
`cast-to-parameter-type` +5 → `?:` +5 … reaching all 129 only once every cause is
addressed. Full table: `python3 scripts/rank-macro-fixes.py /tmp/sdl3-survey --funclike`.

### The three grammar gaps worth doing first

Ranked by *user-facing* macros unlocked per unit of work, not by raw count. The
big-count causes at the top of the table (`attribute-argument-name`, `attribute`,
`empty-body`) are all SDL's internal annotation plumbing — `SDL_ACQUIRE`,
`SDL_GUARDED_BY`, `SDL_PRINTF_VARARG_FUNC`, `SDL_OUT_Z_CAP`. Nobody calls those
from Haskell; the right treatment is a prescriptive binding spec that omits them,
not a grammar extension.

1. **Conditional `?:` — cheap, 5 macros, all user-facing.**
   `SDL_min`, `SDL_max`, `SDL_clamp`, `SDL_BITSPERPIXEL`, `SDL_BYTESPERPIXEL`.
   The result type is the usual arithmetic conversions, so it needs a `Cond` /
   `CondRes` class in `c-expr-runtime` shaped exactly like the existing
   `Add`/`AddRes` (`core/C/Operator/Classes.hs:104`), plus a level-13 entry in
   the operator table. This is the single highest-value cheap fix: these are the
   macros a user reaches for first.

2. **Enum constants in macro resolution scope — cheap, 11 macros, all user-facing.**
   `SDL_ISPIXELFORMAT_{INDEXED,PACKED,ARRAY,ALPHA,10BIT,FLOAT}` and
   `SDL_ISCOLORSPACE_{FULL,LIMITED}_RANGE`, `SDL_ISCOLORSPACE_MATRIX_*`. These
   parse and would typecheck; they fail only because enumerators are absent from
   the `DeclIndex` (`bare identifier "SDL_PIXELTYPE_INDEX1" not found`). This is
   `hs-bindgen`'s side, not the grammar. Unlike every other row it needs no new
   type-level machinery at all.

3. **Cast to a concrete type — moderate, 11 macros, all user-facing.**
   `SDL_MS_TO_NS`, `SDL_US_TO_NS`, `SDL_SECONDS_TO_NS`, the six
   `SDL_COLORSPACE*` accessors, `SDL_DEFINE_COLORSPACE`, `SDL_stack_free`. The
   target type is always known (`Uint64`, `SDL_ColorType`, …), so this is a
   conversion at a known type rather than the impossible parameter-in-type-position
   case. That is 11 of the 13 macros whose root cause is `cast`; the other two,
   `SDL_CreateThread` and `SDL_CreateThreadWithProperties`, also call a C function
   and so need that too. Required by 3 further macros.

Honourable mention: the **comment-token** filter is a few lines and unlocks
`SDL_ISPIXELFORMAT_FOURCC`, which is not in the "top three" by count but is the
cheapest fix in the whole table.

### Where a C wrapper genuinely is the only answer

9 function-like macros need a per-instantiation C wrapper because a type appears
in parameter or argument position — `SDL_static_cast`, `SDL_const_cast`,
`SDL_reinterpret_cast`, `SDL_stack_alloc`, `SDL_FOURCC`,
`SDL_DEFINE_PIXELFOURCC`, `SDL_iconv_utf8_ucs2`, `SDL_iconv_utf8_ucs4`,
`SDL_iconv_wchar_utf8`. A further 10 have statement bodies (`SDL_assert` family,
`SDL_INIT_INTERFACE`, `SDL_copyp`, `SDL_CPUPauseInstruction`,
`SDL_COMPILE_TIME_ASSERT`) and are not expressions in any translation scheme. So
**the `capi` suggestion in the community report is correct for ~19 of 160**, and
should be credited as such rather than dismissed.

### Reachable anyway through a bound function

Low priority regardless of cause: `SDL_InvalidParamError` and `SDL_Unsupported`
wrap `SDL_SetError`; `SDL_AtomicIncRef`/`SDL_AtomicDecRef` wrap
`SDL_AddAtomicInt`; `SDL_SwapFloatBE` wraps `SDL_SwapFloat`;
`SDL_iconv_utf8_locale` wraps `SDL_iconv_string`. All five underlying functions
*are* bound. A Haskell user loses only the convenience spelling.

### Comma-operator macros: bound, semantics suspect

Per the survey, counted separately and not investigated. No SDL macro landed in
this bucket: the comma-operator path (`MTuple`, `Parse/Expr.hs:429–440`) is
reachable, and the probe header confirms `#define P_COMMA(x, y) ((x), (y))` binds
with a `Tuple2` type, but no SDL macro has that shape. Tracked in hs-bindgen's `.ai/bug.md` /
[#2182](https://github.com/well-typed/hs-bindgen/issues/2182); the fix belongs in
`c-expr`.

---

## B6 — bound ≠ usable

**1. The generated code compiles.** `--select-all` output (3.6 MB, 4 modules)
builds clean against `hs-bindgen-runtime` + `c-expr-runtime` with GHC 9.12.3,
exit 0, no errors. See `use-site/UseSite.hs` for the harness.

**2. Bound macros are callable — but not on SDL's own types.** This is the most
consequential finding in the survey.

`SDL_AUDIO_BITSIZE` operates on an `SDL_AudioFormat` in C. hs-bindgen generates
`SDL_AudioFormat` as a `newtype` over `CUInt`, and `c-expr-runtime` instantiates
its operator classes only at the `Foreign.C.Types` types. So the natural call
does not type-check:

```haskell
sDL_AUDIO_BITSIZE (SDL_AudioFormat 0x8010)
  -- No instance for 'Bitwise SDL_AudioFormat CUInt'
sDL_PIXELTYPE SDL_PIXELFORMAT_RGBA8888
  -- No instance for 'Bitwise (ShiftRes SDL_PixelFormat) CInt'
sDL_AUDIO_BITSIZE (Uint32 0x8010)
  -- No instance for 'Bitwise Uint32 CUInt'
```

Unwrapping the argument by hand does compile, which pins the diagnosis: the
generated macro bindings are fine, only the instances are missing.

```haskell
sDL_AUDIO_BITSIZE (unwrapSDL_AudioFormat (SDL_AudioFormat 0x8010))
```

It is not the fix, though — an unwrap (plus a re-wrap when the result feeds back
into SDL) at every call site discards exactly the type distinction the newtype
exists to make. The fix is on hs-bindgen's side: **derive the `c-expr-runtime`
operator classes — `Bitwise` and its siblings — for the newtypes hs-bindgen
generates**, tracked as
[#2184](https://github.com/well-typed/hs-bindgen/issues/2184). Until then **all
31 bound function-like macros are inapplicable to the values SDL's own API
produces**. `Uint32`/`Uint16`/`Sint64` — SDL's own fixed-width aliases, used
throughout its signatures — are equally affected, as is every generated
`newtype`-over-`Word32` and every enum newtype.

**3. A bare literal needs an annotation at every call site.**

```haskell
sDL_AUDIO_BITSIZE 0x8010
  -- Ambiguous type variable 'a00' … prevents 'Bitwise a00 CUInt' from being solved
```

Annotating the argument (`0x8010 :: CUInt`) is sufficient; the result type is a
type family and resolves on its own. Composition works when the inner call is
annotated (`sDL_PIXELTYPE (sDL_DEFINE_PIXELFORMAT (1::CInt) …)`).

**4. `Data.Word` / `Data.Int` types have no instances.** `Word32`, `Int64` etc.
fail (`No instance for 'Bitwise Word32 CUInt'`) even though `Uint32` is generated
as a newtype *over* `HsBindgen.Runtime.LibC.Word32`. Only the `Foreign.C.Types`
set works.

Taken together, this is very plausibly the *actual* experience behind "macros
aren't bound": the macros that are bound reject SDL's own types, so from a use
site they look no more available than the ones that were dropped. Fixes here are
`hs-bindgen`'s (derive the operator classes for generated newtypes, #2184) and
`c-expr-runtime`'s (instance coverage for the `Data.Word` / `Data.Int` types),
not `c-expr-dsl`'s.

## B7 — diagnostics visibility

| | macro drops named in the log |
|---|---|
| default verbosity | **72 of 881** (809 silent, 92%) |
| `--log-enable-macro-warnings -v 3` | 881 of 881 (0 silent) |

For function-like macros specifically: 27 of 129 named by default, 102 silent.
Silent at default verbosity: `SDL_min`, `SDL_max`, `SDL_clamp`, `SDL_MS_TO_NS`,
`SDL_arraysize`, `SDL_BITSPERPIXEL`, `SDL_AUDIO_FRAMESIZE`, `SDL_MUSTLOCK`,
`SDL_COLORSPACETYPE`, `SDL_ISPIXELFORMAT_INDEXED`, …

What *is* visible by default is the cascade layer — `[select]` emits
`Transitive dependency unusable` at `Warning`. The primary failures underneath it
(`[select-parse-macro]`, `[select-macro-resolution]`, `[select-macro-typecheck]`,
327 + 694 + 101 messages) are all at `Info`. So the user sees consequences
without causes.

This is the most likely root cause of the community report's incorrect rationale:
the specific failures were silent, so a blanket explanation ("function-like
macros have no linkable symbol") got invented to fill the gap. Follow-up, and
this one *is* `hs-bindgen`'s: surface macro drops by default, or emit a closing
summary (`N macros not bound; use --log-enable-macro-warnings`).

## Artefacts

All in this repository (they were produced under `hs-bindgen`'s git-excluded
`.ai/` and moved here afterwards, so that the probe header — the reproducibility
anchor for Part A — is tracked). Paths below are relative to the repository root;
`run-survey.sh` resolves the SDL and `hs-bindgen` inputs itself, so no particular
local checkout is assumed. See `README.md`.

- `run-survey.sh` — driver, runs everything below
- `scripts/collect-macro-defs.py` — `-dM`/`-dD` → definition site + body
- `scripts/parse-frontend-dump.py` — frontend `Show` dump → verdicts / selected / deps
- `scripts/classify-macro-failures.py` — root-cause assignment
- `scripts/rank-macro-fixes.py` — blocker-set modelling and ranking
- `scripts/compare-selection.py` — macros bound per selection mode
- `probe/macro-grammar-probe.h` — 38 probes + 14 controls (Part A / B4)
- `use-site/UseSite.hs`, `use-site/UseSiteNewtype.hs` — B6 harness, run by
  `use-site/run-use-site.sh` (the first must compile, the second must not)
- `report/2026-07-31-sdl3-macro-support-appendix.csv` — per-macro appendix, all 1980
  SDL macros with stage, root cause, `also_contains`, dependency, error token and body

The `Show`-output parser was preferred to a new JSON subcommand: the `declIndex`
section proved regular enough to parse reliably (54/54 on the probe, 4692/4692 on
SDL3), so no instrumentation was added to `hs-bindgen`. **No `hs-bindgen`,
`c-expr` or SDL source was modified by this survey.**

A second run into a fresh output directory reproduces `classified.csv` and
`summary.txt` byte-for-byte.

## Follow-ups this survey generated

In `c-expr` (grammar / runtime):

1. conditional `?:` — cheap, 5 user-facing macros
2. skip `CXToken_Comment` in macro bodies — cheapest fix in the table
3. reject empty function-like bodies explicitly instead of reparsing as object-like
4. string-literal concatenation
5. cast to a concrete type
6. comma operator mis-typed as a tuple (#2182, already tracked)
7. negative tests for the ~24 constructs listed in Part A that have none

In `hs-bindgen`:

8. enum constants absent from macro resolution scope — 11 user-facing macros
9. derive the `c-expr-runtime` operator classes (`Bitwise`, …) for generated
   newtypes (`Uint32`, enum newtypes) — the B6 blocker; without it the bound
   macros are unusable on SDL's own types
   ([#2184](https://github.com/well-typed/hs-bindgen/issues/2184))
10. surface macro drops at default verbosity / closing summary
11. a prescriptive binding spec for SDL that omits the annotation plumbing
    (`SDL_ACQUIRE`, `SDL_GUARDED_BY`, `SDL_OUT_Z_CAP`, … — 36 function-like, 114
    SDL macros in total) so they stop appearing as failures
12. stale CLAUDE.md: it claims `c-expr-dsl` / `c-expr-runtime` /
    `libclang-bindings` / `doxygen-parser` are `source-repository-package`s pinned
    in `cabal.project.base`; they are plain Hackage dependencies

## Caveats

- One platform, one clang version, one SDL SHA. `09552d5be` is not a tag, so the
  report is reproducible only against that SHA.
- SDL wraps much of its API in `SDL_FORCE_INLINE` functions and
  `extern SDL_DECLSPEC` declarations; a dropped macro whose functionality is
  reachable through a bound function is low priority regardless of cause.
- The `also_contains` blocker sets come from regex inspection of `-dM`-normalised
  bodies. They are deliberately conservative (over-reporting a blocker makes an
  estimate pessimistic, never optimistic). Spot-checked by hand against all 60
  function-like parse failures; two false positives found and fixed
  (`(S)->flags` and `(cspace) & 0x1F` read as casts).
- `SDL_ISPIXELFORMAT_FOURCC`'s comment is stripped by `clang -dM`, so that class
  is detectable only from the parser's error token. If other macros have comments
  in a position the parser reaches *after* another failure, they would be
  attributed to the earlier cause.
