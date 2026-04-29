"""Snapshot a Blender armature's pose-bone constraints into BRConstraints.

The IR constraint dataclasses already mirror Blender's constraint API
(target_bone names, track / up axes, owner-space enums, etc.), so the
direct read produces IR-shaped values that BRConstraints holds by
reference. Plan unwraps them in O(1).
"""
import bpy

try:
    from .....shared.BR.constraints import BRConstraints
    from .....shared.IR.constraints import (
        IRIKConstraint, IRBoneReposition, IRCopyLocationConstraint,
        IRTrackToConstraint, IRCopyRotationConstraint, IRLimitConstraint,
    )
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.BR.constraints import BRConstraints
    from shared.IR.constraints import (
        IRIKConstraint, IRBoneReposition, IRCopyLocationConstraint,
        IRTrackToConstraint, IRCopyRotationConstraint, IRLimitConstraint,
    )
    from shared.helpers.logger import StubLogger


def describe_constraints(armature, ir_bones, logger=StubLogger()):
    """In: armature (bpy.types.Object); ir_bones (list[IRBone] for chain
    walks the IK reposition needs); logger.
    Out: BRConstraints holding the six IR constraint lists.
    """
    bone_name_to_idx = {b.name: i for i, b in enumerate(ir_bones)}

    ik = []
    copy_loc = []
    track_to = []
    copy_rot = []
    limit_rot = []
    limit_loc = []

    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='POSE')

    for pose_bone in armature.pose.bones:
        bone_name = pose_bone.name
        if bone_name not in bone_name_to_idx:
            continue

        for constraint in pose_bone.constraints:
            if not constraint.enabled:
                continue

            if constraint.type == 'IK':
                result = _describe_ik(constraint, bone_name, armature, ir_bones, bone_name_to_idx)
                if result:
                    ik.append(result)
            elif constraint.type == 'COPY_LOCATION':
                target_name = constraint.subtarget
                if target_name:
                    copy_loc.append(IRCopyLocationConstraint(
                        bone_name=bone_name,
                        target_bone=target_name,
                        influence=constraint.influence,
                    ))
            elif constraint.type == 'TRACK_TO':
                target_name = constraint.subtarget
                if target_name:
                    track_to.append(IRTrackToConstraint(
                        bone_name=bone_name,
                        target_bone=target_name,
                        track_axis=constraint.track_axis,
                        up_axis=constraint.up_axis,
                    ))
            elif constraint.type == 'COPY_ROTATION':
                target_name = constraint.subtarget
                if target_name:
                    copy_rot.append(IRCopyRotationConstraint(
                        bone_name=bone_name,
                        target_bone=target_name,
                        owner_space=constraint.owner_space,
                        target_space=constraint.target_space,
                    ))
            elif constraint.type == 'LIMIT_ROTATION':
                result = _describe_limit(constraint, bone_name)
                if result:
                    limit_rot.append(result)
            elif constraint.type == 'LIMIT_LOCATION':
                result = _describe_limit(constraint, bone_name)
                if result:
                    limit_loc.append(result)

    bpy.ops.object.mode_set(mode='OBJECT')

    total = len(ik) + len(copy_loc) + len(track_to) + len(copy_rot) + len(limit_rot) + len(limit_loc)
    if total:
        logger.info("  Described %d constraint(s) (IK=%d, CopyLoc=%d, TrackTo=%d, CopyRot=%d, LimitRot=%d, LimitLoc=%d)",
                    total, len(ik), len(copy_loc), len(track_to), len(copy_rot), len(limit_rot), len(limit_loc))

    return BRConstraints(
        ik=ik, copy_location=copy_loc, track_to=track_to,
        copy_rotation=copy_rot, limit_rotation=limit_rot, limit_location=limit_loc,
    )


def _describe_ik(constraint, bone_name, armature, ir_bones, bone_name_to_idx):
    chain_length = constraint.chain_count
    if chain_length not in (2, 3):
        return None

    target_bone = constraint.subtarget if constraint.target else None
    pole_target_bone = constraint.pole_subtarget if constraint.pole_target else None
    pole_angle = constraint.pole_angle

    repositions = []
    bone_idx = bone_name_to_idx.get(bone_name)
    if bone_idx is not None:
        current_idx = bone_idx
        for _ in range(chain_length - 1):
            parent_idx = ir_bones[current_idx].parent_index
            if parent_idx is None:
                break
            parent_scale = ir_bones[parent_idx].accumulated_scale[0]
            if parent_scale == 0:
                parent_scale = 1.0
            data_bone = armature.data.bones.get(ir_bones[current_idx].name)
            if data_bone and data_bone.parent:
                from mathutils import Vector
                current_pos = Vector(data_bone.matrix_local.translation)
                parent_pos = Vector(data_bone.parent.matrix_local.translation)
                raw_length = (current_pos - parent_pos).length
                bone_length = raw_length / parent_scale
                repositions.append(IRBoneReposition(
                    bone_name=ir_bones[current_idx].name,
                    bone_length=bone_length,
                ))
            current_idx = parent_idx

    return IRIKConstraint(
        bone_name=bone_name,
        chain_length=chain_length,
        target_bone=target_bone,
        pole_target_bone=pole_target_bone,
        pole_angle=pole_angle,
        bone_repositions=repositions,
    )


def _describe_limit(constraint, bone_name):
    has_any = False
    kwargs = {'bone_name': bone_name, 'owner_space': constraint.owner_space}
    for axis in ('x', 'y', 'z'):
        for direction in ('min', 'max'):
            enable_attr = 'use_%s_%s' % (direction, axis)
            if getattr(constraint, enable_attr, False):
                kwargs['%s_%s' % (direction, axis)] = getattr(constraint, '%s_%s' % (direction, axis))
                has_any = True
    if not has_any:
        return None
    return IRLimitConstraint(**kwargs)
