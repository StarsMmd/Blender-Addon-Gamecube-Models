"""Tests for GX texture format encoding.

Validates that each encoder produces data that the existing decoders
can read back correctly (encode-decode round-trip), and that the
pixel analysis and format selection work as expected.
"""
import array
import pytest

from shared.texture_encoder import (
    analyze_pixels, select_format, encode_texture,
    encode_i4, encode_i8, encode_ia4, encode_ia8,
    encode_rgb565, encode_rgb5a3, encode_rgba8, encode_cmpr,
    encode_c4, encode_c8,
)
from shared.Constants.gx import (
    GX_TF_I4, GX_TF_I8, GX_TF_IA4, GX_TF_IA8,
    GX_TF_RGB565, GX_TF_RGB5A3, GX_TF_RGBA8, GX_TF_CMPR,
    GX_TF_C4, GX_TF_C8,
)
from shared.Nodes.Classes.Texture.Image import (
    convert_I4_block, convert_I8_block, convert_IA4_block, convert_IA8_block,
    convert_RGB565_block, convert_RGB5A3_block, convert_RGBA8_block,
    convert_CMPR_block, convert_C4_block, convert_C8_block,
    format_dict, CCC,
)
from shared.IR.enums import GXTextureFormat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_solid_image(width, height, r, g, b, a=255):
    """Create a solid-color RGBA image (bottom-to-top)."""
    return bytes([r, g, b, a] * (width * height))


def _make_gradient_image(width, height):
    """Create an RGBA gradient image (bottom-to-top)."""
    pixels = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            off = (y * width + x) * 4
            pixels[off] = (x * 255) // max(width - 1, 1)
            pixels[off + 1] = (y * 255) // max(height - 1, 1)
            pixels[off + 2] = 128
            pixels[off + 3] = 255
    return bytes(pixels)


def _decode_tiles(encoded, width, height, fmt_id, palette=None):
    """Decode GX tile data back to RGBA using the import decoders.

    Returns RGBA bytes in top-to-bottom order (GX convention, pre-flip).
    """
    bpp, tile_s, tile_t, decode_func = format_dict[fmt_id]
    blocks_x = (width + tile_s - 1) // tile_s
    blocks_y = (height + tile_t - 1) // tile_t
    padded_w = blocks_x * tile_s
    padded_h = blocks_y * tile_t

    out = bytearray(padded_w * padded_h * CCC)
    dst = memoryview(out)
    src = memoryview(encoded)

    tile_bytes = (tile_s * tile_t * bpp) >> 3

    for by in range(blocks_y):
        for bx in range(blocks_x):
            tile_offset = (by * blocks_x + bx) * tile_bytes
            dst_offset = (by * tile_t * padded_w + bx * tile_s) * CCC
            decode_func(dst[dst_offset:], src[tile_offset:], blocks_x, palette)

    # Crop to actual dimensions and flip vertically (GX top-to-bottom → bottom-to-top)
    result = bytearray(width * height * CCC)
    for row in range(height):
        src_start = row * padded_w * CCC
        dst_start = (height - 1 - row) * width * CCC
        result[dst_start:dst_start + width * CCC] = out[src_start:src_start + width * CCC]

    return bytes(result)


def _max_diff(pixels_a, pixels_b):
    """Return the maximum per-channel difference between two pixel arrays."""
    max_d = 0
    for i in range(min(len(pixels_a), len(pixels_b))):
        max_d = max(max_d, abs(pixels_a[i] - pixels_b[i]))
    return max_d


# ---------------------------------------------------------------------------
# Pixel analysis tests
# ---------------------------------------------------------------------------

class TestPixelAnalysis:

    def test_solid_red(self):
        pixels = _make_solid_image(4, 4, 255, 0, 0)
        a = analyze_pixels(pixels, 4, 4)
        assert a['is_grayscale'] is False
        assert a['has_alpha'] is False
        assert a['unique_color_count'] == 1

    def test_grayscale(self):
        pixels = _make_solid_image(4, 4, 128, 128, 128)
        a = analyze_pixels(pixels, 4, 4)
        assert a['is_grayscale'] is True
        assert a['has_alpha'] is False

    def test_grayscale_with_alpha(self):
        pixels = _make_solid_image(4, 4, 128, 128, 128, 100)
        a = analyze_pixels(pixels, 4, 4)
        assert a['is_grayscale'] is True
        assert a['has_alpha'] is True
        assert a['alpha_is_binary'] is False

    def test_binary_alpha(self):
        pixels = bytes([255, 0, 0, 255] * 8 + [255, 0, 0, 0] * 8)
        a = analyze_pixels(pixels, 4, 4)
        assert a['has_alpha'] is True
        assert a['alpha_is_binary'] is True

    def test_gradient_colors(self):
        pixels = _make_gradient_image(8, 8)
        a = analyze_pixels(pixels, 8, 8)
        assert a['unique_color_count'] > 1
        assert a['is_grayscale'] is False


# ---------------------------------------------------------------------------
# Format selection tests
# ---------------------------------------------------------------------------

class TestFormatSelection:

    def test_default_is_cmpr(self):
        a = {'is_grayscale': False, 'has_alpha': False, 'unique_color_count': 100, 'alpha_is_binary': True}
        assert select_format(a) == GX_TF_CMPR

    def test_grayscale_alpha_selects_i8(self):
        a = {'is_grayscale': True, 'has_alpha': True, 'unique_color_count': 50, 'alpha_is_binary': False}
        assert select_format(a) == GX_TF_I8

    def test_few_colors_still_cmpr(self):
        """CMPR is the default even for low color count — matches original game behavior."""
        a = {'is_grayscale': False, 'has_alpha': False, 'unique_color_count': 5, 'alpha_is_binary': True}
        assert select_format(a) == GX_TF_CMPR

    def test_user_override(self):
        a = {'is_grayscale': False, 'has_alpha': False, 'unique_color_count': 100, 'alpha_is_binary': True}
        assert select_format(a, GXTextureFormat.RGBA8) == GX_TF_RGBA8
        assert select_format(a, GXTextureFormat.C8) == GX_TF_C8

    def test_auto_override_uses_heuristic(self):
        a = {'is_grayscale': False, 'has_alpha': False, 'unique_color_count': 100, 'alpha_is_binary': True}
        assert select_format(a, GXTextureFormat.AUTO) == GX_TF_CMPR


# ---------------------------------------------------------------------------
# Encode-decode round-trip tests
# ---------------------------------------------------------------------------

class TestEncodeDecodeRoundTrip:
    """Verify each encoder produces data the existing decoders can read back."""

    def test_rgba8_roundtrip(self):
        pixels = _make_solid_image(8, 8, 200, 100, 50)
        encoded = encode_rgba8(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_RGBA8)
        assert _max_diff(pixels, decoded) == 0

    def test_rgb565_roundtrip(self):
        pixels = _make_solid_image(8, 8, 200, 100, 50)
        encoded = encode_rgb565(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_RGB565)
        # RGB565 is lossy (5/6/5 bit quantization)
        assert _max_diff(pixels, decoded) <= 8

    def test_rgb5a3_opaque_roundtrip(self):
        pixels = _make_solid_image(8, 8, 200, 100, 50)
        encoded = encode_rgb5a3(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_RGB5A3)
        assert _max_diff(pixels, decoded) <= 8

    def test_rgb5a3_alpha_roundtrip(self):
        pixels = _make_solid_image(8, 8, 200, 100, 50, 128)
        encoded = encode_rgb5a3(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_RGB5A3)
        # Transparent mode uses 4-bit channels → more quantization
        assert _max_diff(pixels, decoded) <= 32

    def test_i8_roundtrip(self):
        # I8 stores intensity as R=G=B=A, so input alpha must equal intensity
        pixels = _make_solid_image(8, 8, 128, 128, 128, 128)
        encoded = encode_i8(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_I8)
        assert _max_diff(pixels, decoded) == 0

    def test_i4_roundtrip(self):
        # I4 stores intensity as R=G=B=A, input alpha must equal intensity
        pixels = _make_solid_image(8, 8, 128, 128, 128, 128)
        encoded = encode_i4(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_I4)
        # I4 is 4-bit quantized
        assert _max_diff(pixels, decoded) <= 16

    def test_ia8_roundtrip(self):
        pixels = _make_solid_image(8, 8, 100, 100, 100, 200)
        encoded = encode_ia8(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_IA8)
        assert _max_diff(pixels, decoded) == 0

    def test_ia4_roundtrip(self):
        pixels = _make_solid_image(8, 8, 128, 128, 128, 200)
        encoded = encode_ia4(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_IA4)
        # IA4 uses 4-bit quantization for both channels
        assert _max_diff(pixels, decoded) <= 16

    def test_cmpr_solid_roundtrip(self):
        pixels = _make_solid_image(8, 8, 200, 100, 50)
        encoded = encode_cmpr(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_CMPR)
        # CMPR/DXT1 is lossy — allow moderate difference
        assert _max_diff(pixels, decoded) <= 16

    def test_cmpr_gradient_roundtrip(self):
        pixels = _make_gradient_image(8, 8)
        encoded = encode_cmpr(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_CMPR)
        # Gradient is harder for DXT1 — allow generous tolerance
        assert _max_diff(pixels, decoded) <= 80

    def test_c4_roundtrip(self):
        """C4 with few colors should be lossless."""
        # 4 colors
        pixels = bytes(
            [255, 0, 0, 255] * 16 +
            [0, 255, 0, 255] * 16 +
            [0, 0, 255, 255] * 16 +
            [255, 255, 0, 255] * 16
        )
        tile_data, pal_data, pal_fmt, pal_count = encode_c4(pixels, 8, 8)
        # Build a mock palette for decoding
        pal = _MockPalette(pal_data, pal_fmt)
        decoded = _decode_tiles(tile_data, 8, 8, GX_TF_C4, palette=pal)
        # RGB5A3 palette has some quantization
        assert _max_diff(pixels, decoded) <= 8

    def test_c8_roundtrip(self):
        """C8 with moderate colors should be nearly lossless."""
        pixels = _make_gradient_image(8, 4)
        tile_data, pal_data, pal_fmt, pal_count = encode_c8(pixels, 8, 4)
        pal = _MockPalette(pal_data, pal_fmt)
        decoded = _decode_tiles(tile_data, 8, 4, GX_TF_C8, palette=pal)
        # Palette quantization from RGB5A3
        assert _max_diff(pixels, decoded) <= 8


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_single_pixel(self):
        pixels = bytes([255, 128, 64, 255])
        result = encode_texture(pixels, 1, 1, GX_TF_CMPR)
        assert len(result['image_data']) == 32  # Minimum CMPR block

    def test_non_power_of_two(self):
        pixels = _make_solid_image(5, 3, 100, 100, 100)
        result = encode_texture(pixels, 5, 3, GX_TF_RGBA8)
        assert len(result['image_data']) > 0

    def test_single_color_cmpr(self):
        pixels = _make_solid_image(8, 8, 0, 0, 0)
        encoded = encode_cmpr(pixels, 8, 8)
        decoded = _decode_tiles(encoded, 8, 8, GX_TF_CMPR)
        assert _max_diff(pixels, decoded) <= 8

    def test_dispatch_returns_palette_for_c4(self):
        pixels = _make_solid_image(8, 8, 255, 0, 0)
        result = encode_texture(pixels, 8, 8, GX_TF_C4)
        assert result['palette_data'] is not None
        assert result['palette_count'] >= 1

    def test_dispatch_no_palette_for_cmpr(self):
        pixels = _make_solid_image(8, 8, 255, 0, 0)
        result = encode_texture(pixels, 8, 8, GX_TF_CMPR)
        assert result['palette_data'] is None


# ---------------------------------------------------------------------------
# Mock palette for C4/C8 decode tests
# ---------------------------------------------------------------------------

class _MockPalette:
    """Mimics the Palette node interface for decode testing."""
    def __init__(self, raw_data, fmt):
        self.raw_data = raw_data
        self.format = fmt
