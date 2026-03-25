"""Build Blender bone animations from IRBoneAnimationSet.

Reads generic decoded keyframes from the IR and performs Blender-specific
baking: inserts into temp fcurves, samples frame-by-frame with scale
correction, decomposes to bone-local Euler, creates final Actions.
"""
import bpy
from mathutils import Matrix, Vector

try:
    from .....shared.Constants.hsd import *
    from .....shared.IO.Logger import StubLogger
    from .....shared.BlenderVersion import BlenderVersion
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.IO.Logger import StubLogger
    from shared.BlenderVersion import BlenderVersion

from ...describe.helpers.bones import _compile_srt_matrix


def build_bone_animations(ir_model, armature, options, logger=StubLogger()):
    """Create Blender Actions from IRBoneAnimationSet list.

    Args:
        ir_model: IRModel with bone_animations and bones populated.
        armature: Blender armature object.
        options: importer options dict.
        logger: Logger instance.
    """
    max_frame = options.get("max_frame", 1000)
    bone_data = _build_bone_data_lookup(ir_model.bones)
    actions = []

    for anim_set in ir_model.bone_animations:
        action = bpy.data.actions.new(anim_set.name)
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

        for track in anim_set.tracks:
            _bake_bone_track(track, action, bone_data, max_frame, logger)

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
            action.name = anim_set.name.replace('Anim', 'Pose')

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


def _bake_bone_track(track, action, bone_data, max_frame, logger):
    """Bake one bone's IRBoneTrack into Blender fcurves."""
    bone_name = track.bone_name
    bone_idx = track.bone_index
    bd = bone_data[bone_idx]
    parent_idx = bd['parent_index']

    if track.path_keyframes is not None:
        _apply_path_animation(track, action, bd, max_frame)
        return

    # Pass 1: insert decoded IR keyframes into temporary fcurves
    TRANSFORM_COUNT = 10
    transform_list = [None] * TRANSFORM_COUNT

    channel_mapping = [
        (track.rotation, 'r', [0, 1, 2]),
        (track.location, 'l', [4, 5, 6]),
        (track.scale, 's', [7, 8, 9]),
    ]

    for channels, letter, indices in channel_mapping:
        for comp, idx in enumerate(indices):
            keyframes = channels[comp]
            if keyframes:
                data_path = 'pose.bones["%s"].%s' % (bone_name, letter)
                curve = action.fcurves.new(data_path, index=comp)
                for kf in keyframes:
                    point = curve.keyframe_points.insert(kf.frame, kf.value)
                    point.interpolation = kf.interpolation.value
                transform_list[idx] = curve

                # Apply bezier handles after all points are inserted
                kf_count = len(curve.keyframe_points)
                offset = kf_count - len(keyframes)
                for i, kf in enumerate(keyframes):
                    point = curve.keyframe_points[offset + i]
                    if kf.handle_left:
                        point.handle_left[:] = kf.handle_left
                    if kf.handle_right:
                        point.handle_right[:] = kf.handle_right

    # Fill missing channels with rest-pose constants
    rest = {
        'r': track.rest_rotation,
        'l': track.rest_position,
        's': track.rest_scale,
    }
    for channels, letter, indices in channel_mapping:
        for comp, idx in enumerate(indices):
            if not transform_list[idx]:
                data_path = 'pose.bones["%s"].%s' % (bone_name, letter)
                curve = action.fcurves.new(data_path, index=comp)
                curve.keyframe_points.insert(0, rest[letter][comp])
                transform_list[idx] = curve

    # Create final Blender fcurves
    new_transform_list = [None] * TRANSFORM_COUNT
    for i in range(3):
        new_transform_list[i] = action.fcurves.new(
            'pose.bones["%s"].rotation_euler' % bone_name, index=i)
        new_transform_list[i + 4] = action.fcurves.new(
            'pose.bones["%s"].location' % bone_name, index=i)
        new_transform_list[i + 7] = action.fcurves.new(
            'pose.bones["%s"].scale' % bone_name, index=i)

    # Pre-fetch Blender-specific matrices
    local_edit_matrix = bd['local_edit_matrix']
    edit_scale_correction = bd['edit_scale_correction']
    temp_matrix_local = bd['temp_matrix_local']
    parent_edit_scale_correction = (
        bone_data[parent_idx]['edit_scale_correction'] if parent_idx is not None else None
    )
    parent_scl = track.parent_accumulated_scale

    # Pass 2: frame-by-frame baking with scale correction
    end_frame = 0
    for curve in transform_list:
        if curve and len(curve.keyframe_points) > 0:
            last = curve.keyframe_points[-1].co[0]
            end_frame = max(end_frame, int(last) + 1)
    end_frame = min(end_frame, max_frame)

    for frame in range(end_frame):
        s = [transform_list[7].evaluate(frame),
             transform_list[8].evaluate(frame),
             transform_list[9].evaluate(frame)]
        r = [transform_list[0].evaluate(frame),
             transform_list[1].evaluate(frame),
             transform_list[2].evaluate(frame)]
        l = [transform_list[4].evaluate(frame),
             transform_list[5].evaluate(frame),
             transform_list[6].evaluate(frame)]

        mtx = _compile_srt_matrix(s, r, l, parent_scl)

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


def _apply_path_animation(track, action, bone_data_entry, max_frame):
    """Apply spline path-based animation from IRBoneTrack."""
    if not track.path_keyframes or not track.spline_points:
        return

    bone_name = track.bone_name

    # Create temp fcurve for path parameter
    param_curve = action.fcurves.new('pose.bones["%s"].path_param' % bone_name, index=0)
    for kf in track.path_keyframes:
        point = param_curve.keyframe_points.insert(kf.frame, kf.value)
        point.interpolation = kf.interpolation.value
    # Apply handles
    kf_count = len(param_curve.keyframe_points)
    offset = kf_count - len(track.path_keyframes)
    for i, kf in enumerate(track.path_keyframes):
        point = param_curve.keyframe_points[offset + i]
        if kf.handle_left:
            point.handle_left[:] = kf.handle_left
        if kf.handle_right:
            point.handle_right[:] = kf.handle_right

    loc_curves = [
        action.fcurves.new('pose.bones["%s"].location' % bone_name, index=i)
        for i in range(3)
    ]

    invmtx = bone_data_entry['temp_matrix_local'].inverted()
    points = track.spline_points

    end = min(int(track.path_keyframes[-1].frame) + 1 if track.path_keyframes else 0, max_frame)

    for frame in range(end):
        t = param_curve.evaluate(frame)
        t = max(0.0, min(t, len(points) - 1))
        idx = int(t)
        frac = t - idx
        if idx >= len(points) - 1:
            pos = points[-1]
        else:
            p0 = points[idx]
            p1 = points[idx + 1]
            pos = [p0[j] + frac * (p1[j] - p0[j]) for j in range(3)]

        world_pos = Vector(pos)
        local_mtx = Matrix.Translation(world_pos)
        Bmtx = invmtx @ local_mtx
        trans = Bmtx.to_translation()

        for i in range(3):
            loc_curves[i].keyframe_points.insert(frame, trans[i]).interpolation = 'BEZIER'

    action.fcurves.remove(param_curve)


def _build_bone_data_lookup(bones):
    """Build Blender-specific bone data for animation baking.

    Computes matrices from IRBone data needed for the scale correction
    formula. This is target-specific and belongs in Phase 5A.
    """
    lookup = {}
    for i, bone in enumerate(bones):
        lookup[i] = {
            'name': bone.name,
            'parent_index': bone.parent_index,
            'local_edit_matrix': Matrix(bone.normalized_local_matrix),
            'edit_scale_correction': Matrix(bone.scale_correction),
            'temp_matrix_local': Matrix(bone.local_matrix),
        }
    return lookup
