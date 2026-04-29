"""Blender pose-fcurves → IRBoneAnimationSet decoder.

Reads bone animation fcurves from Blender Actions and reverses the
baking formula applied during import to recover raw HSD SRT values.
Works with any Blender armature — no assumptions about import origin.

Used as the deep-work backend for ``describe/helpers/animations.py`` —
the BR shell wraps the IRBoneAnimationSet returned here while the BR↔IR
distinction for animation tracks is still under-specified. A future
pass can faithfully serialise pose fcurves into ``BRBoneTrack`` and
``BRMaterialTrack`` and move the unbaking + sparsification logic into
``plan/helpers/animations.py``.
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
    from .material_animations_decode import (
        describe_material_animations_for_action,
        build_material_lookup_from_meshes,
    )
except (ImportError, SystemError):
    from shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRKeyframe
    from shared.IR.enums import Interpolation
    from shared.helpers.math_shim import compile_srt_matrix
    from shared.helpers.logger import StubLogger
    from exporter.phases.describe.helpers.material_animations_decode import (
        describe_material_animations_for_action,
        build_material_lookup_from_meshes,
    )


def describe_bone_animations(armature, bones, logger=StubLogger(), use_bezier=True,
                              referenced_actions=None,
                              meshes=None, mesh_materials=None):
    """Read Blender Actions and produce IRBoneAnimationSet list.

    Finds all actions associated with the armature, samples each
    frame-by-frame, unbakes from Blender pose space to HSD SRT values,
    and applies sparsification to reduce keyframe count. Also scans each
    action for material animation fcurves and attaches them as
    ``material_tracks`` on the resulting IRBoneAnimationSet.
    """
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

    if referenced_actions:
        before = len(actions)
        actions = [a for a in actions if a.name in referenced_actions]
        dropped = before - len(actions)
        if dropped:
            logger.info("  PKX references %d action(s); dropped %d unreferenced action(s)",
                        len(referenced_actions), dropped)

    slot_order = _collect_slot_ordered_action_names(armature)
    if slot_order:
        actions = _reorder_actions_by_slot(actions, slot_order)

    if not actions:
        return []

    bone_data = _build_bone_data(bones)
    bone_name_to_index = {b.name: i for i, b in enumerate(bones)}

    mat_lookup = (
        build_material_lookup_from_meshes(meshes, mesh_materials, bones)
        if meshes is not None and mesh_materials is not None else {})

    anim_sets = []
    for action in actions:
        anim_set = _describe_action(action, bones, bone_data, bone_name_to_index, logger, use_bezier)
        if anim_set is None:
            continue
        if mat_lookup:
            anim_set.material_tracks = describe_material_animations_for_action(
                action, mat_lookup, logger=logger)
            if anim_set.material_tracks:
                logger.debug("    action '%s': %d material tracks",
                             action.name, len(anim_set.material_tracks))
        anim_sets.append(anim_set)

    logger.info("  Described %d animation set(s) from armature '%s'",
                len(anim_sets), armature.name)
    return anim_sets


def _collect_slot_ordered_action_names(armature):
    if armature.get("dat_pkx_format") is None:
        return None

    ordered = []
    seen = set()

    anim_count = armature.get("dat_pkx_anim_count", 17)
    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        for s in range(3):
            name = armature.get(prefix + "_sub_%d_anim" % s, "")
            if isinstance(name, str) and name and name not in seen:
                seen.add(name)
                ordered.append(name)

    for i in range(4):
        name = armature.get("dat_pkx_sub_anim_%d_anim_ref" % i, "")
        if isinstance(name, str) and name and name not in seen:
            seen.add(name)
            ordered.append(name)

    return ordered or None


def _reorder_actions_by_slot(actions, slot_order):
    by_name = {a.name: a for a in actions}
    ordered = []
    seen = set()
    for name in slot_order:
        a = by_name.get(name)
        if a is not None and a.name not in seen:
            ordered.append(a)
            seen.add(a.name)
    for a in actions:
        if a.name not in seen:
            ordered.append(a)
            seen.add(a.name)
    return ordered


def _build_bone_data(bones):
    data = {}
    for i, bone in enumerate(bones):
        local_edit = Matrix(bone.normalized_local_matrix)
        edit_sc = Matrix(bone.scale_correction)
        local_matrix = Matrix(bone.local_matrix)

        rest_decomp = local_matrix.decompose()
        rest_loc = rest_decomp[0]
        rest_quat = rest_decomp[1]
        rest_s = rest_decomp[2]

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


def _bone_fcurves_frame_range(bone_fcurves):
    """Compute (frame_start, frame_end, end_frame) from the bone fcurves only.

    `action.frame_range` spans every slot in a slotted Action, so material-
    animation fcurves on a separate MATERIAL slot can stretch it past the
    bones' real keyframe span. Using that range would pad every bone with
    flat keyframes out to whatever the longest material track reaches.
    """
    min_frame = None
    max_frame = None
    for channels in bone_fcurves.values():
        for ch_fcs in channels.values():
            for fc in ch_fcs.values():
                for kp in fc.keyframe_points:
                    f = kp.co[0]
                    min_frame = f if min_frame is None else min(min_frame, f)
                    max_frame = f if max_frame is None else max(max_frame, f)
    if min_frame is None:
        return None
    frame_start = int(min_frame)
    frame_end = int(max_frame)
    end_frame = max(1, frame_end - frame_start + 1)
    return frame_start, frame_end, end_frame


def _describe_action(action, bones, bone_data, bone_name_to_index, logger, use_bezier=True):
    bone_fcurves = {}
    for fc in action.fcurves:
        match = re.match(r'pose\.bones\["(.+?)"\]\.(.+)', fc.data_path)
        if not match:
            continue
        bone_name, channel = match.groups()
        if channel not in ('rotation_euler', 'rotation_quaternion', 'location', 'scale'):
            continue
        if bone_name not in bone_fcurves:
            bone_fcurves[bone_name] = {}
        if channel not in bone_fcurves[bone_name]:
            bone_fcurves[bone_name][channel] = {}
        bone_fcurves[bone_name][channel][fc.array_index] = fc

    if not bone_fcurves:
        return None

    frame_range = _bone_fcurves_frame_range(bone_fcurves)
    if frame_range is None:
        return None
    frame_start, frame_end, end_frame = frame_range

    tracks = []
    for bone_name, channels in bone_fcurves.items():
        bone_idx = bone_name_to_index.get(bone_name)
        if bone_idx is None:
            continue

        track = _unbake_bone_track(
            bone_name, bone_idx, channels, bone_data, bones,
            frame_start, frame_end, end_frame, logger, use_bezier)
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
                       frame_start, frame_end, end_frame, logger, use_bezier=True):
    bd = bone_data[bone_idx]
    parent_idx = bd['parent_index']
    use_legacy = bd['use_legacy']

    rot_channels = [[], [], []]
    loc_channels = [[], [], []]
    scl_channels = [[], [], []]
    prev_euler = None

    for frame in range(frame_start, frame_end + 1):
        blender_rot = [0.0, 0.0, 0.0]
        blender_loc = [0.0, 0.0, 0.0]
        blender_scl = [1.0, 1.0, 1.0]

        rot_euler_fcs = channels.get('rotation_euler', {})
        rot_quat_fcs = channels.get('rotation_quaternion', {})
        loc_fcs = channels.get('location', {})
        scl_fcs = channels.get('scale', {})

        if rot_quat_fcs:
            qw = rot_quat_fcs[0].evaluate(frame) if 0 in rot_quat_fcs else 1.0
            qx = rot_quat_fcs[1].evaluate(frame) if 1 in rot_quat_fcs else 0.0
            qy = rot_quat_fcs[2].evaluate(frame) if 2 in rot_quat_fcs else 0.0
            qz = rot_quat_fcs[3].evaluate(frame) if 3 in rot_quat_fcs else 0.0
            euler = Quaternion((qw, qx, qy, qz)).to_euler('XYZ')
            blender_rot = [euler.x, euler.y, euler.z]
        else:
            for i in range(3):
                if i in rot_euler_fcs:
                    blender_rot[i] = rot_euler_fcs[i].evaluate(frame)

        for i in range(3):
            if i in loc_fcs:
                blender_loc[i] = loc_fcs[i].evaluate(frame)
            if i in scl_fcs:
                blender_scl[i] = scl_fcs[i].evaluate(frame)

        if use_legacy:
            r, l, s = _unbake_legacy(blender_rot, blender_loc, blender_scl, bd, bone_data,
                                     prev_euler=prev_euler)
        else:
            r, l, s = _unbake_direct(blender_rot, blender_loc, blender_scl, bd,
                                     prev_euler=prev_euler)
        prev_euler = Euler(r, 'XYZ')

        relative_frame = frame - frame_start
        for i in range(3):
            rot_channels[i].append((relative_frame, r[i]))
            loc_channels[i].append((relative_frame, l[i]))
            scl_channels[i].append((relative_frame, s[i]))

    # Unwrap Euler rotation channels so values that cross ±π stay continuous.
    for i in range(3):
        samples = rot_channels[i]
        if len(samples) < 2:
            continue
        unwrapped = [samples[0]]
        prev = samples[0][1]
        offset = 0.0
        for frame, val in samples[1:]:
            candidate = val + offset
            delta = candidate - prev
            if delta > math.pi:
                offset -= 2 * math.pi
                candidate -= 2 * math.pi
            elif delta < -math.pi:
                offset += 2 * math.pi
                candidate += 2 * math.pi
            unwrapped.append((frame, candidate))
            prev = candidate
        rot_channels[i] = unwrapped

    if use_bezier:
        all_ch = rot_channels + loc_channels + scl_channels
        sparsified = []
        for ch in all_ch:
            slopes = _compute_slopes(ch)
            sparsified.append(_sparsify_bezier(ch, slopes))
        rotation = sparsified[0:3]
        location = sparsified[3:6]
        scale = sparsified[6:9]
    else:
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


def _unbake_legacy(blender_rot, blender_loc, blender_scl, bd, bone_data,
                   prev_euler=None):
    """Reverse the legacy baking formula (uniform parent scale).

    Forward: Bmtx = local_edit.inv() @ [parent_edit_sc @] mtx @ edit_sc.inv()
    Reverse: mtx = [parent_edit_sc.inv() @] local_edit @ Bmtx @ edit_sc
    """
    local_edit = bd['local_edit']
    edit_sc = bd['edit_sc']
    parent_idx = bd['parent_index']

    Bmtx = compile_srt_matrix(blender_scl, blender_rot, blender_loc)

    try:
        if parent_idx is not None:
            parent_edit_sc = bone_data[parent_idx]['edit_sc']
            mtx = parent_edit_sc.inverted() @ local_edit @ Bmtx @ edit_sc
        else:
            mtx = local_edit @ Bmtx @ edit_sc
    except (ValueError, ZeroDivisionError):
        return [0, 0, 0], [0, 0, 0], [1, 1, 1]

    trans, quat, scale = mtx.decompose()
    if prev_euler is not None:
        euler = quat.to_euler('XYZ', prev_euler)
    else:
        euler = quat.to_euler('XYZ')

    return (
        [euler.x, euler.y, euler.z],
        [trans.x, trans.y, trans.z],
        [scale.x, scale.y, scale.z],
    )


def _unbake_direct(blender_rot, blender_loc, blender_scl, bd, prev_euler=None):
    """Reverse the direct SRT delta formula (non-uniform parent scale)."""
    rest_loc = bd['rest_loc']
    rest_quat = bd['rest_quat']
    rest_s = bd['rest_s']

    trans = Vector(blender_loc)
    trans.rotate(rest_quat)
    anim_loc = rest_loc + trans

    blender_euler = Euler(blender_rot, 'XYZ')
    anim_quat = rest_quat @ blender_euler.to_quaternion()
    if prev_euler is not None:
        anim_euler = anim_quat.to_euler('XYZ', prev_euler)
    else:
        anim_euler = anim_quat.to_euler('XYZ')

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


# Sparsification ------------------------------------------------------------

_TOLERANCE = 1e-4


def _sparsify(frame_values):
    if not frame_values:
        return []

    first_val = frame_values[0][1]
    if all(abs(v - first_val) < _TOLERANCE for _, v in frame_values):
        start_frame = frame_values[0][0]
        end_frame = frame_values[-1][0]
        if end_frame == start_frame:
            return [IRKeyframe(frame=start_frame, value=first_val,
                               interpolation=Interpolation.CONSTANT)]
        return [
            IRKeyframe(frame=start_frame, value=first_val, interpolation=Interpolation.CONSTANT),
            IRKeyframe(frame=end_frame, value=first_val, interpolation=Interpolation.CONSTANT),
        ]

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

    result = [IRKeyframe(
        frame=frame_values[0][0],
        value=frame_values[0][1],
        interpolation=Interpolation.LINEAR,
    )]

    last_emitted = 0
    for i in range(1, len(frame_values) - 1):
        f_start, v_start = frame_values[last_emitted]
        f_end, v_end = frame_values[i + 1]
        f_range = f_end - f_start
        if f_range > 0:
            t = (frame_values[i][0] - f_start) / f_range
            expected = v_start + t * (v_end - v_start)
            if abs(frame_values[i][1] - expected) > _TOLERANCE:
                result.append(IRKeyframe(
                    frame=frame_values[i][0],
                    value=frame_values[i][1],
                    interpolation=Interpolation.LINEAR,
                ))
                last_emitted = i

    result.append(IRKeyframe(
        frame=frame_values[-1][0],
        value=frame_values[-1][1],
        interpolation=Interpolation.LINEAR,
    ))

    return result


def _compute_slopes(frame_values):
    n = len(frame_values)
    if n == 0:
        return []
    if n == 1:
        return [0.0]

    slopes = []
    for i in range(n):
        if i == 0:
            dt = frame_values[1][0] - frame_values[0][0]
            slopes.append((frame_values[1][1] - frame_values[0][1]) / max(dt, 1))
        elif i == n - 1:
            dt = frame_values[i][0] - frame_values[i - 1][0]
            slopes.append((frame_values[i][1] - frame_values[i - 1][1]) / max(dt, 1))
        else:
            dt = frame_values[i + 1][0] - frame_values[i - 1][0]
            slopes.append((frame_values[i + 1][1] - frame_values[i - 1][1]) / max(dt, 1))

    return slopes


def _hermite_eval(p0, s0, p1, s1, dt, t_frac):
    t = t_frac
    t2 = t * t
    t3 = t2 * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    return h00 * p0 + h10 * s0 * dt + h01 * p1 + h11 * s1 * dt


def _sparsify_bezier(frame_values, slopes):
    if not frame_values:
        return []

    if len(frame_values) == 1:
        return [IRKeyframe(
            frame=frame_values[0][0],
            value=frame_values[0][1],
            interpolation=Interpolation.CONSTANT,
        )]

    first_val = frame_values[0][1]
    if all(abs(v - first_val) < _TOLERANCE for _, v in frame_values):
        start_frame = frame_values[0][0]
        end_frame = frame_values[-1][0]
        if end_frame == start_frame:
            return [IRKeyframe(frame=start_frame, value=first_val,
                               interpolation=Interpolation.CONSTANT)]
        return [
            IRKeyframe(frame=start_frame, value=first_val, interpolation=Interpolation.CONSTANT),
            IRKeyframe(frame=end_frame, value=first_val, interpolation=Interpolation.CONSTANT),
        ]

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

    indices = list(range(len(frame_values)))

    while len(indices) > 2:
        best_idx_pos = -1
        best_error = float('inf')

        for pos in range(1, len(indices) - 1):
            left = indices[pos - 1]
            right = indices[pos + 1]

            f_left = frame_values[left][0]
            f_right = frame_values[right][0]
            v_left = frame_values[left][1]
            v_right = frame_values[right][1]
            s_left = slopes[left]
            s_right = slopes[right]
            dt = f_right - f_left

            if dt <= 0:
                continue

            max_err = 0.0
            for k in range(left, right + 1):
                f_k = frame_values[k][0]
                v_k = frame_values[k][1]
                t_frac = (f_k - f_left) / dt
                h_val = _hermite_eval(v_left, s_left, v_right, s_right, dt, t_frac)
                err = abs(v_k - h_val)
                if err > max_err:
                    max_err = err

            if max_err < best_error:
                best_error = max_err
                best_idx_pos = pos

        if best_error >= _TOLERANCE or best_idx_pos < 0:
            break

        indices.pop(best_idx_pos)

    result = []
    for i, idx in enumerate(indices):
        frame = frame_values[idx][0]
        value = frame_values[idx][1]
        slope = slopes[idx]

        if i < len(indices) - 1:
            next_idx = indices[i + 1]
            interp = _detect_segment_interpolation(
                frame_values, idx, next_idx, slope, slopes[next_idx])
        else:
            interp = result[-1].interpolation if result else Interpolation.BEZIER

        result.append(IRKeyframe(
            frame=frame,
            value=value,
            interpolation=interp,
            slope_in=slope,
            slope_out=slope,
        ))

    return result


def _detect_segment_interpolation(frame_values, left_idx, right_idx, slope_left, slope_right):
    f_left = frame_values[left_idx][0]
    f_right = frame_values[right_idx][0]
    v_left = frame_values[left_idx][1]
    v_right = frame_values[right_idx][1]
    dt = f_right - f_left

    if dt <= 0:
        return Interpolation.CONSTANT

    chord_slope = (v_right - v_left) / dt

    if abs(slope_left - chord_slope) < _TOLERANCE and abs(slope_right - chord_slope) < _TOLERANCE:
        return Interpolation.LINEAR

    return Interpolation.BEZIER
