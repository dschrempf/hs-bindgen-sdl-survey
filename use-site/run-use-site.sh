#!/usr/bin/env bash
# B6: does the generated code compile, and are the bound macros callable?
#
# Usage: SDL=… run-use-site.sh OUT      (OUT/hs must hold a preprocess run)
#
# Two builds, staged in OUT/use-site so the survey checkout stays read-only:
#
#   UseSite         must SUCCEED — 20 bound macros called at Foreign.C types
#   UseSiteNewtype  must FAIL    — the same macros applied to SDL's own newtypes
#
# The second failing is the finding, not an error: c-expr-runtime instantiates
# its operator classes only at the Foreign.C.Types types and hs-bindgen does not
# derive them for the newtypes it generates (hs-bindgen#2184), so a bound macro
# cannot be applied to the values SDL's API produces.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT=${1:?usage: SDL=… run-use-site.sh OUT}
SDL=${SDL:?SDL must point at the SDL checkout the bindings were generated from}
STAGE=$OUT/use-site

[ -f "$OUT/hs/SDL3.hs" ] || { echo "no bindings in $OUT/hs — run run-survey.sh first" >&2; exit 1; }

mkdir -p "$STAGE"          # dist-newstyle is kept: the two builds share it
rm -rf "$STAGE/gen"
cp -r "$OUT/hs" "$STAGE/gen"
cp "$HERE"/UseSite.hs "$HERE"/UseSiteNewtype.hs "$STAGE/"

# Generated module names, derived from the file tree rather than assumed.
GEN_MODULES=$( cd "$STAGE/gen" && find . -name '*.hs' \
  | sed 's|^\./||; s|\.hs$||; s|/|.|g' | sort | tr '\n' ' ' )

# Prefer hs-bindgen-runtime from the checkout that produced the bindings; its
# version has to match the CLI's. Fall back to Hackage.
{
  echo "packages: ."
  if [ -n "${HS_BINDGEN:-}" ] && [ -d "$HS_BINDGEN/hs-bindgen-runtime" ]; then
    echo "packages: $HS_BINDGEN/hs-bindgen-runtime"
  fi
  # This is a compile check on 3.6 MB of generated code, so -O0. The dynamic way
  # has to stay on: the generated modules run TH splices from hs-bindgen-runtime.
  echo "optimization: 0"
} > "$STAGE/cabal.project"

build() {
  local module=$1 log=$OUT/use-site-$1.log
  sed -e "s|@MODULES@|$GEN_MODULES $module|" -e "s|@SDL_INCLUDE@|$SDL/include|" \
    "$HERE/use-site.cabal.in" > "$STAGE/use-site.cabal"
  ( cd "$STAGE" && cabal build -v1 use-site ) > "$log" 2>&1
}

echo "1. generated bindings + UseSite (expect success)"
if build UseSite; then
  echo "   OK: exit 0, see $OUT/use-site-UseSite.log"
else
  echo "   UNEXPECTED FAILURE, see $OUT/use-site-UseSite.log" >&2
fi

echo "2. UseSiteNewtype: macros applied to SDL's own newtypes (expect failure)"
if build UseSiteNewtype; then
  echo "   UNEXPECTED SUCCESS — the B6 finding no longer reproduces" >&2
else
  echo "   as expected, does not compile:"
  grep -A3 -E "^UseSiteNewtype\.hs:[0-9]+:[0-9]+: error" "$OUT/use-site-UseSiteNewtype.log" \
    | sed 's/^/     /'
fi
