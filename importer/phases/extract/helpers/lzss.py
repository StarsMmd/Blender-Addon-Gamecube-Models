"""LZSS decompression for FSYS archive entries.

Ported from GoD-Tool's LZSSCompressor.swift (QuickBMS reference).
"""

try:
    from .....shared.helpers.binary import read
except (ImportError, SystemError):
    from shared.helpers.binary import read


LZSS_MAGIC = b'LZSS'
LZSS_HEADER_SIZE = 16

# Algorithm parameters (SysDolphin / GoD-Tool defaults)
_EI = 12
_EJ = 4
_P = 2


def is_lzss(data, offset=0):
    """Check if data at offset starts with the LZSS magic.

    In: data (bytes); offset (int, non-negative byte offset, default 0).
    Out: bool, True iff data[offset:offset+4] == b'LZSS'.
    """
    return data[offset:offset + 4] == LZSS_MAGIC


def decompress_lzss(data, offset=0):
    """Decompress LZSS data starting at the given offset.

    In: data (bytes, contains LZSS header + payload); offset (int, non-negative offset of the LZSS header).
    Out: bytes, decompressed payload; raises ValueError on bad magic.
    """
    if not is_lzss(data, offset):
        raise ValueError("LZSS magic not found at offset 0x%X" % offset)

    compressed_size = read('uint', data, offset + 8)  # includes 16-byte header

    # Compressed payload starts after the 16-byte header
    src = data[offset + LZSS_HEADER_SIZE:offset + compressed_size]

    N = 1 << _EI       # 4096
    F = 1 << _EJ        # 16
    rless = 2

    ring = bytearray(N)
    output = bytearray()

    r = (N - F) - rless  # 4078
    pos = 0
    flags = 0

    N -= 1  # 4095, used as bitmask
    F -= 1  # 15, used as bitmask

    while pos < len(src):
        if (flags & 0x100) == 0:
            flags = src[pos] | 0xFF00
            pos += 1

        if pos >= len(src):
            break

        if flags & 1:
            # Literal byte
            c = src[pos]
            pos += 1
            output.append(c)
            ring[r] = c
            r = (r + 1) & N
        else:
            if pos + 1 >= len(src):
                break
            i = src[pos]
            j = src[pos + 1]
            pos += 2

            i |= (j >> _EJ) << 8
            j = (j & F) + _P

            for k in range(j + 1):
                c = ring[(i + k) & N]
                output.append(c)
                ring[r] = c
                r = (r + 1) & N

        flags >>= 1

    return bytes(output)
