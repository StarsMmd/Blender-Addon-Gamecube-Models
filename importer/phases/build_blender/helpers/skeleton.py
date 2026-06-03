"""Build a Blender armature from a BRArmature spec.

Pure bpy executor — every decision (edit-bone matrix, inherit_scale, tail
offset, display type) is already baked into the BR by the Plan phase.
"""
import bpy
from mathutils import Matrix, Vector

try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_skeleton(br_armature, context, logger=StubLogger()):
    """Create a Blender armature + bones from a BRArmature.

    Args:
        br_armature: BRArmature spec from the Plan phase.
        context: Blender context.
        logger: Logger instance.

    Returns:
        The armature object.
    """
    armature_data = bpy.data.armatures.new(name=br_armature.name)
    armature = bpy.data.objects.new(name=br_armature.name, object_data=armature_data)

    if br_armature.matrix_basis is not None:
        armature.matrix_basis = Matrix(br_armature.matrix_basis)

    bpy.context.scene.collection.objects.link(armature)
    armature_data.display_type = br_armature.display_type

    # Enter edit mode on this armature alone (multi-armature edit mode would
    # break bone creation).
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = []
    for br_bone in br_armature.bones:
        bone = armature_data.edit_bones.new(name=br_bone.name)
        bone.tail = Vector(br_bone.tail_offset)
        if br_bone.parent_index is not None:
            bone.parent = edit_bones[br_bone.parent_index]
        bone.matrix = Matrix(br_bone.edit_matrix)
        bone.inherit_scale = br_bone.inherit_scale
        bone.use_connect = br_bone.use_connect
        edit_bones.append(bone)

    logger.info("  Created armature '%s' with %d bones", br_armature.name, len(edit_bones))

    bpy.ops.object.mode_set(mode='POSE')
    for br_bone in br_armature.bones:
        pose_bone = armature.pose.bones.get(br_bone.name)
        if pose_bone:
            pose_bone.rotation_mode = br_bone.rotation_mode

    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()

    for key, value in br_armature.custom_props.items():
        armature[key] = value

    # Describe-phase leniencies come via the logger, not BR — they're a
    # per-run diagnostic, not part of the plan.
    if getattr(logger, "leniency_categories", None):
        armature["dat_leniencies"] = [
            "%s:%d" % (k, v) for k, v in sorted(logger.leniency_categories.items())
        ]

    return armature
