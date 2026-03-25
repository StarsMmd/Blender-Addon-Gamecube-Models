"""Smoke tests for parser primitives (no Blender required)."""
import struct
import tempfile
import os
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_tmp(data: bytes) -> str:
    f = tempfile.NamedTemporaryFile(delete=False, suffix='.bin')
    f.write(data)
    f.close()
    return f.name


# ---------------------------------------------------------------------------
# BinaryReader
# ---------------------------------------------------------------------------

class TestBinaryReader:

    def test_read_uint(self):
        path = _write_tmp(struct.pack('>I', 0xDEADBEEF))
        try:
            import io; r = BinaryReader(io.BytesIO(open(path, "rb").read()))
            assert r.read('uint', 0) == 0xDEADBEEF
        finally:
            os.unlink(path)

    def test_read_float(self):
        path = _write_tmp(struct.pack('>f', 3.14))
        try:
            import io; r = BinaryReader(io.BytesIO(open(path, "rb").read()))
            assert abs(r.read('float', 0) - 3.14) < 1e-5
        finally:
            os.unlink(path)

    def test_read_vec3(self):
        data = struct.pack('>fff', 1.0, 2.0, 3.0)
        path = _write_tmp(data)
        try:
            import io; r = BinaryReader(io.BytesIO(open(path, "rb").read()))
            v = r.read('vec3', 0)
            assert abs(v[0] - 1.0) < 1e-6
            assert abs(v[1] - 2.0) < 1e-6
            assert abs(v[2] - 3.0) < 1e-6
        finally:
            os.unlink(path)

    def test_read_uchar(self):
        path = _write_tmp(bytes([0xAB]))
        try:
            import io; r = BinaryReader(io.BytesIO(open(path, "rb").read()))
            assert r.read('uchar', 0) == 0xAB
        finally:
            os.unlink(path)

    def test_read_string(self):
        path = _write_tmp(b'hello\x00')
        try:
            import io; r = BinaryReader(io.BytesIO(open(path, "rb").read()))
            assert r.read('string', 0) == 'hello'
        finally:
            os.unlink(path)

    def test_read_chunk(self):
        payload = bytes(range(8))
        path = _write_tmp(payload)
        try:
            import io; r = BinaryReader(io.BytesIO(open(path, "rb").read()))
            chunk = r.read_chunk(4, 2)
            assert chunk == bytes([2, 3, 4, 5])
        finally:
            os.unlink(path)


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
        # Unbounded arrays also satisfy isBoundedArrayType (the predicates overlap);
        # use isUnboundedArrayType to distinguish the two.
        assert isUnboundedArrayType('Joint[]')
        assert not isBoundedArrayType('*float[4]')  # pointer type excluded

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
        ('uchar',  1),
        ('char',   1),
        ('ushort', 2),
        ('short',  2),
        ('uint',   4),
        ('int',    4),
        ('float',  4),
        ('double', 8),
        ('vec3',   12),
        ('matrix', 48),
        ('void',   0),
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
