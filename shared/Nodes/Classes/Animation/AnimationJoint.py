import bpy
import math
from mathutils import Matrix, Vector

from ...Node import Node
from ....Constants import *
from .Frame import read_fobjdesc
from ....BlenderVersion import BlenderVersion

# Mapping: HSD animation type code → (temp data-path letter, component index)
_t_jointanim_type_dict = {
    HSD_A_J_ROTX: ('r', 0),
    HSD_A_J_ROTY: ('r', 1),
    HSD_A_J_ROTZ: ('r', 2),
    HSD_A_J_TRAX: ('l', 0),
    HSD_A_J_TRAY: ('l', 1),
    HSD_A_J_TRAZ: ('l', 2),
    HSD_A_J_SCAX: ('s', 0),
    HSD_A_J_SCAY: ('s', 1),
    HSD_A_J_SCAZ: ('s', 2),
}

# Number of transform channels (ROTX..SCAZ inclusive, 1-indexed so index = type - HSD_A_J_ROTX)
_TRANSFORMCOUNT = (HSD_A_J_SCAZ - HSD_A_J_ROTX) + 1


# Animation Joint
class AnimationJoint(Node):
    class_name = "Animation Joint"
    fields = [
        ('child', 'AnimationJoint'),
        ('next', 'AnimationJoint'),
        ('animation', 'Animation'),
        ('render_animation', 'RenderAnimation'),
        ('flags', 'uint'),
    ]

    def build(self, joint, action, builder, armature=None):
        """
        joint:    the corresponding Joint node (bone)
        action:   a bpy.data.actions object
        builder:  ModelBuilder
        armature: the armature object (needed for path animation)
        """
        max_frame = builder.options.get("max_frame", 1000)

        if self.animation:
            _apply_animation_to_bone(joint, self.animation, action, max_frame, armature)

        if self.child and joint.child:
            self.child.build(joint.child, action, builder, armature)
        if self.next and joint.next:
            self.next.build(joint.next, action, builder, armature)


def _apply_animation_to_bone(joint, aobj, action, max_frame, armature=None):
    """Port of add_jointanim_to_armature_total from reference."""
    if aobj.flags & AOBJ_NO_ANIM:
        return

    transform_list = [None] * _TRANSFORMCOUNT
    uses_path = False

    fobj = aobj.frame
    while fobj:
        if fobj.type == HSD_A_J_PATH:
            uses_path = True
            _apply_path_animation(joint, fobj, action, aobj, armature)
        elif HSD_A_J_ROTX <= fobj.type <= HSD_A_J_SCAZ:
            data_letter, component = _t_jointanim_type_dict[fobj.type]
            data_path = 'pose.bones["' + joint.temp_name + '"].' + data_letter
            curve = action.fcurves.new(data_path, index=component)
            transform_list[fobj.type - HSD_A_J_ROTX] = curve

            read_fobjdesc(fobj, curve, 0, 1)

            if aobj.flags & AOBJ_ANIM_LOOP:
                curve.modifiers.new('CYCLES')

        fobj = fobj.next

    # Fill any missing channels with a constant rest-pose keyframe
    for i in range(3):
        if not transform_list[i]:
            curve = action.fcurves.new(
                'pose.bones["' + joint.temp_name + '"].r', index=i)
            curve.keyframe_points.insert(0, joint.rotation[i])
            transform_list[i] = curve
        if not transform_list[i + 4]:
            curve = action.fcurves.new(
                'pose.bones["' + joint.temp_name + '"].l', index=i)
            curve.keyframe_points.insert(0, joint.position[i])
            transform_list[i + 4] = curve
        if not transform_list[i + 7]:
            curve = action.fcurves.new(
                'pose.bones["' + joint.temp_name + '"].s', index=i)
            curve.keyframe_points.insert(0, joint.scale[i])
            transform_list[i + 7] = curve

    # Create the final Blender-path fcurves
    new_transform_list = [None] * 10
    for i in range(3):
        curve = action.fcurves.new(
            'pose.bones["' + joint.temp_name + '"].rotation_euler', index=i)
        new_transform_list[i] = curve
        curve = action.fcurves.new(
            'pose.bones["' + joint.temp_name + '"].location', index=i)
        new_transform_list[i + 4] = curve
        curve = action.fcurves.new(
            'pose.bones["' + joint.temp_name + '"].scale', index=i)
        new_transform_list[i + 7] = curve

    end = min(int(aobj.end_frame), max_frame)
    for frame in range(end):
        mtx = joint.compileSRTMatrix(
            [transform_list[7].evaluate(frame),
             transform_list[8].evaluate(frame),
             transform_list[9].evaluate(frame)],
            [transform_list[0].evaluate(frame),
             transform_list[1].evaluate(frame),
             transform_list[2].evaluate(frame)],
            [transform_list[4].evaluate(frame),
             transform_list[5].evaluate(frame),
             transform_list[6].evaluate(frame)],
        )

        # When using path animation, pre-multiply by coordinate rotation
        if uses_path:
            mtx = Matrix.Rotation(-math.pi / 2, 4, 'X') @ mtx

        # New matrix formula accounting for scale correction
        if joint.temp_parent:
            Bmtx = joint.local_edit_matrix.inverted() @ joint.temp_parent.edit_scale_correction @ mtx @ joint.edit_scale_correction.inverted()
        else:
            Bmtx = joint.local_edit_matrix.inverted() @ mtx @ joint.edit_scale_correction.inverted()

        trans, rot, scale = Bmtx.decompose()
        rot = rot.to_euler()
        new_transform_list[0].keyframe_points.insert(frame, rot[0]).interpolation = 'BEZIER'
        new_transform_list[1].keyframe_points.insert(frame, rot[1]).interpolation = 'BEZIER'
        new_transform_list[2].keyframe_points.insert(frame, rot[2]).interpolation = 'BEZIER'
        new_transform_list[4].keyframe_points.insert(frame, trans[0]).interpolation = 'BEZIER'
        new_transform_list[5].keyframe_points.insert(frame, trans[1]).interpolation = 'BEZIER'
        new_transform_list[6].keyframe_points.insert(frame, trans[2]).interpolation = 'BEZIER'
        new_transform_list[7].keyframe_points.insert(frame, scale[0]).interpolation = 'BEZIER'
        new_transform_list[8].keyframe_points.insert(frame, scale[1]).interpolation = 'BEZIER'
        new_transform_list[9].keyframe_points.insert(frame, scale[2]).interpolation = 'BEZIER'

    # Remove the temporary raw-HSD fcurves
    for c in transform_list:
        if c:
            action.fcurves.remove(c)


def _apply_path_animation(joint, fobj, action, aobj, armature):
    """Handle HSD_A_J_PATH: build spline curve and follow-path constraint."""
    if not armature:
        return

    spline = joint.property
    if not spline:
        return

    from ..Misc.Spline import Spline
    if not isinstance(spline, Spline):
        return

    # Build the spline curve object
    curve_obj = spline.build()
    if not curve_obj:
        return

    # Create a loose bone hierarchy for spline positioning
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='EDIT')
    loose_bone = armature.data.edit_bones.new(name=joint.temp_name + '_path')
    loose_bone.head = Vector((0, 0, 0))
    loose_bone.tail = Vector((0, 1e-3, 0))
    bpy.ops.object.mode_set(mode='POSE')

    pose_bone = armature.pose.bones[loose_bone.name]

    # Add FOLLOW_PATH constraint
    follow = pose_bone.constraints.new(type='FOLLOW_PATH')
    follow.target = curve_obj
    follow.use_fixed_location = True

    # Add LIMIT_LOCATION constraint to cancel global translation
    limit = pose_bone.constraints.new(type='LIMIT_LOCATION')
    limit.owner_space = 'LOCAL'

    # Create fcurve for path offset
    data_path = 'pose.bones["' + loose_bone.name + '"].constraints["' + follow.name + '"].offset_factor'
    curve = action.fcurves.new(data_path)
    read_fobjdesc(fobj, curve, 0, 1)

    if aobj.flags & AOBJ_ANIM_LOOP:
        curve.modifiers.new('CYCLES')
