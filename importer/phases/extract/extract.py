"""Phase 1 — Container Extraction: raw file bytes → DAT bytes.

Detects the container format (.dat, .pkx, .fsys) and extracts
the raw DAT model bytes, stripping any container headers.
"""
from dataclasses import dataclass
from shared.helpers.binary import read


@dataclass
class ContainerMetadata:
    """Metadata about the source container."""
    filename: str


def extract_dat(raw_bytes, filename):
    """Extract DAT bytes from raw file contents.

    Args:
        raw_bytes: Complete file contents as bytes.
        filename: Original filename (used to detect container type by extension).

    Returns:
        list of (dat_bytes, ContainerMetadata) tuples.
        A .dat/.pkx yields one entry. A .fsys would yield multiple (future).
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    if ext == 'pkx':
        return _extract_pkx(raw_bytes, filename)
    else:
        # .dat, .fdat, .rdat — pass through unchanged
        metadata = ContainerMetadata(filename=filename)
        return [(raw_bytes, metadata)]


def _extract_pkx(raw, filename):
    """Extract DAT bytes from a PKX container.

    PKX files have a header before the DAT data:
    - Colosseum: 0x40 byte header
    - XD: 0xE60 byte header + optional GPT1 chunk
    """
    # Detect XD vs Colosseum: compare first 4 bytes at offset 0 vs 0x40
    val_0 = read('uint', raw, 0)
    val_40 = read('uint', raw, 0x40)
    is_xd = val_0 != val_40

    if is_xd:
        header_size = 0xE60
        gpt1_size = read('uint', raw, 8)
        if gpt1_size > 0:
            header_size += gpt1_size + ((0x20 - (gpt1_size % 0x20)) % 0x20)
    else:
        header_size = 0x40

    dat_bytes = raw[header_size:]
    metadata = ContainerMetadata(filename=filename)
    return [(dat_bytes, metadata)]
