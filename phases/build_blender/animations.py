"""Build Blender bone animations from raw animation data.

Performs the two-pass baking strategy:
1. Decode HSD keyframes into temporary Blender fcurves
2. Sample frame-by-frame, apply scale correction, decompose to bone-local

This must run in Blender (Phase 5A) since it uses fcurve.evaluate().
"""
import bpy
from mathutils import Matrix, Vector

try:
    from ...shared.Constants.hsd import *
    from ...shared.IO.Logger import NullLogger
    from ...shared.Nodes.Classes.Animation.Frame import read_fobjdesc
    from ...shared.BlenderVersion import BlenderVersion
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.IO.Logger import NullLogger
    from shared.Nodes.Classes.Animation.Frame import read_fobjdesc
    from shared.BlenderVersion import BlenderVersion

from ..describe.bones import _compile_srt_matrix

# HSD type → (temp data-path letter, component index)
_TYPE_MAP = {
    HSD_A_J_ROTX: ('r', 0), HSD_A_J_ROTY: ('r', 1), HSD_A_J_ROTZ: ('r', 2),
    HSD_A_J_TRAX: ('l', 0), HSD_A_J_TRAY: ('l', 1), HSD_A_J_TRAZ: ('l', 2),
    HSD_A_J_SCAX: ('s', 0), HSD_A_J_SCAY: ('s', 1), HSD_A_J_SCAZ: ('s', 2),
}

_TRANSFORMCOUNT = (HSD_A_J_SCAZ - HSD_A_J_ROTX) + 1


def build_bone_animations(raw_animation_sets, ir_model, armature, options, logger=None):
    """Create Blender Actions from raw animation data.

    Args:
        raw_animation_sets: list[RawAnimationSet] from describe phase.
        ir_model: IRModel with bones data.
        armature: Blender armature object.
        options: importer options dict.
        logger: Logger instance.
    """
    if logger is None:
        logger = NullLogger()

    max_frame = options.get("max_frame", 1000)
    actions = []

    for raw_set in raw_animation_sets:
        action = bpy.data.actions.new(raw_set.name)
        action.use_fake_user = True
        if bpy.app.version >= BlenderVersion(4, 5, 0):
            action.slots.new('OBJECT', 'Armature')
            action.slots.active = action.slots[0]

        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='POSE')

        for bone in armature.pose.bones:
            bone.rotation_mode = 'XYZ'
        for bone in armature.data.bones:
            bone.use_local_location = True

        armature.animation_data_create()
        armature.animation_data.action = action
        if bpy.app.version >= BlenderVersion(4, 4, 0):
            armature.animation_data.action_slot = action.slots[0]

        for raw_anim in raw_set.bone_anims:
            _bake_bone_animation(raw_anim, action, armature, ir_model, max_frame, logger, raw_set.bone_data_lookup)

        # Detect static poses
        is_static = True
        for fcurve in action.fcurves:
            if len(fcurve.keyframe_points) > 1:
                first_val = fcurve.keyframe_points[0].co[1]
                for kp in fcurve.keyframe_points:
                    if abs(kp.co[1] - first_val) > 1e-6:
                        is_static = False
                        break
            if not is_static:
                break

        if is_static:
            action.name = raw_set.name.replace('Anim', 'Pose')

        actions.append(action)
        logger.info("  Action '%s': %d fcurves, static=%s", action.name, len(action.fcurves), is_static)

        bpy.ops.object.mode_set(mode='OBJECT')

    # Reset pose to rest position and select the first animation
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='POSE')
    for bone in armature.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.scale = (1, 1, 1)
    bpy.ops.object.mode_set(mode='OBJECT')

    if actions:
        first_anim = next((a for a in actions if '_Anim_' in a.name), None)
        armature.animation_data.action = first_anim or actions[0]
    bpy.context.scene.frame_set(0)


def _bake_bone_animation(raw_anim, action, armature, ir_model, max_frame, logger, bone_data_lookup):
    """Bake one bone's animation using the two-pass strategy."""
    bone_name = raw_anim.bone_name
    bone_idx = raw_anim.bone_index
    bone_data = bone_data_lookup[bone_idx]
    parent_idx = bone_data['parent_index']

    if raw_anim.has_path:
        _apply_path_animation(raw_anim, action, bone_data_lookup[bone_idx], max_frame)
        return

    # Pass 1: decode HSD keyframes into temporary fcurves
    transform_list = [None] * _TRANSFORMCOUNT

    for hsd_type, fobj in raw_anim.channels.items():
        data_letter, component = _TYPE_MAP[hsd_type]
        data_path = 'pose.bones["%s"].%s' % (bone_name, data_letter)
        curve = action.fcurves.new(data_path, index=component)
        transform_list[hsd_type - HSD_A_J_ROTX] = curve
        read_fobjdesc(fobj, curve, 0, 1, logger)

        if raw_anim.loop:
            curve.modifiers.new('CYCLES')

    # Fill missing channels with rest-pose constants
    for i in range(3):
        if not transform_list[i]:
            curve = action.fcurves.new('pose.bones["%s"].r' % bone_name, index=i)
            curve.keyframe_points.insert(0, raw_anim.rest_rotation[i])
            transform_list[i] = curve
        if not transform_list[i + 4]:
            curve = action.fcurves.new('pose.bones["%s"].l' % bone_name, index=i)
            curve.keyframe_points.insert(0, raw_anim.rest_position[i])
            transform_list[i + 4] = curve
        if not transform_list[i + 7]:
            curve = action.fcurves.new('pose.bones["%s"].s' % bone_name, index=i)
            curve.keyframe_points.insert(0, raw_anim.rest_scale[i])
            transform_list[i + 7] = curve

    # Create final Blender fcurves
    new_transform_list = [None] * 10
    for i in range(3):
        new_transform_list[i] = action.fcurves.new(
            'pose.bones["%s"].rotation_euler' % bone_name, index=i)
        new_transform_list[i + 4] = action.fcurves.new(
            'pose.bones["%s"].location' % bone_name, index=i)
        new_transform_list[i + 7] = action.fcurves.new(
            'pose.bones["%s"].scale' % bone_name, index=i)

    # Pre-fetch matrices from bone_data_lookup (no Joint node access)
    local_edit_matrix = bone_data['local_edit_matrix']
    edit_scale_correction = bone_data['edit_scale_correction']
    temp_matrix_local = bone_data['temp_matrix_local']
    parent_edit_scale_correction = (
        bone_data_lookup[parent_idx]['edit_scale_correction'] if parent_idx is not None else None
    )
    parent_scl = raw_anim.parent_scl

    # Pass 2: frame-by-frame baking with scale correction
    end = min(int(raw_anim.end_frame), max_frame)
    for frame in range(end):
        scale = [transform_list[7].evaluate(frame),
                 transform_list[8].evaluate(frame),
                 transform_list[9].evaluate(frame)]
        rotation = [transform_list[0].evaluate(frame),
                    transform_list[1].evaluate(frame),
                    transform_list[2].evaluate(frame)]
        location = [transform_list[4].evaluate(frame),
                    transform_list[5].evaluate(frame),
                    transform_list[6].evaluate(frame)]

        mtx = _compile_srt_matrix(scale, rotation, location, parent_scl)

        try:
            if parent_idx is not None:
                Bmtx = (local_edit_matrix.inverted()
                        @ parent_edit_scale_correction
                        @ mtx
                        @ edit_scale_correction.inverted())
            else:
                Bmtx = (local_edit_matrix.inverted()
                        @ mtx
                        @ edit_scale_correction.inverted())
        except ValueError:
            Bmtx = temp_matrix_local.inverted_safe() @ mtx

        trans, rot, scl = Bmtx.decompose()
        rot = rot.to_euler()

        max_scl = 100.0
        scl = Vector((
            max(-max_scl, min(max_scl, scl[0])),
            max(-max_scl, min(max_scl, scl[1])),
            max(-max_scl, min(max_scl, scl[2])),
        ))

        new_transform_list[0].keyframe_points.insert(frame, rot[0]).interpolation = 'BEZIER'
        new_transform_list[1].keyframe_points.insert(frame, rot[1]).interpolation = 'BEZIER'
        new_transform_list[2].keyframe_points.insert(frame, rot[2]).interpolation = 'BEZIER'
        new_transform_list[4].keyframe_points.insert(frame, trans[0]).interpolation = 'BEZIER'
        new_transform_list[5].keyframe_points.insert(frame, trans[1]).interpolation = 'BEZIER'
        new_transform_list[6].keyframe_points.insert(frame, trans[2]).interpolation = 'BEZIER'
        new_transform_list[7].keyframe_points.insert(frame, scl[0]).interpolation = 'BEZIER'
        new_transform_list[8].keyframe_points.insert(frame, scl[1]).interpolation = 'BEZIER'
        new_transform_list[9].keyframe_points.insert(frame, scl[2]).interpolation = 'BEZIER'

    # Remove temporary raw fcurves
    for c in transform_list:
        if c:
            action.fcurves.remove(c)


def _apply_path_animation(raw_anim, action, bone_data, max_frame):
    """Apply spline path-based animation to a bone."""
    fobj = raw_anim.path_fobj
    if not fobj:
        return

    spline_points = getattr(raw_anim, 'spline_points', None)
    if not spline_points:
        return

    bone_name = raw_anim.bone_name
    param_curve = action.fcurves.new('pose.bones["%s"].path_param' % bone_name, index=0)
    read_fobjdesc(fobj, param_curve, 0, 1)

    loc_curves = [
        action.fcurves.new('pose.bones["%s"].location' % bone_name, index=i)
        for i in range(3)
    ]

    invmtx = bone_data['temp_matrix_local'].inverted()
    end = min(int(raw_anim.end_frame), max_frame)

    for frame in range(end):
        t = param_curve.evaluate(frame)
        t = max(0.0, min(t, len(spline_points) - 1))
        idx = int(t)
        frac = t - idx
        if idx >= len(spline_points) - 1:
            pos = spline_points[-1]
        else:
            p0 = spline_points[idx]
            p1 = spline_points[idx + 1]
            pos = [p0[j] + frac * (p1[j] - p0[j]) for j in range(3)]

        world_pos = Vector(pos)
        local_mtx = Matrix.Translation(world_pos)
        Bmtx = invmtx @ local_mtx
        trans = Bmtx.to_translation()

        for i in range(3):
            loc_curves[i].keyframe_points.insert(frame, trans[i]).interpolation = 'BEZIER'

    if raw_anim.loop:
        for c in loc_curves:
            c.modifiers.new('CYCLES')

    action.fcurves.remove(param_curve)
