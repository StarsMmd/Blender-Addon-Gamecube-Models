"""FSYS archive parser for Pokemon Colosseum/XD container files.

Parses the FSYS header and file metadata entries, extracts and
decompresses model-relevant files (dat, mdat, pkx).
"""

try:
    from .....shared.helpers.binary import read
except (ImportError, SystemError):
    from shared.helpers.binary import read

try:
    from .lzss import is_lzss, decompress_lzss
except (ImportError, SystemError):
    from importer.phases.extract.helpers.lzss import is_lzss, decompress_lzss


FSYS_MAGIC = b'FSYS'

# FSYS header field offsets (big-endian)
_HEADER_ENTRY_COUNT = 0x0C
_HEADER_METADATA_LIST_PTR = 0x40

# File metadata entry field offsets (relative to entry start)
_ENTRY_FILE_TYPE = 0x02        # uint8
_ENTRY_DATA_ADDRESS = 0x04     # uint32
_ENTRY_FLAGS = 0x0C            # uint32
_ENTRY_FILE_SIZE = 0x14        # uint32
_ENTRY_FULL_FILENAME_PTR = 0x1C  # uint32 — full filename (if debug flag set)
_ENTRY_FILENAME_PTR = 0x24     # uint32 — short entry name

# Compression flag (bit 31)
_FLAG_COMPRESSED = 0x80000000

# File type IDs that contain model data (Colosseum/XD)
_MODEL_FILE_TYPES = {
    0x02: 'dat',   # mdat — model data, treat as dat
    0x04: 'dat',   # dat
    0x1E: 'pkx',   # pkx — Pokemon model, needs header stripping
}


def is_fsys(data):
    """Check if data starts with the FSYS magic bytes."""
    return len(data) >= 4 and data[:4] == FSYS_MAGIC


def parse_fsys(raw_bytes, archive_filename):
    """Parse an FSYS archive and extract model-relevant file entries.

    Args:
        raw_bytes: Complete FSYS archive as bytes.
        archive_filename: Original archive filename (for fallback naming).

    Returns:
        list of (file_data, file_type_ext, entry_filename) tuples.
        file_type_ext is 'dat' or 'pkx'.

    Raises:
        ValueError: If the FSYS magic is not found.
    """
    if not is_fsys(raw_bytes):
        raise ValueError("Not an FSYS archive: magic bytes not found")

    entry_count = read('uint', raw_bytes, _HEADER_ENTRY_COUNT)
    metadata_list_ptr = read('uint', raw_bytes, _HEADER_METADATA_LIST_PTR)

    results = []

    for i in range(entry_count):
        entry_ptr = read('uint', raw_bytes, metadata_list_ptr + i * 4)

        file_type = read('uchar', raw_bytes, entry_ptr + _ENTRY_FILE_TYPE)
        if file_type not in _MODEL_FILE_TYPES:
            continue

        data_address = read('uint', raw_bytes, entry_ptr + _ENTRY_DATA_ADDRESS)
        file_size = read('uint', raw_bytes, entry_ptr + _ENTRY_FILE_SIZE)
        flags = read('uint', raw_bytes, entry_ptr + _ENTRY_FLAGS)

        entry_filename = _read_entry_filename(
            raw_bytes, entry_ptr, file_type, archive_filename, i
        )

        file_data = raw_bytes[data_address:data_address + file_size]

        if flags & _FLAG_COMPRESSED:
            file_data = decompress_lzss(file_data)

        ext = _MODEL_FILE_TYPES[file_type]
        results.append((file_data, ext, entry_filename))

    return results


def _read_string(raw_bytes, ptr):
    """Read a null-terminated ASCII string at the given offset."""
    end = raw_bytes.index(b'\x00', ptr)
    return raw_bytes[ptr:end].decode('ascii', errors='replace')


def _read_entry_filename(raw_bytes, entry_ptr, file_type, archive_filename, index):
    """Build the filename for an FSYS entry.

    Checks full_filename_pointer first (set when the debug flag is on),
    then falls back to short name + file type extension.
    """
    # Prefer the full filename if present (includes extension)
    full_ptr = read('uint', raw_bytes, entry_ptr + _ENTRY_FULL_FILENAME_PTR)
    if full_ptr != 0 and full_ptr < len(raw_bytes):
        return _read_string(raw_bytes, full_ptr)

    # Short entry name — append file type extension
    short_ptr = read('uint', raw_bytes, entry_ptr + _ENTRY_FILENAME_PTR)
    if short_ptr != 0 and short_ptr < len(raw_bytes):
        name = _read_string(raw_bytes, short_ptr)
        ext = _MODEL_FILE_TYPES.get(file_type, 'dat')
        if not name.endswith('.' + ext):
            name = name + '.' + ext
        return name

    # Last resort fallback
    base = archive_filename.rsplit('.', 1)[0] if '.' in archive_filename else archive_filename
    return "%s_entry_%d.dat" % (base, index)
