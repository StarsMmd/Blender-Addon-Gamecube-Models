"""Unit tests for the collision plan leg (collision IR → collision BR)."""
import pytest

from shared.IR.collision import (
    IRCollisionScene, IRCollisionEntry, IRCollisionMesh, IRCollisionFace,
)
from shared.Constants.collision import CollisionSubsystem
from shared.helpers.srgb import srgb_to_linear
from importer.phases.plan.plan_collision import (
    plan_collision, PROP_TYPE, PROP_ENTRY, PROP_REGION, PROP_NPC_BLOCKS,
    PROP_DYNAMIC, ATTR_EDGE_MASK, ATTR_LAYER_A, ATTR_LAYER_B,
    ATTR_SURFACE_A, ATTR_SURFACE_B,
)
from importer.phases.plan.helpers.armature import Y_UP_TO_Z_UP

_SQUARE = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 1.0)]


def _mesh(subsystem, faces, vertices=None):
    return IRCollisionMesh(subsystem=subsystem,
                           vertices=list(vertices if vertices else _SQUARE),
                           faces=faces)


def _plan(*entries, name='map'):
    return plan_collision(IRCollisionScene(name=name, entries=list(entries)))


def _by_name(br_collision, suffix):
    return next(obj for obj in br_collision.objects if obj.name.endswith(suffix))


def test_overlay_lives_in_one_collection_with_a_child_per_type():
    plan = _plan(
        IRCollisionEntry(index=0, meshes=[
            _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))]),
            _mesh(CollisionSubsystem.WALK, [IRCollisionFace(indices=(0, 1, 2))]),
        ]),
        IRCollisionEntry(index=1, meshes=[
            _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))])]),
    )

    assert plan.collection_name == 'Collision_map'
    # File slot order, each type once, types with no objects omitted.
    assert plan.subcollections == ['Collision_map_Walk', 'Collision_map_Wall']
    assert [obj.collection_name for obj in plan.objects] == [
        'Collision_map_Wall', 'Collision_map_Walk', 'Collision_map_Wall']


def test_every_subsystem_gets_its_own_subcollection_name():
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(subsystem, [IRCollisionFace(indices=(0, 1, 2))])
        for subsystem in (CollisionSubsystem.ZONE_TRIGGER,
                          CollisionSubsystem.BUTTON_TRIGGER,
                          CollisionSubsystem.NPC_WALL,
                          CollisionSubsystem.SUN)]))

    assert plan.subcollections == [
        'Collision_map_Zone Trigger', 'Collision_map_Button Trigger',
        'Collision_map_NPC Wall', 'Collision_map_Sun']


def test_root_carries_the_y_up_to_z_up_rotation():
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))])]))

    assert plan.name == 'map'
    assert plan.root_name == 'Collision_map'
    assert plan.root_matrix == Y_UP_TO_Z_UP


def test_objects_are_named_by_scene_entry_and_type():
    plan = _plan(IRCollisionEntry(index=4, meshes=[
        _mesh(CollisionSubsystem.NPC_WALL, [IRCollisionFace(indices=(0, 1, 2))])]))

    assert plan.objects[0].name == 'Col_map_04_npc_wall'


def test_geometry_passes_through_unrotated():
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(CollisionSubsystem.WALK, [IRCollisionFace(indices=(0, 1, 2))])]))
    obj = plan.objects[0]

    assert obj.vertices == _SQUARE[:3]
    assert obj.faces == [(0, 1, 2)]


# --- Region splitting -------------------------------------------------------

def test_region_bearing_meshes_split_one_object_per_region():
    vertices = _SQUARE + [(2.0, 0.0, 0.0), (2.0, 0.0, 1.0)]
    faces = [
        IRCollisionFace(indices=(0, 1, 2), region_id=3),
        IRCollisionFace(indices=(1, 2, 3), region_id=3),
        IRCollisionFace(indices=(1, 3, 4), region_id=1),
    ]
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(CollisionSubsystem.BUTTON_TRIGGER, faces, vertices)]))

    assert [obj.name for obj in plan.objects] == [
        'Col_map_00_button_trigger_r1', 'Col_map_00_button_trigger_r3']
    assert plan.objects[0].custom_props[PROP_REGION] == 1
    assert plan.objects[1].custom_props[PROP_REGION] == 3
    assert len(plan.objects[0].faces) == 1
    assert len(plan.objects[1].faces) == 2


def test_split_objects_only_keep_the_vertices_they_use():
    vertices = _SQUARE + [(2.0, 0.0, 0.0), (2.0, 0.0, 1.0)]
    faces = [
        IRCollisionFace(indices=(0, 1, 2), region_id=0),
        IRCollisionFace(indices=(3, 4, 5), region_id=1),
    ]
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(CollisionSubsystem.ZONE_TRIGGER, faces, vertices)]))

    second = _by_name(plan, '_r1')
    assert second.vertices == vertices[3:]
    assert second.faces == [(0, 1, 2)]


def test_zone_trigger_regions_keep_their_edge_masks_per_face():
    faces = [
        IRCollisionFace(indices=(0, 1, 2), region_id=5, edge_mask=0b011),
        IRCollisionFace(indices=(1, 2, 3), region_id=5, edge_mask=0b100),
    ]
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(CollisionSubsystem.ZONE_TRIGGER, faces)]))

    assert plan.objects[0].face_attributes[ATTR_EDGE_MASK] == [0b011, 0b100]


def test_non_region_meshes_are_not_split():
    faces = [IRCollisionFace(indices=(0, 1, 2), region_id=1),
             IRCollisionFace(indices=(1, 2, 3), region_id=2)]
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(CollisionSubsystem.WALK, faces)]))

    assert len(plan.objects) == 1
    assert PROP_REGION not in plan.objects[0].custom_props


# --- Properties and attributes ----------------------------------------------

def test_every_object_carries_type_entry_and_dynamic_props():
    plan = _plan(IRCollisionEntry(index=12, is_dynamic=True, meshes=[
        _mesh(CollisionSubsystem.SUN, [IRCollisionFace(indices=(0, 1, 2))])]))
    props = plan.objects[0].custom_props

    assert props[PROP_TYPE] == 'SUN'
    assert props[PROP_ENTRY] == 12
    assert props[PROP_DYNAMIC] is True
    assert PROP_NPC_BLOCKS not in props


def test_player_wall_objects_record_whether_npcs_share_them():
    shared = _plan(IRCollisionEntry(index=0, npc_shares_walls=True, meshes=[
        _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))])]))
    unshared = _plan(IRCollisionEntry(index=0, npc_shares_walls=False, meshes=[
        _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))])]))

    assert shared.objects[0].custom_props[PROP_NPC_BLOCKS] is True
    assert unshared.objects[0].custom_props[PROP_NPC_BLOCKS] is False


def test_walk_faces_expose_layer_and_surface_attributes():
    faces = [IRCollisionFace(indices=(0, 1, 2), layer_a=0xF, layer_b=1,
                             surface_a=2, surface_b=3)]
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(CollisionSubsystem.WALK, faces)]))
    attributes = plan.objects[0].face_attributes

    assert attributes[ATTR_LAYER_A] == [0xF]
    assert attributes[ATTR_LAYER_B] == [1]
    assert attributes[ATTR_SURFACE_A] == [2]
    assert attributes[ATTR_SURFACE_B] == [3]
    assert ATTR_EDGE_MASK not in attributes


def test_button_trigger_and_sun_faces_have_no_per_face_attributes():
    for subsystem in (CollisionSubsystem.BUTTON_TRIGGER, CollisionSubsystem.SUN):
        plan = _plan(IRCollisionEntry(index=0, meshes=[
            _mesh(subsystem, [IRCollisionFace(indices=(0, 1, 2))])]))

        assert plan.objects[0].face_attributes == {}


# --- Materials --------------------------------------------------------------

def test_one_translucent_material_per_subsystem_in_use():
    plan = _plan(
        IRCollisionEntry(index=0, meshes=[
            _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))]),
            _mesh(CollisionSubsystem.WALK, [IRCollisionFace(indices=(0, 1, 2))]),
        ]),
        IRCollisionEntry(index=1, meshes=[
            _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))])]),
    )

    assert [material.name for material in plan.materials] == [
        'DATPlugin_Collision_WALL', 'DATPlugin_Collision_WALK']
    assert [obj.material_index for obj in plan.objects] == [0, 1, 0]


def test_opacity_is_per_collision_type():
    expected = {
        CollisionSubsystem.WALK: 0.3,
        CollisionSubsystem.WALL: 0.5,
        CollisionSubsystem.NPC_WALL: 0.5,
        CollisionSubsystem.ZONE_TRIGGER: 0.7,
        CollisionSubsystem.BUTTON_TRIGGER: 0.7,
        CollisionSubsystem.SUN: 0.3,
    }
    for subsystem, alpha in expected.items():
        plan = _plan(IRCollisionEntry(index=0, meshes=[
            _mesh(subsystem, [IRCollisionFace(indices=(0, 1, 2))])]))

        assert plan.materials[0].color[3] == alpha, subsystem


def test_material_colour_is_linearised():
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))])]))
    red, green, blue, _ = plan.materials[0].color

    assert red == pytest.approx(srgb_to_linear(0.90))
    assert green == pytest.approx(srgb_to_linear(0.10))
    assert blue == pytest.approx(srgb_to_linear(0.10))
    assert plan.materials[0].blend_method == 'BLEND'
    assert plan.materials[0].surface_render_method == 'BLENDED'


# --- Entry-level -----------------------------------------------------------

def test_entry_without_meshes_becomes_a_marker():
    plan = _plan(IRCollisionEntry(index=3, is_dynamic=True))

    assert plan.objects == []
    assert len(plan.markers) == 1
    assert plan.markers[0].name == 'Col_map_03'
    assert plan.markers[0].custom_props == {PROP_ENTRY: 3, PROP_DYNAMIC: True}


def test_identity_entry_transform_leaves_the_object_at_the_root():
    plan = _plan(IRCollisionEntry(index=0, meshes=[
        _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))])]))

    assert plan.objects[0].matrix_basis is None


def test_non_identity_entry_transform_becomes_the_object_matrix():
    plan = _plan(IRCollisionEntry(
        index=0, position=(1.0, 2.0, 3.0), meshes=[
            _mesh(CollisionSubsystem.WALL, [IRCollisionFace(indices=(0, 1, 2))])]))
    matrix = plan.objects[0].matrix_basis

    assert matrix is not None
    assert [row[3] for row in matrix[:3]] == [1.0, 2.0, 3.0]


def test_plan_does_not_mutate_the_input_ir():
    faces = [IRCollisionFace(indices=(0, 1, 2), region_id=2),
             IRCollisionFace(indices=(1, 2, 3), region_id=1)]
    mesh = _mesh(CollisionSubsystem.BUTTON_TRIGGER, faces)
    entry = IRCollisionEntry(index=0, meshes=[mesh])
    plan_collision(IRCollisionScene(name='map', entries=[entry]))

    assert [face.region_id for face in mesh.faces] == [2, 1]
    assert len(mesh.vertices) == 4
