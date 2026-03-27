"""Build a Blender armature from IRModel.bones."""
import bpy
import math
import os
from mathutils import Matrix, Vector

try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_skeleton(ir_model, context, options, logger=StubLogger(), model_index=0):
    """Create a Blender armature with bones from IRModel.

    Args:
        ir_model: IRModel with bones list populated.
        context: Blender context.
        options: dict of importer options.
        logger: Logger instance (defaults to StubLogger).
        model_index: Index of this model in the scene (for unique naming).

    Returns:
        The armature object.
    """
    filepath = options.get("filepath", "")
    base_name = os.path.basename(filepath).split('.')[0] if filepath else "model"
    if ir_model.name:
        armature_name = f"{base_name}_{ir_model.name}_{model_index}"
    else:
        armature_name = f"{base_name}_{model_index}"

    armature_data = bpy.data.armatures.new(name=armature_name)
    armature = bpy.data.objects.new(name=armature_name, object_data=armature_data)

    # Coordinate system rotation: GameCube Y-up → Blender Z-up (pi/2 around X)
    armature.matrix_basis = Matrix.Translation(Vector((0, 0, 0)))
    armature.matrix_basis @= Matrix.Rotation(math.pi / 2, 4, [1.0, 0.0, 0.0])

    # Link to scene
    bpy.context.scene.collection.objects.link(armature)
    armature.select_set(True)

    if options.get("ik_hack"):
        armature_data.display_type = 'STICK'

    bpy.context.view_layer.objects.active = armature

    # Create edit bones
    bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = []
    for bone_data in ir_model.bones:
        bone = armature_data.edit_bones.new(name=bone_data.name)

        # IK hack: shrink effector/spline bones
        if bone_data.ik_shrink:
            bone.tail = Vector((0.0, 1e-3 / bone_data.scale[1] if bone_data.scale[1] != 0 else 1e-3, 0.0))
        else:
            bone.tail = Vector((0.0, 1.0, 0.0))

        # Set parent
        if bone_data.parent_index is not None:
            bone.parent = edit_bones[bone_data.parent_index]

        # Set world matrix
        bone.matrix = Matrix(bone_data.world_matrix)
        bone.inherit_scale = 'ALIGNED'

        edit_bones.append(bone)

    logger.info("  Created armature '%s' with %d bones", armature_name, len(edit_bones))

    bpy.ops.object.mode_set(mode='POSE')

    # Set rotation mode for pose bones
    for bone_data in ir_model.bones:
        pose_bone = armature.pose.bones.get(bone_data.name)
        if pose_bone:
            pose_bone.rotation_mode = 'XYZ'

    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()

    return armature
