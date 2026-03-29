"""Phase 1 — Container Extraction: raw file bytes → DAT bytes.

Detects the container format (.dat, .pkx, .fsys) and extracts
the raw DAT model bytes, stripping any container headers.
"""
from dataclasses import dataclass, field

try:
    from ....shared.helpers.binary import read
except (ImportError, SystemError):
    from shared.helpers.binary import read

try:
    from .helpers.fsys import is_fsys, parse_fsys
except (ImportError, SystemError):
    from importer.phases.extract.helpers.fsys import is_fsys, parse_fsys


@dataclass
class ContainerMetadata:
    """Metadata about the source container."""
    filename: str
    shiny_params: dict | None = None


def extract_dat(raw_bytes, filename, options=None):
    """Extract DAT bytes from raw file contents.

    Args:
        raw_bytes: Complete file contents as bytes.
        filename: Original filename (used to detect container type by extension).
        options: dict of importer options (optional). When include_shiny is True,
                 shiny color parameters are extracted from PKX headers.

    Returns:
        list of (dat_bytes, ContainerMetadata) tuples.
        A .dat/.pkx yields one entry. A .fsys yields one per model inside.
    """
    if options is None:
        options = {}

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    if ext == 'fsys' or is_fsys(raw_bytes):
        return _extract_fsys(raw_bytes, filename, options)
    elif ext == 'pkx':
        return _extract_pkx(raw_bytes, filename, options)
    else:
        # .dat, .fdat, .rdat — pass through unchanged
        metadata = ContainerMetadata(filename=filename)
        return [(raw_bytes, metadata)]


def _extract_pkx(raw, filename, options):
    """Extract DAT bytes from a PKX container.

    PKX files have a header before the DAT data:
    - Colosseum: 0x40 byte header
    - XD: 0xE60 byte header + optional GPT1 chunk
    """
    # Detect XD vs Colosseum: compare first 4 bytes at offset 0 vs 0x40
    val_0 = read('uint', raw, 0)
    val_40 = read('uint', raw, 0x40)
    is_xd = val_0 != val_40

    # Extract shiny params before stripping header (offsets are relative to full PKX)
    shiny_params = None
    if options.get("include_shiny"):
        shiny_params = _extract_shiny_params(raw, is_xd)

    if is_xd:
        header_size = 0xE60
        gpt1_size = read('uint', raw, 8)
        if gpt1_size > 0:
            header_size += gpt1_size + ((0x20 - (gpt1_size % 0x20)) % 0x20)
    else:
        header_size = 0x40

    dat_bytes = raw[header_size:]
    metadata = ContainerMetadata(filename=filename, shiny_params=shiny_params)
    return [(dat_bytes, metadata)]


def _extract_fsys(raw_bytes, archive_filename, options):
    """Extract all model entries from an FSYS archive.

    Decompresses LZSS if needed, and strips PKX headers for pkx entries.
    """
    entries = parse_fsys(raw_bytes, archive_filename)
    results = []
    for file_data, file_ext, entry_filename in entries:
        if file_ext == 'pkx':
            results.extend(_extract_pkx(file_data, entry_filename, options))
        else:
            results.append((file_data, ContainerMetadata(filename=entry_filename)))
    return results


def _extract_shiny_params(raw_bytes, is_xd):
    """Extract shiny color filter parameters from PKX raw bytes.

    Color1 (channel routing): 4 bytes with 3-byte gaps — each byte (0-3) indicates
    which source RGBA channel maps to that output position.

    Color2 (brightness): 4 contiguous bytes — per-channel brightness.
    Colosseum stores as ABGR (reversed); XD stores as RGBA.
    Byte values are mapped from [0, 255] to [-1.0, 1.0].

    Returns a plain dict (no IR dependency) or None on bounds-check failure.
    """
    file_length = len(raw_bytes)

    if is_xd:
        base = 0x73
    else:
        base = file_length - 0x11

    # Need 17 bytes from base (offsets 0..16)
    if base < 0 or base + 17 > file_length:
        return None

    # Color1: channel routing at base+0, base+4, base+8, base+12
    route_r = read('uchar', raw_bytes, base + 0)
    route_g = read('uchar', raw_bytes, base + 4)
    route_b = read('uchar', raw_bytes, base + 8)
    route_a = read('uchar', raw_bytes, base + 12)

    # Color2: brightness at base+13..16
    raw_brightness = [
        read('uchar', raw_bytes, base + 13),
        read('uchar', raw_bytes, base + 14),
        read('uchar', raw_bytes, base + 15),
        read('uchar', raw_bytes, base + 16),
    ]

    # Colosseum stores Color2 in ABGR order; XD stores RGBA
    if not is_xd:
        raw_brightness = list(reversed(raw_brightness))  # ABGR → RGBA

    # No-op check on raw byte values before conversion
    if _is_noop_shiny(route_r, route_g, route_b, route_a, raw_brightness):
        return None

    # Map [0, 255] → [-1.0, 1.0]
    def to_brightness(byte_val):
        return (byte_val / 255.0 * 2.0) - 1.0

    return {
        "route_r": route_r,
        "route_g": route_g,
        "route_b": route_b,
        "route_a": route_a,
        "brightness_r": to_brightness(raw_brightness[0]),
        "brightness_g": to_brightness(raw_brightness[1]),
        "brightness_b": to_brightness(raw_brightness[2]),
        "brightness_a": to_brightness(raw_brightness[3]),
    }


def _is_noop_shiny(route_r, route_g, route_b, route_a, raw_brightness):
    """Check if shiny parameters are a no-op (identity routing + neutral brightness).

    Models without a shiny variant store identity routing (R=0, G=1, B=2, A=3)
    and brightness bytes near 128 (neutral). These produce no visible change
    and should be treated as having no shiny variant.
    """
    identity_routing = (route_r == 0 and route_g == 1 and route_b == 2 and route_a == 3)
    neutral_brightness = all(abs(b - 128) <= 1 for b in raw_brightness)
    return identity_routing and neutral_brightness
