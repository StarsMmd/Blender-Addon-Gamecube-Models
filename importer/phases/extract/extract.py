"""Phase 1 — Container Extraction: raw file bytes → DAT bytes.

Detects the container format (.dat, .pkx, .fsys) and extracts
the raw DAT model bytes, stripping any container headers.
"""
from dataclasses import dataclass, field

try:
    from ....shared.helpers.pkx import PKXContainer
except (ImportError, SystemError):
    from shared.helpers.pkx import PKXContainer

try:
    from ....shared.helpers.shiny_params import ShinyParams
except (ImportError, SystemError):
    from shared.helpers.shiny_params import ShinyParams

try:
    from ....shared.helpers.pkx_header import PKXHeader
except (ImportError, SystemError):
    from shared.helpers.pkx_header import PKXHeader

try:
    from .helpers.fsys import is_fsys, parse_fsys
except (ImportError, SystemError):
    from importer.phases.extract.helpers.fsys import is_fsys, parse_fsys

try:
    from ....shared.helpers.wzx import is_wzx, extract_wzx
except (ImportError, SystemError):
    from shared.helpers.wzx import is_wzx, extract_wzx


@dataclass
class ContainerMetadata:
    """Metadata about the source container."""
    filename: str
    shiny_params: ShinyParams | None = None
    pkx_header: PKXHeader | None = None
    gpt1_data: bytes = b''


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
    elif ext == 'wzx' or is_wzx(raw_bytes):
        return _extract_wzx(raw_bytes, filename, options)
    else:
        # .dat, .fdat, .rdat — pass through unchanged
        metadata = ContainerMetadata(filename=filename)
        return [(raw_bytes, metadata)]


def _extract_pkx(raw, filename, options):
    """Extract DAT bytes from a PKX container."""
    pkx = PKXContainer(raw)
    shiny_params = pkx.shiny_params if options.get("include_shiny") else None
    pkx_header = pkx.header
    gpt1_data = pkx.gpt1_data
    metadata = ContainerMetadata(
        filename=filename,
        shiny_params=shiny_params,
        pkx_header=pkx_header,
        gpt1_data=gpt1_data,
    )
    return [(pkx.dat_bytes, metadata)]


def _extract_wzx(raw, filename, options):
    """Extract DAT and GPT1 payloads from a WZX effect container.

    Each payload becomes a separate entry. DAT+GPT1 pairs stay paired.
    Standalone GPT1 blocks (no DAT) are returned with empty dat_bytes
    so the importer can still process the particle data.
    """
    payloads = extract_wzx(raw)
    if not payloads:
        return []

    results = []
    base_name = filename.rsplit('.', 1)[0] if '.' in filename else filename
    for idx, (dat_bytes, gpt1_bytes) in enumerate(payloads):
        if not dat_bytes and not gpt1_bytes:
            continue
        suffix = "_%d" % idx if len(payloads) > 1 else ""
        entry_name = "%s%s.wzx" % (base_name, suffix)
        metadata = ContainerMetadata(
            filename=entry_name,
            gpt1_data=gpt1_bytes,
        )
        results.append((dat_bytes, metadata))
    return results


def _extract_fsys(raw_bytes, archive_filename, options):
    """Extract all model entries from an FSYS archive.

    Decompresses LZSS if needed, and strips PKX headers for pkx entries.
    """
    entries = parse_fsys(raw_bytes, archive_filename)
    results = []
    for file_data, file_ext, entry_filename in entries:
        if file_ext == 'pkx':
            results.extend(_extract_pkx(file_data, entry_filename, options))
        elif file_ext == 'wzx':
            results.extend(_extract_wzx(file_data, entry_filename, options))
        else:
            results.append((file_data, ContainerMetadata(filename=entry_filename)))
    return results
