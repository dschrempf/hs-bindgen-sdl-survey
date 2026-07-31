-- B6.2 use-site check for the 31 bound function-like SDL3 macros.
--
-- Everything in this module compiles. The cases that do NOT compile are
-- recorded in UseSiteNewtype.hs.
{-# LANGUAGE ScopedTypeVariables #-}

module UseSite where

import Foreign.C.Types
import Data.Word

import SDL3

-- bitwise --------------------------------------------------------------------

bitsize_CUInt      = sDL_AUDIO_BITSIZE     (0x8010 :: CUInt)
bitsize_CInt       = sDL_AUDIO_BITSIZE     (0x8010 :: CInt)
bytesize_CUInt     = sDL_AUDIO_BYTESIZE    (0x8010 :: CUInt)
wpos_centered      = sDL_WINDOWPOS_CENTERED_DISPLAY (0 :: CInt)
wpos_undefined     = sDL_WINDOWPOS_UNDEFINED_DISPLAY (0 :: CUInt)

-- shift ----------------------------------------------------------------------

pixelflag_CUInt    = sDL_PIXELFLAG         (0 :: CUInt)
pixeltype_CInt     = sDL_PIXELTYPE         (0 :: CInt)
buttonmask_CInt    = sDL_BUTTON_MASK       (1 :: CInt)

-- arithmetic -----------------------------------------------------------------

versionnum_CInt    = sDL_VERSIONNUM        (3 :: CInt) (4 :: CInt) (0 :: CInt)
ns_to_ms_CLLong    = sDL_NS_TO_MS          (1000000 :: CLLong)
ns_to_us_CLLong    = sDL_NS_TO_US          (1000 :: CLLong)
vnum_major         = sDL_VERSIONNUM_MAJOR  (3004000 :: CInt)
vnum_minor         = sDL_VERSIONNUM_MINOR  (3004000 :: CInt)
vnum_micro         = sDL_VERSIONNUM_MICRO  (3004000 :: CInt)

-- relational / logical -------------------------------------------------------

atleast_CInt       = sDL_VERSION_ATLEAST   (3 :: CInt) (4 :: CInt) (0 :: CInt)
iscentered_CInt    = sDL_WINDOWPOS_ISCENTERED (0 :: CInt)
isint_CUInt        = sDL_AUDIO_ISINT       (0x8010 :: CUInt)
isfloat_CUInt      = sDL_AUDIO_ISFLOAT     (0x8010 :: CUInt)

-- identity (little-endian host) -----------------------------------------------

swap16le_Word16    = sDL_Swap16LE          (1 :: Word16)

-- composition ----------------------------------------------------------------

composed           = sDL_PIXELTYPE (sDL_DEFINE_PIXELFORMAT
                        (1 :: CInt) (2 :: CInt) (3 :: CInt) (4 :: CInt) (5 :: CInt))

-- SDL's own newtypes only work unwrapped -------------------------------------
--
-- Evidence that the bindings are fine and only the instances are missing; not
-- the fix. That is hs-bindgen#2184: derive Bitwise & co. for generated newtypes.

unwrapped          = sDL_AUDIO_BITSIZE (unwrapSDL_AudioFormat (SDL_AudioFormat 0x8010))
