"""FSYS archive read/write helpers for the exporter.

Parses an existing FSYS archive into a summary of its entries (preserving
every byte of header, metadata table, and string table) so the package
phase can replace a single model entry while leaving everything else
untouched. Includes an LZSS compressor ported from GoD-Tool's
LZSSCompressor.swift (originally from QuickBMS by Luigi Auriemma).
"""
from dataclasses import dataclass
from typing import List, Optional

try:
    from .binary import read, pack
except (ImportError, SystemError):
    from shared.helpers.binary import read, pack


FSYS_MAGIC = b'FSYS'
LZSS_MAGIC = b'LZSS'
LZSS_HEADER_SIZE = 16

# Header field offsets (big-endian)
_HEADER_ENTRY_COUNT = 0x0C
_HEADER_FILE_SIZE = 0x20
_HEADER_METADATA_LIST_PTR = 0x40

# Per-entry field offsets (within each metadata entry)
_ENTRY_FILE_TYPE = 0x02
_ENTRY_DATA_ADDRESS = 0x04
_ENTRY_UNCOMPRESSED_SIZE = 0x08
_ENTRY_FLAGS = 0x0C
_ENTRY_FILE_SIZE = 0x14
_ENTRY_FULL_FILENAME_PTR = 0x1C
_ENTRY_FILENAME_PTR = 0x24

_FLAG_COMPRESSED = 0x80000000

# File-type IDs that hold a model payload.
_DAT_TYPES = {0x02, 0x04, 0x18}  # mdat / dat / cam
_PKX_TYPE = 0x1E

MODEL_TYPE_DAT = 'dat'
MODEL_TYPE_PKX = 'pkx'

_DATA_ALIGNMENT = 0x20


@dataclass
class FSYSEntrySummary:
    """One entry of an FSYS, located by metadata offset within the file."""
    index: int
    metadata_offset: int     # absolute offset of entry metadata in raw_bytes
    data_address: int        # absolute offset of entry payload in raw_bytes
    file_size: int           # stored size on disk (compressed if compressed)
    uncompressed_size: int
    file_type: int
    flags: int
    filename: str

    @property
    def is_compressed(self) -> bool:
        return bool(self.flags & _FLAG_COMPRESSED)

    @property
    def model_kind(self) -> Optional[str]:
        if self.file_type == _PKX_TYPE:
            return MODEL_TYPE_PKX
        if self.file_type in _DAT_TYPES:
            return MODEL_TYPE_DAT
        return None


def is_fsys(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] == FSYS_MAGIC


def parse_fsys_summary(raw_bytes: bytes) -> List[FSYSEntrySummary]:
    """Walk every metadata entry in an FSYS, returning a summary list.

    Unlike `importer/.../fsys.py:parse_fsys`, this does NOT decompress
    payloads or filter to model types — it returns one summary per entry
    in their original order so the rebuild can preserve them all.
    """
    if not is_fsys(raw_bytes):
        raise ValueError("Not an FSYS archive: magic bytes not found")
    entry_count = read('uint', raw_bytes, _HEADER_ENTRY_COUNT)
    metadata_list_ptr = read('uint', raw_bytes, _HEADER_METADATA_LIST_PTR)

    entries = []
    for i in range(entry_count):
        meta_off = read('uint', raw_bytes, metadata_list_ptr + i * 4)
        entries.append(FSYSEntrySummary(
            index=i,
            metadata_offset=meta_off,
            data_address=read('uint', raw_bytes, meta_off + _ENTRY_DATA_ADDRESS),
            file_size=read('uint', raw_bytes, meta_off + _ENTRY_FILE_SIZE),
            uncompressed_size=read('uint', raw_bytes, meta_off + _ENTRY_UNCOMPRESSED_SIZE),
            file_type=read('uchar', raw_bytes, meta_off + _ENTRY_FILE_TYPE),
            flags=read('uint', raw_bytes, meta_off + _ENTRY_FLAGS),
            filename=_read_entry_filename(raw_bytes, meta_off, i),
        ))
    return entries


def find_model_entries(entries: List[FSYSEntrySummary]) -> List[FSYSEntrySummary]:
    return [e for e in entries if e.model_kind is not None]


def rebuild_fsys_replacing(raw_bytes: bytes,
                           replace_index: int,
                           new_payload: bytes) -> bytes:
    """Re-emit an FSYS, replacing one entry's payload bytes.

    All other entries' payload bytes are copied verbatim from `raw_bytes`.
    The replaced entry is wrapped in an LZSS header and compressed if (and
    only if) the original entry was compressed; otherwise it's written
    raw. Header, pointer table, string table, and metadata table bytes
    are preserved — only the affected entry's `data_address`,
    `file_size`, `uncompressed_size`, plus the global `file_size` field
    at 0x20, are updated. Entry data offsets shift to fit the replaced
    payload's new length.
    """
    entries = parse_fsys_summary(raw_bytes)
    if not 0 <= replace_index < len(entries):
        raise ValueError(
            "replace_index %d out of range for FSYS with %d entries"
            % (replace_index, len(entries))
        )

    replaced = entries[replace_index]

    # Determine where the data region starts. Everything before it is
    # header + pointer table + string table + metadata table + padding,
    # all copied verbatim.
    data_region_start = min(e.data_address for e in entries)
    out = bytearray(raw_bytes[:data_region_start])

    # Pre-stage the replacement bytes (compress if needed).
    if replaced.is_compressed:
        replacement_stored = _wrap_lzss(new_payload)
        replacement_uncompressed = len(new_payload)
    else:
        replacement_stored = bytes(new_payload)
        replacement_uncompressed = len(new_payload)

    for entry in entries:
        # Align data start to the FSYS alignment.
        pad = (-len(out)) % _DATA_ALIGNMENT
        out += b'\x00' * pad

        new_data_address = len(out)
        if entry.index == replace_index:
            payload_bytes = replacement_stored
            new_file_size = len(replacement_stored)
            new_uncompressed = replacement_uncompressed
        else:
            payload_bytes = raw_bytes[entry.data_address:
                                      entry.data_address + entry.file_size]
            if len(payload_bytes) != entry.file_size:
                raise ValueError(
                    "FSYS entry %d truncated: metadata says %d bytes "
                    "at 0x%X but only %d available"
                    % (entry.index, entry.file_size,
                       entry.data_address, len(payload_bytes))
                )
            new_file_size = entry.file_size
            new_uncompressed = entry.uncompressed_size

        out += payload_bytes

        meta_off = entry.metadata_offset
        out[meta_off + _ENTRY_DATA_ADDRESS:
            meta_off + _ENTRY_DATA_ADDRESS + 4] = pack('uint', new_data_address)
        out[meta_off + _ENTRY_FILE_SIZE:
            meta_off + _ENTRY_FILE_SIZE + 4] = pack('uint', new_file_size)
        out[meta_off + _ENTRY_UNCOMPRESSED_SIZE:
            meta_off + _ENTRY_UNCOMPRESSED_SIZE + 4] = pack('uint', new_uncompressed)

    # Footer: copy whatever the original archive had after its last
    # entry's stored bytes (typically a 0x20-byte FSYS-magic footer).
    last_entry = max(entries, key=lambda e: e.data_address)
    footer_start = last_entry.data_address + last_entry.file_size
    footer_pad = (-footer_start) % _DATA_ALIGNMENT
    footer_bytes = raw_bytes[footer_start + footer_pad:]
    if footer_bytes:
        pad = (-len(out)) % _DATA_ALIGNMENT
        out += b'\x00' * pad
        out += footer_bytes

    out[_HEADER_FILE_SIZE:_HEADER_FILE_SIZE + 4] = pack('uint', len(out))
    return bytes(out)


def _read_entry_filename(raw_bytes: bytes, meta_off: int, index: int) -> str:
    full_ptr = read('uint', raw_bytes, meta_off + _ENTRY_FULL_FILENAME_PTR)
    if full_ptr and full_ptr < len(raw_bytes):
        return _read_string(raw_bytes, full_ptr)
    short_ptr = read('uint', raw_bytes, meta_off + _ENTRY_FILENAME_PTR)
    if short_ptr and short_ptr < len(raw_bytes):
        return _read_string(raw_bytes, short_ptr)
    return "entry_%d" % index


def _read_string(raw_bytes: bytes, ptr: int) -> str:
    end = raw_bytes.index(b'\x00', ptr)
    return raw_bytes[ptr:end].decode('ascii', errors='replace')


def _wrap_lzss(payload: bytes) -> bytes:
    """Compress `payload` and prepend the 16-byte LZSS header used by FSYS."""
    compressed = compress_lzss(payload)
    compressed_size = len(compressed) + LZSS_HEADER_SIZE
    header = (
        LZSS_MAGIC
        + pack('uint', len(payload))
        + pack('uint', compressed_size)
        + b'\x00\x00\x00\x00'
    )
    return header + compressed


# ---------------------------------------------------------------------------
# LZSS compression — ported from GoD-Tool's LZSSCompressor.swift (QuickBMS).
# ---------------------------------------------------------------------------

def compress_lzss(data: bytes, EI: int = 12, EJ: int = 4, P: int = 2) -> bytes:
    """Compress raw bytes into an LZSS payload (without the 16-byte header).

    Default parameters match the FSYS / Genius Sonority convention
    (window=4096, max-match=18, threshold=2). Output is byte-for-byte
    decodable by `importer/phases/extract/helpers/lzss.decompress_lzss`
    when wrapped with a matching header.
    """
    THRESHOLD = P
    N = 1 << EI
    F = (1 << EJ) + THRESHOLD
    NIL = N

    text_buffer = bytearray(N + F - 1)

    left = [0] * (N + 1)
    right = [0] * (N + 257)
    parent = [0] * (N + 1)
    for i in range(N + 1, N + 257):
        right[i] = NIL
    for i in range(N):
        parent[i] = NIL

    state = {'match_position': 0, 'match_length': 0}
    inputBytes = data
    outputBytes = bytearray()

    def insert(node):
        cmp_v = 1
        p = N + 1 + text_buffer[node]
        right[node] = NIL
        left[node] = NIL
        state['match_length'] = 0
        while True:
            if cmp_v >= 0:
                if right[p] != NIL:
                    p = right[p]
                else:
                    right[p] = node
                    parent[node] = p
                    return
            else:
                if left[p] != NIL:
                    p = left[p]
                else:
                    left[p] = node
                    parent[node] = p
                    return
            i = 1
            while i < F:
                cmp_v = text_buffer[node + i] - text_buffer[p + i]
                if cmp_v != 0:
                    break
                i += 1
            if i > state['match_length']:
                state['match_position'] = p
                state['match_length'] = i
                if state['match_length'] >= F:
                    break
        parent[node] = parent[p]
        left[node] = left[p]
        right[node] = right[p]
        parent[left[p]] = node
        parent[right[p]] = node
        if right[parent[p]] == p:
            right[parent[p]] = node
        else:
            left[parent[p]] = node
        parent[p] = NIL

    def delete(node):
        if parent[node] == NIL:
            return
        if right[node] == NIL:
            new_child = left[node]
        elif left[node] == NIL:
            new_child = right[node]
        else:
            new_child = left[node]
            if right[new_child] != NIL:
                while right[new_child] != NIL:
                    new_child = right[new_child]
                right[parent[new_child]] = left[new_child]
                parent[left[new_child]] = parent[new_child]
                left[new_child] = left[node]
                parent[left[node]] = new_child
            right[new_child] = right[node]
            parent[right[node]] = new_child
        parent[new_child] = parent[node]
        if right[parent[node]] == node:
            right[parent[node]] = new_child
        else:
            left[parent[node]] = new_child
        parent[node] = NIL

    code_buffer = bytearray([0])
    mask = 1

    length = min(F, len(inputBytes))
    if length == 0:
        return bytes()

    r = N - F
    s = 0
    inputPosition = 0

    for i in range(length):
        text_buffer[r + i] = inputBytes[inputPosition]
        inputPosition += 1

    for i in range(1, F + 1):
        insert(r - i)
    insert(r)

    while length > 0:
        if state['match_length'] > length:
            state['match_length'] = length
        if state['match_length'] <= THRESHOLD:
            state['match_length'] = 1
            code_buffer[0] |= mask
            code_buffer.append(text_buffer[r])
        else:
            mp = state['match_position']
            ml = state['match_length']
            code_buffer.append(mp & 0xFF)
            code_buffer.append(((mp >> 4) & 0xF0) | (ml - (THRESHOLD + 1)))

        if mask == 0x80:
            outputBytes += code_buffer
            code_buffer = bytearray([0])
            mask = 1
        else:
            mask <<= 1

        last_match_length = state['match_length']
        last_match_cutoff = 0
        for _ in range(last_match_length):
            if inputPosition >= len(inputBytes):
                break
            c = inputBytes[inputPosition]
            inputPosition += 1
            delete(s)
            text_buffer[s] = c
            if s < F - 1:
                text_buffer[s + N] = c
            s = (s + 1) % N
            r = (r + 1) % N
            insert(r)
            last_match_cutoff += 1

        while last_match_cutoff < last_match_length:
            delete(s)
            s = (s + 1) % N
            r = (r + 1) % N
            length -= 1
            if length != 0:
                insert(r)
            last_match_cutoff += 1

    if len(code_buffer) > 1:
        outputBytes += code_buffer

    return bytes(outputBytes)
