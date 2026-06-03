"""Create Blender Actions from a BR action list.

Pure bpy executor for everything except the per-frame pose-basis formula,
which lives in the Plan phase's ``compute_pose_basis`` helper so it can be
unit-tested without a Blender runtime.
"""
import math
import bpy
from mathutils import Matrix, Vector

try:
    from .....shared.helpers.logger import StubLogger
    from ...plan.helpers.animations import compute_pose_basis
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger
    from importer.phases.plan.helpers.animations import compute_pose_basis


def build_bone_animations(br_actions, armature, options, logger=StubLogger(), material_lookup=None):
    """Create Blender Actions from a list of BRAction specs.

    Each Action gets an OBJECT slot for the armature plus MATERIAL slots
    for any paired material tracks (multi-slot actions).

    In: br_actions (list[BRAction]); armature (bpy.types.Object, armature);
        options (dict, reads 'max_frame'); logger (Logger);
        material_lookup (dict[str, bpy.types.Material]|None, keyed by id).
    Out: (list[bpy.types.Action], dict[bpy.types.Material, int]) — Actions in
         the order given + slot index map for material animations.
    """
    from .material_animations import apply_color_tracks, apply_texture_uv_tracks

    max_frame = options.get("max_frame", 1000)
    actions = []
    mat_slot_indices = {}

    for br_action in br_actions:
        action = bpy.data.actions.new(br_action.name)
        action.use_fake_user = True

        armature_slot = action.slots.new('OBJECT', 'Armature')
        action.slots.active = armature_slot

        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='POSE')

        for bone in armature.pose.bones:
            bone.rotation_mode = 'XYZ'
        for bone in armature.data.bones:
            bone.use_local_location = True

        armature.animation_data_create()
        armature.animation_data.action = action
        armature.animation_data.action_slot = armature_slot

        for track in br_action.bone_tracks:
            _bake_bone_track(track, action, max_frame, logger, armature)

        mat_fcurve_count = _build_material_tracks(
            br_action, action, material_lookup, mat_slot_indices, max_frame,
            apply_color_tracks, apply_texture_uv_tracks, logger,
        )

        action.slots.active = armature_slot
        actions.append(action)
        logger.info("  Action '%s': %d bone fcurves, %d material fcurves",
                    action.name, len(action.fcurves), mat_fcurve_count)

        bpy.ops.object.mode_set(mode='OBJECT')

    return actions, mat_slot_indices


def reset_pose(armature):
    """Reset every pose bone to rest — zeros basis transforms.

    Direct property assignment (not mode-switching operators) so the reset
    is robust when prior imports leave Blender in unexpected state.

    In: armature (bpy.types.Object, armature; pose bones mutated in place).
    Out: None.
    """
    for bone in armature.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.scale = (1, 1, 1)


# ---------------------------------------------------------------------------
# Per-track bake — drives Blender fcurve interpolation, delegates math.
# ---------------------------------------------------------------------------

_CHANNEL_COUNT = 10
_ROT_INDICES = (0, 1, 2)
_LOC_INDICES = (4, 5, 6)
_SCL_INDICES = (7, 8, 9)


def _bake_bone_track(track, action, max_frame, logger, armature):
    """Insert raw IR keyframes into temp fcurves, evaluate frame-by-frame,
    run them through the pure pose-basis formula, and batch-write final
    rotation_euler / location / scale fcurves.

    In: track (BRBoneTrack); action (bpy.types.Action, mutated);
        max_frame (int, upper bake bound); logger (Logger);
        armature (bpy.types.Object|None, needed for FOLLOW_PATH setup).
    Out: None. The temporary raw fcurves are removed before returning.
    """
    if track.spline_path is not None and armature is not None:
        _apply_path_constraint(track, action, armature, logger)

    raw_curves = _insert_raw_keyframes(track, action)
    _fill_missing_channels_with_rest(track, action, raw_curves)

    final_curves = _create_final_fcurves(track.bone_name, action)
    end_frame = min(int(track.end_frame), max_frame)
    baked_values = _bake_frames(track, raw_curves, end_frame, logger)
    _write_baked_values(final_curves, baked_values)

    for curve in raw_curves:
        if curve is not None:
            action.fcurves.remove(curve)


def _insert_raw_keyframes(track, action):
    """Create temp fcurves on the 'r'/'l'/'s' data paths and seed them with
    the decoded IR keyframes.

    In: track (BRBoneTrack); action (bpy.types.Action, fcurves mutated).
    Out: list[bpy.types.FCurve|None] of length _CHANNEL_COUNT; None for any
         channel that had no keyframes in the input (filled by
         _fill_missing_channels_with_rest next).
    """
    raw = [None] * _CHANNEL_COUNT
    for keyframe_channels, letter, indices in (
        (track.rotation, 'r', _ROT_INDICES),
        (track.location, 'l', _LOC_INDICES),
        (track.scale, 's', _SCL_INDICES),
    ):
        for component, idx in enumerate(indices):
            keyframes = keyframe_channels[component]
            if not keyframes:
                continue
            data_path = 'pose.bones["%s"].%s' % (track.bone_name, letter)
            curve = action.fcurves.new(data_path, index=component)
            for kf in keyframes:
                point = curve.keyframe_points.insert(kf.frame, kf.value)
                point.interpolation = kf.interpolation.value
            offset = len(curve.keyframe_points) - len(keyframes)
            for i, kf in enumerate(keyframes):
                point = curve.keyframe_points[offset + i]
                if kf.handle_left is not None:
                    point.handle_left[:] = kf.handle_left
                if kf.handle_right is not None:
                    point.handle_right[:] = kf.handle_right
            raw[idx] = curve
    return raw


def _fill_missing_channels_with_rest(track, action, raw_curves):
    """Seed any channel without keyframes with a single rest-pose value so
    evaluate() returns a sensible constant during the bake loop.

    In: track (BRBoneTrack); action (bpy.types.Action, mutated);
        raw_curves (list[bpy.types.FCurve|None], mutated — None slots filled).
    Out: None.
    """
    rest_per_letter = {
        'r': track.rest_rotation,
        'l': track.rest_position,
        's': track.rest_scale,
    }
    for letter, indices in (('r', _ROT_INDICES), ('l', _LOC_INDICES), ('s', _SCL_INDICES)):
        for component, idx in enumerate(indices):
            if raw_curves[idx] is not None:
                continue
            data_path = 'pose.bones["%s"].%s' % (track.bone_name, letter)
            curve = action.fcurves.new(data_path, index=component)
            curve.keyframe_points.insert(0, rest_per_letter[letter][component])
            raw_curves[idx] = curve


def _create_final_fcurves(bone_name, action):
    """Create the nine final fcurves (rotation_euler × 3, location × 3, scale × 3).

    In: bone_name (str); action (bpy.types.Action, fcurves mutated).
    Out: list[bpy.types.FCurve|None] of length _CHANNEL_COUNT; index 3 is
         always None (channel layout reserves it).
    """
    curves = [None] * _CHANNEL_COUNT
    for component in range(3):
        curves[component] = action.fcurves.new(
            'pose.bones["%s"].rotation_euler' % bone_name, index=component)
        curves[component + 4] = action.fcurves.new(
            'pose.bones["%s"].location' % bone_name, index=component)
        curves[component + 7] = action.fcurves.new(
            'pose.bones["%s"].scale' % bone_name, index=component)
    return curves


def _bake_frames(track, raw_curves, end_frame, logger):
    """Evaluate raw fcurves at every integer frame and run the result
    through compute_pose_basis.

    In: track (BRBoneTrack, read for bake_context); raw_curves (list[FCurve]);
        end_frame (int, exclusive upper bound); logger (Logger).
    Out: list[list[tuple[int, float]]] of length _CHANNEL_COUNT — per-channel
         (frame, value) pairs ready for bulk insert.
    """
    baked = [[] for _ in range(_CHANNEL_COUNT)]
    ctx = track.bake_context

    for frame in range(end_frame):
        s = (raw_curves[7].evaluate(frame),
             raw_curves[8].evaluate(frame),
             raw_curves[9].evaluate(frame))
        r = (raw_curves[0].evaluate(frame),
             raw_curves[1].evaluate(frame),
             raw_curves[2].evaluate(frame))
        l = (raw_curves[4].evaluate(frame),
             raw_curves[5].evaluate(frame),
             raw_curves[6].evaluate(frame))

        if frame <= 3 or frame == end_frame - 1:
            logger.info("  EVAL %s f=%d r=(%.6f,%.6f,%.6f) l=(%.6f,%.6f,%.6f) s=(%.6f,%.6f,%.6f)",
                        track.bone_name, frame, r[0], r[1], r[2], l[0], l[1], l[2], s[0], s[1], s[2])

        trans, rot, scl = compute_pose_basis(ctx, s, r, l)

        if frame <= 3 or frame == end_frame - 1:
            logger.info("  BAKE %s f=%d loc=(%.6f,%.6f,%.6f) rot=(%.6f,%.6f,%.6f) scl=(%.6f,%.6f,%.6f)",
                        track.bone_name, frame, trans[0], trans[1], trans[2],
                        rot[0], rot[1], rot[2], scl[0], scl[1], scl[2])

        baked[0].append((frame, rot[0]))
        baked[1].append((frame, rot[1]))
        baked[2].append((frame, rot[2]))
        baked[4].append((frame, trans[0]))
        baked[5].append((frame, trans[1]))
        baked[6].append((frame, trans[2]))
        baked[7].append((frame, scl[0]))
        baked[8].append((frame, scl[1]))
        baked[9].append((frame, scl[2]))
    return baked


def _write_baked_values(curves, baked):
    """Bulk-write per-frame values with BEZIER interpolation. Using add()
    once + per-slot assignment is O(n); per-frame insert() is O(n log k).

    In: curves (list[FCurve|None]); baked (list[list[tuple[int, float]]]).
    Out: None; fcurves are mutated in place.
    """
    for idx in (0, 1, 2, 4, 5, 6, 7, 8, 9):
        curve = curves[idx]
        values = baked[idx]
        if not values:
            continue
        curve.keyframe_points.add(len(values))
        for i, (frame, value) in enumerate(values):
            point = curve.keyframe_points[i]
            point.co = (frame, value)
            point.interpolation = 'BEZIER'


def _build_material_tracks(br_action, action, material_lookup, mat_slot_indices,
                           max_frame, apply_color_tracks, apply_texture_uv_tracks,
                           logger):
    """Attach paired material animation tracks to the action as additional
    slots. Still consumes IR-shaped material tracks (carried through BR
    as pass-through until the materials stage migrates them).

    In: br_action (BRAction); action (bpy.types.Action, mutated);
        material_lookup (dict[str, bpy.types.Material]|None);
        mat_slot_indices (dict[bpy.types.Material, int], mutated);
        max_frame (int); apply_color_tracks / apply_texture_uv_tracks (callables
        injected from material_animations to avoid a circular import);
        logger (Logger).
    Out: int, number of material fcurves created across all material tracks.
    """
    if not br_action.material_tracks or not material_lookup:
        return 0

    if action.layers:
        layer = action.layers[0]
        strip = layer.strips[0]
    else:
        layer = action.layers.new("Layer")
        strip = layer.strips.new(type='KEYFRAME')

    animated_materials = set()
    mat_fcurve_count = 0
    for mat_track in br_action.material_tracks:
        mat = material_lookup.get(mat_track.material_mesh_name)
        logger.debug("    MatTrack lookup: '%s' → %s",
                     mat_track.material_mesh_name, mat.name if mat else 'NOT FOUND')
        if not mat:
            continue
        if id(mat) in animated_materials:
            logger.debug("    MatTrack '%s': skipping (material '%s' already animated)",
                         mat_track.material_mesh_name, mat.name)
            continue
        animated_materials.add(id(mat))

        mat_slot = action.slots.new('MATERIAL', mat.name or 'Material')
        channelbag = strip.channelbag(mat_slot, ensure=True)

        if not mat.animation_data:
            mat.animation_data_create()
        mat.animation_data.action = action
        mat.animation_data.action_slot = mat_slot

        before = len(channelbag.fcurves)
        apply_color_tracks(mat_track, mat, channelbag.fcurves, max_frame, logger)
        apply_texture_uv_tracks(mat_track, mat, channelbag.fcurves, logger)
        mat_fcurve_count += len(channelbag.fcurves) - before

        if mat not in mat_slot_indices:
            mat_slot_indices[mat] = len(action.slots) - 1

    return mat_fcurve_count


# ---------------------------------------------------------------------------
# Spline-path bones — unchanged from before. Still reads from the track's
# spline_path pass-through until a dedicated stage migrates it.
# ---------------------------------------------------------------------------

_SPLINE_TYPE_MAP = {
    0: 'POLY',
    2: 'NURBS',
}


def _apply_path_constraint(track, action, armature, logger):
    """Create a Blender curve from spline points and add a FOLLOW_PATH
    constraint. Bone follows the curve; path parameter is animated via
    the constraint's offset fcurve.

    In: track (BRBoneTrack with non-None spline_path); action (bpy.types.Action,
        gets an offset fcurve); armature (bpy.types.Object);
        logger (Logger).
    Out: None. Creates a bpy.types.Curve object parented to the armature and
         adds FOLLOW_PATH + LIMIT_LOCATION constraints on the pose bone.
    """
    bone_name = track.bone_name
    path = track.spline_path
    points = path.control_points
    spline_type = path.curve_type
    num_cvs = path.num_control_points
    tension = path.tension

    curve_data = bpy.data.curves.new('path_' + bone_name, 'CURVE')
    curve_data.use_path = True
    curve_data.dimensions = '3D'
    curve_obj = bpy.data.objects.new('Path_' + bone_name, curve_data)
    curve_obj.parent = armature
    if path.world_matrix:
        curve_obj.matrix_local = Matrix(path.world_matrix)
    bpy.context.scene.collection.objects.link(curve_obj)
    bpy.context.view_layer.update()

    if spline_type == 0:
        spline = curve_data.splines.new('POLY')
        spline.points.add(len(points) - 1)
        for i, pt in enumerate(points):
            spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

    elif spline_type == 1:
        spline = curve_data.splines.new('BEZIER')
        spline.bezier_points.add(num_cvs - 1)
        for i in range(num_cvs):
            spline.bezier_points[i].co = points[3 * i]
            if i > 0:
                spline.bezier_points[i].handle_left = points[3 * (i - 1) + 2]
            if i < num_cvs - 1:
                spline.bezier_points[i].handle_right = points[3 * i + 1]

    elif spline_type == 2:
        spline = curve_data.splines.new('NURBS')
        spline.points.add(len(points) - 1)
        spline.order_u = 4
        for i, pt in enumerate(points):
            spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

    elif spline_type == 3:
        spline = curve_data.splines.new('BEZIER')
        spline.bezier_points.add(num_cvs - 1)
        for i in range(num_cvs):
            cp = points[i + 1]
            spline.bezier_points[i].co = cp
            if i > 0:
                p_prev = Vector(points[i])
                p_next = Vector(points[i + 2])
                spline.bezier_points[i].handle_left = (Vector(cp) - tension / 3.0 * (p_next - p_prev))[:]
            if i < num_cvs - 1:
                p_prev = Vector(points[i])
                p_next = Vector(points[i + 2])
                spline.bezier_points[i].handle_right = (Vector(cp) + tension / 3.0 * (p_next - p_prev))[:]

    else:
        logger.info("  PATH %s: unsupported spline type %d", bone_name, spline_type)
        return

    pose_bone = armature.pose.bones[bone_name]

    path_constr = pose_bone.constraints.new('FOLLOW_PATH')
    pose_bone.constraints.move(len(pose_bone.constraints) - 1, 0)
    path_constr.target = curve_obj

    limit_constr = pose_bone.constraints.new('LIMIT_LOCATION')
    pose_bone.constraints.move(len(pose_bone.constraints) - 1, 0)
    for axis in ('x', 'y', 'z'):
        setattr(limit_constr, 'use_min_' + axis, True)
        setattr(limit_constr, 'use_max_' + axis, True)
        setattr(limit_constr, 'min_' + axis, 0.0)
        setattr(limit_constr, 'max_' + axis, 0.0)

    path_duration = curve_data.path_duration
    data_path = 'pose.bones["%s"].constraints["%s"].offset' % (bone_name, path_constr.name)
    offset_curve = action.fcurves.new(data_path)
    for kf in path.parameter_keyframes:
        scaled_value = kf.value * -path_duration
        point = offset_curve.keyframe_points.insert(kf.frame, scaled_value)
        point.interpolation = kf.interpolation.value
    kf_offset = len(offset_curve.keyframe_points) - len(path.parameter_keyframes)
    for i, kf in enumerate(path.parameter_keyframes):
        point = offset_curve.keyframe_points[kf_offset + i]
        if kf.handle_left:
            point.handle_left = (kf.handle_left[0], kf.handle_left[1] * -path_duration)
        if kf.handle_right:
            point.handle_right = (kf.handle_right[0], kf.handle_right[1] * -path_duration)

    logger.info("  PATH_SETUP bone=%s curve_obj=%s path_duration=%d",
                bone_name, curve_obj.name, path_duration)
