"""Describe Joint tree as a flat list of IRBone dataclasses.

Ports the pure-data computation from Joint.buildBoneHierarchy() and
Joint.compileSRTMatrix(), producing IRBone instances without any bpy calls.
"""
from shared.helpers.math_shim import Matrix, Vector, Euler
from shared.IR.skeleton import IRBone
from shared.IR.enums import ScaleInheritance
from shared.Constants.hsd import (
    JOBJ_HIDDEN, JOBJ_INSTANCE, JOBJ_EFFECTOR, JOBJ_SPLINE,
    JOBJ_TYPE_MASK,
)


def describe_bones(root_joint, options=None):
    """Walk a Joint tree and produce a flat list of IRBone.

    Args:
        root_joint: Root Joint node from the parsed node tree.
        options: dict of importer options (uses 'ik_hack').

    Returns:
        (list[IRBone], dict[int, int]) — bones list and joint_address→bone_index map.
    """
    if options is None:
        options = {}

    bones = []
    joint_to_bone_index = {}
    bone_count = [0]  # mutable counter for closure

    def _walk(joint, parent_index, parent_data):
        """Recursively describe a Joint and its children/siblings.

        parent_data is a dict with keys: scl, world_matrix, edit_matrix,
        edit_scale_correction — or None for roots.
        """
        my_index = len(bones)
        joint_to_bone_index[joint.address] = my_index

        name = 'Bone_' + str(bone_count[0])
        bone_count[0] += 1

        # Determine IK shrink
        ik_shrink = bool(
            options.get("ik_hack")
            and ((joint.flags & JOBJ_TYPE_MASK) == JOBJ_EFFECTOR
                 or joint.flags & JOBJ_SPLINE)
        )

        # Accumulate parent scales for aligned scale inheritance
        if parent_data:
            accumulated_scale = tuple(
                joint.scale[i] * parent_data['scl'][i] for i in range(3)
            )
            parent_scl = parent_data['scl']
        else:
            accumulated_scale = tuple(joint.scale)
            parent_scl = None

        # Build local SRT matrix
        local_matrix = _compile_srt_matrix(
            joint.scale, joint.rotation, joint.position, parent_scl
        )

        # Compute world matrix
        if parent_data:
            world_matrix = parent_data['world_matrix'] @ local_matrix
        else:
            world_matrix = local_matrix

        # Compute normalized matrices for rest-pose binding
        normalized_world = world_matrix.normalized()
        if parent_data:
            normalized_local = parent_data['edit_matrix'].inverted() @ normalized_world
            scale_correction = (
                parent_data['edit_scale_correction']
                @ local_matrix.normalized().inverted()
                @ local_matrix
            )
        else:
            normalized_local = normalized_world
            scale_correction = local_matrix.normalized().inverted() @ local_matrix

        # Get inverse bind matrix if present
        inverse_bind = None
        if hasattr(joint, 'inverse_bind') and joint.inverse_bind is not None:
            inv = joint.inverse_bind
            if hasattr(inv, 'to_list'):
                inverse_bind = inv.to_list()
            elif isinstance(inv, (list, tuple)):
                inverse_bind = [list(row) for row in inv]
            else:
                inverse_bind = [[inv[i][j] for j in range(4)] for i in range(4)]

        bone = IRBone(
            name=name,
            parent_index=parent_index,
            position=tuple(joint.position),
            rotation=tuple(joint.rotation),
            scale=tuple(joint.scale),
            inverse_bind_matrix=inverse_bind,
            flags=joint.flags,
            is_hidden=bool(joint.flags & JOBJ_HIDDEN),
            inherit_scale=ScaleInheritance.ALIGNED,
            ik_shrink=ik_shrink,
            world_matrix=_matrix_to_list(world_matrix),
            local_matrix=_matrix_to_list(local_matrix),
            normalized_world_matrix=_matrix_to_list(normalized_world),
            normalized_local_matrix=_matrix_to_list(normalized_local),
            scale_correction=_matrix_to_list(scale_correction),
            accumulated_scale=accumulated_scale,
        )
        bones.append(bone)

        # Data passed to children
        my_data = {
            'scl': accumulated_scale,
            'world_matrix': world_matrix,
            'edit_matrix': normalized_world,
            'edit_scale_correction': scale_correction,
        }

        # Recurse into children (skip instances)
        if joint.child and not (joint.flags & JOBJ_INSTANCE):
            _walk(joint.child, my_index, my_data)

        # Recurse into siblings (same parent)
        if joint.next:
            _walk(joint.next, parent_index, parent_data)

    _walk(root_joint, None, None)
    return bones, joint_to_bone_index


def _compile_srt_matrix(scale, rotation, position, parent_scl=None):
    """Build a local SRT matrix, matching Joint.compileSRTMatrix()."""
    scale_x = Matrix.Scale(scale[0], 4, [1.0, 0.0, 0.0])
    scale_y = Matrix.Scale(scale[1], 4, [0.0, 1.0, 0.0])
    scale_z = Matrix.Scale(scale[2], 4, [0.0, 0.0, 1.0])
    rotation_x = Matrix.Rotation(rotation[0], 4, 'X')
    rotation_y = Matrix.Rotation(rotation[1], 4, 'Y')
    rotation_z = Matrix.Rotation(rotation[2], 4, 'Z')
    translation = Matrix.Translation(Vector(position))
    mtx = translation @ rotation_z @ rotation_y @ rotation_x @ scale_z @ scale_y @ scale_x
    # Aligned scale inheritance: corrects for non-uniform parent scales
    if parent_scl:
        for i in range(3):
            for j in range(3):
                mtx[i][j] *= parent_scl[j] / parent_scl[i]
    return mtx


def _matrix_to_list(matrix):
    """Convert a Matrix to list[list[float]] for IR storage."""
    if hasattr(matrix, 'to_list'):
        return matrix.to_list()
    return [[matrix[i][j] for j in range(4)] for i in range(4)]
