-- B6.2, sharper: can a bound macro be applied to a value of the type SDL's own
-- API actually produces?
--
-- SDL_AUDIO_BITSIZE takes an SDL_AudioFormat in C; SDL_PIXELTYPE takes an
-- SDL_PixelFormat; the *_TO_NS macros take Uint64. hs-bindgen generates each of
-- those C types as a Haskell newtype, and c-expr-runtime instantiates its
-- operator classes only at the Foreign.C.Types types. Cases 1-3 therefore fail
-- to compile until hs-bindgen derives those classes for the newtypes it
-- generates (hs-bindgen#2184).
module UseSiteNewtype where

import Foreign.C.Types
import SDL3

-- 1. the natural call: macro applied to the C type it is declared for
natural_audioformat = sDL_AUDIO_BITSIZE (SDL_AudioFormat 0x8010)

-- 2. same, via the enum pattern synonym SDL exposes
natural_pixelformat = sDL_PIXELTYPE SDL_PIXELFORMAT_RGBA8888

-- 3. Uint32, SDL's own fixed-width alias
natural_uint32 = sDL_AUDIO_BITSIZE (Uint32 0x8010)

-- 4. compiles only unwrapped: the bindings are fine, the instances are missing
workaround = sDL_AUDIO_BITSIZE (unwrapSDL_AudioFormat (SDL_AudioFormat 0x8010))
