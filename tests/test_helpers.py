"""Tests for shared/helpers: math_shim and srgb."""
import math
import pytest

from shared.helpers.srgb import srgb_to_linear, linear_to_srgb
from shared.helpers.math_shim import Matrix, Vector, Euler


# ---- sRGB tests ----

def test_srgb_to_linear_low():
    """Low values use linear segment."""
    assert abs(srgb_to_linear(0.0) - 0.0) < 1e-6
    assert abs(srgb_to_linear(0.04) - 0.04 / 12.92) < 1e-6


def test_srgb_to_linear_high():
    """High values use power curve."""
    result = srgb_to_linear(0.5)
    expected = ((0.5 + 0.055) / 1.055) ** 2.4
    assert abs(result - expected) < 1e-6


def test_srgb_to_linear_one():
    assert abs(srgb_to_linear(1.0) - 1.0) < 1e-6


def test_linear_to_srgb_round_trip():
    """srgb -> linear -> srgb round-trips correctly."""
    for v in [0.0, 0.01, 0.1, 0.5, 0.9, 1.0]:
        assert abs(linear_to_srgb(srgb_to_linear(v)) - v) < 1e-6


def test_linear_to_srgb_low():
    assert abs(linear_to_srgb(0.0) - 0.0) < 1e-6


# ---- Vector tests ----

def test_vector_basic():
    v = Vector((1, 2, 3))
    assert v.x == 1.0
    assert v.y == 2.0
    assert v.z == 3.0
    assert len(v) == 3


def test_vector_add():
    a = Vector((1, 2, 3))
    b = Vector((4, 5, 6))
    c = a + b
    assert c[0] == 5.0
    assert c[1] == 7.0
    assert c[2] == 9.0


def test_vector_length():
    v = Vector((3, 4, 0))
    assert abs(v.length - 5.0) < 1e-6


def test_vector_normalize():
    v = Vector((0, 3, 4))
    n = v.normalized()
    assert abs(n.length - 1.0) < 1e-6


def test_vector_dot():
    a = Vector((1, 0, 0))
    b = Vector((0, 1, 0))
    assert abs(a.dot(b)) < 1e-6


def test_vector_cross():
    x = Vector((1, 0, 0))
    y = Vector((0, 1, 0))
    z = x.cross(y)
    assert abs(z[0]) < 1e-6
    assert abs(z[1]) < 1e-6
    assert abs(z[2] - 1.0) < 1e-6


# ---- Matrix tests ----

def test_matrix_identity():
    m = Matrix.Identity(4)
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            assert abs(m[i][j] - expected) < 1e-6


def test_matrix_multiply_identity():
    m = Matrix.Identity(4)
    v = Vector((1, 2, 3))
    result = m @ v
    assert abs(result[0] - 1.0) < 1e-6
    assert abs(result[1] - 2.0) < 1e-6
    assert abs(result[2] - 3.0) < 1e-6


def test_matrix_translation():
    m = Matrix.Translation(Vector((10, 20, 30)))
    v = Vector((1, 2, 3))
    result = m @ v
    assert abs(result[0] - 11.0) < 1e-6
    assert abs(result[1] - 22.0) < 1e-6
    assert abs(result[2] - 33.0) < 1e-6


def test_matrix_scale():
    m = Matrix.Scale(2, 4)
    v = Vector((1, 2, 3))
    result = m @ v
    assert abs(result[0] - 2.0) < 1e-6
    assert abs(result[1] - 4.0) < 1e-6
    assert abs(result[2] - 6.0) < 1e-6


def test_matrix_rotation_z_90():
    m = Matrix.Rotation(math.pi / 2, 4, 'Z')
    v = Vector((1, 0, 0))
    result = m @ v
    assert abs(result[0]) < 1e-6
    assert abs(result[1] - 1.0) < 1e-6
    assert abs(result[2]) < 1e-6


def test_matrix_rotation_x_90():
    m = Matrix.Rotation(math.pi / 2, 4, 'X')
    v = Vector((0, 1, 0))
    result = m @ v
    assert abs(result[0]) < 1e-6
    assert abs(result[1]) < 1e-6
    assert abs(result[2] - 1.0) < 1e-6


def test_matrix_matmul():
    a = Matrix.Translation(Vector((1, 0, 0)))
    b = Matrix.Translation(Vector((0, 2, 0)))
    c = a @ b
    v = Vector((0, 0, 0))
    result = c @ v
    assert abs(result[0] - 1.0) < 1e-6
    assert abs(result[1] - 2.0) < 1e-6


def test_matrix_inverse():
    m = Matrix.Translation(Vector((5, 10, 15)))
    inv = m.inverted()
    result = m @ inv
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            assert abs(result[i][j] - expected) < 1e-8


def test_matrix_inverse_rotation():
    m = Matrix.Rotation(0.7, 4, 'Y')
    inv = m.inverted()
    result = m @ inv
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            assert abs(result[i][j] - expected) < 1e-8


def test_matrix_decompose():
    trans = Matrix.Translation(Vector((1, 2, 3)))
    rot = Matrix.Rotation(math.pi / 4, 4, 'Z')
    scl = Matrix.Scale(2, 4)
    # Compose: T @ R @ S
    m = trans @ rot @ scl
    t, q, s = m.decompose()
    assert abs(t[0] - 1.0) < 1e-6
    assert abs(t[1] - 2.0) < 1e-6
    assert abs(t[2] - 3.0) < 1e-6
    assert abs(s[0] - 2.0) < 1e-6
    assert abs(s[1] - 2.0) < 1e-6
    assert abs(s[2] - 2.0) < 1e-6


def test_matrix_normalized():
    m = Matrix.Scale(3, 4)
    m = m @ Matrix.Rotation(0.5, 4, 'X')
    n = m.normalized()
    # Each column of the 3x3 part should have unit length
    for j in range(3):
        col_len = math.sqrt(sum(n[i][j] ** 2 for i in range(3)))
        assert abs(col_len - 1.0) < 1e-8


def test_matrix_to_3x3():
    m = Matrix.Identity(4)
    m[0][3] = 99  # translation shouldn't appear in 3x3
    m3 = m.to_3x3()
    # Verify it's a 3x3 by checking row/col access
    assert len(m3[0]) == 3
    assert len(m3[1]) == 3
    assert len(m3[2]) == 3
    # Identity rotation part preserved
    assert abs(m3[0][0] - 1.0) < 1e-6


def test_matrix_determinant():
    m = Matrix.Identity(4)
    assert abs(m.determinant() - 1.0) < 1e-6
    s = Matrix.Scale(2, 4)
    assert abs(s.determinant() - 8.0) < 1e-8


# ---- Euler tests ----

def test_euler_to_matrix_identity():
    e = Euler((0, 0, 0))
    m = e.to_matrix()
    for i in range(3):
        for j in range(3):
            expected = 1.0 if i == j else 0.0
            assert abs(m[i][j] - expected) < 1e-6


def test_euler_round_trip():
    """Euler -> Matrix -> Euler round-trips for small angles."""
    original = Euler((0.3, 0.5, 0.7))
    m = original.to_matrix()
    m4 = m.to_4x4()
    recovered = m4.to_euler()
    assert abs(recovered.x - original.x) < 1e-6
    assert abs(recovered.y - original.y) < 1e-6
    assert abs(recovered.z - original.z) < 1e-6


def test_matrix_to_euler_90_x():
    m = Matrix.Rotation(math.pi / 2, 4, 'X')
    e = m.to_euler()
    assert abs(e.x - math.pi / 2) < 1e-6
    assert abs(e.y) < 1e-6
    assert abs(e.z) < 1e-6
