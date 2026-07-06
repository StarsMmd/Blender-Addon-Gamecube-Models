"""Regression test: bake_imported_transforms must preserve the world
placement of non-mesh children OBJECT-parented to the armature.

The bake resets the armature's viewing rotation (matrix_basis) to identity
after folding it into bone/mesh data. Children whose data is not baked —
e.g. the FOLLOW_PATH Path_* curves — must have the old armature world
folded into their own basis, or they are left behind in the raw Y-up
frame (spline-following characters walk on a vertical plane).

Uses the real bpy module (any version ≥ 3.x provides the APIs the bake
touches); skipped when only a mock is available.
"""
import math
import pytest

bpy = pytest.importorskip("bpy")
if not hasattr(bpy.data, 'armatures'):  # mocked bpy
    pytest.skip("bpy is mocked", allow_module_level=True)

from mathutils import Matrix

from importer.phases.post_process.post_process import bake_imported_transforms


def _clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for coll in (bpy.data.meshes, bpy.data.armatures, bpy.data.curves,
                 bpy.data.actions):
        for block in list(coll):
            coll.remove(block)


def _matrices_close(a, b, tol=1e-5):
    return all(abs(a[i][j] - b[i][j]) <= tol for i in range(4) for j in range(4))


def test_object_parented_curve_keeps_world_placement():
    _clear_scene()

    arm_data = bpy.data.armatures.new('arm')
    arm = bpy.data.objects.new('arm', arm_data)
    bpy.context.scene.collection.objects.link(arm)
    # Viewing rotation the plan phase applies: pi/2 about X.
    arm.matrix_basis = Matrix.Rotation(math.pi / 2, 4, 'X')

    curve_data = bpy.data.curves.new('path', 'CURVE')
    curve = bpy.data.objects.new('Path_test', curve_data)
    curve.parent = arm
    # Y-up placement, as _apply_path_constraint sets from the raw spline joint.
    curve.matrix_local = Matrix.Translation((1.0, 2.0, 3.0))
    bpy.context.scene.collection.objects.link(curve)
    bpy.context.view_layer.update()

    world_before = curve.matrix_world.copy()
    assert not _matrices_close(world_before, curve.matrix_basis)  # rotation active

    bake_imported_transforms([arm])
    bpy.context.view_layer.update()

    assert _matrices_close(arm.matrix_world, Matrix.Identity(4))
    assert _matrices_close(curve.matrix_world, world_before), (
        f"curve world moved during bake:\nbefore={world_before}\nafter={curve.matrix_world}")

# Bone-parented children (the JOBJ_SPLINE *_spline curves) are deliberately
# not asserted here: they ride whatever frame their bone ends up in, their
# placement is documented as non-fidelity-critical (_build_bone_splines),
# and Armature.transform recomputes bone roll, so the bone-local frame is
# not exactly preserved by design.


def test_externally_constrained_armature_is_not_baked():
    """An armature whose pose bones are pinned by external-target
    constraints (FOLLOW_PATH onto a path curve) must keep its viewing
    rotation — rewriting its rest data shifts the constrained chain's
    skinned meshes off the skeleton (the D6 walking-characters bug)."""
    _clear_scene()

    arm_data = bpy.data.armatures.new('arm')
    arm = bpy.data.objects.new('arm', arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones.new('Bone_0')
    eb.head = (0.0, 0.0, 0.0)
    eb.tail = (0.0, 1.0, 0.0)
    bpy.ops.object.mode_set(mode='OBJECT')
    rotation = Matrix.Rotation(math.pi / 2, 4, 'X')
    arm.matrix_basis = rotation.copy()

    curve_data = bpy.data.curves.new('path', 'CURVE')
    curve_data.use_path = True
    curve = bpy.data.objects.new('Path_test', curve_data)
    curve.parent = arm
    bpy.context.scene.collection.objects.link(curve)

    constr = arm.pose.bones['Bone_0'].constraints.new('FOLLOW_PATH')
    constr.target = curve
    bpy.context.view_layer.update()

    baked = bake_imported_transforms([arm])

    assert baked == 0
    assert _matrices_close(arm.matrix_basis, rotation), (
        "externally constrained armature must keep its viewing rotation")
