"""Identity tests for the numpy-vectorized CMPR codec paths.

The vectorized encoder/decoder must be byte-identical to the pure-Python
per-block implementations: BNB/NBN compare exact bytes, and DATBuilder
dedups pixel buffers by content, so any divergence is a correctness bug,
not a quality tradeoff.
"""
import random
import pytest

import shared.gx_texture as gxt
import shared.texture_encoder as te
from shared.Constants import gx

numpy_missing = gxt._np is None or te._np is None
pytestmark = pytest.mark.skipif(
    numpy_missing, reason="numpy not available; vectorized paths inactive")


def _decode_pure(raw, width, height):
    """Run decode_texture with the numpy fast path disabled."""
    saved = gxt._np
    gxt._np = None
    try:
        return gxt.decode_texture(raw, width, height, gx.GX_TF_CMPR)
    finally:
        gxt._np = saved


def _encode_pure(pixels, width, height):
    """Run encode_cmpr with the numpy fast path disabled."""
    saved = te._np
    te._np = None
    try:
        return te.encode_cmpr(pixels, width, height)
    finally:
        te._np = saved


def _analyze_pure(pixels, width, height):
    saved = te._np
    te._np = None
    try:
        return te.analyze_pixels(pixels, width, height)
    finally:
        te._np = saved


def _cmpr_size(width, height):
    return ((width + 7) // 8) * ((height + 7) // 8) * 32


# Sizes chosen to cover: single tile, tile-aligned, crop on both axes,
# smaller than one tile, and a realistic texture size.
SIZES = [(8, 8), (16, 16), (12, 20), (4, 4), (64, 32), (40, 8)]


class TestCmprDecodeIdentity:

    @pytest.mark.parametrize("width,height", SIZES)
    def test_random_data(self, width, height):
        rng = random.Random(width * 1000 + height)
        raw = bytes(rng.randrange(256) for _ in range(_cmpr_size(width, height)))
        fast = gxt.decode_texture(raw, width, height, gx.GX_TF_CMPR)
        pure = _decode_pure(raw, width, height)
        assert fast is not None and pure is not None
        assert bytes(fast) == bytes(pure)

    def test_equal_endpoints_three_color_mode(self):
        """c0 == c1 exercises the 3-color branch in every sub-block."""
        block = bytes([0x12, 0x34, 0x12, 0x34, 0b00011011, 0xFF, 0x00, 0xE4])
        raw = block * 4  # one 8x8 macro-tile
        fast = gxt.decode_texture(raw, 8, 8, gx.GX_TF_CMPR)
        pure = _decode_pure(raw, 8, 8)
        assert bytes(fast) == bytes(pure)

    def test_all_zero_data(self):
        raw = bytes(_cmpr_size(16, 16))
        fast = gxt.decode_texture(raw, 16, 16, gx.GX_TF_CMPR)
        pure = _decode_pure(raw, 16, 16)
        assert bytes(fast) == bytes(pure)


def _random_rgba(rng, width, height, alpha_mode='mixed'):
    n = width * height
    out = bytearray(n * 4)
    for i in range(n):
        out[i * 4 + 0] = rng.randrange(256)
        out[i * 4 + 1] = rng.randrange(256)
        out[i * 4 + 2] = rng.randrange(256)
        if alpha_mode == 'opaque':
            out[i * 4 + 3] = 255
        elif alpha_mode == 'transparent':
            out[i * 4 + 3] = rng.randrange(0x80)
        else:
            out[i * 4 + 3] = rng.randrange(256)
    return bytes(out)


class TestCmprEncodeIdentity:

    @pytest.mark.parametrize("width,height", SIZES)
    @pytest.mark.parametrize("alpha_mode", ['opaque', 'mixed', 'transparent'])
    def test_random_pixels(self, width, height, alpha_mode):
        rng = random.Random(hash((width, height, alpha_mode)) & 0xFFFF)
        pixels = _random_rgba(rng, width, height, alpha_mode)
        assert te.encode_cmpr(pixels, width, height) == \
            _encode_pure(pixels, width, height)

    @pytest.mark.parametrize("width,height", [(8, 8), (12, 20)])
    def test_posterized_pixels(self, width, height):
        """Few distinct colors — exercises the unique-color dedup ordering."""
        rng = random.Random(7)
        colors = [(255, 0, 0, 255), (0, 255, 0, 255),
                  (4, 4, 4, 255), (0, 0, 255, 40)]
        out = bytearray()
        for _ in range(width * height):
            out += bytes(rng.choice(colors))
        pixels = bytes(out)
        assert te.encode_cmpr(pixels, width, height) == \
            _encode_pure(pixels, width, height)

    def test_uniform_block(self):
        pixels = bytes([10, 20, 30, 255]) * 64
        assert te.encode_cmpr(pixels, 8, 8) == _encode_pure(pixels, 8, 8)

    def test_near_duplicate_colors_same_565(self):
        """Colors that quantize to the same RGB565 value must collapse
        identically in both paths (first-occurrence dedup)."""
        a = (100, 100, 100, 255)
        b = (101, 101, 101, 255)  # same 565 as a
        c = (200, 50, 25, 255)
        pixels = (bytes(a) + bytes(b) + bytes(c) + bytes(a)) * 16
        assert te.encode_cmpr(pixels, 8, 8) == _encode_pure(pixels, 8, 8)

    def test_short_pixel_buffer(self):
        """A truncated buffer reads as transparent black past its end."""
        rng = random.Random(3)
        pixels = _random_rgba(rng, 8, 8, 'opaque')[:100]
        assert te.encode_cmpr(pixels, 8, 8) == _encode_pure(pixels, 8, 8)

    def test_encode_decode_round_trip_uniform(self):
        """Sanity: a uniform opaque image survives encode→decode exactly
        (its color is representable in RGB565 expansion)."""
        pixels = bytes([64, 128, 192, 255]) * (16 * 16)
        encoded = te.encode_cmpr(pixels, 16, 16)
        decoded = gxt.decode_texture(encoded, 16, 16, gx.GX_TF_CMPR)
        assert bytes(decoded) == bytes(
            bytes([64, 128, 192, 255]) * (16 * 16))


class TestAnalyzePixelsIdentity:

    @pytest.mark.parametrize("alpha_mode", ['opaque', 'mixed', 'transparent'])
    def test_random(self, alpha_mode):
        rng = random.Random(11)
        pixels = _random_rgba(rng, 16, 16, alpha_mode)
        assert te.analyze_pixels(pixels, 16, 16) == \
            _analyze_pure(pixels, 16, 16)

    def test_grayscale_binary_alpha(self):
        out = bytearray()
        for i in range(64):
            v = (i * 3) % 256
            out += bytes([v, v, v, 255 if i % 2 else 0])
        pixels = bytes(out)
        assert te.analyze_pixels(pixels, 8, 8) == _analyze_pure(pixels, 8, 8)

    def test_many_colors_saturates_at_257(self):
        out = bytearray()
        for i in range(400):
            out += bytes([i % 256, (i // 256) * 7, 3, 255])
        pixels = bytes(out)
        fast = te.analyze_pixels(pixels, 20, 20)
        pure = _analyze_pure(pixels, 20, 20)
        assert fast == pure
        assert fast['unique_color_count'] == 257

    def test_empty(self):
        assert te.analyze_pixels(b'', 0, 0) == _analyze_pure(b'', 0, 0)
