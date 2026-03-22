import bpy
from mathutils import Matrix, Vector

from ...Node import Node
from ....Constants import *
from ....IO.Logger import NullLogger
from .Frame import read_fobjdesc

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

    def build(self, joint, action, armature, builder):
        """
        joint:    the corresponding Joint node (bone)
        action:   a bpy.data.actions object
        armature: the Blender armature object
        builder:  ModelBuilder
        """
        logger = builder.logger
        max_frame = builder.options.get("max_frame", 1000)

        bone_name = getattr(joint, 'temp_name', '???')
        has_anim = self.animation is not None
        logger.debug("AnimJoint build: bone=%s anim_joint_addr=0x%X has_animation=%s",
                     bone_name, self.address, has_anim)

        if self.animation:
            _apply_animation_to_bone(joint, self.animation, action, armature, max_frame, logger)

        # Log traversal decisions
        has_anim_child = self.child is not None
        has_joint_child = joint.child is not None
        has_anim_next = self.next is not None
        has_joint_next = joint.next is not None

        if has_anim_child != has_joint_child:
            logger.warning("AnimJoint TREE MISMATCH at bone=%s: anim_child=%s joint_child=%s",
                           bone_name, has_anim_child, has_joint_child)
        if has_anim_next != has_joint_next:
            logger.warning("AnimJoint TREE MISMATCH at bone=%s: anim_next=%s joint_next=%s",
                           bone_name, has_anim_next, has_joint_next)

        if self.child and joint.child:
            self.child.build(joint.child, action, armature, builder)
        if self.next and joint.next:
            self.next.build(joint.next, action, armature, builder)


def _apply_animation_to_bone(joint, aobj, action, armature, max_frame, logger=NullLogger()):
    """Port of add_jointanim_to_armature_total from reference."""
    bone_name = getattr(joint, 'temp_name', '???')

    if aobj.flags & AOBJ_NO_ANIM:
        logger.debug("  %s: AOBJ_NO_ANIM flag set, skipping", bone_name)
        return

    logger.debug("  %s: aobj flags=0x%X end_frame=%.1f", bone_name, aobj.flags, aobj.end_frame)

    transform_list = [None] * _TRANSFORMCOUNT
    has_path = False
    channel_types = []

    fobj = aobj.frame
    while fobj:
        if fobj.type == HSD_A_J_PATH:
            has_path = True
            channel_types.append('PATH')
            _apply_path_animation(joint, fobj, aobj, action, armature, max_frame)
        elif HSD_A_J_ROTX <= fobj.type <= HSD_A_J_SCAZ:
            data_letter, component = _t_jointanim_type_dict[fobj.type]
            channel_types.append('%s[%d]' % (data_letter, component))
            data_path = 'pose.bones["' + joint.temp_name + '"].' + data_letter
            curve = action.fcurves.new(data_path, index=component)
            transform_list[fobj.type - HSD_A_J_ROTX] = curve

            read_fobjdesc(fobj, curve, 0, 1)

            if aobj.flags & AOBJ_ANIM_LOOP:
                curve.modifiers.new('CYCLES')
        else:
            channel_types.append('UNKNOWN(%d)' % fobj.type)

        fobj = fobj.next

    logger.debug("  %s: channels=[%s] has_path=%s", bone_name, ', '.join(channel_types), has_path)

    if has_path:
        # Path animation handles its own keyframes; clean up any partial SRT curves
        for c in transform_list:
            if c:
                action.fcurves.remove(c)
        return

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

    invmtx = joint.temp_matrix_local.inverted()

    # Log frame-0 raw values from temp curves
    r0 = [transform_list[i].evaluate(0) if transform_list[i] else None for i in range(3)]
    t0 = [transform_list[i+4].evaluate(0) if transform_list[i+4] else None for i in range(3)]
    s0 = [transform_list[i+7].evaluate(0) if transform_list[i+7] else None for i in range(3)]
    logger.debug("  %s: frame0 raw: rot=%s trans=%s scale=%s", bone_name, r0, t0, s0)
    logger.debug("  %s: rest pose:  rot=%s trans=%s scale=%s",
                 bone_name, list(joint.rotation), list(joint.position), list(joint.scale))

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
        Bmtx = invmtx @ mtx
        trans, rot, scale = Bmtx.decompose()
        rot = rot.to_euler()
        if frame == 0:
            logger.debug("  %s: frame0 final: rot=(%.4f,%.4f,%.4f) loc=(%.4f,%.4f,%.4f) scale=(%.4f,%.4f,%.4f)",
                         bone_name, rot[0], rot[1], rot[2], trans[0], trans[1], trans[2], scale[0], scale[1], scale[2])
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


def _apply_path_animation(joint, fobj, aobj, action, armature, max_frame):
    """Apply spline path-based animation to a bone.
    The path fobj references a Spline attached to the joint. The bone
    follows the spline curve instead of using SRT keyframes."""
    from ..Misc.Spline import Spline

    spline = None
    if joint.property and isinstance(joint.property, Spline):
        spline = joint.property
    elif hasattr(joint, 'flags') and joint.flags & JOBJ_SPLINE and joint.property:
        spline = joint.property

    if not spline or not spline.s1:
        return

    # Build a temporary fcurve for the path parameter
    param_curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].path_param', index=0)
    read_fobjdesc(fobj, param_curve, 0, 1)

    # Create Blender fcurves for location
    loc_curves = []
    for i in range(3):
        curve = action.fcurves.new(
            'pose.bones["' + joint.temp_name + '"].location', index=i)
        loc_curves.append(curve)

    invmtx = joint.temp_matrix_local.inverted()
    end = min(int(aobj.end_frame), max_frame)
    points = spline.s1

    for frame in range(end):
        t = param_curve.evaluate(frame)
        # Clamp t to valid range
        t = max(0.0, min(t, len(points) - 1))
        # Linear interpolation between spline control points
        idx = int(t)
        frac = t - idx
        if idx >= len(points) - 1:
            pos = points[-1]
        else:
            p0 = points[idx]
            p1 = points[idx + 1]
            pos = [p0[j] + frac * (p1[j] - p0[j]) for j in range(3)]

        # Convert from HSD space to bone-local pose space
        world_pos = Vector(pos)
        local_mtx = Matrix.Translation(world_pos)
        Bmtx = invmtx @ local_mtx
        trans = Bmtx.to_translation()

        for i in range(3):
            loc_curves[i].keyframe_points.insert(frame, trans[i]).interpolation = 'BEZIER'

    if aobj.flags & AOBJ_ANIM_LOOP:
        for c in loc_curves:
            c.modifiers.new('CYCLES')

    # Remove the temporary parameter curve
    action.fcurves.remove(param_curve)
