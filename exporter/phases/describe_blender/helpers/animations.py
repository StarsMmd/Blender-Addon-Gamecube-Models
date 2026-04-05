"""Describe Blender Actions as IRBoneAnimationSet dataclasses.

Reads bone animation fcurves from Blender Actions and reverses the
baking formula applied during import to recover raw HSD SRT values.
Works with any Blender armature — no assumptions about import origin.
"""
import math
import re
import bpy
from mathutils import Matrix, Vector, Euler, Quaternion

try:
    from .....shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRKeyframe
    from .....shared.IR.enums import Interpolation
    from .....shared.helpers.math_shim import compile_srt_matrix
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRKeyframe
    from shared.IR.enums import Interpolation
    from shared.helpers.math_shim import compile_srt_matrix
    from shared.helpers.logger import StubLogger


def describe_bone_animations(armature, bones, logger=StubLogger()):
    """Read Blender Actions and produce IRBoneAnimationSet list.

    Finds all actions associated with the armature, samples each
    frame-by-frame, unbakes from Blender pose space to HSD SRT values,
    and applies sparsification to reduce keyframe count.

    Args:
        armature: Blender armature object.
        bones: list[IRBone] from describe_skeleton.
        logger: Logger instance.

    Returns:
        list[IRBoneAnimationSet]
    """
    # Find actions associated with this armature
    armature_prefix = armature.name.split('_skeleton_')[0] if '_skeleton_' in armature.name else armature.name
    actions = []
    for action in bpy.data.actions:
        if action.name.startswith(armature_prefix + '_'):
            actions.append(action)
        elif action.id_root == 'OBJECT':
            for fc in action.fcurves:
                if fc.data_path.startswith('pose.bones['):
                    actions.append(action)
                    break

    if not actions:
        return []

    # Build bone data lookup for unbaking
    bone_data = _build_bone_data(bones)
    bone_name_to_index = {b.name: i for i, b in enumerate(bones)}

    anim_sets = []
    for action in actions:
        anim_set = _describe_action(action, bones, bone_data, bone_name_to_index, logger)
        if anim_set is not None:
            anim_sets.append(anim_set)

    logger.info("  Described %d animation set(s) from armature '%s'",
                len(anim_sets), armature.name)
    return anim_sets


def _build_bone_data(bones):
    """Build lookup data needed for unbaking."""
    data = {}
    for i, bone in enumerate(bones):
        local_edit = Matrix(bone.normalized_local_matrix)
        edit_sc = Matrix(bone.scale_correction)
        local_matrix = Matrix(bone.local_matrix)

        # Decompose rest local matrix for direct delta formula
        rest_decomp = local_matrix.decompose()
        rest_loc = rest_decomp[0]
        rest_quat = rest_decomp[1]
        rest_s = rest_decomp[2]

        # Determine bake strategy from accumulated scale uniformity
        accum = bone.accumulated_scale
        mn = min(abs(x) for x in accum if abs(x) > 1e-6) if any(abs(x) > 1e-6 for x in accum) else 0
        mx = max(abs(x) for x in accum)
        use_legacy = (mn > 0 and mx / max(mn, 1e-9) < 1.1)

        data[i] = {
            'local_edit': local_edit,
            'edit_sc': edit_sc,
            'local_matrix': local_matrix,
            'rest_loc': rest_loc,
            'rest_quat': rest_quat,
            'rest_s': rest_s,
            'use_legacy': use_legacy,
            'parent_index': bone.parent_index,
            'rest_rotation': bone.rotation,
            'rest_position': bone.position,
            'rest_scale': bone.scale,
        }
    return data


def _describe_action(action, bones, bone_data, bone_name_to_index, logger):
    """Convert a single Blender Action to an IRBoneAnimationSet."""

    # Group fcurves by bone name
    bone_fcurves = {}  # {bone_name: {channel: {index: fcurve}}}
    for fc in action.fcurves:
        match = re.match(r'pose\.bones\["(.+?)"\]\.(.+)', fc.data_path)
        if not match:
            continue
        bone_name, channel = match.groups()
        if channel not in ('rotation_euler', 'location', 'scale'):
            continue
        if bone_name not in bone_fcurves:
            bone_fcurves[bone_name] = {}
        if channel not in bone_fcurves[bone_name]:
            bone_fcurves[bone_name][channel] = {}
        bone_fcurves[bone_name][channel][fc.array_index] = fc

    if not bone_fcurves:
        return None

    # Determine frame range
    frame_start = int(action.frame_range[0])
    frame_end = int(action.frame_range[1])
    end_frame = max(1, frame_end - frame_start)

    tracks = []
    for bone_name, channels in bone_fcurves.items():
        bone_idx = bone_name_to_index.get(bone_name)
        if bone_idx is None:
            continue

        track = _unbake_bone_track(
            bone_name, bone_idx, channels, bone_data, bones,
            frame_start, frame_end, end_frame, logger)
        if track is not None:
            tracks.append(track)

    if not tracks:
        return None

    is_loop = '_Loop' in action.name or '_loop' in action.name

    anim_set = IRBoneAnimationSet(
        name=action.name,
        tracks=tracks,
        loop=is_loop,
    )

    logger.debug("    action '%s': %d tracks, %d frames, loop=%s",
                 action.name, len(tracks), end_frame, is_loop)
    return anim_set


def _unbake_bone_track(bone_name, bone_idx, channels, bone_data, bones,
                       frame_start, frame_end, end_frame, logger):
    """Unbake Blender pose-space fcurves to HSD SRT keyframes for one bone."""
    bd = bone_data[bone_idx]
    parent_idx = bd['parent_index']
    use_legacy = bd['use_legacy']

    # Sample fcurves at each frame
    rot_channels = [[], [], []]
    loc_channels = [[], [], []]
    scl_channels = [[], [], []]

    for frame in range(frame_start, frame_end + 1):
        # Read Blender pose-space values
        blender_rot = [0.0, 0.0, 0.0]
        blender_loc = [0.0, 0.0, 0.0]
        blender_scl = [1.0, 1.0, 1.0]

        rot_fcs = channels.get('rotation_euler', {})
        loc_fcs = channels.get('location', {})
        scl_fcs = channels.get('scale', {})

        for i in range(3):
            if i in rot_fcs:
                blender_rot[i] = rot_fcs[i].evaluate(frame)
            if i in loc_fcs:
                blender_loc[i] = loc_fcs[i].evaluate(frame)
            if i in scl_fcs:
                blender_scl[i] = scl_fcs[i].evaluate(frame)

        # Unbake to HSD SRT
        if use_legacy:
            r, l, s = _unbake_legacy(blender_rot, blender_loc, blender_scl, bd, bone_data)
        else:
            r, l, s = _unbake_direct(blender_rot, blender_loc, blender_scl, bd)

        relative_frame = frame - frame_start
        for i in range(3):
            rot_channels[i].append((relative_frame, r[i]))
            loc_channels[i].append((relative_frame, l[i]))
            scl_channels[i].append((relative_frame, s[i]))

    # Build IRKeyframe lists per channel with sparsification
    rotation = [_sparsify(ch) for ch in rot_channels]
    location = [_sparsify(ch) for ch in loc_channels]
    scale = [_sparsify(ch) for ch in scl_channels]

    return IRBoneTrack(
        bone_name=bone_name,
        bone_index=bone_idx,
        rotation=rotation,
        location=location,
        scale=scale,
        rest_local_matrix=bd['local_matrix'].to_list() if hasattr(bd['local_matrix'], 'to_list') else [[bd['local_matrix'][r][c] for c in range(4)] for r in range(4)],
        rest_rotation=bd['rest_rotation'],
        rest_position=bd['rest_position'],
        rest_scale=bd['rest_scale'],
        end_frame=end_frame,
    )


def _unbake_legacy(blender_rot, blender_loc, blender_scl, bd, bone_data):
    """Reverse the legacy baking formula (uniform parent scale).

    Forward: Bmtx = local_edit.inv() @ [parent_edit_sc @] mtx @ edit_sc.inv()
    Reverse: mtx = [parent_edit_sc.inv() @] local_edit @ Bmtx @ edit_sc
    """
    local_edit = bd['local_edit']
    edit_sc = bd['edit_sc']
    parent_idx = bd['parent_index']

    # Reconstruct Bmtx from Blender pose-space values
    Bmtx = compile_srt_matrix(blender_scl, blender_rot, blender_loc)

    # Reverse the sandwich
    try:
        if parent_idx is not None:
            parent_edit_sc = bone_data[parent_idx]['edit_sc']
            mtx = parent_edit_sc.inverted() @ local_edit @ Bmtx @ edit_sc
        else:
            mtx = local_edit @ Bmtx @ edit_sc
    except (ValueError, ZeroDivisionError):
        # Fallback: treat as identity transform
        return [0, 0, 0], [0, 0, 0], [1, 1, 1]

    # Decompose recovered matrix to SRT
    trans, quat, scale = mtx.decompose()
    euler = quat.to_euler('XYZ')

    return (
        [euler.x, euler.y, euler.z],
        [trans.x, trans.y, trans.z],
        [scale.x, scale.y, scale.z],
    )


def _unbake_direct(blender_rot, blender_loc, blender_scl, bd):
    """Reverse the direct SRT delta formula (non-uniform parent scale).

    Forward: trans = (anim_loc - rest_loc).rotated(rest_quat_inv)
             rot = (rest_quat_inv @ anim_quat).to_euler()
             scl = anim_s / rest_s

    Reverse: anim_loc = rest_loc + trans.rotated(rest_quat)
             anim_quat = rest_quat @ rot.to_quaternion()
             anim_s = scl * rest_s
    """
    rest_loc = bd['rest_loc']
    rest_quat = bd['rest_quat']
    rest_s = bd['rest_s']

    # Reverse location
    trans = Vector(blender_loc)
    trans.rotate(rest_quat)
    anim_loc = rest_loc + trans

    # Reverse rotation
    blender_euler = Euler(blender_rot, 'XYZ')
    anim_quat = rest_quat @ blender_euler.to_quaternion()
    anim_euler = anim_quat.to_euler('XYZ')

    # Reverse scale
    anim_s = [
        blender_scl[0] * rest_s[0],
        blender_scl[1] * rest_s[1],
        blender_scl[2] * rest_s[2],
    ]

    return (
        [anim_euler.x, anim_euler.y, anim_euler.z],
        [anim_loc.x, anim_loc.y, anim_loc.z],
        anim_s,
    )


# ---------------------------------------------------------------------------
# Sparsification
# ---------------------------------------------------------------------------

_TOLERANCE = 1e-4


def _sparsify(frame_values):
    """Reduce a dense list of (frame, value) to sparse IRKeyframe list.

    Applies constant and linear collapse to minimize keyframe count
    while preserving the animation within tolerance.
    """
    if not frame_values:
        return []

    # Check if all values are the same → single CONSTANT keyframe
    first_val = frame_values[0][1]
    if all(abs(v - first_val) < _TOLERANCE for _, v in frame_values):
        return [IRKeyframe(
            frame=frame_values[0][0],
            value=first_val,
            interpolation=Interpolation.CONSTANT,
        )]

    # Check if values form a single linear ramp → two LINEAR keyframes
    if len(frame_values) >= 2:
        start_frame, start_val = frame_values[0]
        end_frame, end_val = frame_values[-1]
        frame_range = end_frame - start_frame
        if frame_range > 0:
            is_linear = True
            for f, v in frame_values[1:-1]:
                t = (f - start_frame) / frame_range
                expected = start_val + t * (end_val - start_val)
                if abs(v - expected) > _TOLERANCE:
                    is_linear = False
                    break
            if is_linear:
                return [
                    IRKeyframe(frame=start_frame, value=start_val, interpolation=Interpolation.LINEAR),
                    IRKeyframe(frame=end_frame, value=end_val, interpolation=Interpolation.LINEAR),
                ]

    # Piecewise linear collapse — keep keyframes at points where the
    # direction changes significantly
    result = [IRKeyframe(
        frame=frame_values[0][0],
        value=frame_values[0][1],
        interpolation=Interpolation.LINEAR,
    )]

    last_emitted = 0
    for i in range(1, len(frame_values) - 1):
        # Check if the line from last emitted to current can skip this point
        f_start, v_start = frame_values[last_emitted]
        f_end, v_end = frame_values[i + 1]
        f_range = f_end - f_start
        if f_range > 0:
            t = (frame_values[i][0] - f_start) / f_range
            expected = v_start + t * (v_end - v_start)
            if abs(frame_values[i][1] - expected) > _TOLERANCE:
                # Direction changed — emit this keyframe
                result.append(IRKeyframe(
                    frame=frame_values[i][0],
                    value=frame_values[i][1],
                    interpolation=Interpolation.LINEAR,
                ))
                last_emitted = i

    # Always emit the last keyframe
    result.append(IRKeyframe(
        frame=frame_values[-1][0],
        value=frame_values[-1][1],
        interpolation=Interpolation.LINEAR,
    ))

    return result
