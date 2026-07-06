"""GX texture format encoders.

Encodes RGBA u8 pixel data into GameCube GX texture formats. Each encoder
handles the tiled layout, pixel format conversion, and vertical flip
(IR bottom-to-top → GX top-to-bottom) for its format.

Provides pixel analysis and format selection for automatic format choice.
"""
import struct

# numpy accelerates the CMPR hot path (whole-image vectorized encode) and
# pixel analysis. It ships with Blender and the bpy wheel; the pure-Python
# paths below remain the fallback so shared/ stays importable without it.
try:
    import numpy as _np
except ImportError:
    _np = None

try:
    from .Constants.gx import (
        GX_TF_I4, GX_TF_I8, GX_TF_IA4, GX_TF_IA8,
        GX_TF_RGB565, GX_TF_RGB5A3, GX_TF_RGBA8, GX_TF_CMPR,
        GX_TF_C4, GX_TF_C8, GX_TF_C14X2,
        GX_TL_IA8, GX_TL_RGB565, GX_TL_RGB5A3,
    )
except (ImportError, SystemError):
    from Constants.gx import (
        GX_TF_I4, GX_TF_I8, GX_TF_IA4, GX_TF_IA8,
        GX_TF_RGB565, GX_TF_RGB5A3, GX_TF_RGBA8, GX_TF_CMPR,
        GX_TF_C4, GX_TF_C8, GX_TF_C14X2,
        GX_TL_IA8, GX_TL_RGB565, GX_TL_RGB5A3,
    )


# ---------------------------------------------------------------------------
# Pixel analysis
# ---------------------------------------------------------------------------

def analyze_pixels(pixels, width, height):
    """Analyze RGBA u8 pixel data for format selection.

    Args:
        pixels: bytes — RGBA u8 data, bottom-to-top row order.
        width: Image width.
        height: Image height.

    Returns:
        dict with keys: is_grayscale, has_alpha, unique_color_count, alpha_is_binary
    """
    if _np is not None:
        return _analyze_pixels_numpy(pixels, width, height)
    is_grayscale = True
    has_alpha = False
    alpha_is_binary = True
    colors = set()
    max_colors = 257  # Stop counting after this (enough to distinguish C4/C8/more)

    pixel_count = width * height
    for i in range(pixel_count):
        off = i * 4
        if off + 3 >= len(pixels):
            break
        r, g, b, a = pixels[off], pixels[off + 1], pixels[off + 2], pixels[off + 3]

        if r != g or g != b:
            is_grayscale = False
        if a != 255:
            has_alpha = True
            if a != 0:
                alpha_is_binary = False
        if len(colors) < max_colors:
            colors.add((r, g, b, a))

    return {
        'is_grayscale': is_grayscale,
        'has_alpha': has_alpha,
        'unique_color_count': len(colors),
        'alpha_is_binary': alpha_is_binary,
    }


def _analyze_pixels_numpy(pixels, width, height):
    """Vectorized analyze_pixels — same results as the pure-Python loop
    (unique_color_count saturates at 257, matching its early-stop cap)."""
    np = _np
    n = min(width * height, len(pixels) // 4)
    arr = np.frombuffer(bytes(pixels[:n * 4]), dtype=np.uint8).reshape(n, 4)
    r, g, b, a = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3]
    non_opaque = a != 255
    rgba32 = (r.astype(np.uint32) << 24) | (g.astype(np.uint32) << 16) \
        | (b.astype(np.uint32) << 8) | a
    return {
        'is_grayscale': bool(((r == g) & (g == b)).all()),
        'has_alpha': bool(non_opaque.any()),
        'unique_color_count': min(int(np.unique(rgba32).size), 257),
        'alpha_is_binary': not bool((non_opaque & (a != 0)).any()),
    }


def select_format(analysis, user_override=None):
    """Select the best GX texture format based on pixel analysis.

    Matches original developer behavior: CMPR is the default for almost
    everything. Other formats are only selected for specific pixel
    characteristics or via explicit user override.

    Args:
        analysis: dict from analyze_pixels().
        user_override: GXTextureFormat enum value, or None for auto.

    Returns:
        int — GX format ID.
    """
    # User override takes priority
    if user_override is not None:
        from .IR.enums import GXTextureFormat
        if user_override != GXTextureFormat.AUTO:
            return _FORMAT_ENUM_TO_ID.get(user_override, GX_TF_CMPR)

    # Grayscale with alpha → I8 (stores intensity as both RGB and alpha)
    if analysis['is_grayscale'] and analysis['has_alpha']:
        return GX_TF_I8

    # Default: CMPR — matches 73-98% of original game textures
    return GX_TF_CMPR


# ---------------------------------------------------------------------------
# Pixel accessor (handles vertical flip: IR bottom-to-top → GX top-to-bottom)
# ---------------------------------------------------------------------------

def _get_pixel(pixels, width, height, x, y):
    """Get RGBA values for a pixel, flipping Y for GX convention.

    Returns (r, g, b, a) or (0, 0, 0, 0) if out of bounds.
    """
    # Flip Y: GX is top-to-bottom, IR is bottom-to-top
    flipped_y = (height - 1) - y
    if x < 0 or x >= width or flipped_y < 0 or flipped_y >= height:
        return 0, 0, 0, 0
    off = (flipped_y * width + x) * 4
    if off + 3 >= len(pixels):
        return 0, 0, 0, 0
    return pixels[off], pixels[off + 1], pixels[off + 2], pixels[off + 3]


# ---------------------------------------------------------------------------
# Encoders
# ---------------------------------------------------------------------------

def encode_i4(pixels, width, height):
    """Encode as I4 — 4bpp grayscale, 8x8 tiles."""
    tw, th = 8, 8
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * (tw * th * 4 // 8))
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            for py in range(th):
                for px in range(0, tw, 2):
                    x0 = bx * tw + px
                    y0 = by * th + py
                    r0, _, _, _ = _get_pixel(pixels, width, height, x0, y0)
                    r1, _, _, _ = _get_pixel(pixels, width, height, x0 + 1, y0)
                    out[idx] = ((r0 >> 4) << 4) | (r1 >> 4)
                    idx += 1
    return bytes(out[:idx])


def encode_i8(pixels, width, height):
    """Encode as I8 — 8bpp grayscale (intensity = alpha on decode), 8x4 tiles."""
    tw, th = 8, 4
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * tw * th)
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            for py in range(th):
                for px in range(tw):
                    r, _, _, _ = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    out[idx] = r
                    idx += 1
    return bytes(out[:idx])


def encode_ia4(pixels, width, height):
    """Encode as IA4 — 8bpp (4-bit intensity + 4-bit alpha), 8x4 tiles."""
    tw, th = 8, 4
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * tw * th)
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            for py in range(th):
                for px in range(tw):
                    r, _, _, a = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    out[idx] = (a & 0xF0) | (r >> 4)
                    idx += 1
    return bytes(out[:idx])


def encode_ia8(pixels, width, height):
    """Encode as IA8 — 16bpp (8-bit alpha + 8-bit intensity), 4x4 tiles."""
    tw, th = 4, 4
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * tw * th * 2)
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            for py in range(th):
                for px in range(tw):
                    r, _, _, a = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    out[idx] = a
                    out[idx + 1] = r
                    idx += 2
    return bytes(out[:idx])


def encode_rgb565(pixels, width, height):
    """Encode as RGB565 — 16bpp (R5:G6:B5, no alpha), 4x4 tiles."""
    tw, th = 4, 4
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * tw * th * 2)
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            for py in range(th):
                for px in range(tw):
                    r, g, b, _ = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    r5 = r >> 3
                    g6 = g >> 2
                    b5 = b >> 3
                    val = (r5 << 11) | (g6 << 5) | b5
                    out[idx] = val >> 8
                    out[idx + 1] = val & 0xFF
                    idx += 2
    return bytes(out[:idx])


def encode_rgb5a3(pixels, width, height):
    """Encode as RGB5A3 — 16bpp (opaque: 1:R5:G5:B5, transparent: 0:A3:R4:G4:B4), 4x4 tiles."""
    tw, th = 4, 4
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * tw * th * 2)
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            for py in range(th):
                for px in range(tw):
                    r, g, b, a = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    if a == 255:
                        # Opaque: 1RRRRRGGGGGBBBBB
                        val = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
                    else:
                        # Transparent: 0AARRRRGGGGBBBB
                        val = ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
                    out[idx] = val >> 8
                    out[idx + 1] = val & 0xFF
                    idx += 2
    return bytes(out[:idx])


def encode_rgba8(pixels, width, height):
    """Encode as RGBA8 — 32bpp, 4x4 tiles with AR+GB halves."""
    tw, th = 4, 4
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * tw * th * 4)
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            # AR half
            for py in range(th):
                for px in range(tw):
                    r, _, _, a = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    out[idx] = a
                    out[idx + 1] = r
                    idx += 2
            # GB half
            for py in range(th):
                for px in range(tw):
                    _, g, b, _ = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    out[idx] = g
                    out[idx + 1] = b
                    idx += 2
    return bytes(out[:idx])


def encode_cmpr(pixels, width, height):
    """Encode as CMPR — 4bpp S3TC/DXT1 compressed, 8x8 macro-tiles of four 4x4 sub-blocks."""
    if _np is not None:
        return _encode_cmpr_numpy(pixels, width, height)
    tw, th = 8, 8  # macro-tile
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * 32)  # 32 bytes per macro-tile
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            # Four 4x4 sub-blocks within the 8x8 macro-tile
            for sy in range(2):
                for sx in range(2):
                    block_x = bx * 8 + sx * 4
                    block_y = by * 8 + sy * 4
                    _encode_dxt1_block(pixels, width, height, block_x, block_y, out, idx)
                    idx += 8
    return bytes(out[:idx])


def _encode_cmpr_numpy(pixels, width, height):
    """Vectorized CMPR encode — byte-identical to the _encode_dxt1_block loop.

    Every choice the per-block encoder makes by scan order (first-occurrence
    color dedup, first-strictly-greatest endpoint pair, first-minimum palette
    index) is reproduced with row-major argmax/argmin, which also return the
    first extremum. Blocks are processed in chunks to bound the (chunk, 16,
    16) pairwise intermediates.
    """
    np = _np
    bw = (width + 7) // 8
    bh = (height + 7) // 8

    # Source pixels padded/truncated to width*height*4 (a trailing partial
    # pixel reads as zeros, like _get_pixel), flipped to GX top-to-bottom.
    buf = np.zeros(width * height * 4, dtype=np.uint8)
    src = np.frombuffer(bytes(pixels[:width * height * 4]), dtype=np.uint8)
    usable = (len(src) // 4) * 4
    buf[:usable] = src[:usable]
    img = buf.reshape(height, width, 4)[::-1]

    # Pad to 8-multiples with (0,0,0,0) — out-of-bounds pixels are
    # transparent black, like _get_pixel. Carve into 4x4 sub-blocks in
    # (macro-row, macro-col, sub-row, sub-col) emission order.
    padded = np.zeros((bh * 8, bw * 8, 4), dtype=np.uint8)
    padded[:height, :width] = img
    blocks = (padded.reshape(bh, 2, 4, bw, 2, 4, 4)
                    .transpose(0, 3, 1, 4, 2, 5, 6)
                    .reshape(bh * bw * 4, 16, 4)
                    .astype(np.int32))

    n = blocks.shape[0]
    out = np.empty((n, 8), dtype=np.uint8)
    tri = np.tril(np.ones((16, 16), dtype=bool), -1)  # tri[i, j] = j < i
    chunk = 4096
    for start in range(0, n, chunk):
        _encode_cmpr_chunk(np, blocks[start:start + chunk], tri,
                           out[start:start + chunk])
    return out.tobytes()


def _encode_cmpr_chunk(np, b, tri, out):
    """Encode one chunk of 4x4 blocks; writes 8 bytes per block into out."""
    r, g, bl, a = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    opaque = a >= 0x80
    c565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (bl >> 3)  # (m, 16)
    m = b.shape[0]
    rows = np.arange(m)

    # Unique-color mask: pixel i stands for its RGB565 value when it is
    # opaque and no earlier opaque pixel j<i has the same value. Pairs of
    # such pixels enumerate the unique-color pairs in the same order the
    # per-block encoder scans them.
    same = c565[:, :, None] == c565[:, None, :]
    dup = (same & opaque[:, None, :] & tri[None]).any(axis=2)
    valid = opaque & ~dup

    # Endpoint pair: greatest RGB565 distance (after RGB888 expansion),
    # first pair wins ties — row-major argmax mirrors the nested scan.
    dr = ((c565 >> 11) & 0x1F) << 3
    dg = ((c565 >> 5) & 0x3F) << 2
    db = (c565 & 0x1F) << 3
    dist = (np.abs(dr[:, :, None] - dr[:, None, :])
            + np.abs(dg[:, :, None] - dg[:, None, :])
            + np.abs(db[:, :, None] - db[:, None, :]))
    pair_ok = valid[:, :, None] & valid[:, None, :]
    best = np.where(pair_ok, dist, -1).reshape(m, 256).argmax(axis=1)
    bc0 = c565[rows, best // 16]
    bc1 = c565[rows, best % 16]

    # Transparent blocks need c0 <= c1; opaque blocks need c0 > c1.
    has_transp = (~opaque).any(axis=1)
    lo = np.minimum(bc0, bc1)
    hi = np.maximum(bc0, bc1)
    hex1 = np.where(has_transp, lo, hi)
    hex2 = np.where(has_transp, hi, lo)

    def _expand565(v):
        return np.stack((((v >> 11) & 0x1F) << 3,
                         ((v >> 5) & 0x3F) << 2,
                         (v & 0x1F) << 3), axis=1)

    p0 = _expand565(hex1)  # (m, 3)
    p1 = _expand565(hex2)
    four_color = (hex1 > hex2)[:, None]
    pal = np.empty((m, 4, 3), dtype=np.int32)
    pal[:, 0] = p0
    pal[:, 1] = p1
    pal[:, 2] = np.where(four_color, (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3] = np.where(four_color, (2 * p1 + p0) // 3, 0)

    # Closest palette entry (Manhattan on RGB), first minimum wins ties;
    # transparent pixels always take index 3.
    pdist = (np.abs(r[:, :, None] - pal[:, None, :, 0])
             + np.abs(g[:, :, None] - pal[:, None, :, 1])
             + np.abs(bl[:, :, None] - pal[:, None, :, 2]))
    idx = np.where(opaque, pdist.argmin(axis=2), 3).reshape(m, 4, 4)

    row_bytes = (idx[:, :, 0] << 6) | (idx[:, :, 1] << 4) \
        | (idx[:, :, 2] << 2) | idx[:, :, 3]
    out[:, 0] = hex1 >> 8
    out[:, 1] = hex1 & 0xFF
    out[:, 2] = hex2 >> 8
    out[:, 3] = hex2 & 0xFF
    out[:, 4:8] = row_bytes

    # Fully transparent block — null endpoints, all indices 3.
    sentinel = ~valid.any(axis=1)
    out[sentinel, 0:4] = 0
    out[sentinel, 4:8] = 0xFF


def _encode_dxt1_block(pixels, width, height, block_x, block_y, out, idx):
    """Encode a single 4x4 DXT1 sub-block at the given position.

    Mirrors the GoD-Tool CMPR encoder:
    - Dedup colors into RGB565 before picking endpoints, so near-duplicate
      RGB888 values that quantize to the same 565 value are collapsed.
    - Pick endpoints by greatest RGB565 distance across unique colors.
    - Use 3-color + alpha mode (c0 <= c1) when any pixel is transparent;
      index 3 carries the transparent color.
    - Uniform blocks fall through naturally: one unique color ⇒ c0 == c1,
      palette entries 0..2 all equal, every opaque pixel picks index 0.
      No bit-level c0 += 1 bump, no RGB565 field-boundary corruption.
    """
    block = []
    for py in range(4):
        for px in range(4):
            block.append(_get_pixel(pixels, width, height,
                                    block_x + px, block_y + py))

    has_transparency = False
    unique_rgb565 = []
    for r, g, b, a in block:
        if a < 0x80:
            has_transparency = True
            continue
        c = _rgb_to_565(r, g, b)
        if c not in unique_rgb565:
            unique_rgb565.append(c)

    # Fully transparent block — emit a null-endpoint sentinel with every
    # index set to 3 so every pixel decodes transparent.
    if not unique_rgb565:
        out[idx] = 0
        out[idx + 1] = 0
        out[idx + 2] = 0
        out[idx + 3] = 0
        out[idx + 4] = 0xFF
        out[idx + 5] = 0xFF
        out[idx + 6] = 0xFF
        out[idx + 7] = 0xFF
        return

    # Pick endpoints by greatest RGB565 distance across unique colors.
    best_c0 = best_c1 = unique_rgb565[0]
    if len(unique_rgb565) > 1:
        greatest = -1
        for c0 in unique_rgb565:
            for c1 in unique_rgb565:
                d = _rgb565_distance(c0, c1)
                if d > greatest:
                    greatest = d
                    best_c0, best_c1 = c0, c1

    # Transparent blocks need c0 <= c1; opaque blocks need c0 > c1.
    if has_transparency:
        hex1, hex2 = min(best_c0, best_c1), max(best_c0, best_c1)
    else:
        hex1, hex2 = max(best_c0, best_c1), min(best_c0, best_c1)

    pc1 = _decode_rgb565(hex1)
    pc2 = _decode_rgb565(hex2)
    palette = [pc1, pc2, (0, 0, 0, 0xFF), (0, 0, 0, 0xFF)]
    if hex1 > hex2:
        palette[2] = ((2 * pc1[0] + pc2[0]) // 3,
                      (2 * pc1[1] + pc2[1]) // 3,
                      (2 * pc1[2] + pc2[2]) // 3, 0xFF)
        palette[3] = ((2 * pc2[0] + pc1[0]) // 3,
                      (2 * pc2[1] + pc1[1]) // 3,
                      (2 * pc2[2] + pc1[2]) // 3, 0xFF)
    else:
        palette[2] = ((pc1[0] + pc2[0]) // 2,
                      (pc1[1] + pc2[1]) // 2,
                      (pc1[2] + pc2[2]) // 2, 0xFF)
        palette[3] = (0, 0, 0, 0)

    # Closest-palette selection (Manhattan on RGB). Transparent pixels
    # always get index 3.
    index_bits = 0
    for r, g, b, a in block:
        index_bits <<= 2
        if a < 0x80:
            index_bits |= 3
        else:
            best_idx = 0
            min_dist = 1 << 30
            for j, (pr, pg, pb, _pa) in enumerate(palette):
                d = abs(r - pr) + abs(g - pg) + abs(b - pb)
                if d < min_dist:
                    min_dist = d
                    best_idx = j
            index_bits |= best_idx

    out[idx] = hex1 >> 8
    out[idx + 1] = hex1 & 0xFF
    out[idx + 2] = hex2 >> 8
    out[idx + 3] = hex2 & 0xFF
    out[idx + 4] = (index_bits >> 24) & 0xFF
    out[idx + 5] = (index_bits >> 16) & 0xFF
    out[idx + 6] = (index_bits >> 8) & 0xFF
    out[idx + 7] = index_bits & 0xFF


def _rgb_to_565(r, g, b):
    """Convert RGB888 to RGB565."""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _decode_rgb565(raw):
    """Inverse of _rgb_to_565 — returns (r, g, b, 0xFF) in RGB888."""
    r = ((raw >> 11) & 0x1F) << 3
    g = ((raw >> 5) & 0x3F) << 2
    b = (raw & 0x1F) << 3
    return r, g, b, 0xFF


def _rgb565_distance(c0, c1):
    """Manhattan distance between two RGB565 values after RGB888 decode."""
    a = _decode_rgb565(c0)
    b = _decode_rgb565(c1)
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


# ---------------------------------------------------------------------------
# Palette-indexed format encoders
# ---------------------------------------------------------------------------

def encode_c4(pixels, width, height, palette_format=None):
    """Encode as C4 — 4bpp palette-indexed, 8x8 tiles. Max 16 colors.

    palette_format: GX_TL_* id, or None to default to RGB5A3.

    Returns:
        (tile_data, palette_data, palette_format, entry_count)
    """
    palette, index_map = _build_palette(pixels, width, height, max_colors=16)
    tw, th = 8, 8
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * (tw * th // 2))
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            for py in range(th):
                for px in range(0, tw, 2):
                    r0, g0, b0, a0 = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    r1, g1, b1, a1 = _get_pixel(pixels, width, height, bx * tw + px + 1, by * th + py)
                    i0 = index_map.get((r0, g0, b0, a0), 0)
                    i1 = index_map.get((r1, g1, b1, a1), 0)
                    out[idx] = (i0 << 4) | i1
                    idx += 1
    pal_fmt = palette_format if palette_format is not None else GX_TL_RGB5A3
    pal_data = _encode_palette(palette, pal_fmt)
    return bytes(out[:idx]), pal_data, pal_fmt, len(palette)


def encode_c8(pixels, width, height, palette_format=None):
    """Encode as C8 — 8bpp palette-indexed, 8x4 tiles. Max 256 colors.

    palette_format: GX_TL_* id, or None to default to RGB5A3.

    Returns:
        (tile_data, palette_data, palette_format, entry_count)
    """
    palette, index_map = _build_palette(pixels, width, height, max_colors=256)
    tw, th = 8, 4
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * tw * th)
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            for py in range(th):
                for px in range(tw):
                    r, g, b, a = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    out[idx] = index_map.get((r, g, b, a), 0)
                    idx += 1
    pal_fmt = palette_format if palette_format is not None else GX_TL_RGB5A3
    pal_data = _encode_palette(palette, pal_fmt)
    return bytes(out[:idx]), pal_data, pal_fmt, len(palette)


def encode_c14x2(pixels, width, height, palette_format=None):
    """Encode as C14X2 — 16bpp palette-indexed, 4x4 tiles. Max 16384 colors.

    palette_format: GX_TL_* id, or None to default to RGB5A3.

    Returns:
        (tile_data, palette_data, palette_format, entry_count)
    """
    palette, index_map = _build_palette(pixels, width, height, max_colors=16384)
    tw, th = 4, 4
    bw = (width + tw - 1) // tw
    bh = (height + th - 1) // th
    out = bytearray(bw * bh * tw * th * 2)
    idx = 0
    for by in range(bh):
        for bx in range(bw):
            for py in range(th):
                for px in range(tw):
                    r, g, b, a = _get_pixel(pixels, width, height, bx * tw + px, by * th + py)
                    ci = index_map.get((r, g, b, a), 0)
                    out[idx] = ci >> 8
                    out[idx + 1] = ci & 0xFF
                    idx += 2
    pal_fmt = palette_format if palette_format is not None else GX_TL_RGB5A3
    pal_data = _encode_palette(palette, pal_fmt)
    return bytes(out[:idx]), pal_data, pal_fmt, len(palette)


def _build_palette(pixels, width, height, max_colors):
    """Build a color palette from pixel data.

    Returns:
        (palette_list, index_map) where palette_list is a list of (r,g,b,a)
        and index_map maps (r,g,b,a) → palette index.
    """
    colors = []
    index_map = {}
    pixel_count = width * height
    for i in range(pixel_count):
        off = i * 4
        if off + 3 >= len(pixels):
            break
        key = (pixels[off], pixels[off + 1], pixels[off + 2], pixels[off + 3])
        if key not in index_map:
            if len(colors) >= max_colors:
                continue  # Drop extra colors (shouldn't happen if analysis is correct)
            index_map[key] = len(colors)
            colors.append(key)
    return colors, index_map


def _encode_palette_ia8(palette):
    """Encode a palette as IA8 (format 0) — 2 bytes per entry: [alpha, intensity].

    IA8 is grayscale-only; RGB is collapsed to a single intensity (the
    inverse of get_palette_color, which expands intensity into R=G=B).
    """
    out = bytearray(len(palette) * 2)
    for i, (r, g, b, a) in enumerate(palette):
        out[i * 2] = a
        out[i * 2 + 1] = round((r + g + b) / 3)
    return bytes(out)


def _encode_palette_rgb565(palette):
    """Encode a palette as RGB565 (format 1) — 2 bytes per entry, big-endian.

    RGB565 has no alpha channel; alpha is discarded.
    """
    out = bytearray(len(palette) * 2)
    for i, (r, g, b, a) in enumerate(palette):
        val = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        out[i * 2] = val >> 8
        out[i * 2 + 1] = val & 0xFF
    return bytes(out)


def _encode_palette_rgb5a3(palette):
    """Encode a palette as RGB5A3 (format 2) — 2 bytes per entry."""
    out = bytearray(len(palette) * 2)
    for i, (r, g, b, a) in enumerate(palette):
        if a == 255:
            val = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
        else:
            val = ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
        out[i * 2] = val >> 8
        out[i * 2 + 1] = val & 0xFF
    return bytes(out)


def _encode_palette(palette, palette_format):
    """Encode a palette list in the given GX TLUT format (GX_TL_* id)."""
    if palette_format == GX_TL_IA8:
        return _encode_palette_ia8(palette)
    if palette_format == GX_TL_RGB565:
        return _encode_palette_rgb565(palette)
    return _encode_palette_rgb5a3(palette)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def encode_texture(pixels, width, height, format_id, palette_format=None):
    """Encode pixels into the specified GX texture format.

    Args:
        pixels: bytes — RGBA u8 data, bottom-to-top row order.
        width: Image width.
        height: Image height.
        format_id: GX texture format constant (e.g. GX_TF_CMPR).
        palette_format: GX_TL_* id for indexed formats, or None to default
            to RGB5A3. Ignored for non-indexed formats.

    Returns:
        dict with keys:
            image_data: bytes — encoded tile data
            palette_data: bytes | None — encoded palette (C4/C8/C14X2 only)
            palette_format: int | None — palette format ID
            palette_count: int | None — number of palette entries
    """
    if format_id == GX_TF_C4:
        tile_data, pal_data, pal_fmt, pal_count = encode_c4(pixels, width, height, palette_format)
        return {'image_data': tile_data, 'palette_data': pal_data,
                'palette_format': pal_fmt, 'palette_count': pal_count}
    elif format_id == GX_TF_C8:
        tile_data, pal_data, pal_fmt, pal_count = encode_c8(pixels, width, height, palette_format)
        return {'image_data': tile_data, 'palette_data': pal_data,
                'palette_format': pal_fmt, 'palette_count': pal_count}
    elif format_id == GX_TF_C14X2:
        tile_data, pal_data, pal_fmt, pal_count = encode_c14x2(pixels, width, height, palette_format)
        return {'image_data': tile_data, 'palette_data': pal_data,
                'palette_format': pal_fmt, 'palette_count': pal_count}

    encoder = _ENCODERS.get(format_id)
    if encoder is None:
        raise ValueError(f"Unsupported GX texture format: {format_id}")

    image_data = encoder(pixels, width, height)
    return {'image_data': image_data, 'palette_data': None,
            'palette_format': None, 'palette_count': None}


_ENCODERS = {
    GX_TF_I4: encode_i4,
    GX_TF_I8: encode_i8,
    GX_TF_IA4: encode_ia4,
    GX_TF_IA8: encode_ia8,
    GX_TF_RGB565: encode_rgb565,
    GX_TF_RGB5A3: encode_rgb5a3,
    GX_TF_RGBA8: encode_rgba8,
    GX_TF_CMPR: encode_cmpr,
}


# Mapping from GXTextureFormat enum to GX format IDs
_FORMAT_ENUM_TO_ID = {}
try:
    from .IR.enums import GXTextureFormat
    _FORMAT_ENUM_TO_ID = {
        GXTextureFormat.I4: GX_TF_I4,
        GXTextureFormat.I8: GX_TF_I8,
        GXTextureFormat.IA4: GX_TF_IA4,
        GXTextureFormat.IA8: GX_TF_IA8,
        GXTextureFormat.RGB565: GX_TF_RGB565,
        GXTextureFormat.RGB5A3: GX_TF_RGB5A3,
        GXTextureFormat.RGBA8: GX_TF_RGBA8,
        GXTextureFormat.CMPR: GX_TF_CMPR,
        GXTextureFormat.C4: GX_TF_C4,
        GXTextureFormat.C8: GX_TF_C8,
        GXTextureFormat.C14X2: GX_TF_C14X2,
    }
except (ImportError, SystemError):
    pass


# Mapping from GXPaletteFormat enum to GX TLUT format IDs
_PALETTE_FORMAT_ENUM_TO_ID = {}
try:
    from .IR.enums import GXPaletteFormat
    _PALETTE_FORMAT_ENUM_TO_ID = {
        GXPaletteFormat.IA8: GX_TL_IA8,
        GXPaletteFormat.RGB565: GX_TL_RGB565,
        GXPaletteFormat.RGB5A3: GX_TL_RGB5A3,
    }
except (ImportError, SystemError):
    pass


def select_palette_format(user_override=None):
    """Resolve a palette TLUT format ID from an optional GXPaletteFormat.

    Args:
        user_override: GXPaletteFormat enum value, or None for auto.

    Returns:
        GX_TL_* id, or None to let the encoder use its default (RGB5A3).
    """
    if user_override is None:
        return None
    from .IR.enums import GXPaletteFormat
    if user_override == GXPaletteFormat.AUTO:
        return None
    return _PALETTE_FORMAT_ENUM_TO_ID.get(user_override)
