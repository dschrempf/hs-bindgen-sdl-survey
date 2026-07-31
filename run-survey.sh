#!/usr/bin/env bash
# Driver for the SDL3 macro-support survey (plan/2026-07-31-sdl3-macro-support-survey.md).
#
# Runnable from any directory and on a machine with no local checkouts: SDL and
# hs-bindgen are resolved from $SDL / $HS_BINDGEN / $BINDGEN, a sibling
# hs-bindgen checkout, $PATH, or a cached clone at the pins.env revisions — see
# README.md. Both are treated as read-only; everything is written under $OUT.
#
#   SDL=…              path to an SDL checkout        (default: cached clone)
#   HS_BINDGEN=…       path to a hs-bindgen checkout  (default: sibling, then clone)
#   BINDGEN=…          command running hs-bindgen-cli (overrides HS_BINDGEN)
#   CEXPR=…            path to a c-expr checkout      (provenance only, optional)
#   OUT=…              output directory               (default: /tmp/sdl3-survey)
#   CACHE=…            where clones land              (default: XDG cache dir)
#   SURVEY_USE_SITE=1  also run the B6 use-site check (slow: builds the bindings)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT=${OUT:-/tmp/sdl3-survey}

# shellcheck source=pins.env
. "$ROOT/pins.env"
# shellcheck source=lib/inputs.sh
. "$ROOT/lib/inputs.sh"

mkdir -p "$OUT"

step() { printf '\n=== %s ===\n' "$1" >&2; }

step "B0 provenance"
resolve_sdl
resolve_bindgen
{
  echo "date:           $(date -Iseconds)"
  echo "survey:         $ROOT @ $(head_of "$ROOT")"
  echo "sdl:            $SDL @ $(head_of "$SDL") ($(git -C "$SDL" describe --tags 2>/dev/null || echo 'no tag'))"
  echo "hs-bindgen:     $BINDGEN_DESC"
  echo "c-expr:         ${CEXPR:+$CEXPR @ $(head_of "${CEXPR:-.}")}${CEXPR:-not checked out; Hackage c-expr-dsl is used (reference $REF_CEXPR_DSL)}"
  echo "clang:          $(clang --version | head -1)   (reference $REF_CLANG)"
  echo "ghc:            $(ghc --numeric-version 2>/dev/null || echo unknown)   (reference $REF_GHC)"
  echo "cabal:          $(cabal --numeric-version 2>/dev/null || echo unknown)"
  if [ -n "${HS_BINDGEN:-}" ] && [ -f "$HS_BINDGEN/cabal.project.local" ]; then
    echo "cabal.project.local in $HS_BINDGEN:"
    sed 's/^/  | /' "$HS_BINDGEN/cabal.project.local"
  else
    echo "cabal.project.local: none"
  fi
} | tee "$OUT/provenance.txt" >&2

step "A grammar probe (frontend over probe/macro-grammar-probe.h)"
bindgen internal frontend --pass final --unique-id probe --select-all \
  "$ROOT/probe/macro-grammar-probe.h" > "$OUT/frontend-probe.txt" 2> "$OUT/frontend-probe.log"
python3 "$ROOT/scripts/parse-frontend-dump.py" verdicts "$OUT/frontend-probe.txt" \
  > "$OUT/probe-verdicts.csv"

step "B1 denominator (clang -E -dM / -dD)"
clang -E -dM -I "$SDL/include" -x c "$SDL/include/SDL3/SDL.h" > "$OUT/dM.txt"
clang -E -dD -I "$SDL/include" -x c "$SDL/include/SDL3/SDL.h" > "$OUT/dD.txt"
python3 "$ROOT/scripts/collect-macro-defs.py" "$SDL/include" "$OUT/dM.txt" "$OUT/dD.txt" \
  > "$OUT/defs.json"

step "B2 frontend dump (select-all) + generated bindings"
bindgen internal frontend --pass final \
  --unique-id sdl3 --select-all \
  -I "$SDL/include" SDL3/SDL.h > "$OUT/frontend-all.txt" 2> "$OUT/frontend-all.log"

# Selection variants, to show the macro counts do not depend on the mode.
bindgen internal frontend --pass final \
  --unique-id sdl3 --select-from-main-headers \
  -I "$SDL/include" SDL3/SDL.h > "$OUT/frontend-main.txt" 2> "$OUT/frontend-main.log"

bindgen internal frontend --pass final \
  --unique-id sdl3 --select-from-main-header-dirs \
  -I "$SDL/include" SDL3/SDL.h > "$OUT/frontend-maindirs.txt" 2> "$OUT/frontend-maindirs.log"

# B7: what the user sees by default vs with macro warnings enabled.
rm -rf "$OUT/hs" && mkdir -p "$OUT/hs"
bindgen \
  preprocess --unique-id sdl3 --select-all --module SDL3 \
    --hs-output-dir "$OUT/hs" --create-output-dirs --overwrite-files \
    -I "$SDL/include" SDL3/SDL.h > "$OUT/preprocess-default.log" 2>&1 || true

bindgen \
  --log-enable-macro-warnings -v 3 \
  preprocess --unique-id sdl3 --select-all --module SDL3 \
    --hs-output-dir "$OUT/hs" --create-output-dirs --overwrite-files \
    -I "$SDL/include" SDL3/SDL.h > "$OUT/preprocess-verbose.log" 2>&1 || true

step "B3 verdicts + selection"
python3 "$ROOT/scripts/parse-frontend-dump.py" verdicts "$OUT/frontend-all.txt" > "$OUT/verdicts.csv"
python3 "$ROOT/scripts/parse-frontend-dump.py" selected "$OUT/frontend-all.txt" > "$OUT/selected-all.txt"
python3 "$ROOT/scripts/parse-frontend-dump.py" selected "$OUT/frontend-main.txt" > "$OUT/selected-main.txt"
python3 "$ROOT/scripts/parse-frontend-dump.py" selected "$OUT/frontend-maindirs.txt" > "$OUT/selected-maindirs.txt"
python3 "$ROOT/scripts/compare-selection.py" "$OUT" > "$OUT/selection-modes.txt"
python3 "$ROOT/scripts/parse-frontend-dump.py" deps "$OUT/frontend-all.txt" > "$OUT/deps.csv"

step "B4/B5 classification + ranking"
python3 "$ROOT/scripts/classify-macro-failures.py" "$OUT" "$OUT/classified-all.csv" \
  > "$OUT/classified.csv" 2> "$OUT/summary.txt"
python3 "$ROOT/scripts/rank-macro-fixes.py" "$OUT" --funclike > "$OUT/rank-funclike.txt"
python3 "$ROOT/scripts/rank-macro-fixes.py" "$OUT" > "$OUT/rank-all.txt"
cat "$OUT/summary.txt" >&2

if [ "${SURVEY_USE_SITE:-0}" = 1 ]; then
  step "B6 use-site check (builds the generated bindings)"
  HS_BINDGEN=${HS_BINDGEN:-} "$ROOT/use-site/run-use-site.sh" "$OUT" >&2
fi

step "reproduction check"
# classified.csv *is* the report's appendix, so a matching run reproduces it byte
# for byte; a difference means some pin, clang or c-expr-dsl version differs.
APPENDIX=$ROOT/report/2026-07-31-sdl3-macro-support-appendix.csv
if diff -q "$APPENDIX" "$OUT/classified.csv" >/dev/null; then
  echo "classified.csv matches report/…-appendix.csv" >&2
else
  echo "classified.csv DIFFERS from report/…-appendix.csv:" >&2
  diff "$APPENDIX" "$OUT/classified.csv" | head -20 >&2 || true
  echo "(see $OUT/provenance.txt for what moved)" >&2
fi

step "done"
echo "artefacts in $OUT" >&2
ls -1 "$OUT" >&2
