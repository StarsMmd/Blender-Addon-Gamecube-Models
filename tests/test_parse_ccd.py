"""Unit tests for the .ccd binary structure layer (shared/Collision/parser.py)."""
import struct

import pytest

from helpers import build_ccd, build_ccd_poly
from shared.Collision.parser import parse_ccd
from shared.Constants.collision import CollisionSubsystem


def _tri(x=0.0, meta0=0, meta1=0):
    """One axis-aligned triangle offset along X."""
    return {
        'v0': (x, 0.0, 0.0),
        'v1': (x + 1.0, 0.0, 0.0),
        'v2': (x, 0.0, 1.0),
        'normal': (0.0, 1.0, 0.0),
        'meta0': meta0,
        'meta1': meta1,
    }


def test_parses_file_head_and_entry_count():
    data = build_ccd([{'meshes': {'walk': [_tri()]}},
                      {'meshes': {'wall': [_tri()]}}])

    ccd = parse_ccd(data, name='test_map')

    assert ccd.name == 'test_map'
    assert len(ccd.entries) == 2
    assert [entry.index for entry in ccd.entries] == [0, 1]


def test_parses_entry_transform_and_dynamic_flag():
    data = build_ccd([{
        'position': (1.0, 2.0, 3.0),
        'rotation': (0.0, 0.5, 0.0),
        'scale': (2.0, 2.0, 2.0),
        'flags': 1,
        'meshes': {'wall': [_tri()]},
    }])

    entry = parse_ccd(data).entries[0]

    assert entry.position == (1.0, 2.0, 3.0)
    assert entry.rotation == pytest.approx((0.0, 0.5, 0.0))
    assert entry.scale == (2.0, 2.0, 2.0)
    assert entry.is_dynamic is True


def test_identity_entry_is_not_dynamic():
    data = build_ccd([{'meshes': {'wall': [_tri()]}}])

    entry = parse_ccd(data).entries[0]

    assert entry.flags == 0
    assert entry.is_dynamic is False
    assert entry.position == (0.0, 0.0, 0.0)
    assert entry.scale == (1.0, 1.0, 1.0)


def test_parses_every_subsystem_slot():
    data = build_ccd([{'meshes': {
        'walk': [_tri(0.0)],
        'wall': [_tri(2.0), _tri(4.0)],
        'zone_trigger': [_tri(6.0)],
        'button_trigger': [_tri(8.0)],
        'npc_wall': [_tri(2.0)],
        'sun': [_tri(10.0)],
    }}])

    entry = parse_ccd(data).entries[0]

    assert set(entry.meshes) == set(CollisionSubsystem)
    assert len(entry.meshes[CollisionSubsystem.WALL].polys) == 2
    assert len(entry.meshes[CollisionSubsystem.WALK].polys) == 1


def test_parses_poly_geometry_and_metadata():
    data = build_ccd([{'meshes': {'zone_trigger': [_tri(0.0, meta0=0b101, meta1=42)]}}])

    poly = parse_ccd(data).entries[0].meshes[CollisionSubsystem.ZONE_TRIGGER].polys[0]

    assert poly.v0 == (0.0, 0.0, 0.0)
    assert poly.v1 == (1.0, 0.0, 0.0)
    assert poly.v2 == (0.0, 0.0, 1.0)
    assert poly.normal == (0.0, 1.0, 0.0)
    assert poly.vertices == (poly.v0, poly.v1, poly.v2)
    assert poly.meta0 == 0b101
    assert poly.meta1 == 42


def test_sun_polys_carry_no_metadata():
    data = build_ccd([{'meshes': {'sun': [_tri()]}}])

    mesh = parse_ccd(data).entries[0].meshes[CollisionSubsystem.SUN]

    assert mesh.poly_size == 0x30
    assert mesh.polys[0].meta0 == 0
    assert mesh.polys[0].meta1 == 0
    assert mesh.grid is None


def test_gridded_meshes_parse_their_grid():
    data = build_ccd([{'meshes': {'walk': [_tri(0.0), _tri(4.0)]}}])

    mesh = parse_ccd(data).entries[0].meshes[CollisionSubsystem.WALK]

    assert mesh.grid is not None
    assert (mesh.grid.width, mesh.grid.height) == (1, 1)
    assert mesh.grid.cells == [(0, 2)]
    assert mesh.grid.index_pool == [0, 1]
    assert mesh.grid.origin_x == 0.0


def test_button_trigger_meshes_have_no_grid():
    data = build_ccd([{'meshes': {'button_trigger': [_tri()]}}])

    mesh = parse_ccd(data).entries[0].meshes[CollisionSubsystem.BUTTON_TRIGGER]

    assert mesh.grid is None
    assert mesh.poly_size == 0x34


def test_rejects_file_too_short_for_a_header():
    with pytest.raises(ValueError, match="too short"):
        parse_ccd(b'\x00\x00', name='stub')


def test_rejects_entry_table_past_end_of_file():
    data = bytearray(build_ccd([{'meshes': {'wall': [_tri()]}}]))
    struct.pack_into('>I', data, 0x04, 999)   # absurd entry count

    with pytest.raises(ValueError, match="entry table"):
        parse_ccd(bytes(data), name='broken')


def test_rejects_entry_table_overlapping_the_header():
    data = bytearray(build_ccd([{'meshes': {'wall': [_tri()]}}]))
    struct.pack_into('>I', data, 0x00, 0x04)

    with pytest.raises(ValueError, match="overlaps the file header"):
        parse_ccd(bytes(data), name='broken')


def test_rejects_poly_array_past_end_of_file():
    data = bytearray(build_ccd([{'meshes': {'button_trigger': [_tri()]}}]))
    head = struct.unpack_from('>I', data, 0x10 + 0x30)[0]   # button-trigger slot pointer
    struct.pack_into('>I', data, head + 0x04, 4096)          # absurd poly count

    with pytest.raises(ValueError, match="BUTTON_TRIGGER polys"):
        parse_ccd(bytes(data), name='broken')


def test_rejects_grid_index_pointing_past_the_poly_array():
    data = bytearray(build_ccd([{'meshes': {'walk': [_tri()]}}]))
    head = struct.unpack_from('>I', data, 0x10 + 0x24)[0]    # walk slot pointer
    pool = struct.unpack_from('>I', data, head + 0x0C)[0]
    struct.pack_into('>I', data, pool, 7)

    with pytest.raises(ValueError, match="grid index pool references poly 7"):
        parse_ccd(bytes(data), name='broken')


def test_empty_entry_parses_with_no_meshes():
    data = build_ccd([{'meshes': {}}, {'meshes': {'wall': [_tri()]}}])

    ccd = parse_ccd(data)

    assert ccd.entries[0].meshes == {}
    assert len(ccd.entries[1].meshes) == 1


def test_sun_poly_packing_is_four_bytes_shorter():
    assert len(build_ccd_poly((0, 0, 0), (1, 0, 0), (0, 0, 1), sun=True)) == 0x30
    assert len(build_ccd_poly((0, 0, 0), (1, 0, 0), (0, 0, 1))) == 0x34
