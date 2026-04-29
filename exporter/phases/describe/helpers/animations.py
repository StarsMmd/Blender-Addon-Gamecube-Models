"""Snapshot Blender Actions into BRAction dataclasses.

Interim: the unbaking / sparsification / slot-reorder logic still lives
in the legacy `describe_blender/helpers/animations.py::
describe_bone_animations`. This helper wraps that output as a list of
BRAction shells so the rest of the pipeline runs through BR.

The legacy function returns `list[IRBoneAnimationSet]`; we stash each
IRBoneAnimationSet on the matching BRAction so plan can hand it back
unchanged. A future pass can faithfully serialise pose-bone fcurves
into BRBoneTrack / BRMaterialTrack and move the unbaking logic into
plan.
"""
try:
    from .....shared.BR.actions import BRAction
    from .....shared.helpers.logger import StubLogger
    from .animations_decode import describe_bone_animations
except (ImportError, SystemError):
    from shared.BR.actions import BRAction
    from shared.helpers.logger import StubLogger
    from exporter.phases.describe.helpers.animations_decode import describe_bone_animations


def describe_actions(armature, br_armature, ir_bones, logger=StubLogger(),
                     use_bezier=True, referenced_actions=None,
                     ir_meshes=None, blender_materials=None):
    """Read Blender Actions associated with an armature into BRAction list.

    In: armature (bpy.types.Object); br_armature (BRArmature, currently
        unused but kept for forward compatibility); ir_bones (list[IRBone]
        the legacy unbaker still needs); logger; use_bezier (bool, controls
        sparsifier); referenced_actions (optional set[str] used to drop
        unreferenced actions that bloat the DAT); ir_meshes /
        blender_materials (parallel lists for material-anim binding;
        either both supplied or both None).
    Out: list[BRAction]. Each BRAction carries the legacy
         IRBoneAnimationSet on ``_ir_animation_set`` until the unbake
         logic migrates into plan.
    """
    ir_anim_sets = describe_bone_animations(
        armature, ir_bones, logger=logger, use_bezier=use_bezier,
        referenced_actions=referenced_actions,
        meshes=ir_meshes, mesh_materials=blender_materials,
    )

    actions = []
    for ir_set in ir_anim_sets:
        action = BRAction(name=ir_set.name)
        action._ir_animation_set = ir_set
        actions.append(action)
    return actions
