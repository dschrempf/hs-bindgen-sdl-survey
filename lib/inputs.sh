# shellcheck shell=bash
#
# Resolves the survey's two external inputs — the SDL headers and a
# hs-bindgen-cli — cloning either into $CACHE when the machine has neither.
# Sourced by run-survey.sh; defines $SDL, $CEXPR, bindgen() and $BINDGEN_DESC.

CACHE=${CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/hs-bindgen-sdl-survey}

die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n'         "$*" >&2; }

# clone_at DIR URL SHA [SPARSE_PATH...] — idempotent checkout of one revision.
# Given sparse paths, only those are materialised and blobs are fetched lazily:
# SDL's include/ is a megabyte, its full tree is hundreds.
clone_at() {
  local dir=$1 url=$2 sha=$3; shift 3
  local filter=()
  if [ -e "$dir/.git" ] && git -C "$dir" rev-parse -q --verify "$sha^{commit}" >/dev/null; then
    git -C "$dir" checkout -q "$sha"
    return
  fi
  note "  cloning $url @ ${sha:0:9} into $dir (one-off, cached)"
  mkdir -p "$dir"
  git -C "$dir" init -q
  git -C "$dir" remote add origin "$url" 2>/dev/null || true
  if [ $# -gt 0 ]; then
    filter=(--filter=blob:none)
    git -C "$dir" sparse-checkout init --cone
    git -C "$dir" sparse-checkout set "$@"
  fi
  # GitHub serves fetch-by-SHA; fall back to a full fetch where it does not.
  git -C "$dir" fetch -q --depth 1 "${filter[@]}" origin "$sha" \
    || git -C "$dir" fetch -q "${filter[@]}" origin \
    || die "cannot fetch $url — clone it yourself and pass its path (see README.md)"
  git -C "$dir" checkout -q "$sha" || die "$url has no commit $sha"
}

# head_of DIR — SHA plus dirty-file count, or why there is none.
head_of() {
  local dir=$1 sha
  [ -e "$dir/.git" ] || { printf 'not a git checkout'; return; }
  sha=$(git -C "$dir" rev-parse HEAD 2>/dev/null) || { printf 'no commit yet'; return; }
  printf '%s (%s dirty files)' "$sha" "$(git -C "$dir" status --porcelain | wc -l)"
}

# warn_pin WHAT DIR SHA — the numbers in report/ hold only at the pinned SHA.
warn_pin() {
  local what=$1 dir=$2 sha=$3 have
  [ -e "$dir/.git" ] || return 0
  have=$(git -C "$dir" rev-parse HEAD)
  [ "$have" = "$sha" ] && return 0
  note "  note: $what is at ${have:0:9}, pins.env says ${sha:0:9} —" \
       "expect numbers to differ from report/"
}

resolve_sdl() {
  if [ -n "${SDL:-}" ]; then
    [ -d "$SDL" ] || die "SDL=$SDL does not exist"
  elif [ -d "$CACHE/SDL" ]; then
    SDL=$CACHE/SDL
  else
    SDL=$CACHE/SDL
    clone_at "$SDL" "$SDL_URL" "$SDL_SHA" include   # the survey reads headers only
  fi
  [ -f "$SDL/include/SDL3/SDL.h" ] \
    || die "$SDL is not an SDL checkout (no include/SDL3/SDL.h)"
  warn_pin SDL "$SDL" "$SDL_SHA"
  note "  SDL:        $SDL"
}

# Resolution order: an explicit command, an explicit checkout, a sibling
# checkout, a hs-bindgen-cli on PATH, then a cached clone. A checkout is
# preferred over PATH because only a checkout has a revision to record.
resolve_bindgen() {
  local sibling=$ROOT/../hs-bindgen
  if [ -n "${BINDGEN:-}" ]; then
    read -r -a BINDGEN_ARGV <<<"$BINDGEN"
    BINDGEN_CWD=$ROOT
    BINDGEN_DESC="BINDGEN=$BINDGEN (revision unknown)"
  elif [ -n "${HS_BINDGEN:-}" ]; then
    [ -f "$HS_BINDGEN/cabal.project" ] || die "HS_BINDGEN=$HS_BINDGEN is not a hs-bindgen checkout"
    use_checkout "$HS_BINDGEN"
  elif [ -f "$sibling/cabal.project" ]; then
    use_checkout "$sibling"
  elif command -v hs-bindgen-cli >/dev/null; then
    BINDGEN_ARGV=(hs-bindgen-cli)
    BINDGEN_CWD=$ROOT
    BINDGEN_DESC="$(command -v hs-bindgen-cli) (revision unknown)"
  else
    clone_at "$CACHE/hs-bindgen" "$HS_BINDGEN_URL" "$HS_BINDGEN_SHA"
    use_checkout "$CACHE/hs-bindgen"
  fi
  note "  hs-bindgen: $BINDGEN_DESC"
}

use_checkout() {
  HS_BINDGEN=$(cd "$1" && pwd)
  BINDGEN_ARGV=(cabal run -v0 hs-bindgen-cli --)
  BINDGEN_CWD=$HS_BINDGEN
  BINDGEN_DESC="$HS_BINDGEN @ $(head_of "$HS_BINDGEN")"
  warn_pin hs-bindgen "$HS_BINDGEN" "$HS_BINDGEN_SHA"
  note "  building hs-bindgen-cli (first run takes a while)"
  ( cd "$HS_BINDGEN" && cabal build -v0 hs-bindgen-cli ) \
    || die "cannot build hs-bindgen-cli in $HS_BINDGEN"
}

# The CLI, wherever it came from.
bindgen() { ( cd "$BINDGEN_CWD" && "${BINDGEN_ARGV[@]}" "$@" ); }
