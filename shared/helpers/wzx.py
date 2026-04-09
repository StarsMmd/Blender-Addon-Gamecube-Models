"""WZX container helper — extract DAT and GPT1 payloads from WZX effect files.

WZX files are WazaSequence containers for move/effect animations.
They contain a chain of sections, each with:
  - A 0x70-byte SequenceEntry header
  - A 0x20-byte section header (padded to 0xA0 from file start for the first section)
  - Optional HSD archive (DAT) at 0xA0 if section header's hsd_archive_size > 0
  - Sub-entries with type-specific extra data (Particle, Model, Effect, etc.)

This module extracts all embedded DAT models and GPT1 particle data
so they can be fed into the normal import pipeline.
"""
from .binary import read


# --- Format detection ---

_WZX_SENTINEL = b'\xff' * 12  # bytes 0x10-0x1B in every WZX file
_GPT1_V1_SIG = 0x47505431     # "GPT1"
_GPT1_V2_SIG = 0x01F056DA


def is_wzx(data):
    """Check if data is a WZX file by looking for the 12-byte sentinel."""
    if len(data) < 0xA0:
        return False
    return data[0x10:0x1C] == _WZX_SENTINEL


def _align32(value):
    """Round up to the next 32-byte boundary."""
    return (value + 0x1F) & ~0x1F


def _is_dat_header(data, offset):
    """Check if offset contains a plausible DAT header."""
    if offset + 0x20 > len(data):
        return False
    file_size = read('uint', data, offset)
    data_block = read('uint', data, offset + 0x04)
    reloc_count = read('uint', data, offset + 0x08)
    root_count = read('uint', data, offset + 0x0C)
    ref_count = read('uint', data, offset + 0x10)
    # Padding bytes 0x14-0x1F should be zero
    pad1 = read('uint', data, offset + 0x14)
    pad2 = read('uint', data, offset + 0x18)
    pad3 = read('uint', data, offset + 0x1C)
    return (file_size > 0x20
            and data_block > 0
            and data_block < file_size
            and root_count > 0
            and root_count < 100
            and ref_count < 100
            and reloc_count < 100000
            and pad1 == 0 and pad2 == 0 and pad3 == 0
            and file_size <= len(data) - offset)


def _is_gpt1(data, offset):
    """Check if offset contains a GPT1 V1 or V2 signature."""
    if offset + 4 > len(data):
        return False
    sig = read('uint', data, offset)
    return sig == _GPT1_V1_SIG or sig == _GPT1_V2_SIG


# --- Sub-entry data size computation ---

# Entry type IDs from the Load dispatch table
_TYPE_CAMERA = 0
_TYPE_MODEL = 1
_TYPE_PARTICLE = 2
_TYPE_EFFECT = 3
_TYPE_SOUND = 4
_TYPE_EVENT = 5
_TYPE_LENSFLARE = 6



def _parse_entry_extra(data, offset, entry_type, logger):
    """Parse a sub-entry's type-specific extra data and extract content.

    Args:
        data: Full WZX file bytes.
        offset: Position right after the 0x70-byte SequenceEntry header.
        entry_type: The entry_type field from the SequenceEntry.
        logger: Logger instance.

    Returns:
        (new_offset, dat_bytes, gpt1_bytes) or None if parsing failed.
        dat_bytes and gpt1_bytes are empty bytes if not present.
    """
    if entry_type == _TYPE_SOUND:
        return (offset + 0x14, b'', b'')

    if entry_type == _TYPE_EVENT:
        return (offset + 0x08, b'', b'')

    if entry_type == _TYPE_CAMERA:
        if offset + 0x0C > len(data):
            return None
        cam_type = read('uint', data, offset)
        new_offset = offset + 0x0C
        if cam_type == 3 and new_offset + 4 <= len(data):
            count = read('uint', data, new_offset)
            new_offset += count * 8
        return (new_offset, b'', b'')

    if entry_type == _TYPE_MODEL:
        if offset + 0x28 > len(data):
            return None
        dat_size = read('uint', data, offset + 0x1C)
        new_offset = _align32(offset + 0x28)
        extracted_dat = b''
        if dat_size > 0 and new_offset + dat_size <= len(data):
            if _is_dat_header(data, new_offset):
                actual_size = read('uint', data, new_offset)
                extracted_dat = data[new_offset:new_offset + actual_size]
                logger.info("WZX: Found Model DAT at 0x%x (%d bytes)", new_offset, actual_size)
            new_offset += _align32(dat_size)
        return (new_offset, extracted_dat, b'')

    if entry_type == _TYPE_PARTICLE:
        if offset + 0x14 > len(data):
            return None
        particle_size = read('uint', data, offset + 0x08)
        new_offset = _align32(offset + 0x14)
        extracted_gpt1 = b''
        if particle_size > 0 and new_offset + particle_size <= len(data):
            if _is_gpt1(data, new_offset):
                extracted_gpt1 = data[new_offset:new_offset + particle_size]
                logger.info("WZX: Found Particle GPT1 at 0x%x (%d bytes)", new_offset, particle_size)
            new_offset += _align32(particle_size)
        return (new_offset, b'', extracted_gpt1)

    if entry_type == _TYPE_LENSFLARE:
        if offset + 0x14 > len(data):
            return None
        lf_size = read('uint', data, offset)
        new_offset = _align32(offset + 0x14)
        if lf_size > 0:
            new_offset += _align32(lf_size)
        return (new_offset, b'', b'')

    if entry_type == _TYPE_EFFECT:
        # Effect entries: 0x0C effect header, then sub-type-specific data.
        # The effect header has: [0x00] sub_type, [0x04] timing (float),
        # [0x08] particle_data_size.
        # After the 0x0C header + 0x10 sub-type header, the GPT1 particle
        # data begins at the next 0x20-aligned position. The particle size
        # at effect_header[0x08] gives the exact byte count.
        #
        # We CAN extract the GPT1, but we CANNOT determine the Effect entry's
        # total size (that requires reverse-engineering all specialized effect
        # load functions). So we extract GPT1 and return None to stop parsing.
        if offset + 0x0C > len(data):
            return None
        particle_size = read('uint', data, offset + 0x08)
        particle_start = _align32(offset + 0x0C + 0x10)

        extracted_gpt1 = b''
        if particle_size > 0 and particle_start + particle_size <= len(data):
            if _is_gpt1(data, particle_start):
                extracted_gpt1 = data[particle_start:particle_start + particle_size]
                logger.info("WZX: Found Effect GPT1 at 0x%x (%d bytes)",
                            particle_start, particle_size)
        # Return the GPT1 with a sentinel offset (-1) to signal "stop parsing"
        return (-1, b'', extracted_gpt1)

    # Unknown entry type
    return None


# --- Main extraction ---

def extract_wzx(data, logger=None):
    """Extract all DAT and GPT1 payloads from a WZX file.

    Args:
        data: Raw WZX file bytes.
        logger: Optional logger instance.

    Returns:
        List of (dat_bytes, gpt1_bytes) tuples. Each tuple represents one
        embedded model/particle pair found in the WZX. gpt1_bytes may be
        empty if no particle data accompanies the DAT.
    """

    class _log:
        """Minimal fallback if no logger provided."""
        @staticmethod
        def info(*a, **kw): pass
        @staticmethod
        def debug(*a, **kw): pass
        @staticmethod
        def warning(*a, **kw): pass

    if logger is None:
        logger = _log()

    if not is_wzx(data):
        logger.warning("Not a valid WZX file (sentinel not found)")
        return []

    results = []

    # Read section header fields
    version = read('uint', data, 0x80)
    entry_count = read('uint', data, 0x74)
    hsd_size = read('uint', data, 0x84)
    sub_entries = entry_count - 1 if entry_count > 0 else 0

    logger.info("WZX: version=%d entries=%d hsd_size=%d", version, entry_count, hsd_size)

    # Case 1: HSD archive (DAT) embedded directly at 0xA0
    if hsd_size > 0 and _is_dat_header(data, 0xA0):
        dat_size = read('uint', data, 0xA0)  # DAT's own file_size
        dat_bytes = data[0xA0:0xA0 + dat_size]
        logger.info("WZX: Found DAT at 0xA0 (%d bytes)", dat_size)
        results.append((dat_bytes, b''))

    # Walk sub-entries starting at 0xA0 (or after the DAT)
    if hsd_size > 0:
        offset = 0xA0 + _align32(hsd_size)
    else:
        offset = 0xA0

    # Try structured parsing of sub-entries, extracting content as we go
    parsed_ok = True
    pending_gpt1 = b''  # GPT1 waiting to be paired with a DAT

    for i in range(sub_entries):
        if offset + 0x70 > len(data):
            logger.debug("WZX: Ran out of data at entry %d (offset 0x%x)", i, offset)
            parsed_ok = False
            break

        entry_type = read('uint', data, offset + 0x04)
        logger.debug("WZX: Entry %d at 0x%x: type=%d", i, offset, entry_type)

        # Advance past the 0x70-byte SequenceEntry header
        extra_offset = offset + 0x70

        # Parse type-specific extra data and extract content
        result = _parse_entry_extra(data, extra_offset, entry_type, logger)

        if result is None:
            logger.debug("WZX: Cannot parse entry type %d at 0x%x, stopping",
                         entry_type, offset)
            parsed_ok = False
            break

        new_offset, entry_dat, entry_gpt1 = result

        # Sentinel offset -1 means "extracted content but can't continue"
        if new_offset == -1:
            if entry_gpt1:
                pending_gpt1 = entry_gpt1
            if entry_dat:
                results.append((entry_dat, pending_gpt1))
                pending_gpt1 = b''
            parsed_ok = False
            break

        # Collect extracted content
        if entry_gpt1:
            pending_gpt1 = entry_gpt1
        if entry_dat:
            results.append((entry_dat, pending_gpt1))
            pending_gpt1 = b''

        offset = new_offset

    # If we have a GPT1 without a DAT, store it as standalone
    if pending_gpt1:
        results.append((b'', pending_gpt1))
        pending_gpt1 = b''

    # If structured parsing covered all entries, check for chained sections
    if parsed_ok and offset < len(data):
        _parse_chained_sections(data, offset, results, logger)

    return results


def _parse_chained_sections(data, offset, results, logger):
    """Parse additional chained sections after the first section's sub-entries.

    Multi-phase effects (attack + damage + special) chain multiple sections.
    Each starts with a SequenceEntry (0x70) + section header (0x20) at the
    current offset, identifiable by the version field (5 or 6) at +0x80.
    """
    while offset + 0xA0 <= len(data):
        ver_offset = offset + 0x80
        if ver_offset + 4 > len(data):
            break
        ver = read('uint', data, ver_offset)
        if ver not in (5, 6):
            break

        hsd_size = read('uint', data, offset + 0x84)
        dat_start = offset + 0xA0

        if hsd_size > 0 and dat_start + 0x20 <= len(data) and _is_dat_header(data, dat_start):
            dat_size = read('uint', data, dat_start)
            dat_bytes = data[dat_start:dat_start + dat_size]
            logger.info("WZX: Found chained DAT at 0x%x (%d bytes)", dat_start, dat_size)
            results.append((dat_bytes, b''))
            offset = dat_start + _align32(dat_size)
        else:
            # No DAT in this chained section — can't skip without full
            # sub-entry parsing, so stop here.
            break
