"""Describe a Blender armature as a flat list of IRBone dataclasses.

Reads edit bones from an arbitrary Blender armature, applies the coordinate
system conversion (Blender Z-up → GameCube Y-up), and decomposes bone
matrices into HSD-convention SRT values.

No assumptions are made about bone naming conventions or import-specific
metadata — this works with any well-formed Blender armature.
"""
import math
import bpy
from mathutils import Matrix

try:
    from ......shared.IR.skeleton import IRBone
    from ......shared.IR.enums import ScaleInheritance
    from ......shared.Constants.hsd import JOBJ_SKELETON, JOBJ_HIDDEN
    from ......shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.skeleton import IRBone
    from shared.IR.enums import ScaleInheritance
    from shared.Constants.hsd import JOBJ_SKELETON, JOBJ_HIDDEN
    from shared.helpers.logger import StubLogger


# Blender Z-up → GameCube Y-up: inverse of the pi/2 X rotation applied on import
_COORD_ROTATION_INV = Matrix.Rotation(math.pi / 2, 4, [1.0, 0.0, 0.0]).inverted()


def describe_skeleton(armature, logger=StubLogger()):
    """Read a Blender armature and produce a flat list of IRBone.

    Bones are output in a depth-first order that mirrors the parent/child
    hierarchy — parents always appear before their children. This is the
    order the DAT format expects.

    Args:
        armature: Blender armature object (bpy.types.Object with armature data).
        logger: Logger instance.

    Returns:
        list[IRBone] — flat bone list with parent_index references.
    """
    armature_data = armature.data

    # Enter edit mode to read edit bone data
    prev_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = armature
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    armature.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    # Build a depth-first ordered list of edit bones.
    # Blender's edit_bones collection has no guaranteed order, so we walk
    # the hierarchy manually: roots first, then children recursively.
    roots = [b for b in armature_data.edit_bones if b.parent is None]
    ordered_bones = []
    _collect_depth_first(roots, ordered_bones)

    # Build name → index lookup for parent resolution
    bone_name_to_index = {bone.name: i for i, bone in enumerate(ordered_bones)}

    # Snapshot edit bone data (must be read while in edit mode)
    edit_bone_data = []
    for bone in ordered_bones:
        parent_name = bone.parent.name if bone.parent else None
        edit_bone_data.append({
            'name': bone.name,
            'parent_name': parent_name,
            'matrix': bone.matrix.copy(),
            'hide': bone.hide,
        })

    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = prev_active

    # Convert edit bone data to IRBone list
    bones = []
    gc_world_matrices = {}  # {index: Matrix} in GameCube coordinate space

    for i, data in enumerate(edit_bone_data):
        parent_index = bone_name_to_index.get(data['parent_name']) if data['parent_name'] else None

        # Edit bone .matrix is a 4x4 in armature-local space (normalized, no scale).
        # Undo the coordinate rotation to get GameCube-space world matrix.
        gc_world = _COORD_ROTATION_INV @ data['matrix']
        gc_world_matrices[i] = gc_world

        # Compute local matrix relative to parent
        if parent_index is not None:
            gc_local = gc_world_matrices[parent_index].inverted() @ gc_world
        else:
            gc_local = gc_world

        # Decompose local matrix to SRT
        translation, quat, scale = gc_local.decompose()
        euler = quat.to_euler('XYZ')

        position = (translation.x, translation.y, translation.z)
        rotation = (euler.x, euler.y, euler.z)
        scale_tuple = (scale.x, scale.y, scale.z)

        # Accumulated scale (product of this bone's scale with all ancestors)
        if parent_index is not None:
            parent_accum = bones[parent_index].accumulated_scale
            accumulated_scale = tuple(scale_tuple[c] * parent_accum[c] for c in range(3))
        else:
            accumulated_scale = scale_tuple

        # Flags — deduce from Blender state where possible
        flags = JOBJ_SKELETON
        is_hidden = data['hide']
        if is_hidden:
            flags |= JOBJ_HIDDEN

        # Matrix representations for IR
        world_list = _matrix_to_list(gc_world)
        local_list = _matrix_to_list(gc_local)
        identity_list = _matrix_to_list(Matrix.Identity(4))

        bone = IRBone(
            name=data['name'],
            parent_index=parent_index,
            position=position,
            rotation=rotation,
            scale=scale_tuple,
            inverse_bind_matrix=None,
            flags=flags,
            is_hidden=is_hidden,
            inherit_scale=ScaleInheritance.ALIGNED,
            ik_shrink=False,
            world_matrix=world_list,
            local_matrix=local_list,
            normalized_world_matrix=world_list,
            normalized_local_matrix=local_list,
            scale_correction=identity_list,
            accumulated_scale=accumulated_scale,
        )
        bones.append(bone)

    logger.info("  Described %d bones from armature '%s'", len(bones), armature.name)
    return bones


def _collect_depth_first(siblings, result):
    """Recursively collect bones in depth-first order (parent before children)."""
    for bone in siblings:
        result.append(bone)
        if bone.children:
            _collect_depth_first(bone.children, result)


def _matrix_to_list(matrix):
    """Convert a Blender Matrix to list[list[float]]."""
    return [[matrix[i][j] for j in range(4)] for i in range(4)]
