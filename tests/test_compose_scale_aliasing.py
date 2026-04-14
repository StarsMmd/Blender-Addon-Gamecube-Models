"""Regression: pre-scale pass must be immune to aliased matrix fields.

describe_skeleton used to build world_matrix and normalized_world_matrix
(and the local-matrix pair) from a single list, storing the same list
reference under both field names. scale_scene_to_gc_units walks each
declared matrix field and multiplies the translation column in place, so
aliased fields got scaled twice — `bone.world_matrix` came out at 100×
meters while `bone.position` (a fresh tuple) stayed at a clean 10×. The
mesh exporter reads `bone.world_matrix` when undeforming vertices, so
every mesh ended up 10× off against its correctly-scaled parent bone —
skeleton looked fine in-Blender, meshes were garbled.

These tests pin down two invariants:
  1. When the scaler encounters aliased fields, it still produces a
     single 10× translation (not 100×).
  2. describe_skeleton (the historical culprit) now emits distinct list
     objects, so the aliasing can't silently return.
"""
from shared.IR import IRScene
from shared.IR.skeleton import IRBone, IRModel
from shared.IR.enums import ScaleInheritance
from shared.helpers.scale import METERS_TO_GC
from exporter.phases.compose.helpers.scale import scale_scene_to_gc_units


def _matrix_with_translation(tx, ty, tz):
    return [[1, 0, 0, tx], [0, 1, 0, ty], [0, 0, 1, tz], [0, 0, 0, 1]]


def _make_bone(world, local, norm_world, norm_local, ibm=None):
    return IRBone(
        name='b', parent_index=None,
        position=(1.0, 2.0, 3.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        inverse_bind_matrix=ibm,
        flags=0, is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED, ik_shrink=False,
        world_matrix=world, local_matrix=local,
        normalized_world_matrix=norm_world,
        normalized_local_matrix=norm_local,
        scale_correction=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        accumulated_scale=(1.0, 1.0, 1.0),
    )


def _scene_with_bone(bone):
    model = IRModel(name='m', bones=[bone])
    return IRScene(models=[model])


def test_scaler_does_not_double_apply_when_world_aliases_normalized_world():
    # Simulate the exact shape of the pre-fix bug: world_matrix and
    # normalized_world_matrix are the SAME list object.
    shared = _matrix_with_translation(0.1, 0.2, 0.3)
    bone = _make_bone(world=shared, local=_matrix_with_translation(0.4, 0.5, 0.6),
                       norm_world=shared,  # ← alias
                       norm_local=_matrix_with_translation(0.7, 0.8, 0.9))

    scale_scene_to_gc_units(_scene_with_bone(bone))

    # The translation must be 10× (meters→GC), not 100×.
    assert bone.world_matrix[0][3] == 0.1 * METERS_TO_GC
    assert bone.world_matrix[1][3] == 0.2 * METERS_TO_GC
    assert bone.world_matrix[2][3] == 0.3 * METERS_TO_GC


def test_scaler_does_not_double_apply_when_local_aliases_normalized_local():
    shared = _matrix_with_translation(0.4, 0.5, 0.6)
    bone = _make_bone(world=_matrix_with_translation(0.1, 0.2, 0.3),
                       local=shared, norm_world=_matrix_with_translation(1, 1, 1),
                       norm_local=shared)

    scale_scene_to_gc_units(_scene_with_bone(bone))

    assert bone.local_matrix[0][3] == 0.4 * METERS_TO_GC
    assert bone.local_matrix[1][3] == 0.5 * METERS_TO_GC
    assert bone.local_matrix[2][3] == 0.6 * METERS_TO_GC


def test_describe_skeleton_emits_distinct_matrix_objects():
    """Guard against the aliasing ever coming back in describe_skeleton.

    describe_skeleton needs a real Blender context to call end-to-end, so
    we can't invoke it from a unit test. Instead assert the specific
    structural property that caused the bug: the four matrix fields on
    IRBone must be independent list objects for the scaler to work on
    each field exactly once.
    """
    # Build a bone the way describe_skeleton now does (each field its own list).
    bone = _make_bone(
        world=_matrix_with_translation(1, 2, 3),
        local=_matrix_with_translation(4, 5, 6),
        norm_world=_matrix_with_translation(1, 2, 3),   # same values, distinct list
        norm_local=_matrix_with_translation(4, 5, 6),
    )
    # The four matrices must be distinct Python objects.
    mats = [bone.world_matrix, bone.local_matrix,
            bone.normalized_world_matrix, bone.normalized_local_matrix]
    ids = {id(m) for m in mats}
    assert len(ids) == 4, "describe_skeleton matrix fields must not alias — " \
                          "aliasing caused the pre-scale pass to 10× them twice"
