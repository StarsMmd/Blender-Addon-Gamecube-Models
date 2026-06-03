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
    """Extract DAT bytes from raw file contents, dispatching by container type.

    In: raw_bytes (bytes, complete file contents); filename (str, used to detect container by extension); options (dict|None, importer options — `include_shiny` extracts PKX shiny params).
    Out: list[tuple[bytes, ContainerMetadata]], one entry per model (>=1 for .fsys, exactly 1 for .dat/.pkx, >=0 for .wzx).
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
        # Kirby Air Ride "A2" multi-asset containers share the .dat extension
        # but hold Kirby-proprietary payloads (.tm 2D menu / animation files
        # and .tex raw textures), not HAL DAT archives. The signature
        # (file_size=0 + plausible TOC + ASCII entry names) is distinctive
        # enough to check unconditionally — no real HAL DAT trips it.
        summary = _sniff_a2_container(raw_bytes)
        if summary is not None:
            raise ValueError(
                "%s is a Kirby Air Ride 'A2' multi-asset container "
                "(%d entries: %s). It holds .tm/.tex payloads, not HAL DAT "
                "archives, so the import pipeline has nothing to load from "
                "it." % (filename, summary['count'], summary['preview'])
            )

        # .dat, .fdat, .rdat — pass through unchanged
        metadata = ContainerMetadata(filename=filename)
        return [(raw_bytes, metadata)]


def _sniff_a2_container(raw):
    """Return a brief summary if `raw` looks like a Kirby Air Ride A2 container, else None.

    In: raw (bytes).
    Out: dict with 'count' and 'preview' (printable entry names found near the top of the file) if A2-shaped; None otherwise.
    """
    if len(raw) < 32:
        return None

    import struct
    import re

    file_size = struct.unpack('>I', raw[:4])[0]
    # Every real HAL DAT declares its own byte length here; A2 containers
    # park a zero. That's a cheap, reliable discriminator across all the
    # variants seen in the retail dump (A2Kirby/A2Info-style with a TOC of
    # name-offset pointers, A2a2dBG_*-style with inline name strings, etc.).
    if file_size != 0:
        return None

    count = struct.unpack('>I', raw[4:8])[0]
    # All A2 variants use u32[1] as a count of some kind. 1..4096 covers
    # everything in the retail dump while rejecting accidental zero-headers
    # on unrelated formats.
    if count == 0 or count > 4096:
        return None

    # Pull printable strings out of the first ~4 KB. We don't try to follow
    # the TOC structure — the layout differs between A2 variants (some store
    # name offsets, others embed names inline) — but *all* variants put
    # ASCII payload names within the first few KB, so a regex sweep finds
    # them reliably without committing to one TOC interpretation.
    head = raw[:min(len(raw), 4096)]
    name_re = re.compile(rb'[A-Za-z][A-Za-z0-9_./]{2,63}\.(?:tm|tex|t3l|t1c|t1l|tg)')
    names = [m.group(0).decode('ascii') for m in name_re.finditer(head)]
    # de-dupe while preserving order
    seen = set()
    deduped = []
    for n in names:
        if n not in seen:
            seen.add(n)
            deduped.append(n)
    if not deduped:
        return None
    preview = ', '.join(deduped[:3]) + (', …' if len(deduped) > 3 else '')
    return {'count': count, 'preview': preview}


def _extract_pkx(raw, filename, options):
    """Extract DAT bytes plus shiny/header/GPT1 metadata from a PKX container.

    In: raw (bytes, complete .pkx file); filename (str); options (dict, `include_shiny` toggles shiny extraction).
    Out: list[tuple[bytes, ContainerMetadata]], single-entry list with the embedded DAT payload.
    """
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

    In: raw (bytes, complete .wzx file); filename (str, base for per-payload naming); options (dict, unused but accepted).
    Out: list[tuple[bytes, ContainerMetadata]], one per payload (DAT bytes may be empty for standalone GPT1 blocks).
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
    """Extract all model entries from an FSYS archive (decompressing LZSS if needed).

    In: raw_bytes (bytes, complete .fsys file); archive_filename (str, fallback base name); options (dict, importer options).
    Out: list[tuple[bytes, ContainerMetadata]], one per model-bearing FSYS entry.
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
