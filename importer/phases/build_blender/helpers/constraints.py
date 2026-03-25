"""Build Blender bone constraints from IR constraint types."""
import bpy
from mathutils import Vector


def build_constraints(ir_model, armature, logger):
    """Create Blender bone constraints from IRModel constraint lists."""
    total = (len(ir_model.ik_constraints) + len(ir_model.copy_location_constraints) +
             len(ir_model.track_to_constraints) + len(ir_model.copy_rotation_constraints) +
             len(ir_model.limit_rotation_constraints) + len(ir_model.limit_location_constraints))
    if total == 0:
        return

    logger.info("  Building %d constraint(s)", total)

    for ik in ir_model.ik_constraints:
        _build_ik(ik, armature)

    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='POSE')

    for cl in ir_model.copy_location_constraints:
        c = armature.pose.bones[cl.bone_name].constraints.new(type='COPY_LOCATION')
        c.influence = cl.influence
        c.target = armature
        c.subtarget = cl.target_bone

    for tt in ir_model.track_to_constraints:
        c = armature.pose.bones[tt.bone_name].constraints.new(type='TRACK_TO')
        c.target = armature
        c.subtarget = tt.target_bone
        c.track_axis = tt.track_axis
        c.up_axis = tt.up_axis

    for cr in ir_model.copy_rotation_constraints:
        c = armature.pose.bones[cr.bone_name].constraints.new(type='COPY_ROTATION')
        c.target = armature
        c.subtarget = cr.target_bone
        c.owner_space = cr.owner_space
        c.target_space = cr.target_space

    for lim in ir_model.limit_rotation_constraints:
        _build_limit(armature, lim, 'LIMIT_ROTATION')

    for lim in ir_model.limit_location_constraints:
        _build_limit(armature, lim, 'LIMIT_LOCATION')

    bpy.ops.object.mode_set(mode='OBJECT')


def _build_ik(ik, armature):
    """Build IK constraint with bone repositioning."""
    # Reposition bones based on IK bone lengths
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

    # Add the IK constraint
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
    """Build a LIMIT_ROTATION or LIMIT_LOCATION constraint."""
    # Find or create constraint
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
