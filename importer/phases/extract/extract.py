"""Phase 1 — Container Extraction: binary file → DAT bytes.

Detects the container format (.dat, .pkx, .fsys) and extracts
the raw DAT model bytes, stripping any container headers.
"""
import struct
from dataclasses import dataclass


@dataclass
class ContainerMetadata:
    """Metadata about the source container."""
    source_path: str
    container_type: str  # 'dat', 'pkx_xd', 'pkx_colo', 'fsys'
    is_xd_model: bool = False


def extract_dat(filepath):
    """Extract DAT bytes from a container file.

    Args:
        filepath: Path to .dat, .pkx, or .fsys file.

    Returns:
        list of (dat_bytes, ContainerMetadata) tuples.
        A .dat/.pkx yields one entry. A .fsys would yield multiple (future).
    """
    with open(filepath, 'rb') as f:
        raw = f.read()

    ext = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''

    if ext == 'pkx':
        return _extract_pkx(raw, filepath)
    else:
        # .dat, .fdat, .rdat — pass through unchanged
        metadata = ContainerMetadata(
            source_path=filepath,
            container_type='dat',
        )
        return [(raw, metadata)]


def _extract_pkx(raw, filepath):
    """Extract DAT bytes from a PKX container.

    PKX files have a header before the DAT data:
    - Colosseum: 0x40 byte header
    - XD: 0xE60 byte header + optional GPT1 chunk
    """
    # Detect XD vs Colosseum: compare first 4 bytes at offset 0 vs 0x40
    val_0 = struct.unpack_from('>I', raw, 0)[0]
    val_40 = struct.unpack_from('>I', raw, 0x40)[0]
    is_xd = val_0 != val_40

    if is_xd:
        header_size = 0xE60
        gpt1_size = struct.unpack_from('>I', raw, 8)[0]
        if gpt1_size > 0:
            header_size += gpt1_size + ((0x20 - (gpt1_size % 0x20)) % 0x20)
        container_type = 'pkx_xd'
    else:
        header_size = 0x40
        container_type = 'pkx_colo'

    dat_bytes = raw[header_size:]
    metadata = ContainerMetadata(
        source_path=filepath,
        container_type=container_type,
        is_xd_model=is_xd,
    )
    return [(dat_bytes, metadata)]
