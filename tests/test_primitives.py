"""Smoke tests for parser primitives (no Blender required)."""
import io
import struct
import pytest

from shared.helpers.file_io import BinaryReader
from shared.Constants.RecursiveTypes import (
    isPointerType,
    isUnboundedArrayType,
    isBoundedArrayType,
    isBracketedType,
    getPointerSubType,
    getArraySubType,
    getArrayTypeBound,
)
from shared.Constants.PrimitiveTypes import (
    get_primitive_type_length,
    is_primitive_type,
)


def _reader(data: bytes) -> BinaryReader:
    return BinaryReader(io.BytesIO(data))


# ---------------------------------------------------------------------------
# BinaryReader
# ---------------------------------------------------------------------------

class TestBinaryReader:

    def test_read_uint(self):
        r = _reader(struct.pack('>I', 0xDEADBEEF))
        assert r.read('uint', 0) == 0xDEADBEEF

    def test_read_float(self):
        r = _reader(struct.pack('>f', 3.14))
        assert abs(r.read('float', 0) - 3.14) < 1e-5

    def test_read_vec3(self):
        r = _reader(struct.pack('>fff', 1.0, 2.0, 3.0))
        v = r.read('vec3', 0)
        assert abs(v[0] - 1.0) < 1e-6
        assert abs(v[1] - 2.0) < 1e-6
        assert abs(v[2] - 3.0) < 1e-6

    def test_read_uchar(self):
        r = _reader(bytes([0xAB]))
        assert r.read('uchar', 0) == 0xAB

    def test_read_string(self):
        r = _reader(b'hello\x00')
        assert r.read('string', 0) == 'hello'

    def test_read_chunk(self):
        r = _reader(bytes(range(8)))
        chunk = r.read_chunk(4, 2)
        assert chunk == bytes([2, 3, 4, 5])


# ---------------------------------------------------------------------------
# RecursiveTypes
# ---------------------------------------------------------------------------

class TestRecursiveTypes:

    def test_isPointerType(self):
        assert isPointerType('*Joint')
        assert not isPointerType('Joint')
        assert not isPointerType('Joint[]')

    def test_isUnboundedArrayType(self):
        assert isUnboundedArrayType('Joint[]')
        assert not isUnboundedArrayType('*Joint[]')
        assert not isUnboundedArrayType('[4]float')

    def test_isBoundedArrayType(self):
        assert isBoundedArrayType('float[4]')
        assert isBoundedArrayType('uchar[3]')
        assert not isBoundedArrayType('float')
        assert isUnboundedArrayType('Joint[]')
        assert not isBoundedArrayType('*float[4]')

    def test_isBracketedType(self):
        assert isBracketedType('(*Joint)')
        assert not isBracketedType('*Joint')

    def test_getPointerSubType(self):
        assert getPointerSubType('*Joint') == 'Joint'

    def test_getArraySubType_bounded(self):
        assert getArraySubType('float[4]') == 'float'
        assert getArraySubType('uchar[3]') == 'uchar'

    def test_getArraySubType_unbounded(self):
        assert getArraySubType('Joint[]') == 'Joint'

    def test_getArrayTypeBound(self):
        assert getArrayTypeBound('float[4]') == 4
        assert getArrayTypeBound('uchar[12]') == 12


# ---------------------------------------------------------------------------
# PrimitiveTypes
# ---------------------------------------------------------------------------

class TestPrimitiveTypes:

    @pytest.mark.parametrize('type_name,expected', [
        ('uchar',  1), ('char', 1), ('ushort', 2), ('short', 2),
        ('uint', 4), ('int', 4), ('float', 4), ('double', 8),
        ('vec3', 12), ('matrix', 48), ('void', 0),
    ])
    def test_get_primitive_type_length(self, type_name, expected):
        assert get_primitive_type_length(type_name) == expected

    @pytest.mark.parametrize('type_name', [
        'uchar', 'char', 'ushort', 'short', 'uint', 'int',
        'float', 'double', 'string', 'vec3', 'matrix', 'void',
    ])
    def test_is_primitive_type(self, type_name):
        assert is_primitive_type(type_name)

    def test_not_primitive_type(self):
        assert not is_primitive_type('Joint')
        assert not is_primitive_type('Frame')
        assert not is_primitive_type('*uint')
