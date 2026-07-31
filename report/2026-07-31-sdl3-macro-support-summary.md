# SDL3 macro support survey — summary

Summary of `report/2026-07-31-sdl3-macro-support.md`.

**What it is:** a measurement-only survey (nothing fixed, no source modified) of
how many SDL3 macros `hs-bindgen` binds and why the rest fail. One platform,
clang 21.1.8, one SDL SHA, `c-expr-dsl-0.1.0.1`. Every number reproducible via
`run-survey.sh`.

## Counts

Denominator = 1980 macros whose `#define` is inside `SDL/include`.

| | total | bound | dropped (cascade) | dropped (primary) |
|---|---|---|---|---|
| function-like | 160 | 31 | 14 | 115 |
| object-like | 1820 | 1068 | 39 | 713 |
| all | 1980 | 1099 | 53 | 828 |

Rows sum exactly — every macro has a verdict, no residue. 594 of the 713 primary
object-like failures are `SDL_oldnames.h` SDL2→SDL3 shims that define each old
name to a deliberately non-existent sentinel; they are *meant* to be unbindable.
So the survey's real subject is 160 function-like + ~119 object-like macros, not
881 failures.

## Most consequential finding: bound ≠ usable

All 31 bound function-like macros are **inapplicable to the values SDL's own API
produces** without a manual unwrap. `c-expr-runtime` instantiates its operator
classes only at the `Foreign.C.Types` types, while hs-bindgen generates SDL's
types as newtypes:

```haskell
sDL_AUDIO_BITSIZE (SDL_AudioFormat 0x8010)
  -- No instance for 'Bitwise SDL_AudioFormat CUInt'
sDL_AUDIO_BITSIZE (Uint32 0x8010)          -- SDL's own fixed-width alias
  -- No instance for 'Bitwise Uint32 CUInt'
sDL_AUDIO_BITSIZE (unwrapSDL_AudioFormat (SDL_AudioFormat 0x8010))  -- compiles
```

Same for every enum newtype, and `Word32`/`Int64` from `Data.Word`/`Data.Int`
have no instances either. A bare literal also needs an annotation at each call
site (`0x8010 :: CUInt`) or the type variable is ambiguous. From a use site the
bound macros therefore look no more available than the dropped ones — very
plausibly the *actual* experience behind "macros aren't bound". Fixes belong to
`c-expr-runtime` (instance coverage) and `hs-bindgen` (deriving operator
instances for generated newtypes).

The generated code itself does compile: `--select-all` output (3.6 MB, 4 modules)
builds clean with GHC 9.12.3.

## Diagnostics hide the causes

| | macro drops named in the log |
|---|---|
| default verbosity | 72 of 881 (92% silent) |
| `--log-enable-macro-warnings -v 3` | 881 of 881 |

For function-like macros, 27 of 129 visible in traces by default. What *is*
visible is the cascade layer (`Transitive dependency unusable`, at `Warning`),
while the primary parse/resolve/typecheck failures underneath log at `Info`.
Users see consequences without causes.

## The `capi` verdict

The community report claimed that

> Function-like macros aren't bound: No linkable symbol exists.

A user suggested that we could

> get `hs-bindgen` to emit "capi" bindings

Both halves need correcting:

- There are no linkable symbols. C does not create linkable symbols for macros
  at all. This is not something we can fix on the `hs-bindgen` side.
- `hs-bindgen` _does_ create bindings for function-like macros it can parse and
  translate. According to our analysis, it does so for 31 function-like macros
  out of 160.
- In general, proper bindings to function-like macros are a good thing!
- However, the survey showed that they are not the only answer, and we may need
  CAPI-based bindings for 19 of 160 function-like macros:
  - **9 macros put a type in parameter or argument position.**
    `SDL_static_cast`, `SDL_const_cast`, `SDL_reinterpret_cast`,
    `SDL_stack_alloc`, `SDL_FOURCC`, `SDL_DEFINE_PIXELFOURCC`,
    `SDL_iconv_utf8_{ucs2,ucs4}`, `SDL_iconv_wchar_utf8`. E.g.
    `#define SDL_static_cast(type, expression) ((type)(expression))` — no
    Haskell function has that type, so it needs one C wrapper *per
    instantiation*.
  - **10 macros have statement bodies,** not expressions: the `SDL_assert`
    family, `SDL_INIT_INTERFACE`, `SDL_copyp`, `SDL_CPUPauseInstruction`,
    `SDL_COMPILE_TIME_ASSERT` — `do { … } while(0)`, `({ … })`, inline
    `__asm__`. Not expressible in any translation scheme.

Everything else that fails is a fixable grammar or resolution gap, not a wrapper
case.

## Two new bugs found

**1. Comment tokens between parameter list and body are not skipped.** No rule
consumes `CXToken_Comment`, so this fails purely on the comment even though every
operator in the body is supported:

```c
#define SDL_ISPIXELFORMAT_FOURCC(format)  /* The flag is set to 1 because … */ \
    ((format) && (SDL_PIXELFLAG(format) != 1))
```

Error: `unexpected Token {tokenKind = CXToken_Comment, …}` at
`SDL_pixels.h 507:43`. Because `clang -dM` strips comments, only that error token
reveals the cause. A lexer filter fixes it — the cheapest fix in the whole
report.

**2. An empty function-like body is silently reparsed as object-like.** For
`#define SDL_OUT_Z_CAP(x)` with nothing after it, the function-like parser fails
(no body), falls through to the object-like parser, and the *parameter list*
`(x)` is then parsed as the body — a reference to a variable named `x`. The
reported error, `bare identifier "x" not found`, points nowhere near the real
problem. 9 function-like and 68 object-like SDL macros land here (77 total).

(A third, already tracked as
[#2182](https://github.com/well-typed/hs-bindgen/issues/2182): the comma operator
parses and binds but is mis-typed as a `Tuple2`. No SDL macro has that shape, so
it cost nothing here.)

## Cheapest high-value fixes

Ranked by *user-facing* macros unlocked per unit of work. The largest-count
causes (`attribute-argument-name` 18, `attribute` 7, `empty-body` 9) are all
SDL's internal annotation plumbing — `SDL_ACQUIRE`, `SDL_GUARDED_BY`,
`SDL_PRINTF_VARARG_FUNC`, `SDL_OUT_Z_CAP` — which nobody calls from Haskell; the
right treatment is a prescriptive binding spec that omits them, not a grammar
extension.

1. **Conditional `?:`** — cheap, 5 macros, all user-facing: `SDL_min`,
   `SDL_max`, `SDL_clamp`, `SDL_BITSPERPIXEL`, `SDL_BYTESPERPIXEL`. Needs a
   `Cond`/`CondRes` class shaped like the existing `Add`/`AddRes`, plus a
   level-13 entry in the operator table. Highest value of the cheap fixes —
   these are the macros a user reaches for first.
2. **Enum constants in macro resolution scope** — cheap, 11 macros, all
   user-facing (`SDL_ISPIXELFORMAT_{INDEXED,PACKED,ARRAY,…}`,
   `SDL_ISCOLORSPACE_*`). They parse and would typecheck; they fail only because
   enumerators are absent from the `DeclIndex`. This is hs-bindgen's side and
   needs no new type-level machinery.
3. **Cast to a concrete type** — moderate, 11 macros (`SDL_MS_TO_NS`, the
   `SDL_COLORSPACE*` accessors, …). The target type is always known, so it's a
   conversion at a known type, distinct from the impossible
   parameter-in-type-position case.

Underlying grammar picture: the expression parser covers cppreference precedence
levels 2–12 only. Level 1 is present but empty and 13–14 are absent, which
explains most rejections (no `?:`, no member access, no subscript, no
postfix/prefix `++`, no assignment).

## Follow-ups

**In `c-expr`:** `?:`; skip comment tokens; reject empty function-like bodies
explicitly; string-literal concatenation; cast to concrete type; comma-operator
typing (#2182); negative tests for the ~24 constructs currently untested
(`sizeof`, `#`, `##`, statement expressions, `.`/`->`/`[]`, `_Generic`,
`__VA_ARGS__`, …) — a fix in any of these could regress silently today.

**In hs-bindgen:** enum constants in macro resolution scope; operator instances
for generated newtypes (the usability blocker); surface macro drops at default
verbosity or emit a closing summary; a prescriptive SDL binding spec omitting the
annotation plumbing (36 function-like, 114 macros total); and a stale CLAUDE.md
claim that `c-expr-dsl`/`c-expr-runtime`/`libclang-bindings`/`doxygen-parser` are
pinned source-repository-packages when they are plain Hackage dependencies.

## Caveats

One platform, one clang, one SDL SHA (`09552d5be`, not a tag). Blocker sets come
from conservative regex inspection of `-dM`-normalised bodies (over-reporting
makes estimates pessimistic, never optimistic), spot-checked by hand against all
60 function-like parse failures.
