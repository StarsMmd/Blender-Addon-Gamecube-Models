"""Binary read/write helpers with descriptive type names.

Wraps struct.pack/unpack with named primitive types for readability.
All operations use big-endian (GameCube) byte order unless native is specified.
"""
import struct

# type_name → (format_char, byte_size)
_TYPES = {
    'uint':   ('>I', 4),
    'int':    ('>i', 4),
    'ushort': ('>H', 2),
    'short':  ('>h', 2),
    'uchar':  ('>B', 1),
    'char':   ('>b', 1),
    'float':  ('>f', 4),
}


def read(type_name, data, offset=0):
    """Read a single value from bytes at the given offset.

    Args:
        type_name: One of 'uint', 'int', 'ushort', 'short', 'uchar', 'char', 'float'.
        data: bytes or bytearray to read from.
        offset: byte offset into data.

    Returns:
        The unpacked value.
    """
    fmt, size = _TYPES[type_name]
    return struct.unpack_from(fmt, data, offset)[0]


def read_many(type_name, count, data, offset=0):
    """Read multiple consecutive values of the same type.

    Args:
        type_name: Primitive type name.
        count: Number of values to read.
        data: bytes or bytearray.
        offset: byte offset into data.

    Returns:
        Tuple of unpacked values.
    """
    fmt, size = _TYPES[type_name]
    combined_fmt = '>' + fmt[1] * count
    return struct.unpack_from(combined_fmt, data, offset)


def size_of(type_name):
    """Return the byte size of a primitive type."""
    return _TYPES[type_name][1]


def read_native(type_name, data, offset=0):
    """Read a single value using native byte order (for keyframe data)."""
    native_types = {
        'float':  ('f', 4),
        'short':  ('h', 2),
        'ushort': ('H', 2),
        'char':   ('b', 1),
        'uchar':  ('B', 1),
    }
    fmt, size = native_types[type_name]
    return struct.unpack(fmt, data[offset:offset + size])[0]


# --- Write helpers ---

def pack(type_name, value):
    """Pack a single value into big-endian bytes.

    Args:
        type_name: One of 'uint', 'int', 'ushort', 'short', 'uchar', 'char', 'float'.
        value: The value to pack.

    Returns:
        bytes of the packed value.
    """
    fmt, _ = _TYPES[type_name]
    return struct.pack(fmt, value)


def pack_many(type_name, *values):
    """Pack multiple values of the same type into big-endian bytes.

    Args:
        type_name: Primitive type name.
        *values: Values to pack.

    Returns:
        bytes of the packed values.
    """
    fmt, _ = _TYPES[type_name]
    combined_fmt = '>' + fmt[1] * len(values)
    return struct.pack(combined_fmt, *values)


def write_into(type_name, value, buffer, offset):
    """Write a single value into a mutable buffer at the given offset.

    Args:
        type_name: Primitive type name.
        value: The value to write.
        buffer: A mutable bytearray or memoryview.
        offset: byte offset into buffer.
    """
    fmt, size = _TYPES[type_name]
    struct.pack_into(fmt, buffer, offset, value)
