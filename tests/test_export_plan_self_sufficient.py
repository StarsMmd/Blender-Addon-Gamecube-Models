"""The exporter Plan phase derives IR bones/meshes from BR itself.

Regression guard for the describe→plan split. Plan used to read
``br_model._ir_bones`` / ``br_model._ir_meshes`` — a side-channel the
describe phase stashed after pre-computing the IR with a live bpy
context. That made BR → IR work *only* on a BRScene produced by export
describe, and crash (AttributeError) on any other BRScene (e.g. one the
importer's Plan produced, as the IBI round-trip now feeds it).

Plan now re-derives bones/meshes from BR via the pure ``plan_armature``
/ ``plan_meshes`` / ``merge_meshes`` helpers, so a hand-built BRScene
with no stash plans cleanly.
"""
from shared.BR.scene import BRScene, BRModel
from shared.BR.armature import BRArmature, BRBone
from exporter.phases.plan.plan import plan_scene


def _identity_bone(name, parent_index):
    return BRBone(
        name=name,
        parent_index=parent_index,
        edit_matrix=[
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        tail_offset=(0.0, 0.1, 0.0),
        inherit_scale='FULL',
    )


def _scene_without_stash():
    armature = BRArmature(
        name="rig",
        bones=[_identity_bone("root", None), _identity_bone("child", 0)],
    )
    model = BRModel(name="rig", armature=armature)
    # Deliberately do NOT set model._ir_bones / model._ir_meshes.
    return BRScene(models=[model])


def test_plan_scene_derives_bones_without_stash():
    """plan_scene works on a BRScene that never carried the describe stash."""
    scene = _scene_without_stash()
    assert not hasattr(scene.models[0], "_ir_bones")

    ir = plan_scene(scene, options={'skip_baked_transforms_validation': True})

    assert len(ir.models) == 1
    bones = ir.models[0].bones
    assert [b.name for b in bones] == ["root", "child"]
    assert bones[1].parent_index == 0


def test_plan_scene_ignores_any_stray_stash():
    """Even if a stale stash is present, plan derives bones from BR itself."""
    scene = _scene_without_stash()
    # An obviously-wrong stash must not leak into the result.
    scene.models[0]._ir_bones = ["garbage"]
    scene.models[0]._ir_meshes = ["garbage"]

    ir = plan_scene(scene, options={'skip_baked_transforms_validation': True})

    assert [b.name for b in ir.models[0].bones] == ["root", "child"]
