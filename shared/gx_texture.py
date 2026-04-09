"""GX texture format decoding and encoding — shared codec for all GX texture operations.

Provides tile-based decoders for all GameCube GX texture formats, plus a
high-level decode_texture() function that handles tile iteration, cropping,
and vertical flip.

Used by:
  - Image node (DAT texture import)
  - Particle texture import (GPT1)
  - Texture encoder (DAT texture export)
  - Tests (encode→decode round-trip)
"""
import array

try:
    from .Constants import gx
except (ImportError, SystemError):
    from shared.Constants import gx

# ---------------------------------------------------------------------------
# Tile dimensions and bits per pixel
# ---------------------------------------------------------------------------

CCC = 4  # Color component count (RGBA)

TILE_S_I4 = 8;      TILE_T_I4 = 8;      BITSPPX_I4 = 4
TILE_S_I8 = 8;      TILE_T_I8 = 4;      BITSPPX_I8 = 8
TILE_S_IA4 = 8;     TILE_T_IA4 = 4;     BITSPPX_IA4 = 8
TILE_S_IA8 = 4;     TILE_T_IA8 = 4;     BITSPPX_IA8 = 16
TILE_S_RGB565 = 4;  TILE_T_RGB565 = 4;  BITSPPX_RGB565 = 16
TILE_S_RGB5A3 = 4;  TILE_T_RGB5A3 = 4;  BITSPPX_RGB5A3 = 16
TILE_S_RGBA8 = 4;   TILE_T_RGBA8 = 4;   BITSPPX_RGBA8 = 32
TILE_S_CMPR = 8;    TILE_T_CMPR = 8;    BITSPPX_CMPR = 4
TILE_S_C4 = 8;      TILE_T_C4 = 8;      BITSPPX_C4 = 4
TILE_S_C8 = 8;      TILE_T_C8 = 4;      BITSPPX_C8 = 8
TILE_S_C14X2 = 4;   TILE_T_C14X2 = 4;   BITSPPX_C14X2 = 16


# ---------------------------------------------------------------------------
# Palette helper
# ---------------------------------------------------------------------------

def get_palette_color(palette, fmt):
    """Decode one palette entry to RGBA.

    Args:
        palette: memoryview or bytes slice starting at the palette entry (2+ bytes).
        fmt: Palette format (GX_TL_IA8, GX_TL_RGB565, GX_TL_RGB5A3).

    Returns:
        array.array of 4 u8 values (RGBA).
    """
    color = [0, 0, 0, 0]
    if len(palette) < 2:
        return array.array('B', color)
    if fmt == gx.GX_TL_IA8:
        color[0] = palette[1]
        color[1] = palette[1]
        color[2] = palette[1]
        color[3] = palette[0]
    elif fmt == gx.GX_TL_RGB565:
        color[0] = (palette[0] >> 3) * 0x8
        color[1] = (((palette[0] & 0x7) << 3) | (palette[1] >> 5)) * 0x4
        color[2] = (palette[1] & 0x1F) * 0x8
        color[3] = 0xFF
    elif fmt == gx.GX_TL_RGB5A3:
        if palette[0] & 0x80:
            color[0] = ((palette[0] >> 2) & 0x1F) * 0x8
            color[1] = (((palette[0] & 0x3) << 3) | (palette[1] >> 5)) * 0x8
            color[2] = (palette[1] & 0x1F) * 0x8
            color[3] = 0xFF
        else:
            color[0] = (palette[0] & 0xF) * 0x10
            color[1] = (palette[1] >> 4) * 0x10
            color[2] = (palette[1] & 0xF) * 0x10
            color[3] = ((palette[0] >> 4) & 0x7) * 0x20
    return array.array('B', color)


# ---------------------------------------------------------------------------
# Block decoder functions
# ---------------------------------------------------------------------------

def decode_I4_block(dst, src, blocks_x, _palette):
    c = 0; s = 0
    for _i in range(TILE_T_I4):
        for _j in range(TILE_S_I4 // 2):
            val = src[s] >> 4 << 4
            dst[c + 0] = val; dst[c + 1] = val; dst[c + 2] = val; dst[c + 3] = val
            val = (src[s] & 0xF) << 4
            dst[c + 4] = val; dst[c + 5] = val; dst[c + 6] = val; dst[c + 7] = val
            c += 2 * CCC; s += (BITSPPX_I4 * 2) >> 3
        c += (blocks_x - 1) * TILE_S_I4 * CCC


def decode_I8_block(dst, src, blocks_x, _palette):
    c = 0; s = 0
    for _i in range(TILE_T_I8):
        for _j in range(TILE_S_I8):
            val = src[s]
            dst[c + 0] = val; dst[c + 1] = val; dst[c + 2] = val; dst[c + 3] = val
            c += CCC; s += BITSPPX_I8 >> 3
        c += (blocks_x - 1) * TILE_S_I8 * CCC


def decode_IA4_block(dst, src, blocks_x, _palette):
    c = 0; s = 0
    for _i in range(TILE_T_IA4):
        for _j in range(TILE_S_IA4):
            val = (src[s] & 0xF) << 4
            dst[c + 0] = val; dst[c + 1] = val; dst[c + 2] = val
            dst[c + 3] = src[s] & 0xF0
            c += CCC; s += BITSPPX_IA4 >> 3
        c += (blocks_x - 1) * TILE_S_IA4 * CCC


def decode_IA8_block(dst, src, blocks_x, _palette):
    c = 0; s = 0
    for _i in range(TILE_T_IA8):
        for _j in range(TILE_S_IA8):
            val = src[s + 1]
            dst[c + 0] = val; dst[c + 1] = val; dst[c + 2] = val
            dst[c + 3] = src[s]
            c += CCC; s += BITSPPX_IA8 >> 3
        c += (blocks_x - 1) * TILE_S_IA8 * CCC


def decode_RGB565_block(dst, src, blocks_x, _palette):
    c = 0; s = 0
    for _i in range(TILE_T_RGB565):
        for _j in range(TILE_S_RGB565):
            dst[c + 0] = (src[s + 0] >> 3) * 0x8
            dst[c + 1] = (((src[s + 0] & 0x7) << 3) | (src[s + 1] >> 5)) * 0x4
            dst[c + 2] = (src[s + 1] & 0x1F) * 0x8
            dst[c + 3] = 0xFF
            c += CCC; s += BITSPPX_RGB565 >> 3
        c += (blocks_x - 1) * TILE_S_RGB565 * CCC


def decode_RGB5A3_block(dst, src, blocks_x, _palette):
    c = 0; s = 0
    for _i in range(TILE_T_RGB5A3):
        for _j in range(TILE_S_RGB5A3):
            if src[s + 0] & 0x80:
                dst[c + 0] = ((src[s + 0] >> 2) & 0x1F) * 0x8
                dst[c + 1] = (((src[s + 0] & 0x3) << 3) | (src[s + 1] >> 5)) * 0x8
                dst[c + 2] = (src[s + 1] & 0x1F) * 0x8
                dst[c + 3] = 0xFF
            else:
                dst[c + 0] = (src[s + 0] & 0xF) * 0x10
                dst[c + 1] = (src[s + 1] >> 4) * 0x10
                dst[c + 2] = (src[s + 1] & 0xF) * 0x10
                dst[c + 3] = ((src[s + 0] >> 4) & 0x7) * 0x20
            c += CCC; s += BITSPPX_RGB5A3 >> 3
        c += (blocks_x - 1) * TILE_S_RGB5A3 * CCC


def decode_RGBA8_block(dst, src, blocks_x, _palette):
    c = 0; s = 0
    for _i in range(TILE_T_RGBA8):
        for _j in range(TILE_S_RGBA8):
            dst[c + 0] = src[s + 1]
            dst[c + 1] = src[s + 32]
            dst[c + 2] = src[s + 33]
            dst[c + 3] = src[s + 0]
            c += CCC; s += 2
        c += (blocks_x - 1) * TILE_S_RGBA8 * CCC


def decode_CMPR_block(dst, src, blocks_x, _palette):
    c = 0; s = 0
    for _j in range(2):
        for _k in range(2):
            colors = [array.array('B', [0] * CCC) for _ in range(4)]
            colors[0][0] = (src[s + 0] >> 3) << 3
            colors[0][1] = (((src[s + 0] & 0x7) << 3) | ((src[s + 1] >> 5) & 0x7)) << 2
            colors[0][2] = (src[s + 1] & 0x1F) << 3
            colors[0][3] = 0xFF
            colors[1][0] = (src[s + 2] >> 3) << 3
            colors[1][1] = (((src[s + 2] & 0x7) << 3) | ((src[s + 3] >> 5) & 0x7)) << 2
            colors[1][2] = (src[s + 3] & 0x1F) << 3
            colors[1][3] = 0xFF
            c0 = (src[s + 0] << 8) | src[s + 1]
            c1 = (src[s + 2] << 8) | src[s + 3]
            if c0 > c1:
                colors[2][0] = (2 * colors[0][0] + colors[1][0]) // 3
                colors[2][1] = (2 * colors[0][1] + colors[1][1]) // 3
                colors[2][2] = (2 * colors[0][2] + colors[1][2]) // 3
                colors[2][3] = 0xFF
                colors[3][0] = (colors[0][0] + 2 * colors[1][0]) // 3
                colors[3][1] = (colors[0][1] + 2 * colors[1][1]) // 3
                colors[3][2] = (colors[0][2] + 2 * colors[1][2]) // 3
                colors[3][3] = 0xFF
            else:
                colors[2][0] = (colors[0][0] + colors[1][0]) // 2
                colors[2][1] = (colors[0][1] + colors[1][1]) // 2
                colors[2][2] = (colors[0][2] + colors[1][2]) // 2
                colors[2][3] = 0xFF
                colors[3][0] = (colors[0][0] + colors[1][0]) // 2
                colors[3][1] = (colors[0][1] + colors[1][1]) // 2
                colors[3][2] = (colors[0][2] + colors[1][2]) // 2
                colors[3][3] = 0x0
            s += 4
            cc = c
            for _l in range(4):
                dst[cc + 0 * CCC: cc + 4 * CCC] = (
                    colors[(src[s + _l] >> 6) & 0x3] +
                    colors[(src[s + _l] >> 4) & 0x3] +
                    colors[(src[s + _l] >> 2) & 0x3] +
                    colors[(src[s + _l] >> 0) & 0x3])
                cc += blocks_x * TILE_S_CMPR * CCC
            s += 4
            c += 4 * CCC
        c += (blocks_x * 4 - 1) * TILE_S_CMPR * CCC


def decode_C4_block(dst, src, blocks_x, tlut):
    palette = memoryview(tlut.raw_data)
    c = 0; s = 0
    for _i in range(TILE_T_C4):
        for _j in range(TILE_S_C4 // 2):
            dst[c + 0: c + CCC] = get_palette_color(palette[((src[s + 0] & 0xF0) >> 4) * 2:], tlut.format)
            dst[c + CCC: c + 2 * CCC] = get_palette_color(palette[(src[s + 0] & 0xF) * 2:], tlut.format)
            s += (BITSPPX_C4 * 2) >> 3; c += 2 * CCC
        c += (blocks_x - 1) * TILE_S_C4 * CCC


def decode_C8_block(dst, src, blocks_x, tlut):
    palette = memoryview(tlut.raw_data)
    c = 0; s = 0
    for _i in range(TILE_T_C8):
        for _j in range(TILE_S_C8):
            dst[c: c + CCC] = get_palette_color(palette[src[s] * 2:], tlut.format)
            s += BITSPPX_C8 >> 3; c += CCC
        c += (blocks_x - 1) * TILE_S_C8 * CCC


def decode_C14X2_block(dst, src, blocks_x, tlut):
    palette = memoryview(tlut.raw_data)
    c = 0; s = 0
    for _i in range(TILE_T_C14X2):
        for _j in range(TILE_S_C14X2):
            dst[c: c + CCC] = get_palette_color(palette[((src[s + 0] << 8) | src[s + 1]) * 2:], tlut.format)
            s += BITSPPX_C14X2 >> 3; c += CCC
        c += (blocks_x - 1) * TILE_S_C14X2 * CCC


# ---------------------------------------------------------------------------
# Format lookup table
# ---------------------------------------------------------------------------

FORMAT_INFO = {
    #                   bpp            tile_W        tile_H        decoder
    gx.GX_TF_I4:     (BITSPPX_I4,     TILE_S_I4,    TILE_T_I4,    decode_I4_block),
    gx.GX_TF_I8:     (BITSPPX_I8,     TILE_S_I8,    TILE_T_I8,    decode_I8_block),
    gx.GX_TF_IA4:    (BITSPPX_IA4,    TILE_S_IA4,   TILE_T_IA4,   decode_IA4_block),
    gx.GX_TF_IA8:    (BITSPPX_IA8,    TILE_S_IA8,   TILE_T_IA8,   decode_IA8_block),
    gx.GX_TF_RGB565: (BITSPPX_RGB565, TILE_S_RGB565,TILE_T_RGB565, decode_RGB565_block),
    gx.GX_TF_RGB5A3: (BITSPPX_RGB5A3, TILE_S_RGB5A3,TILE_T_RGB5A3, decode_RGB5A3_block),
    gx.GX_TF_RGBA8:  (BITSPPX_RGBA8,  TILE_S_RGBA8, TILE_T_RGBA8, decode_RGBA8_block),
    gx.GX_TF_CMPR:   (BITSPPX_CMPR,   TILE_S_CMPR,  TILE_T_CMPR,  decode_CMPR_block),
    gx.GX_TF_C4:     (BITSPPX_C4,     TILE_S_C4,    TILE_T_C4,    decode_C4_block),
    gx.GX_TF_C8:     (BITSPPX_C8,     TILE_S_C8,    TILE_T_C8,    decode_C8_block),
    gx.GX_TF_C14X2:  (BITSPPX_C14X2,  TILE_S_C14X2, TILE_T_C14X2, decode_C14X2_block),
}


# ---------------------------------------------------------------------------
# High-level decode function
# ---------------------------------------------------------------------------

def decode_texture(raw_data, width, height, format_id, palette=None):
    """Decode a GX texture from raw tile data into RGBA pixels.

    Handles tile iteration, padding to block boundaries, cropping to actual
    dimensions, and vertical flip (GX top-to-bottom → bottom-to-top for Blender).

    Args:
        raw_data: Raw GX tile bytes (bytes or bytearray).
        width: Texture width in pixels.
        height: Texture height in pixels.
        format_id: GX texture format ID (e.g. gx.GX_TF_RGBA8).
        palette: Palette node (with .raw_data and .format) for C4/C8/C14X2, or None.

    Returns:
        array.array of u8 RGBA values (width × height × 4), bottom-to-top row order.
        Returns None if format is unsupported or data is insufficient.
    """
    if format_id not in FORMAT_INFO:
        return None
    if width <= 0 or height <= 0:
        return None

    bpp, tile_w, tile_h, decode_func = FORMAT_INFO[format_id]
    blocks_x = (width + tile_w - 1) // tile_w
    blocks_y = (height + tile_h - 1) // tile_h
    tile_bytes = (tile_w * tile_h * bpp) >> 3

    needed = blocks_x * blocks_y * tile_bytes
    if len(raw_data) < needed:
        return None

    # Decode all tiles into padded buffer
    padded_w = blocks_x * tile_w
    padded_h = blocks_y * tile_h
    out = array.array('B', [0] * (padded_w * padded_h * CCC))
    buf = memoryview(out)
    src = memoryview(bytearray(raw_data))

    for _row in range(blocks_y):
        for _col in range(blocks_x):
            decode_func(buf, src, blocks_x, palette)
            src = src[tile_bytes:]
            buf = buf[CCC * tile_w:]
        buf = buf[CCC * blocks_x * tile_w * (tile_h - 1):]

    # Crop to actual dimensions and flip vertically
    decoded_stride = padded_w * CCC
    actual_stride = width * CCC
    cropped = array.array('B', [0] * (width * height * CCC))
    for row in range(height):
        src_start = row * decoded_stride
        dst_start = (height - 1 - row) * actual_stride
        cropped[dst_start:dst_start + actual_stride] = out[src_start:src_start + actual_stride]

    return cropped
