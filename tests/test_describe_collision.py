"""Unit tests for the collision describe leg (CCD structures → collision IR)."""
import pytest

from shared.Collision.structures import CCDFile, CCDEntry, CCDMesh, CCDPoly
from shared.Constants.collision import CollisionSubsystem
from importer.phases.describe.describe_collision import describe_collision


def _poly(x=0.0, meta0=0, meta1=0):
    """One triangle offset along X, so distinct x values give distinct polys."""
    return CCDPoly(v0=(x, 0.0, 0.0), v1=(x + 1.0, 0.0, 0.0), v2=(x, 0.0, 1.0),
                   normal=(0.0, 1.0, 0.0), meta0=meta0, meta1=meta1)


def _entry(meshes, index=0, **kwargs):
    return CCDEntry(
        index=index,
        meshes={subsystem: CCDMesh(subsystem=subsystem, polys=polys)
                for subsystem, polys in meshes.items()},
        **kwargs,
    )


def _describe(*entries, name='map'):
    return describe_collision(CCDFile(name=name, entries=list(entries)))


def _mesh(ir_entry, subsystem):
    return ir_entry.mesh(subsystem)


# --- NPC wall reduction -----------------------------------------------------

def test_npc_walls_identical_to_player_walls_collapse_to_a_flag():
    walls = [_poly(0.0), _poly(2.0)]
    scene = _describe(_entry({
        CollisionSubsystem.WALL: list(walls),
        CollisionSubsystem.NPC_WALL: list(walls),
    }))
    entry = scene.entries[0]

    assert entry.npc_shares_walls is True
    assert _mesh(entry, CollisionSubsystem.NPC_WALL) is None
    assert len(_mesh(entry, CollisionSubsystem.WALL).faces) == 2


def test_npc_walls_that_add_polys_keep_only_the_extras():
    scene = _describe(_entry({
        CollisionSubsystem.WALL: [_poly(0.0)],
        CollisionSubsystem.NPC_WALL: [_poly(0.0), _poly(5.0)],
    }))
    entry = scene.entries[0]
    npc = _mesh(entry, CollisionSubsystem.NPC_WALL)

    assert entry.npc_shares_walls is True
    assert len(npc.faces) == 1
    assert npc.vertices[0] == pytest.approx((0.5, 0.0, 0.0))


def test_npc_walls_that_drop_a_player_wall_are_kept_whole():
    scene = _describe(_entry({
        CollisionSubsystem.WALL: [_poly(0.0), _poly(2.0)],
        CollisionSubsystem.NPC_WALL: [_poly(0.0)],
    }))
    entry = scene.entries[0]

    assert entry.npc_shares_walls is False
    assert len(_mesh(entry, CollisionSubsystem.NPC_WALL).faces) == 1


def test_npc_only_entry_stands_alone():
    scene = _describe(_entry({CollisionSubsystem.NPC_WALL: [_poly(0.0)]}))
    entry = scene.entries[0]

    assert entry.npc_shares_walls is False
    assert _mesh(entry, CollisionSubsystem.WALL) is None
    assert len(_mesh(entry, CollisionSubsystem.NPC_WALL).faces) == 1


def test_player_only_walls_clear_the_shared_flag():
    scene = _describe(_entry({CollisionSubsystem.WALL: [_poly(0.0)]}))
    entry = scene.entries[0]

    assert entry.npc_shares_walls is False
    assert _mesh(entry, CollisionSubsystem.NPC_WALL) is None


def test_walls_differing_only_in_edge_mask_are_not_shared():
    scene = _describe(_entry({
        CollisionSubsystem.WALL: [_poly(0.0, meta0=0b111)],
        CollisionSubsystem.NPC_WALL: [_poly(0.0, meta0=0b001)],
    }))
    entry = scene.entries[0]

    assert entry.npc_shares_walls is False
    assert len(_mesh(entry, CollisionSubsystem.NPC_WALL).faces) == 1


# --- Welding ----------------------------------------------------------------

def test_shared_corners_are_welded():
    shared = CCDPoly(v0=(0.0, 0.0, 0.0), v1=(1.0, 0.0, 0.0), v2=(0.0, 0.0, 1.0))
    neighbour = CCDPoly(v0=(1.0, 0.0, 0.0), v1=(1.0, 0.0, 1.0), v2=(0.0, 0.0, 1.0))
    scene = _describe(_entry({CollisionSubsystem.WALK: [shared, neighbour]}))

    mesh = _mesh(scene.entries[0], CollisionSubsystem.WALK)

    assert len(mesh.vertices) == 4
    assert [face.indices for face in mesh.faces] == [(0, 1, 2), (1, 3, 2)]


def test_vertices_are_scaled_from_gamecube_units_to_meters():
    poly = CCDPoly(v0=(10.0, 0.0, 0.0), v1=(20.0, 0.0, 0.0), v2=(10.0, 0.0, 30.0))
    scene = _describe(_entry({CollisionSubsystem.WALK: [poly]}))

    mesh = _mesh(scene.entries[0], CollisionSubsystem.WALK)

    assert mesh.vertices == pytest.approx([(1.0, 0.0, 0.0), (2.0, 0.0, 0.0),
                                           (1.0, 0.0, 3.0)])


def test_duplicate_triangles_keep_private_vertices():
    scene = _describe(_entry({CollisionSubsystem.WALL: [_poly(0.0), _poly(0.0)]}))

    mesh = _mesh(scene.entries[0], CollisionSubsystem.WALL)

    assert len(mesh.faces) == 2
    assert len(mesh.vertices) == 6
    assert set(mesh.faces[0].indices).isdisjoint(mesh.faces[1].indices)


def test_triangle_with_a_repeated_corner_keeps_three_distinct_indices():
    degenerate = CCDPoly(v0=(0.0, 0.0, 0.0), v1=(0.0, 0.0, 0.0), v2=(1.0, 0.0, 0.0))
    scene = _describe(_entry({CollisionSubsystem.WALL: [degenerate]}))

    face = _mesh(scene.entries[0], CollisionSubsystem.WALL).faces[0]

    assert len(set(face.indices)) == 3


# --- Metadata decoding ------------------------------------------------------

def test_walk_metadata_splits_into_layer_and_surface_nibbles():
    scene = _describe(_entry({CollisionSubsystem.WALK: [_poly(meta0=0xF102)]}))

    face = _mesh(scene.entries[0], CollisionSubsystem.WALK).faces[0]

    assert (face.layer_a, face.layer_b) == (0xF, 0x1)
    assert (face.surface_a, face.surface_b) == (0x0, 0x2)
    assert face.region_id == 0


def test_wall_metadata_is_an_edge_mask():
    scene = _describe(_entry({CollisionSubsystem.WALL: [_poly(meta0=0b101)]}))

    face = _mesh(scene.entries[0], CollisionSubsystem.WALL).faces[0]

    assert face.edge_mask == 0b101
    assert face.region_id == 0


def test_zone_trigger_metadata_carries_both_edge_mask_and_region():
    scene = _describe(_entry({
        CollisionSubsystem.ZONE_TRIGGER: [_poly(meta0=0b011, meta1=17)],
    }))

    face = _mesh(scene.entries[0], CollisionSubsystem.ZONE_TRIGGER).faces[0]

    assert face.edge_mask == 0b011
    assert face.region_id == 17


def test_button_trigger_metadata_is_a_region_id():
    scene = _describe(_entry({CollisionSubsystem.BUTTON_TRIGGER: [_poly(meta0=9)]}))

    face = _mesh(scene.entries[0], CollisionSubsystem.BUTTON_TRIGGER).faces[0]

    assert face.region_id == 9


def test_sun_faces_keep_neutral_metadata():
    scene = _describe(_entry({CollisionSubsystem.SUN: [_poly()]}))

    face = _mesh(scene.entries[0], CollisionSubsystem.SUN).faces[0]

    assert (face.edge_mask, face.region_id) == (0b111, 0)
    assert (face.layer_a, face.layer_b) == (0xF, 0xF)


# --- Entry-level data -------------------------------------------------------

def test_entry_index_transform_and_dynamic_flag_survive():
    scene = _describe(_entry(
        {CollisionSubsystem.WALL: [_poly()]},
        index=7, position=(1.0, 2.0, 3.0), scale=(2.0, 2.0, 2.0), flags=1,
    ))
    entry = scene.entries[0]

    assert entry.index == 7
    assert entry.position == pytest.approx((0.1, 0.2, 0.3))
    assert entry.scale == (2.0, 2.0, 2.0)
    assert entry.is_dynamic is True


def test_meshes_are_ordered_by_file_slot():
    scene = _describe(_entry({
        CollisionSubsystem.SUN: [_poly(8.0)],
        CollisionSubsystem.WALL: [_poly(2.0)],
        CollisionSubsystem.WALK: [_poly(0.0)],
    }))

    assert [mesh.subsystem for mesh in scene.entries[0].meshes] == [
        CollisionSubsystem.WALK, CollisionSubsystem.WALL, CollisionSubsystem.SUN,
    ]


def test_entry_without_meshes_is_preserved():
    scene = _describe(_entry({}), _entry({CollisionSubsystem.WALL: [_poly()]}, index=1))

    assert len(scene.entries) == 2
    assert scene.entries[0].meshes == []
    assert scene.name == 'map'


def test_describe_does_not_mutate_the_parsed_structures():
    ccd_entry = _entry({
        CollisionSubsystem.WALL: [_poly(0.0)],
        CollisionSubsystem.NPC_WALL: [_poly(0.0)],
    })
    describe_collision(CCDFile(name='map', entries=[ccd_entry]))

    assert len(ccd_entry.meshes[CollisionSubsystem.NPC_WALL].polys) == 1
    assert len(ccd_entry.meshes[CollisionSubsystem.WALL].polys) == 1
