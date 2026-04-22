"""Build Blender bone constraints from a BRConstraints pass-through.

The IR constraint dataclasses already mirror Blender's constraint API
(target_bone, track_axis, owner_space, etc.) and BRConstraints holds them
unchanged — so this layer is a mechanical copy from BR fields to bpy.
"""
import bpy
from mathutils import Vector


def build_constraints(br_constraints, armature, logger):
    if br_constraints.is_empty:
        return

    logger.info("  Building %d constraint(s)", br_constraints.total)

    for ik in br_constraints.ik:
        _build_ik(ik, armature)

    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='POSE')

    for cl in br_constraints.copy_location:
        c = armature.pose.bones[cl.bone_name].constraints.new(type='COPY_LOCATION')
        c.influence = cl.influence
        c.target = armature
        c.subtarget = cl.target_bone

    for tt in br_constraints.track_to:
        c = armature.pose.bones[tt.bone_name].constraints.new(type='TRACK_TO')
        c.target = armature
        c.subtarget = tt.target_bone
        c.track_axis = tt.track_axis
        c.up_axis = tt.up_axis

    for cr in br_constraints.copy_rotation:
        c = armature.pose.bones[cr.bone_name].constraints.new(type='COPY_ROTATION')
        c.target = armature
        c.subtarget = cr.target_bone
        c.owner_space = cr.owner_space
        c.target_space = cr.target_space

    for lim in br_constraints.limit_rotation:
        _build_limit(armature, lim, 'LIMIT_ROTATION')
    for lim in br_constraints.limit_location:
        _build_limit(armature, lim, 'LIMIT_LOCATION')

    bpy.ops.object.mode_set(mode='OBJECT')


def _build_ik(ik, armature):
    for reposition in ik.bone_repositions:
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='EDIT')

        bone = armature.data.bones.get(reposition.bone_name)
        if not bone or not bone.parent:
            bpy.ops.object.mode_set(mode='POSE')
            continue

        current_pos = Vector(bone.matrix_local.translation)
        parent_pos = Vector(bone.parent.matrix_local.translation)
        direction = Vector(bone.parent.matrix_local.col[0][0:3]).normalized()
        target_pos = parent_pos + direction * reposition.bone_length

        offset = target_pos - current_pos
        edit_bone = armature.data.edit_bones[reposition.bone_name]
        edit_bone.head = Vector(edit_bone.head[:]) + offset
        edit_bone.tail = Vector(edit_bone.tail[:]) + offset

        bpy.ops.object.mode_set(mode='POSE')

    c = armature.pose.bones[ik.bone_name].constraints.new(type='IK')
    c.chain_count = ik.chain_length
    if ik.target_bone:
        c.target = armature
        c.subtarget = ik.target_bone
    if ik.pole_target_bone:
        c.pole_target = armature
        c.pole_subtarget = ik.pole_target_bone
        c.pole_angle = ik.pole_angle


def _build_limit(armature, lim, limit_type):
    existing = None
    for cnst in armature.pose.bones[lim.bone_name].constraints:
        if cnst.type == limit_type:
            existing = cnst
            break
    if not existing:
        existing = armature.pose.bones[lim.bone_name].constraints.new(type=limit_type)
        existing.owner_space = lim.owner_space

    for axis in ('x', 'y', 'z'):
        for direction in ('min', 'max'):
            attr = '%s_%s' % (direction, axis)
            value = getattr(lim, attr)
            if value is not None:
                enable_attr = 'use_%s' % attr
                setattr(existing, enable_attr, True)
                setattr(existing, attr, value)
